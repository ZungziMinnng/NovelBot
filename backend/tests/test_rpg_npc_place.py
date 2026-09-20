"""剧情挪动人物位置：玩家说「你过来」，她就真的过来。

这一批给「她在哪儿」加了第三个来源，优先级是

    这一局的剧情（npc_places） → 作息表 → 常驻地点

作息表和常驻地点回答「没事的时候她在哪儿」，npc_places 回答「这一格剧情把
她挪到哪了」。两条底线：

1. **只有刚写出来的正文里真的出现过的人**才准被改位置（named_npcs 那条口径），
   外加私聊线的线主（一对一说话时正文很可能只写「她」，见 _settle）。
   玩家嘴上提到一句不行——那会让一个从没出场的角色凭空站在你面前、侧栏写
   「就在你面前」、还能拉进私聊，而玩家没有任何纠正的入口。
2. **推时段清空**。时段一变作息表重新说了算，否则模型随手写的一笔会永久
   盖掉作者排的作息表，而那是他唯一的排期手段。

和玩家自己的位置不同，这条线**在私聊线里也放行**：点开她单独说「你回宿舍去」
是最自然的挪人方式，原先连 NPC 一起丢，只剩一条 toast。
"""
import unittest
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.agents.rpg_turn import _place_block
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession
from app.services.rpg_settlement import DOMAINS, capture, seed_settlement
from app.services.rpg_context import here_npcs, named_npcs, npc_place, onstage_npcs
from app.services.rpg_state import advance_slot, apply_npc_place, apply_state_delta


def _npc(npc_id=3, name="赫敏", location="宿舍", **kwargs):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location, **kwargs)


