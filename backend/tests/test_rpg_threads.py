"""分线对话与大事记。

两条线各自的历史不能串台，这是「真分线」的全部意义；而大事记恰恰相反，
它**必须**跨线——不然后山挖出尸首这种事，换个地方问就没人听说过了。

同时钉住那个反过来会出事的方向：大事记注入每一条线，等于所有 NPC 全知，
所以它的口吻必须是「已经传开的传闻」而不是「发生过的事」。
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


class ThreadResolutionTests(unittest.TestCase):
    """这一轮归哪条线：只在一个地方解析，别处不要重算。"""

    def test_an_explicit_thread_wins(self):
        npcs = [_npc(7), _npc(9, "老板娘")]
        self.assertEqual(rpg_turn.resolve_thread_id(_sess(), npcs, 9, "老兵"), 9)

    def test_a_thread_id_that_is_not_ours_is_dropped(self):
        self.assertIsNone(rpg_turn.resolve_thread_id(_sess(), [_npc(7)], 999, ""))

    def test_a_target_in_scene_becomes_the_thread(self):
        # 不传 thread_id 时按动作对象兜底。这是给不带线的调用方留的那条路
        self.assertEqual(rpg_turn.resolve_thread_id(_sess(), [_npc(7)], None, "老兵"), 7)

    def test_a_target_who_is_elsewhere_does_not_become_the_thread(self):
        # 兜底必须和 thread_blocker 用同一条判据（人在不在这儿）。
        # 否则「对远处的人用动作」会先被解析成他那条线、再被门控拒成 400，
        # 而它本来是个合法操作：数值照加，叙事留在你脚下这条线上
        npcs = [_npc(7, "老兵", location="铁匠铺")]
        self.assertIsNone(rpg_turn.resolve_thread_id(_sess(location="地窖"), npcs, None, "老兵"))

    def test_no_thread_no_target_is_the_scene_line(self):
        self.assertIsNone(rpg_turn.resolve_thread_id(_sess(), [_npc(7)], None, ""))
        self.assertIsNone(rpg_turn.resolve_thread_id(_sess(), [_npc(7)], None, "查无此人"))


class ThreadGateTests(unittest.TestCase):
    def test_a_line_whose_owner_left_takes_no_input(self):
        why = rpg_turn.thread_blocker(
            _sess(location="地窖"), [_npc(7, "老兵", location="铁匠铺")], 7
        )
        self.assertIn("铁匠铺", why)
        self.assertIn("老兵", why)

    def test_a_line_whose_owner_is_here_passes(self):
        self.assertEqual(rpg_turn.thread_blocker(_sess(), [_npc(7)], 7), "")

    def test_the_scene_line_is_never_blocked(self):
        self.assertEqual(rpg_turn.thread_blocker(_sess(), [_npc(7, location="远方")], None), "")


class ThreadIsolationTests(unittest.IsolatedAsyncioTestCase):
    """线和消息的关系：thread_id 落在消息上，NULL 就是场面线。"""

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
        module = RpgModule(user_id=1, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[])
        self.db.add(module)
        await self.db.commit()
        sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="地窖")
        self.db.add(sess)
        await self.db.commit()
        self.db.add_all([
            RpgMessage(session_id=sess.id, role="user", content="场面上的一句"),
            RpgMessage(session_id=sess.id, role="user", content="对老兵说的", thread_id=7),
            RpgMessage(session_id=sess.id, role="user", content="对老板娘说的", thread_id=9),
        ])
        await self.db.commit()
        return sess

    async def _in(self, sess, thread_id):
        return (await self.db.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == sess.id, rpg_turn._thread_clause(thread_id))
            .order_by(RpgMessage.id)
        )).scalars().all()

    async def test_each_line_gets_only_its_own_messages(self):
        sess = await self._seed()
        self.assertEqual([m.content for m in await self._in(sess, 7)], ["对老兵说的"])
        self.assertEqual([m.content for m in await self._in(sess, 9)], ["对老板娘说的"])

    async def test_null_is_the_scene_line(self):
        # NULL 和「空」必须同一个意思：老数据整份都是 NULL，
        # 它们要自动变成一条完整的场面线，一个字都不用回填
        sess = await self._seed()
        self.assertEqual([m.content for m in await self._in(sess, None)], ["场面上的一句"])

    async def test_the_suggest_endpoint_only_reads_the_current_line(self):
        """「帮我想想」取的是这条线的最近几轮。

        在老兵屋里给的建议，不该来自隔壁酒馆刚聊的那些话。
        """
        from app.api.routes.rpg import suggest_actions

        sess = await self._seed()
        user = User(username="alice", password_hash="x")
        self.db.add(user)
        await self.db.commit()
        sess.module_id = sess.module_id  # 归属检查要能过
        await self.db.commit()
        module = await self.db.get(RpgModule, sess.module_id)
        module.user_id = user.id
        await self.db.commit()

        seen = {}

        async def fake(_module, _sess, history, thread_id=None):
            seen["contents"] = [m.content for m in history]
            seen["thread_id"] = thread_id
            return []

        with patch.object(rpg_turn, "suggest_actions", fake):
            await suggest_actions(sess.id, user, 7, self.db)

        self.assertEqual(seen["contents"], ["对老兵说的"])
        # 线号也要传进去：概要是按线存的，拿错线会把别人的往事当成前情
        self.assertEqual(seen["thread_id"], 7)


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
    """开场白归谁。

    它是**场面线**的第一条旁白，不复制到任何人的私聊线——复制的话每条线各自
    演化、各自被总结，同一段话在不同线里会被改写成不同的事实。

    但那一幕是这一局最公共的事实（「你在校长办公室、赫敏就在跟前」），所以
    同时压一条进大事记：那条通道本来就是跨线共享的，私聊线才知道刚发生了什么。
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

    async def test_it_lands_on_the_scene_line_only(self):
        sess, msgs = await self._open("你在校长办公室，赫敏抬头看你。")
        self.assertEqual(len(msgs), 1)
        self.assertIsNone(msgs[0].thread_id)
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


