"""大事记、开场白、瞬移。

大事记**必须**跨地点跨场景——不然后山挖出尸首这种事，换个地方问就没人听说过了，
而它当年立起来正是为了给「线各自独立」补窟窿。同时钉住那个反过来会出事的方向：
大事记每一轮都注入，等于所有 NPC 全知，所以它的口吻必须是「已经传开的传闻」
而不是「发生过的事」。

这个文件原名「分线对话与大事记」。线拆掉之后，测分线的那几组（归属解析、门控、
按线切历史）跟着它们测的代码一起删了——一段叙事归谁看，现在由消息上的 present
快照决定，见 test_rpg_timeline.py。
"""
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import create_session, move_to
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import (
    RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSave, RpgSession,
)
from app.models.user import User
from app.schemas.rpg import RpgMoveIn, RpgSessionCreate
from app.services.rpg_context import build_rpg_messages
from app.services.rpg_state import (
    CHRONICLE_LIMIT, OPENING_CHARS, OPENING_TAG,
    advance_slot, apply_state_delta, note_move, push_chronicle,
)

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


def _module(**kwargs):
    base = {"stat_defs": STAT_DEFS, "relation_stat_defs": []}
    base.update(kwargs)
    return RpgModule(user_id=1, name="测试模组", **base)


def _sess(**kwargs):
    # chronicle 显式给 []：列默认值要 flush 之后才生效，而这几条测的是
    # 纯函数，对象根本没进库
    base = {"stats": {"精力": 100}, "location": "地窖", "status": "alive", "chronicle": []}
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


def _npc(npc_id=7, name="老兵", location="地窖"):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location)