def _sess(**kwargs):
    base = {
        "location": "校长办公室", "slot": "晚", "day": 1,
        "npc_places": {}, "npc_notes": {}, "npc_states": {},
        "stats": {}, "inventory": [], "flags": [], "chronicle": [],
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class PlaceOverrideTests(unittest.TestCase):
    """取值优先级。它同时是后端和前端（condition.npcPlace）的口径。"""

    def test_the_scene_beats_the_schedule(self):
        # 作息表说她晚上在宿舍，剧情把她叫到了办公室——她就在办公室
        npc = _npc(slot_locations={"晚": "宿舍"})
        self.assertEqual(npc_place(npc, "晚", {"3": "校长办公室"}), "校长办公室")

    def test_the_scene_beats_the_home_location(self):
        npc = _npc(location="宿舍")
        self.assertEqual(npc_place(npc, "晚", {"3": "校长办公室"}), "校长办公室")

    def test_clearing_it_falls_back_to_the_schedule(self):
        # 「你回去吧」走的就是这条路：清掉这一格，作息表替她算
        npc = _npc(slot_locations={"晚": "宿舍"})
        self.assertEqual(npc_place(npc, "晚", {"3": ""}), "宿舍")

    def test_no_session_changes_nothing(self):
        # 模组编辑页读不到会话，传 None 必须和加这一列之前逐字一致
        npc = _npc(slot_locations={"晚": "宿舍"})
        self.assertEqual(npc_place(npc, "晚", None), "宿舍")

    def test_the_override_survives_an_empty_place(self):
        # 常驻地点和作息表都空的人（学生）被叫过来之后，清掉位置她就哪儿都
        # 不是——这不是 bug，是「行踪不明」，界面上照实显示
        npc = _npc(location="")
        self.assertEqual(npc_place(npc, "晚", {"3": "校长办公室"}), "校长办公室")
        self.assertEqual(npc_place(npc, "晚", {}), "")

    def test_she_counts_as_here_after_being_called_over(self):
        # 「在场」的判据一个没变，只是 npc_place 多认了一个来源
        npc = _npc(slot_locations={"晚": "宿舍"})
        self.assertEqual(here_npcs([npc], "校长办公室", "晚", {}), [])
        self.assertEqual(here_npcs([npc], "校长办公室", "晚", {"3": "校长办公室"}), [npc])

    def test_injection_follows_too(self):
        # 被提到那一半照旧：人不在这儿、名字在扫描窗口里，两个都算在场
        npc = _npc(slot_locations={"晚": "宿舍"})
        got = onstage_npcs([npc], "校长办公室", "赫敏说了什么", "晚", {"3": "校长办公室"})
        self.assertEqual(got, [npc])

class NamedNpcTests(unittest.TestCase):
    """位置改动的允许名单：这一段正文里出现过谁。"""

    def test_a_name_in_the_text_counts(self):
        npc = _npc()
        self.assertEqual(named_npcs([npc], "赫敏推门进来。"), [npc])

    def test_a_keyword_counts(self):
        npc = _npc(name="赫敏", keywords="万事通,格兰杰")
        self.assertEqual(named_npcs([npc], "万事通又来了"), [npc])

    def test_nothing_matches_an_empty_text(self):
        self.assertEqual(named_npcs([_npc()], ""), [])

    def test_the_protagonist_template_is_never_moved(self):
        # 主角模板是玩家自己的卡，没有「她在哪儿」这回事
        npc = _npc(name="阿隼", role="protagonist")
        self.assertEqual(named_npcs([npc], "阿隼走进办公室"), [])


class WritePathTests(unittest.TestCase):
    """模型提议 → 夹紧 → 落库那一段。"""

    def _delta(self, places):
        return {"npc_places": places}

    def test_it_writes_the_place(self):
        npc = _npc()
        sess = _sess()
        apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"赫敏": "校长办公室"}), [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.npc_places, {"3": "校长办公室"})

    def test_a_blank_value_clears_it(self):
        npc = _npc()
        sess = _sess(npc_places={"3": "校长办公室"})
        apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"赫敏": ""}), [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.npc_places, {})

    def test_someone_who_never_showed_up_in_the_scene_is_refused(self):
        # 玩家嘴上抱怨了一句马尔福，模型顺手把他挪到跟前——这正是要挡的
        mal = _npc(npc_id=4, name="马尔福", location="斯莱特林")
        sess = _sess()
        warnings = apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"马尔福": "校长办公室"}), [mal], move_npcs=[],
        )
        self.assertEqual(sess.npc_places, {})
        self.assertTrue(any("马尔福" in w for w in warnings))

    def test_an_unknown_name_is_warned_about(self):
        npc = _npc()
        sess = _sess()
        warnings = apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"查无此人": "校长办公室"}), [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.npc_places, {})
        self.assertTrue(any("查无此人" in w for w in warnings))

    def test_the_players_own_move_is_applied(self):
        # 叙述把玩家自己挪走照旧放行。「自由打字绕过地图」是文档 §13 的既有
        # 决定，当初的边界画在「场面线放行、私聊线不放行」上——线没了，那个
        # 开关跟着没了，于是所有情况一个待遇
        npc = _npc()
        sess = _sess()
        warnings = apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            {"location": "图书馆"}, [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.location, "图书馆")
        self.assertFalse(any("走动" in w or "地点变化" in w for w in warnings))

    def test_no_allow_list_means_nobody_can_be_moved(self):
        # 老调用点（没传 move_npcs）行为不变：一个都不许挪
        npc = _npc()
        sess = _sess()
        apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"赫敏": "校长办公室"}), [npc],
        )
        self.assertEqual(sess.npc_places, {})

    def test_a_json_blob_is_not_stored_as_a_place_name(self):
        # 模型把值写成 {"地点": "宿舍"}，存进去的话界面上会把这段 JSON 当地名显示
        npc = _npc()
        sess = _sess(npc_places={"3": "校长办公室"})
        apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            self._delta({"赫敏": {"地点": "宿舍"}}), [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.npc_places, {})

    def test_a_non_dict_payload_is_ignored(self):
        # 模型写出一个列表来。位置这条线整段跳过，不该把这一轮的其他结算带崩
        npc = _npc()
        sess = _sess()
        apply_state_delta(
            RpgModule(stat_defs=[], relation_stat_defs=[]), sess,
            {"npc_places": ["赫敏", "校长办公室"]}, [npc], move_npcs=[npc],
        )
        self.assertEqual(sess.npc_places, {})


class ApplyNpcPlaceTests(unittest.TestCase):
    def test_the_dict_is_rebound_not_mutated_in_place(self):
        # 原地改 JSON 列不会标脏、不会落库。这条钉住的是「整个赋回去」这个写法
        sess = _sess(npc_places={"3": "宿舍"})
        apply_npc_place(sess, 3, "大礼堂")
        self.assertEqual(sess.npc_places, {"3": "大礼堂"})

    def test_a_none_value_clears(self):
        sess = _sess(npc_places={"3": "宿舍"})
        apply_npc_place(sess, 3, None)
        self.assertEqual(sess.npc_places, {})

    def test_it_survives_a_missing_table(self):
        sess = _sess(npc_places=None)
        apply_npc_place(sess, 3, "宿舍")
        self.assertEqual(sess.npc_places, {"3": "宿舍"})


