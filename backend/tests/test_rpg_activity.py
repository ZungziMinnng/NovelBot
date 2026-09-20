"""AI 调度：这一轮没被提到的角色，自己过日子。

四条底线：

1. **没勾就是一次调用都没有**。勾了才有，而且勾了的人全在同一轮里就会被
   一次调用写完（一人一次 = 玩家为 N 次往返付钱等时间）。
2. 这一轮在场或被提到的人**不调度**——他们归叙事模型管，两边各写一份，
   玩家下回见到的会和自己刚经历的对不上。
3. 调度出来的句子只落在这个人身上，不进大事记、不动数值；随机移动由引擎执行。
4. 生成失败不能拖垮这一轮（它排在 done 之前，抛出去整轮就报错了）。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.agents import rpg_turn
from app.api.routes.rpg import update_npc
from app.database import Base
from app.models import sensitive_word, text_replace_backup, llm_usage
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgMessage, RpgSession
from app.schemas.rpg import RpgNpcCreate, RpgNpcOut, RpgNpcUpdate
from app.services.rpg_context import here_npcs, npc_place
from app.services.rpg_state import ACTIVITY_CHARS, apply_npc_activity, npc_activity

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


class ActivityStateTests(unittest.TestCase):
    """纯函数那一层：一个角色只有一句，清和写走同一条路。"""

    def _sess(self, **kw):
        return RpgSession(module_id=1, char_name="阿隼", npc_activities=kw.pop("acts", {}))

    def test_a_line_lands_under_the_id_as_a_string(self):
        sess = self._sess()
        apply_npc_activity(sess, 3, "在图书馆翻旧报纸")
        self.assertEqual(sess.npc_activities, {"3": "在图书馆翻旧报纸"})

    def test_a_second_line_replaces_the_first(self):
        # 这是「最近」，不是日志。留着旧的会长成一本流水账，
        # 而它每轮都要注入那个人的设定块
        sess = self._sess(acts={"3": "在图书馆"})
        apply_npc_activity(sess, 3, "在靶场练箭")
        self.assertEqual(sess.npc_activities, {"3": "在靶场练箭"})

    def test_a_blank_line_clears_it(self):
        sess = self._sess(acts={"3": "在图书馆"})
        apply_npc_activity(sess, 3, "  ")
        self.assertEqual(sess.npc_activities, {})
        self.assertEqual(npc_activity(sess, 3), "")

    def test_a_chatty_model_is_clamped(self):
        sess = self._sess()
        apply_npc_activity(sess, 3, "很长" * 200)
        self.assertEqual(len(sess.npc_activities["3"]), ACTIVITY_CHARS + 1)

    def test_clearing_one_leaves_the_others_alone(self):
        sess = self._sess(acts={"3": "在图书馆", "4": "在靶场"})
        apply_npc_activity(sess, 3, "")
        self.assertEqual(sess.npc_activities, {"4": "在靶场"})


class IdleNpcActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    async def _setup(self, *npcs, location="校长办公室", slot="晚", random_movement=False, places=()):
        """npcs 是 (名字, 常驻地点, ai_scheduled) 或 (名字, 常驻地, 调度, role)。"""
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="魔法学院", stat_defs=STAT_DEFS,
                relation_stat_defs=[], time_slots=["早", "中", "晚"],
            )
            db.add(module)
            await db.commit()
            ids = []
            for row in npcs:
                npc = RpgNpc(
                    module_id=module.id, name=row[0], location=row[1],
                    persona="好胜", ai_scheduled=row[2], random_movement=random_movement,
                    **({"role": row[3]} if len(row) > 3 else {}),
                )
                db.add(npc)
                await db.commit()
                ids.append(npc.id)
            db.add_all([RpgLocation(module_id=module.id, name=name) for name in places])
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={"精力": 100},
                location=location, slot=slot, day=3, status="alive",
                chronicle=[], npc_states={}, npc_activities={},
            )
            db.add(sess)
            await db.commit()
            return module.id, sess.id, ids

    async def _run(self, session_id, text="赫敏：在图书馆翻旧报纸", engaged=()):
        """跑一次调度，返回（写入的表, 模型收到的 prompt 列表）。"""
        prompts = []

        async def fake_dispatch(messages=None, **kwargs):
            prompts.append(messages[0]["content"])
            return text

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            got = await rpg_turn.idle_npc_activities(session_id, set(engaged))
        return got, prompts

    async def _saved(self, session_id):
        async with self.sessions() as db:
            return dict((await db.get(RpgSession, session_id)).npc_activities or {})

    async def test_nobody_scheduled_costs_nothing(self):
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", False))
        got, prompts = await self._run(session_id)
        self.assertEqual(got, {})
        self.assertEqual(prompts, [])
        self.assertEqual(await self._saved(session_id), {})

    async def test_someone_in_this_turn_is_left_to_the_narrator(self):
        # 她这一轮在场（或被提到），归叙事模型管。调度器再写一份，
        # 玩家下回见面时听到的会和自己刚经历的对不上
        _m, session_id, (npc_id,) = await self._setup(("赫敏", "格兰芬多塔", True))
        got, prompts = await self._run(session_id, engaged=[npc_id])
        self.assertEqual(got, {})
        self.assertEqual(prompts, [])
        self.assertEqual(await self._saved(session_id), {})

    async def test_an_idle_scheduled_npc_gets_a_line(self):
        _m, session_id, (npc_id,) = await self._setup(("赫敏", "格兰芬多塔", True))
        got, prompts = await self._run(session_id)
        self.assertEqual(got, {str(npc_id): "在图书馆翻旧报纸"})
        self.assertEqual(await self._saved(session_id), {str(npc_id): "在图书馆翻旧报纸"})
        # 提示词里得给她此刻在哪儿，不然模型只能瞎编一个地方
        self.assertIn("格兰芬多塔", prompts[0])
        self.assertIn("第 3 天", prompts[0])

    async def test_everybody_idle_is_written_in_one_call(self):
        _m, session_id, ids = await self._setup(
            ("赫敏", "格兰芬多塔", True), ("罗恩", "大厅", True),
        )
        got, prompts = await self._run(
            session_id, text="赫敏：在图书馆翻旧报纸\n罗恩：在大厅下棋",
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual(set(got), {str(i) for i in ids})

    async def test_the_previous_line_is_shown_so_it_is_not_repeated(self):
        _m, session_id, (npc_id,) = await self._setup(("赫敏", "格兰芬多塔", True))
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_activities = {str(npc_id): "在图书馆翻旧报纸"}
            await db.commit()
        _got, prompts = await self._run(session_id)
        self.assertIn("上次记下：在图书馆翻旧报纸", prompts[0])

    async def test_an_unknown_name_is_dropped_silently(self):
        # 认不出人就整行丢掉。这是玩家没要求过的后台动作，
        # 为它的瑕疵打断他一轮剧情不划算，所以不报 warning
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", True))
        got, _p = await self._run(session_id, text="马尔福：在斯莱特林公共休息室捣鬼")
        self.assertEqual(got, {})
        self.assertEqual(await self._saved(session_id), {})

    async def test_a_half_name_still_finds_her(self):
        # 模型写全名的场合很少，只认全等的话每轮都掉一条
        _m, session_id, (npc_id,) = await self._setup(("赫敏·格兰杰", "格兰芬多塔", True))
        got, _p = await self._run(session_id, text="赫敏：在图书馆翻旧报纸")
        self.assertEqual(got, {str(npc_id): "在图书馆翻旧报纸"})

    async def test_saying_nothing_is_allowed(self):
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", True))
        for said in ("赫敏：无", "赫敏：None", "赫敏：", "什么也没写"):
            with self.subTest(said=said):
                got, _p = await self._run(session_id, text=said)
                self.assertEqual(got, {})
        self.assertEqual(await self._saved(session_id), {})

    async def test_the_protagonist_template_is_never_scheduled(self):
        # 主角模板是玩家自己的卡，不登场，没有「她最近在做什么」这回事
        _m, session_id, _n = await self._setup(("阿隼", "校长办公室", True, "protagonist"))
        got, prompts = await self._run(session_id)
        self.assertEqual(got, {})
        self.assertEqual(prompts, [])

    async def test_a_failing_model_does_not_break_the_turn(self):
        # 它排在 done 之前，抛出去玩家看到的是一整轮报错
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", True))
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete",
                          side_effect=RuntimeError("炸了")):
            got = await rpg_turn.idle_npc_activities(session_id, set())
        self.assertEqual(got, {})
        self.assertEqual(await self._saved(session_id), {})

    async def test_it_never_touches_the_chronicle(self):
        # 这是「她一个人干了什么」，不是「已经传开的事」。写进大事记等于
        # 每条对话线上的所有人都知道了，chronicle 那条规矩禁的正是这个
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", True))
        await self._run(session_id)
        async with self.sessions() as db:
            self.assertEqual(list((await db.get(RpgSession, session_id)).chronicle or []), [])

    async def test_random_movement_needs_no_home_schedule_or_clock(self):
        module_id, session_id, (npc_id,) = await self._setup(
            ("赫敏", "", True), slot="", random_movement=True, places=("图书馆", "寝室", "  "),
        )
        async with self.sessions() as db:
            module = await db.get(RpgModule, module_id)
            module.time_slots = []
            other = RpgModule(name="另一个模组")
            db.add(other)
            await db.flush()
            db.add(RpgLocation(module_id=other.id, name="其他世界"))
            await db.commit()
        with patch.object(rpg_turn.random, "choice", return_value="图书馆") as choose:
            _, prompts = await self._run(session_id)
        self.assertEqual(choose.call_args.args[0], ["图书馆", "寝室"])
        self.assertIn("赫敏：在图书馆", prompts[0])
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            npc = await db.get(RpgNpc, npc_id)
            self.assertEqual(sess.npc_places, {str(npc_id): "图书馆"})
            self.assertEqual(npc_place(npc, sess.slot, sess.npc_places), "图书馆")
            self.assertEqual(here_npcs([npc], "图书馆", sess.slot, sess.npc_places), [npc])
            self.assertEqual(rpg_turn._state_payload(sess)["npc_places"], sess.npc_places)
            self.assertEqual(npc.location, "")
        await self._run(session_id)
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {str(npc_id): "寝室"})

    async def test_random_movement_leaves_engaged_present_and_following_npcs_alone(self):
        _, session_id, identities = await self._setup(
            ("被提到的人", "寝室", True), ("在场的人", "校长办公室", True),
            ("跟随的人", "寝室", True), ("正文人物", "寝室", True),
            ("主角模板", "寝室", True, "protagonist"), ("未启用调度", "寝室", False),
            random_movement=True, places=("图书馆",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_followers = [identities[2]]
            sess.npc_places = {str(identities[2]): "寝室"}
            db.add(RpgMessage(session_id=session_id, role="assistant", content="正文人物走出了房间。"))
            await db.commit()
        with patch.object(rpg_turn.random, "choice") as choose:
            await self._run(session_id, engaged=[identities[0]])
        choose.assert_not_called()
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places,
                {str(identities[2]): "寝室"},
            )

    async def test_random_movement_is_opt_in(self):
        _, session_id, _ = await self._setup(("赫敏", "寝室", True), places=("图书馆",))
        await self._run(session_id)
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})

    async def test_random_movement_handles_zero_or_one_location(self):
        for places in ((), ("寝室",)):
            with self.subTest(places=places):
                _, session_id, (npc_id,) = await self._setup(
                    ("赫敏", "寝室", True), random_movement=True, places=places,
                )
                await self._run(session_id, text="赫敏：无")
                async with self.sessions() as db:
                    sess = await db.get(RpgSession, session_id)
                    self.assertEqual(sess.npc_places, {str(npc_id): "寝室"} if places else {})

    async def test_random_movement_survives_activity_generation_failure(self):
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True, places=("图书馆",),
        )
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", side_effect=RuntimeError("模型失败")):
            self.assertEqual(await rpg_turn.idle_npc_activities(session_id, set()), {})
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {str(npc_id): "图书馆"})


class TurnSchedulingTests(unittest.IsolatedAsyncioTestCase):
    """第五条底线：调度只在**这一轮时段真的翻篇了**的时候跑。

    从前每轮都调一次。可它问的是「不在跟前的那个人最近在做什么」——时段没动，
    答案和上一轮不会有区别，那一次调用是白花的。钉三件事：没翻篇的回合一次
    调用都不发；翻篇的回合照旧要发；跳过的回合末尾那条 state 也照旧要发，
    冷却倒计时和这一格的聊天数只走它。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        # 结算判定这一幕收尾了没有。配上 free_costs_slot + slot_budget=1，
        # 收尾就是这条用例里推动时钟的那只手
        self.wrapped = True
        self.scheduled = []
        self.patchers = [
            patch.object(rpg_turn, "AsyncSessionLocal", self.sessions),
            patch.object(rpg_turn, "build_rpg_messages", self._fake_context),
            patch.object(rpg_turn, "_settle", self._fake_settle),
            patch.object(rpg_turn, "_maybe_summarize", self._noop),
            patch.object(rpg_turn, "idle_npc_activities", self._fake_schedule),
            patch.object(rpg_turn.llm_client, "get_agent_client",
                         lambda *a, **k: ("fake-model", "openai")),
            patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage", self._fake_stream),
        ]
        for p in self.patchers:
            p.start()
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="魔法学院", stat_defs=STAT_DEFS, relation_stat_defs=[],
                time_slots=["早", "中", "晚"], slot_budget=1, free_costs_slot=True,
            )
            db.add(module)
            await db.commit()
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={"精力": 100},
                location="校长办公室", slot="早", day=1, status="alive",
                npc_states={}, npc_activities={},
            )
            db.add(sess)
            await db.commit()
            self.session_id = sess.id

    async def asyncTearDown(self):
        for p in self.patchers:
            p.stop()
        await self.engine.dispose()

    async def _fake_context(self, *args, **kwargs):
        return [{"role": "user", "content": "x"}], {"npcs_here": [], "npcs_onstage": []}

    async def _fake_settle(self, *args, **kwargs):
        return {
            "warnings": [], "state": {"stats": {}, "day": 1, "slot": "早"},
            "settlement": {"status": "done"}, "suggestions": [], "discoveries": [],
            "scene_wrapped": self.wrapped,
            "aux_input_tokens": 0, "aux_output_tokens": 0,
        }

    async def _noop(self, *args, **kwargs):
        return None

    async def _fake_schedule(self, session_id, engaged):
        self.scheduled.append(engaged)
        return {}

    async def _fake_stream(self, *args, **kwargs):
        yield "他推门走了出去。"
        yield ("他推门走了出去。", 10, 20)

    async def _turn(self):
        async with self.sessions() as db:
            row = RpgMessage(session_id=self.session_id, role="user", content="她多大了")
            db.add(row)
            await db.commit()
            message_id = row.id
        events: dict[str, list] = {}
        async for name, data in rpg_turn.run_turn(self.session_id, message_id, "她多大了"):
            events.setdefault(name, []).append(data)
        return events

    async def test_a_turn_that_does_not_move_the_clock_never_calls_it(self):
        self.wrapped = False
        events = await self._turn()
        self.assertEqual(self.scheduled, [])
        # 跳过调度也要把末尾那条 state 发出去：冷却和这一格的聊天数不在
        # STATE_FIELDS 里，结算那条 state 带不上，吞掉它玩家会看到一颗
        # 明明已经能点的技能还灰着
        self.assertIn("state", events)
        self.assertIn("done", events)

    async def test_a_turn_that_moves_the_clock_still_calls_it(self):
        events = await self._turn()
        self.assertEqual(self.scheduled, [set()])
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, self.session_id)).slot, "中")
        self.assertIn("done", events)