class SuggestScopeTests(unittest.IsolatedAsyncioTestCase):
    """「帮我想想」看的是整条时间线。

    它当年按线取，是为了「在老兵屋里给的建议不该来自隔壁酒馆刚聊的那些话」。
    那个理由随线一起没了：现在全场只有一条历史，隔壁酒馆那几句就是你的前情。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _seed(self):
        user = User(username="alice", password_hash="x")
        self.db.add(user)
        await self.db.commit()
        module = RpgModule(
            user_id=user.id, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[],
        )
        self.db.add(module)
        await self.db.commit()
        sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="地窖")
        self.db.add(sess)
        await self.db.commit()
        self.db.add_all([
            RpgMessage(session_id=sess.id, role="user", content="场面上的一句"),
            RpgMessage(session_id=sess.id, role="user", content="对老兵说的"),
            RpgMessage(session_id=sess.id, role="user", content="对老板娘说的"),
        ])
        await self.db.commit()
        return sess, user

    async def test_the_endpoint_hands_over_the_whole_timeline(self):
        from app.api.routes.rpg import suggest_actions

        sess, user = await self._seed()
        seen = {}

        async def fake(_module, _sess, history):
            seen["contents"] = [m.content for m in history]
            return []

        with patch.object(rpg_turn, "suggest_actions", fake):
            await suggest_actions(sess.id, user, self.db)

        self.assertEqual(
            seen["contents"], ["场面上的一句", "对老兵说的", "对老板娘说的"],
        )


class ChronicleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _module(self, **kwargs):
        module = _module(**kwargs)
        self.db.add(module)
        await self.db.commit()
        return module

    # ── 写入 ──

    def test_moves_merge_into_one_line(self):
        # 不合并的话，玩家在镇上连点五个地点，大事记就全是「你去了 X」，
        # 真正传开的那件事被挤出去
        sess = _sess(slot="早", day=1)
        note_move(sess, "铁匠铺")
        note_move(sess, "酒馆")
        self.assertEqual(len(sess.chronicle), 1)
        self.assertIn("酒馆", sess.chronicle[0])
        self.assertNotIn("铁匠铺", sess.chronicle[0])

    def test_a_day_line_breaks_the_merge(self):
        # 中间跨了天就不该合并：那是两条不同的记录
        sess = _sess(slot="早", day=1)
        note_move(sess, "铁匠铺")
        push_chronicle(sess, "第 2 天开始了")
        note_move(sess, "酒馆")
        self.assertEqual(len(sess.chronicle), 3)

    def test_the_list_is_capped_and_drops_the_oldest(self):
        sess = _sess()
        for i in range(CHRONICLE_LIMIT + 5):
            push_chronicle(sess, f"第 {i} 件事")
        self.assertEqual(len(sess.chronicle), CHRONICLE_LIMIT)
        self.assertNotIn("第 0 件事", sess.chronicle)

    def test_junk_values_do_not_become_entries(self):
        sess = _sess()
        push_chronicle(sess, None)
        push_chronicle(sess, "  ")
        push_chronicle(sess, {"不是": "列表"})
        self.assertEqual(sess.chronicle, [])

    def test_a_single_string_is_accepted(self):
        # 模型有时给一条字符串而不是数组，没必要为这个丢掉一条大事
        sess = _sess()
        push_chronicle(sess, "后山挖出了尸首")
        self.assertEqual(sess.chronicle, ["后山挖出了尸首"])

    # ── 引擎写入的时机 ──

    def test_plain_slot_advance_is_not_a_chronicle_entry(self):
        # 每推一格都写的话，时钟噪音会把真正传开的事挤出去
        module = _module(time_slots=["早", "中", "晚"])
        sess = _sess(slot="早", day=1)
        advance_slot(module, sess)
        self.assertEqual(sess.chronicle, [])

    def test_a_new_day_is_recorded_once(self):
        # 一行都不写的话，换个地点就不知道过了几天
        module = _module(time_slots=["早", "中", "晚"])
        sess = _sess(slot="晚", day=1)
        advance_slot(module, sess)
        self.assertEqual(len(sess.chronicle), 1)
        self.assertIn("第 2 天", sess.chronicle[0])

    def test_walking_somewhere_is_recorded(self):
        target = RpgLocation(id=2, module_id=1, name="铁匠铺", connections=["地窖"])
        sess = _sess(location="地窖")
        rpg_turn._move(sess, target, [])
        self.assertEqual(sess.location, "铁匠铺")
        self.assertEqual(len(sess.chronicle), 1)
        self.assertIn("铁匠铺", sess.chronicle[0])

    def test_walking_somewhere_lights_it_up_for_good(self):
        # 大事记里的移动行会被下一次移动合并掉，所以迷雾不能读它，得有自己的名单
        target = RpgLocation(id=2, module_id=1, name="铁匠铺", connections=["地窖"])
        sess = _sess(location="地窖", visited=["地窖"])
        rpg_turn._move(sess, target, [])
        self.assertEqual(sess.visited, ["地窖", "铁匠铺"])

    # ── 注入 ──

    async def test_the_outside_block_reaches_the_model(self):
        module = await self._module()
        sess = _sess(chronicle=["后山挖出了尸首，镇上都在传"], location="地窖")
        self.db.add(sess)
        await self.db.commit()
        messages, diag = await build_rpg_messages(
            self.db, module, sess, [], "我问问老板"
        )
        system = messages[0]["content"]
        self.assertIn("【外场】", system)
        self.assertIn("后山挖出了尸首", system)
        self.assertGreater(diag["chronicle_tokens"], 0)
        # 口吻定死在这里：注入每一条线 = 所有 NPC 全知，
        # 所以要明说「听说」不等于「亲眼见过」
        self.assertIn("传开", system)
        self.assertIn("亲眼", system)

    async def test_an_empty_chronicle_adds_nothing(self):
        module = await self._module()
        sess = _sess(location="地窖")
        self.db.add(sess)
        await self.db.commit()
        messages, diag = await build_rpg_messages(self.db, module, sess, [], "我看看四周")
        self.assertNotIn("【外场】", messages[0]["content"])
        self.assertEqual(diag["chronicle_tokens"], 0)


class OpeningSceneTests(unittest.IsolatedAsyncioTestCase):
    """开场白怎么落。

    它现在是时间线上的**第一条普通消息**（role=assistant），只有一条——从前它
    是「场面线的第一条旁白」，还得防着被复制进各条私聊线；线拆掉之后没有复制
    这回事，它就是这段历史的开头，模型顺着读下来自然看得见。

    同时压一条进大事记：那一幕是这一局最公共的事实（「你在校长办公室、赫敏就在
    跟前」），而大事记是跨地点共享的那一路。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _open(self, opening):
        module = _module(opening_scene=opening, default_location="校长办公室")
        self.db.add(module)
        await self.db.commit()
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db,
        )
        msgs = (await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == sess.id)
        )).scalars().all()
        return sess, msgs

    async def test_it_lands_once_as_the_first_message(self):
        sess, msgs = await self._open("你在校长办公室，赫敏抬头看你。")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].role, "assistant")

    async def test_it_also_becomes_one_public_fact(self):
        sess, _ = await self._open("你在校长办公室，赫敏抬头看你。")
        self.assertEqual(len(sess.chronicle), 1)
        self.assertTrue(sess.chronicle[0].startswith(OPENING_TAG))
        self.assertIn("赫敏", sess.chronicle[0])

    async def test_a_long_opening_does_not_camp_in_the_outside_block(self):
        # 大事记是一行一条的硬事实，整段旁白塞进去会常驻吃掉外场的预算
        sess, _ = await self._open("很长的开场" * 200)
        self.assertLessEqual(len(sess.chronicle[0]), OPENING_CHARS + len(OPENING_TAG))

    async def test_no_opening_means_no_message_and_no_fact(self):
        sess, msgs = await self._open("   ")
        self.assertEqual(msgs, [])
        self.assertEqual(sess.chronicle or [], [])

    async def test_the_opening_reaches_the_model_as_a_message(self):
        """它是时间线的开头，不是某块读时拼进去的背景。

        从前私聊线里根本没有开场白——那条线看的是自己的历史——只能靠【场面近况】
        把全文借过去。现在没有别的历史：传进来的那份里就有它，原文一字不少。
        """
        opening = "你在校长办公室。赫敏抬头看你。" + "窗外的雨敲着玻璃，她说她等你很久了。" * 10
        self.assertGreater(len(opening), OPENING_CHARS + 40)
        sess, msgs = await self._open(opening)
        module = await self.db.get(RpgModule, sess.module_id)

        messages, _ = await build_rpg_messages(self.db, module, sess, msgs, "赫敏，你怎么看")
        self.assertEqual(messages[1]["content"], opening)