class SlotResetTests(unittest.TestCase):
    """推时段 = 作息表重新说了算。"""

    def _module(self):
        return RpgModule(name="魔法学院", time_slots=["早", "中", "晚"])

    def test_advancing_the_slot_preserves_the_present_cast(self):
        module = self._module()
        sess = _sess(slot="中", npc_places={"3": "校长办公室"})
        advance_slot(module, sess)
        self.assertEqual(sess.slot, "晚")
        self.assertEqual(sess.npc_places, {"3": "校长办公室"})

    def test_rolling_over_to_a_new_day_preserves_the_present_cast(self):
        module = self._module()
        sess = _sess(slot="晚", day=3, npc_places={"3": "校长办公室"})
        advance_slot(module, sess)
        self.assertEqual(sess.day, 4)
        self.assertEqual(sess.npc_places, {"3": "校长办公室"})

    def test_no_clock_means_no_reset(self):
        # 模组没设时段时按一下不该有任何后果——时钟不存在，也就没有「下一格」
        module = RpgModule(name="无时钟", time_slots=[])
        sess = _sess(slot="", npc_places={"3": "校长办公室"})
        self.assertEqual(advance_slot(module, sess), [])
        self.assertEqual(sess.npc_places, {"3": "校长办公室"})


class PromptBlockTests(unittest.TestCase):
    """结算提示词末尾那一段。不写进去，模型压根不知道有这个字段。"""

    def test_it_lists_everybody_with_their_current_place(self):
        block = _place_block([_npc()], [], _sess())
        self.assertIn("npc_places", block)
        self.assertIn("赫敏 现在在 宿舍", block)

    def test_it_shows_the_scene_place_not_the_schedule(self):
        # 得让她原本在宿舍这件事被看到，模型才写得出「她回去了」那种清空
        block = _place_block([_npc()], [], _sess(npc_places={"3": "校长办公室"}))
        self.assertIn("赫敏 现在在 校长办公室", block)

    def test_nobody_named_means_no_block(self):
        # 一个字段都不提，省掉几十个字，也免得模型凭空想起要挪人
        self.assertEqual(_place_block([], ["宿舍"], _sess()), "")

    def test_a_nameless_person_is_still_shown(self):
        # 作者把名字留空了。这儿写成空串不难看，也不影响别的
        block = _place_block([_npc(name="", location="")], [], _sess())
        self.assertIn("行踪不明", block)

    def test_known_places_are_offered(self):
        # 现编一个模组里没有的地名，侧栏会显示它、地点总览里却找不到，
        # 玩家照提示「去她所在的地方」就走不过去。给一份真名单
        block = _place_block([_npc()], ["宿舍", "图书馆"], _sess())
        self.assertIn("宿舍、图书馆", block)

    def test_no_known_places_means_no_such_line(self):
        # 模组一个地点都没建时，这段不拼，行为和加它之前逐字一致
        self.assertNotIn("只能填", _place_block([_npc()], [], _sess()))