class SceneAndThreadBlockTests(unittest.IsolatedAsyncioTestCase):
    """【当前线】：没有它，模型会把在场三个人写成一锅粥。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _setup(self):
        module = _module()
        self.db.add(module)
        await self.db.commit()
        npc = RpgNpc(module_id=module.id, name="老兵", location="地窖")
        self.db.add(npc)
        await self.db.commit()
        sess = _sess(location="地窖")
        sess.module_id = module.id
        self.db.add(sess)
        await self.db.commit()
        return module, sess, npc

    async def test_a_character_line_names_who_you_are_talking_to(self):
        module, sess, npc = await self._setup()
        messages, diag = await build_rpg_messages(
            self.db, module, sess, [], "你好", thread_id=npc.id
        )
        self.assertIn("老兵", messages[0]["content"])
        self.assertEqual(diag["thread"], {"id": npc.id, "name": "老兵"})

    async def test_the_scene_line_says_so(self):
        # 场面线不只是「独处」：三人同桌、群戏、环境描写都落这里，
        # 所以文案得说「公共场面」，否则玩家不知道该把群戏放哪
        module, sess, _npc = await self._setup()
        messages, diag = await build_rpg_messages(self.db, module, sess, [], "我看看四周")
        self.assertIn("公共场面", messages[0]["content"])
        self.assertIsNone(diag["thread"])


class AllowMoveTests(unittest.TestCase):
    """分线之后「在老兵线里被叙述走到别处」会变成看得见的 bug：

    老兵不在了，他的输入框永久置灰。所以角色线里丢掉 location。
    """

    def test_a_character_line_ignores_a_proposed_move(self):
        sess = _sess(location="地窖")
        warnings = apply_state_delta(
            _module(), sess, {"location": "铁匠铺"}, [], allow_move=False
        )
        self.assertEqual(sess.location, "地窖")
        self.assertTrue(any("地点" in w for w in warnings))

    def test_the_scene_line_still_moves(self):
        # 「自由打字绕过地图」是文档里明确保留的决定，边界就画在这里
        sess = _sess(location="地窖")
        apply_state_delta(_module(), sess, {"location": "铁匠铺"}, [])
        self.assertEqual(sess.location, "铁匠铺")

    def test_a_line_will_not_write_notes_about_someone_who_is_not_there(self):
        # 近况比关系数值收得更紧：数字下一轮会被盖掉，近况是长期事实，会一直
        # 画在角色卡上、每轮注入那个人的设定块。剧情里随口提一句名字不该算数
        npcs = [RpgNpc(id=3, module_id=1, name="赫敏")]
        sess = _sess(location="地窖", npc_notes={})
        warnings = apply_state_delta(
            _module(), sess, {"npc_notes": {"赫敏": {"伤势": "左肩中刀"}}},
            npcs, note_npcs=[],
        )
        self.assertEqual(sess.npc_notes, {})
        self.assertTrue(any("赫敏" in w for w in warnings))


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