class NoteGateTests(unittest.TestCase):
    """近况比关系数值收得更紧：数字下一轮会被盖掉，近况是长期事实。"""

    def test_a_note_about_someone_who_is_not_there_is_refused(self):
        # 剧情里随口提一句名字不该算数：近况会一直画在角色卡上、每轮注入
        # 那个人的设定块，隔着一个镇的人凭一句话就多出一条伤
        npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]
        sess = _sess(location="地窖", npc_notes={})
        warnings = apply_state_delta(
            _module(), sess, {"npc_notes": {"赫敏": {"伤势": "左肩中刀"}}},
            npcs, note_npcs=[],
        )
        self.assertEqual(sess.npc_notes, {})
        self.assertTrue(any("赫敏" in w for w in warnings))

    def test_a_note_about_someone_in_front_of_you_lands(self):
        npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]
        sess = _sess(location="地窖", npc_notes={})
        apply_state_delta(
            _module(), sess, {"npc_notes": {"赫敏": {"伤势": "左肩中刀"}}},
            npcs, note_npcs=npcs,
        )
        self.assertEqual(sess.npc_notes, {"3": {"伤势": "左肩中刀"}})


class SilentMoveTests(unittest.IsolatedAsyncioTestCase):
    """瞬移：点一下地图就过去。零 LLM 调用是这批的前提。

    跑的是**真实路由**，而且故意用文件数据库而不是 :memory:。移动一度是在路由
    已经拍了存档（写事务开着）之后另开一条连接去改 rpg_sessions：内存库共用
    一条连接看不出问题，文件库会原地卡满 busy_timeout 再报 database is locked——
    玩家那边就是「按一下转半分钟然后报错」。
    """

    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.tmp}/t.db")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)

        module = _module(stat_defs=STAT_DEFS)
        self.db.add(module)
        await self.db.commit()
        self.module = module
        self.db.add_all([
            RpgLocation(module_id=module.id, name="地窖", connections=["铁匠铺"]),
            RpgLocation(module_id=module.id, name="铁匠铺", connections=["地窖"]),
            RpgLocation(module_id=module.id, name="后山", connections=["地窖"],
                        enter_requires={"stats": {"精力": {"op": ">=", "value": 200}}}),
            RpgLocation(module_id=module.id, name="荒野"),
        ])
        sess = RpgSession(
            module_id=module.id, char_name="阿隼", stats={"精力": 100}, location="地窖"
        )
        self.db.add(sess)
        await self.db.commit()
        self.sess = sess

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _move(self, target):
        """跑一次瞬移，顺便钉住「一次模型调用都没有」。"""
        with patch.object(
            rpg_turn.llm_client, "get_agent_client",
            side_effect=AssertionError("瞬移不该碰模型"),
        ):
            out = await move_to(self.sess.id, RpgMoveIn(target=target), self.user, self.db)
        return out.message

    async def _reload(self):
        await self.db.refresh(self.sess)
        return self.sess

    async def test_it_moves_you_and_records_it(self):
        message = await self._move("铁匠铺")
        sess = await self._reload()
        self.assertEqual(sess.location, "铁匠铺")
        self.assertIn("铁匠铺", message)
        self.assertEqual(len(sess.chronicle), 1)

    async def test_a_place_with_no_road_is_still_reachable(self):
        # 连接只管画地图和散迷雾，不再是关卡：荒野一条边都没连，照样走得过去
        message = await self._move("荒野")
        sess = await self._reload()
        self.assertEqual(sess.location, "荒野")
        self.assertIn("荒野", message)
        self.assertEqual(len(sess.chronicle), 1)

    async def test_a_gate_you_do_not_pass_is_refused_with_words(self):
        message = await self._move("后山")
        sess = await self._reload()
        self.assertEqual(sess.location, "地窖")
        self.assertIn("精力", message)

    async def test_going_where_you_already_are_is_a_no_op(self):
        # 不该白白往大事记里刷一条「你去了 X」
        message = await self._move("地窖")
        sess = await self._reload()
        self.assertIn("已经", message)
        self.assertEqual(sess.chronicle, [])

    async def test_an_unknown_place_does_not_blow_up(self):
        message = await self._move("不存在的城")
        self.assertIn("不存在的城", message)

    async def test_a_teleport_writes_the_destination_into_the_fog_log(self):
        await self._move("铁匠铺")
        sess = await self._reload()
        self.assertIn("铁匠铺", sess.visited)

    async def test_a_blocked_teleport_leaves_the_fog_alone(self):
        await self._move("后山")
        sess = await self._reload()
        self.assertNotIn("后山", sess.visited)

    async def _saves(self):
        return list((await self.db.execute(
            select(RpgSave).where(RpgSave.session_id == self.sess.id)
        )).scalars().all())

    async def test_a_successful_move_leaves_one_snapshot(self):
        # 瞬移绕过了回合的存档，得自己拍一张，否则中间跳的几格无法反悔
        await self._move("铁匠铺")
        saves = await self._saves()
        self.assertEqual(len(saves), 1)
        self.assertEqual(saves[0].state["location"], "地窖")

    async def test_a_refused_or_repeated_move_leaves_no_junk_snapshots(self):
        # 一局里所有瞬移的 before_message_id 都是同一个（它不产生消息），
        # 一次点击一张档会把 30 张的自动档窗口灌满，真正的回合档被挤掉
        await self._move("后山")          # 精力不够，什么都没改
        self.assertEqual(await self._saves(), [])
        await self._move("铁匠铺")
        await self._move("地窖")
        await self._move("铁匠铺")
        saves = await self._saves()
        self.assertEqual(len(saves), 1)
        # 留下的必须是最早那张：要回到的是「这一串点击之前」
        self.assertEqual(saves[0].state["location"], "地窖")


if __name__ == "__main__":
    unittest.main()