class SettleWiringTests(unittest.IsolatedAsyncioTestCase):
    """把这一整条线跑一遍：提示词里带上位置段 → 模型写回来 → 落库 → 进发给
    前端的那份状态。

    上面每一块单测都绿、而中间那一行忘了拼（`prompt += ...` 少一个加号、
    或者 apply_state_delta 少传一个参数），是这类改动最常见的失败方式：
    没有任何报错，功能就是不生效，而且要等到玩的时候才发现。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="魔法学院", stat_defs=[], relation_stat_defs=[],
                time_slots=["早", "中", "晚"],
            )
            db.add(module)
            await db.commit()
            npc = RpgNpc(
                module_id=module.id, name="赫敏", location="宿舍",
                slot_locations={"晚": "宿舍"}, persona="好胜",
            )
            db.add(npc)
            db.add(RpgLocation(module_id=module.id, name="图书馆"))
            await db.commit()
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={},
                location="校长办公室", slot="晚", day=1, status="alive",
                npc_states={}, npc_notes={}, npc_places={}, chronicle=[],
            )
            db.add(sess)
            await db.commit()
            self.session_id = sess.id
            self.npc_id = npc.id
            self.module_id = module.id

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    async def _run(self, narration: str, reply: dict):
        """跑一次结算，返回（结果, 模型收到的提示词）。"""
        prompts = []
        async with self.sessions() as store:
            sess = await store.get(RpgSession, self.session_id)
            npc = await store.get(RpgNpc, self.npc_id)
            present = [npc.id] if npc_place(npc, sess.slot, sess.npc_places) == sess.location else []
            row = RpgMessage(session_id=sess.id, role="assistant", content=narration, present=present,
                             settlement=seed_settlement(sess, 0, capture(sess), "", None, "group", None, present))
            store.add(row)
            await store.commit()
            message_id = row.id
        reply = {**reply, "checks": {domain: "changed" if any(reply.get(key) for key in keys) else "unchanged" for domain, keys in DOMAINS.items()},
                 "events": [{"kind": "move", "quote": narration, "domains": ["scene"]}] if reply else []}

        async def fake_call_json(messages, *a, **kw):
            prompts.append(messages[0]["content"])
            return reply, 1, 1

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn, "call_json", fake_call_json):
            got = await rpg_turn._settle(
                self.session_id, message_id, narration, "", "",
            )
        return got, prompts[0]

    async def _places(self):
        async with self.sessions() as db:
            return dict((await db.get(RpgSession, self.session_id)).npc_places or {})

    async def test_the_prompt_offers_the_field_with_where_she_is_now(self):
        # 得让她「现在在宿舍」被看到，模型才写得出「她回去了」那种清空。
        # 地名那一行同一次钉住：模型现编一个模组里没有的地名，侧栏会显示它、
        # 地点总览里却找不到，玩家没法照提示走过去
        _got, prompt = await self._run("赫敏推门进来，站在你面前。", {})
        self.assertIn("npc_places", prompt)
        self.assertIn("赫敏 现在在 宿舍", prompt)
        self.assertIn("只能填这些已有的地名：图书馆", prompt)

    async def test_nobody_in_the_text_means_the_field_is_never_offered(self):
        # 一个字都不提，模型也就不会想起要挪谁
        _got, prompt = await self._run("你一个人在屋里坐了会儿。", {})
        self.assertIn("角色表：[]", prompt)

    async def test_the_move_lands_and_reaches_the_frontend(self):
        got, _prompt = await self._run(
            "赫敏推门进来，站在你面前。", {"npc_places": {"赫敏": "校长办公室"}},
        )
        self.assertEqual(await self._places(), {str(self.npc_id): "校长办公室"})
        # 面板是读这一份更新的，不带的话要等整页重拉才动
        self.assertEqual(
            got["state"]["npc_places"], {str(self.npc_id): "校长办公室"},
        )

    async def test_a_name_that_never_showed_up_cannot_be_moved(self):
        # 正文里没露面，只在玩家嘴里出现过的人：整条闸门挡住
        got, _prompt = await self._run(
            "你一个人在屋里坐了会儿。", {"npc_places": {"赫敏": "校长办公室"}},
        )
        self.assertEqual(await self._places(), {})
        self.assertTrue(any("赫敏" in w for w in got["warnings"]))

    async def test_she_can_be_sent_back(self):
        # 「你回宿舍去吧」= 写空串：清掉这一格，作息表重新说了算
        async with self.sessions() as db:
            row = await db.get(RpgSession, self.session_id)
            row.npc_places = {str(self.npc_id): "校长办公室"}
            await db.commit()
        await self._run("赫敏推门进来，说了几句话就走了。",
                        {"npc_places": {"赫敏": ""}})
        self.assertEqual(await self._places(), {})

    async def test_someone_in_the_room_moves_even_if_the_text_only_says_她(self):
        # 面对面说话时正文很可能只写「她」。只认全名的话，玩家最常见的挪人
        # 方式（当着她的面叫她回宿舍）就永远失效——所以在场的人无条件可动。
        # 这一条是替原先那个「线主无条件可动」的：线主本来就是指「你正在跟
        # 她说话的那位」，线没了，等价的集合就是眼前这些人
        async with self.sessions() as db:
            row = await db.get(RpgNpc, self.npc_id)
            # 作息表压过 location，得连它一起改才真的「在跟前」
            row.slot_locations = {"晚": "校长办公室"}
            await db.commit()
        got, _prompt = await self._run(
            "她点点头，收拾好东西出门去了。",
            {"npc_places": {"赫敏": "图书馆"}},
        )
        self.assertEqual(await self._places(), {str(self.npc_id): "图书馆"})
        self.assertEqual(got["state"]["npc_places"], {str(self.npc_id): "图书馆"})


class SnapshotTests(unittest.TestCase):
    def test_the_place_table_is_snapshotted(self):
        # 漏了的话读档回到三天前，赫敏还站在办公室里——而那个办公室
        # 是三天后你才叫她去的
        self.assertIn("npc_places", SNAPSHOT_FIELDS)
        self.assertEqual(SNAPSHOT_DEFAULTS["npc_places"], {})


if __name__ == "__main__":
    unittest.main()