class NpcWritePathTests(unittest.IsolatedAsyncioTestCase):
    """角色卡上这两栏的写入链路：路由 → 模型 → 再读回来。

    这一段原先一条用例都没有。没有它的后果是「勾了又没了」只能靠前端猜——
    而后端这一层是 `setattr` 通用循环，字段名差一个字不报错，只会**静静地
    不生效**，前端显示的还是用户自己刚点的那个值。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        self.module = RpgModule(user_id=1, name="魔法学院", stat_defs=STAT_DEFS,
                                time_slots=["早", "中", "晚"])
        self.db.add(self.module)
        await self.db.commit()
        self.npc = RpgNpc(module_id=self.module.id, name="赫敏", location="大礼堂")
        self.db.add(self.npc)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _patch(self, **fields):
        """走真正的路由函数，再另开一个 session 读回来——同一个 session 读到的
        是身份映射里那个对象，就算没落库也会显示新值。"""
        await update_npc(self.npc.id, RpgNpcUpdate(**fields), self.user, self.db)
        async with self.sessions() as other:
            return await other.get(RpgNpc, self.npc.id)

    async def test_the_switch_survives_the_round_trip(self):
        self.assertTrue((await self._patch(ai_scheduled=True)).ai_scheduled)

    async def test_random_movement_survives_the_round_trip_and_can_be_disabled(self):
        self.assertFalse(RpgNpcCreate(name="赫敏").random_movement)
        npc = await self._patch(ai_scheduled=True, random_movement=True, location="")
        self.assertTrue(RpgNpcOut.model_validate(npc).random_movement)
        self.assertEqual(npc.location, "")
        self.assertFalse((await self._patch(random_movement=False)).random_movement)

    async def test_random_movement_migration_keeps_existing_npcs_opted_out(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE rpg_npcs DROP COLUMN random_movement"))
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        async with self.sessions() as db:
            npc = await db.get(RpgNpc, self.npc.id)
            self.assertFalse(npc.random_movement)

    async def test_turning_it_off_is_not_swallowed_by_exclude_none(self):
        # 路由是 `model_dump(exclude_none=True)`。False 不是 None，所以关得掉——
        # 但这条只有钉住了才知道：写成 `if value:` 之类的过滤会让「关掉它」
        # 变成一次静默的空操作，而界面上的勾已经没了
        await self._patch(ai_scheduled=True)
        self.assertFalse((await self._patch(ai_scheduled=False)).ai_scheduled)

    async def test_the_schedule_survives_the_round_trip(self):
        # 作息表和这个勾在同一个表单里，是同一次「保存」送出来的，一起钉
        got = await self._patch(slot_locations={"早": "大礼堂", "晚": "寝室"})
        self.assertEqual(got.slot_locations, {"早": "大礼堂", "晚": "寝室"})

    async def test_an_untouched_field_is_not_reset_by_a_targeted_patch(self):
        # 前端那两个「立刻生效」的开关只发自己那一个字段，别的一律不许动
        await self._patch(slot_locations={"晚": "寝室"}, ai_scheduled=True)
        got = await self._patch(ai_scheduled=False)
        self.assertEqual(got.slot_locations, {"晚": "寝室"})
        self.assertEqual(got.location, "大礼堂")


class ActivityInjectionTests(unittest.IsolatedAsyncioTestCase):
    """调度记下的那句话要真的进提示词，否则整个功能只是个没人读的记事本。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.module = RpgModule(user_id=1, name="魔法学院", stat_defs=STAT_DEFS)
        self.db.add(self.module)
        await self.db.commit()
        self.npc = RpgNpc(
            module_id=self.module.id, name="赫敏", location="走廊",
            persona="好胜", ai_scheduled=True,
        )
        self.db.add(self.npc)
        await self.db.commit()
        self.sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={"精力": 100},
            location="走廊", slot="晚", npc_states={}, npc_notes={}, npc_activities={},
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _system(self, text="你好"):
        from app.services.rpg_context import build_rpg_messages
        messages, _diag = await build_rpg_messages(
            self.db, self.module, self.sess, [], text, None, None
        )
        return messages[0]["content"]

    async def test_the_line_shows_up_next_time_she_is_on_stage(self):
        self.sess.npc_activities = {str(self.npc.id): "在图书馆翻旧报纸"}
        self.assertIn("最近：在图书馆翻旧报纸", await self._system())

    async def test_no_line_no_extra_row(self):
        # 没调度过的人不该在卡上多出一行空的
        self.assertNotIn("最近：", await self._system())


if __name__ == "__main__":
    unittest.main()
