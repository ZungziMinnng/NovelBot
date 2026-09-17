"""每时段行动预算，和「该推时段了」那三条提醒。

起因是玩家会忘记按「结束这个时段」，而那是整个玩法里唯一一个「必须主动做、
不做也没有任何即时反馈」的操作。时钟一冻住，代价比「天数不动」大得多：
作息表不换班、剧情临时挪过的位置永久盖掉作者排的整张班表、勾了跨天回满的
数值永远不回满。所以这一批给了三条路，各管一件事：

A. slot_budget —— 数**行动**（点动作/道具/技能/移动），攒满自动推一格。
   不数对话：turn_count 对每条玩家消息无差别 +1，拿它当预算等于「话多的人
   时间流逝快」。
B. chat_nudge —— 数纯对话，**只点亮按钮，一格都不推**。
C. scene_wrapped —— 结算里 GM 的提议，同样只点亮按钮。

这里要钉的第一条、也是最要紧的一条：**slot_budget = 0（老模组的默认值）时
行为逐字不变**。剩下的都围绕两个顺序约束：预算推进必须在 apply_stats 之后
（否则跨天回满会抹掉这一格自己的消耗），两个计数器必须进快照（否则读档回到
「还剩两格」那一刻，下一个动作就把时段推走了）。
"""
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS, move_to
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgAction, RpgLocation, RpgMessage, RpgModule, RpgSave, RpgSession
from app.prompts.loader import render
from app.schemas.rpg import RpgMoveIn
from app.services.rpg_settlement import DOMAIN_FIELDS, DOMAINS, STATE_FIELDS
from app.services.rpg_state import (
    advance_slot, check_condition, init_stats, note_slot_chat, spend_slot_action,
)
from app.agents.rpg_turn import _action_gate, _move, _run_action

STAT_DEFS = [
    # 精力勾了跨天回满，用来验证自动推进和动作消耗的先后
    {"name": "精力", "initial": 100, "min": 0, "max": 100,
     "display": "条", "reset_daily": True},
    {"name": "资金", "initial": 300, "min": 0, "max": None, "display": "数字"},
]


def _module(**kwargs):
    base = {"stat_defs": STAT_DEFS, "relation_stat_defs": [],
            "time_slots": ["早", "中", "晚"], "slot_budget": 0, "chat_nudge": 0}
    base.update(kwargs)
    return RpgModule(user_id=1, name="测试模组", **base)


def _sess(**kwargs):
    base = {
        "stats": init_stats(STAT_DEFS),
        "time_slots": ["早", "中", "晚"],
        "slot": "早",
        "day": 1,
        "location": "办公室",
        "status": "alive",
        "slot_actions": 0,
        "slot_chats": 0,
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


def _action(**kwargs):
    base = {"name": "处理商业", "prompt_hint": "", "effects": {}, "relation_effects": {},
            "requires": {}, "needs_target": False, "group": "", "cost_slot": False,
            "at_location": ""}
    base.update(kwargs)
    return RpgAction(module_id=1, **base)


class BudgetDefaultTests(unittest.TestCase):
    """新建的模组默认 3，老模组存的 0 不动。

    默认 0 时时钟只有玩家主动按才走，而推时段带跨天恢复，于是「歇一晚」成了
    零成本回血，数值消耗不构成任何压力。真正生效的是 schema 上那个默认值——
    建模组这条路是 RpgModule(**data.model_dump())，列上的默认管不到它。
    """

    def test_a_newly_created_module_defaults_to_three(self):
        from app.schemas.rpg import RpgModuleCreate
        data = RpgModuleCreate(
            name="新模组", stat_defs=[], relation_stat_defs=[],
            default_inventory=[], default_location="", time_slots=["早", "晚"],
        )
        self.assertEqual(data.slot_budget, 3)
        self.assertEqual(RpgModule(**data.model_dump(), user_id=1).slot_budget, 3)


class BudgetOffTests(unittest.TestCase):
    """slot_budget = 0：老模组读出来就是这个形状，一格都不许自己走。"""

    def test_an_unset_budget_never_moves_the_clock(self):
        sess = _sess()
        for _ in range(20):
            self.assertEqual(spend_slot_action(_module(), sess), [])
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 1)

    def test_it_still_counts_so_turning_the_budget_on_later_works(self):
        # 计数照走，只是没人拿它比。作者中途填上上限，下一格就生效
        sess = _sess()
        spend_slot_action(_module(), sess)
        self.assertEqual(sess.slot_actions, 1)

    def test_a_null_column_counts_as_zero(self):
        # 老库的行 ALTER 出来是 NULL 而不是 0（DEFAULT 只管新插的行）。
        # 这里不能崩在 None + 1 上
        sess = _sess(slot_actions=None)
        self.assertEqual(spend_slot_action(_module(slot_budget=None), sess), [])
        self.assertEqual(sess.slot_actions, 1)


class BudgetSpendTests(unittest.TestCase):
    def test_filling_the_budget_advances_one_slot(self):
        sess = _sess()
        module = _module(slot_budget=3)
        self.assertEqual(spend_slot_action(module, sess), [])
        self.assertEqual(spend_slot_action(module, sess), [])
        facts = spend_slot_action(module, sess)
        self.assertEqual(sess.slot, "中")
        # 得说清楚是预算用完了，否则时段看着像自己乱跳
        self.assertTrue(any("这个时段" in fact for fact in facts))

    def test_the_counter_restarts_in_the_new_slot(self):
        sess = _sess()
        module = _module(slot_budget=2)
        spend_slot_action(module, sess)
        spend_slot_action(module, sess)
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.slot_actions, 0)

    def test_a_module_without_a_clock_says_nothing(self):
        # 没设时段的模组填了上限也不该有任何反应：advance_slot 空转，
        # 那句「这个时段的事做完了」也不能冒出来——界面上没有时钟
        sess = _sess(time_slots=[], slot="")
        module = _module(time_slots=[], slot_budget=1)
        self.assertEqual(spend_slot_action(module, sess), [])
        self.assertEqual(sess.day, 1)

    def test_the_new_day_starts_at_the_recovery_floor_not_pre_drained(self):
        """预算推进必须排在 apply_stats 之后，口径同 _run_action 里的 cost_slot。

        这一格的消耗属于旧的一天，恢复属于新的一天，所以「先扣再恢复」= 新的
        一天从恢复线（七成）起步。反过来排会把玩家点的最后一个动作的账结到
        第二天头上。

        起手压到 50 是为了让两种顺序分得开（满值时恢复是空操作，断言会永真）：
          先扣再恢复（对的）：50-30=20 → 抬到 70
          先恢复再扣（错的）：50→70 → -30 = 40
        """
        sess = _sess(slot="晚", stats={"精力": 50, "资金": 300})
        module = _module(slot_budget=1)
        _run_action(module, sess, _action(effects={"精力": -30}), None)
        spend_slot_action(module, sess)
        self.assertEqual(sess.day, 2)
        self.assertEqual(sess.stats["精力"], 70)

    def test_a_mid_slot_action_keeps_its_cost(self):
        # 上一条的对照：不跨天时消耗当然要留着
        sess = _sess(slot="早")
        module = _module(slot_budget=1)
        _run_action(module, sess, _action(effects={"精力": -30}), None)
        spend_slot_action(module, sess)
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.stats["精力"], 70)

    def test_a_blocked_action_is_not_a_move(self):
        """被拦下的动作不算「世界动了」，所以不吃一格。

        判据是 _action_gate，**不是 facts 非空**：拦下来那一路也会留一句
        「你本想…没能做成」，拿 facts 判会让「撞在门上」也吃掉一个行动位。
        这条测试就是钉住那个区别。
        """
        sess = _sess()
        blocked = _action(requires={"stats": {"资金": {"op": ">=", "value": 9999}}})
        self.assertTrue(_action_gate(sess, blocked, None))
        facts, _ = _run_action(_module(slot_budget=1), sess, blocked, None)
        # 它确实留了一句事实句 —— 所以 facts 不能当判据
        self.assertEqual(len(facts), 1)
        self.assertIn("没能做成", facts[0])
        # 数值一个没动，时段也没动
        self.assertEqual(sess.stats["精力"], 100)
        self.assertEqual(sess.slot, "早")

    def test_a_blocked_move_is_not_a_move_either(self):
        # 进不去的地点同理：人还在原地，_move 却留了一句「被挡在外面」
        sess = _sess()
        target = RpgLocation(
            module_id=1, name="地窖",
            enter_requires={"stats": {"资金": {"op": ">=", "value": 9999}}},
        )
        ok, _why = check_condition(target.enter_requires, sess, None)
        self.assertFalse(ok)
        facts = _move(sess, target, [])
        self.assertEqual(len(facts), 1)
        self.assertEqual(sess.location, "办公室")

    def test_a_cost_slot_action_still_takes_a_budget_slot(self):
        # 勾了 cost_slot 的动作已经自己推过一格，这里再记一格是对的：
        # 它确实占掉了这个时段的一个行动位。两者叠加就是推两格
        sess = _sess()
        module = _module(slot_budget=1)
        _run_action(module, sess, _action(cost_slot=True), None)
        self.assertEqual(sess.slot, "中")
        spend_slot_action(module, sess)
        self.assertEqual(sess.slot, "晚")


class MapMoveTests(unittest.IsolatedAsyncioTestCase):
    """从地点总览点图瞬移，也要吃掉一格行动。

    这一路第一版漏了：`/move` 路由走 move_by_name，压根不经过 _resolve_engine，
    于是玩家一直点地图移动，预算一格都不动、按钮永远不亮。点地图和打字说
    「我去后山」是同一件事，预算上不能有两个口径。

    用文件库而不是 :memory:，理由同 test_rpg_threads 的瞬移那一组：路由这边
    存档的写事务开着，共用一条连接看不出互锁。
    """

    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.tmp}/t.db")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = SimpleNamespace(id=1)
        module = _module(slot_budget=2)
        self.db.add(module)
        await self.db.commit()
        self.db.add_all([
            RpgLocation(module_id=module.id, name="铁匠铺"),
            RpgLocation(module_id=module.id, name="后山"),
            RpgLocation(module_id=module.id, name="禁地", enter_requires={
                "stats": {"资金": {"op": ">=", "value": 9999}}}),
        ])
        sess = RpgSession(
            module_id=module.id, char_name="阿隼", stats=init_stats(STAT_DEFS),
            location="办公室", time_slots=["早", "中", "晚"], slot="早", day=1,
            status="alive", slot_actions=0, slot_chats=0, chronicle=[],
        )
        self.db.add(sess)
        await self.db.commit()
        self.sess = sess

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def _go(self, target):
        out = await move_to(self.sess.id, RpgMoveIn(target=target), self.user, self.db)
        return out.message

    async def test_walking_there_spends_a_slot(self):
        await self._go("铁匠铺")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.slot_actions, 1)

    async def test_the_second_move_advances_the_clock(self):
        await self._go("铁匠铺")
        message = await self._go("后山")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.slot, "中")
        self.assertEqual(self.sess.slot_actions, 0)
        # 时段是自己翻的，得在那句话里说出来，否则时钟看着像自己乱跳
        self.assertIn("这个时段", message)

    async def test_a_place_you_cannot_enter_spends_nothing(self):
        # 被门槛挡住时 sess 一个字段都没动，人还在原地
        await self._go("禁地")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.location, "办公室")
        self.assertEqual(self.sess.slot_actions, 0)

    async def test_walking_where_you_already_are_spends_nothing(self):
        # 「你已经在这儿了」不是一次行动
        await self._go("铁匠铺")
        await self._go("铁匠铺")
        await self.db.refresh(self.sess)
        self.assertEqual(self.sess.slot_actions, 1)


class EngineWiringTests(unittest.IsolatedAsyncioTestCase):
    """整条线跑一遍：点动作 → _resolve_engine 记账 → 落库。

    上面每一块单测都绿、而中间那一行忘了拼（moved 没置上、或者记账排在
    check_zero 之后），是这类改动最常见的失败方式：没有任何报错，功能就是
    不生效，要等到玩的时候才发现。
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
                user_id=1, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[],
                time_slots=["早", "中", "晚"], slot_budget=2, chat_nudge=0,
            )
            db.add(module)
            await db.commit()
            db.add_all([
                RpgAction(module_id=module.id, name="加班", effects={"精力": -10}),
                RpgAction(module_id=module.id, name="翻保险柜", effects={"资金": 100},
                          requires={"stats": {"资金": {"op": ">=", "value": 9999}}}),
            ])
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats=init_stats(STAT_DEFS),
                location="办公室", slot="早", day=1, status="alive",
                slot_actions=0, slot_chats=0,
            )
            db.add(sess)
            await db.commit()
            self.session_id = sess.id
            self.ok_id, self.blocked_id = [
                row.id for row in (await db.execute(
                    select(RpgAction).where(RpgAction.module_id == module.id)
                )).scalars().all()
            ]

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    async def _click(self, action_id):
        return await rpg_turn._resolve_engine(self.session_id, action_id, "", "", "", "")

    async def _reload(self):
        async with self.sessions() as db:
            return await db.get(RpgSession, self.session_id)

    async def test_clicking_an_action_spends_a_slot_and_the_second_one_advances(self):
        await self._click(self.ok_id)
        self.assertEqual((await self._reload()).slot_actions, 1)
        facts, _warnings, state = await self._click(self.ok_id)
        sess = await self._reload()
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.slot_actions, 0)
        # 状态快照里也得带上，否则前端要等整页重拉才看到时段变了
        self.assertEqual(state["slot"], "中")
        self.assertTrue(any("这个时段" in fact for fact in facts))

    async def test_a_blocked_action_spends_nothing(self):
        # 这一条是 moved 那个标记存在的全部理由：拦下来那一路也留了事实句
        facts, _warnings, _state = await self._click(self.blocked_id)
        self.assertTrue(any("没能做成" in fact for fact in facts))
        sess = await self._reload()
        self.assertEqual(sess.slot_actions, 0)
        self.assertEqual(sess.slot, "早")


class ChatNudgeTests(unittest.TestCase):
    def test_talking_never_moves_the_clock(self):
        """纯对话只涨 slot_chats，时间一格都不动。

        「聊得久」不等于世界该变。这也是 A 不用 turn_count 的同一条理由。
        """
        sess = _sess()
        for _ in range(50):
            note_slot_chat(sess)
        self.assertEqual(sess.slot_chats, 50)
        self.assertEqual(sess.slot_actions, 0)
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 1)

    def test_a_null_column_counts_as_zero(self):
        sess = _sess(slot_chats=None)
        note_slot_chat(sess)
        self.assertEqual(sess.slot_chats, 1)


class ResetTests(unittest.TestCase):
    """归零只写在 advance_slot 里：手动按按钮、cost_slot、预算攒满三条路都经过它。"""

    def test_advancing_clears_both_counters(self):
        sess = _sess(slot_actions=2, slot_chats=7)
        advance_slot(_module(), sess)
        self.assertEqual(sess.slot_actions, 0)
        self.assertEqual(sess.slot_chats, 0)

    def test_rolling_over_to_a_new_day_clears_them_too(self):
        sess = _sess(slot="晚", slot_actions=2, slot_chats=7)
        advance_slot(_module(), sess)
        self.assertEqual(sess.day, 2)
        self.assertEqual(sess.slot_actions, 0)
        self.assertEqual(sess.slot_chats, 0)

    def test_no_clock_means_no_reset(self):
        # 没有时钟就没有「这一格」，按一下不该有任何后果。归零写在那个
        # 提前 return 之后就是为了这一条
        sess = _sess(time_slots=[], slot="", slot_actions=2, slot_chats=7)
        self.assertEqual(advance_slot(_module(time_slots=[]), sess), [])
        self.assertEqual(sess.slot_actions, 2)
        self.assertEqual(sess.slot_chats, 7)


class SnapshotTests(unittest.TestCase):
    def test_both_counters_are_snapshotted(self):
        # 漏了不报错、不失败，只会让读档之后的时段预算错位：回到「还剩两格」
        # 那一刻，下一个动作就把时段推走了，时钟看着像自己乱跳
        self.assertIn("slot_actions", SNAPSHOT_FIELDS)
        self.assertIn("slot_chats", SNAPSHOT_FIELDS)

    def test_old_snapshots_fall_back_to_zero(self):
        # 后加的字段必须配兜底，否则老快照里没有这个键，_rewind_to_save
        # 会跳过它、把当前值留在原地
        self.assertEqual(SNAPSHOT_DEFAULTS["slot_actions"], 0)
        self.assertEqual(SNAPSHOT_DEFAULTS["slot_chats"], 0)


class SceneWrappedTests(unittest.TestCase):
    """C：GM 的收尾提议。照 outcome_consistent 的先例，纯建议、零权限。"""

    def test_the_field_is_offered_when_there_is_a_clock(self):
        text = render(
            "rpg_settle.jinja2", narration="他推门走了出去。", outcome_label="",
            stats={}, location="办公室", place_note="", inventory=[], flags={},
            npcs=[], note_keys=[], relation_names=[], step_caps={},
            engine_note="", chronicle=[], tasks=[], has_clock=True,
        )
        self.assertIn("scene_wrapped", text)
        # 得写明写 true 有代价（free_costs_slot 开着就真占一格），否则模型会
        # 为了让剧情"有进展"随手写 true。原先这里断言的是「不会改变任何
        # 东西」——那句话在 free_costs_slot 落地之后是假的
        self.assertIn("占掉玩家一格时间", text)
        self.assertIn("拿不准就省略", text)

    def test_a_module_without_a_clock_is_never_asked(self):
        # 问了也没处用——那颗按钮根本不出现。多问一个字段只会让模型
        # 多一次机会写错 JSON
        text = render(
            "rpg_settle.jinja2", narration="他推门走了出去。", outcome_label="",
            stats={}, location="办公室", place_note="", inventory=[], flags={},
            npcs=[], note_keys=[], relation_names=[], step_caps={},
            engine_note="", chronicle=[], tasks=[], has_clock=False,
        )
        self.assertNotIn("scene_wrapped", text)

    def test_it_cannot_touch_any_state_field(self):
        """它不在任何一张改状态的表里，所以模型写 true 也一个字段都动不了。

        进了 STATE_FIELDS/DOMAINS/DOMAIN_FIELDS 就变成状态改写。
        free_costs_slot 之后它确实能动时段了，但那一格是**引擎**在
        rpg_turn 里推的（走 spend_slot_action），不是模型写进 delta 里的——
        这条边界没变，所以这三张表里仍然不该有它。
        """
        self.assertNotIn("scene_wrapped", STATE_FIELDS)
        for keys in DOMAINS.values():
            self.assertNotIn("scene_wrapped", keys)
        for fields in DOMAIN_FIELDS.values():
            self.assertNotIn("scene_wrapped", fields)


class FreeCostsSlotTests(unittest.IsolatedAsyncioTestCase):
    """D：free_costs_slot —— 自由打字演完一幕也吃一格。

    这是三条提醒里唯一一条真的动时间的，所以它必须**默认关**、而且只在
    「自由打字 + 结算判定收尾」这两个条件同时成立时才动。四条失败方式：
    开关关着也推（老模组的行为变了）、没收尾也推（聊两句就过完一天）、
    点按钮那轮重复推（_resolve_engine 已经记过一格）、推完没告诉前端
    （侧栏那排格子要等整页重拉才更新）。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patchers = [
            patch.object(rpg_turn, "AsyncSessionLocal", self.sessions),
            patch.object(rpg_turn, "build_rpg_messages", self._fake_context),
            patch.object(rpg_turn, "_settle", self._fake_settle),
            patch.object(rpg_turn, "_maybe_summarize", self._noop),
            patch.object(rpg_turn, "idle_npc_activities", self._noop),
            patch.object(rpg_turn.llm_client, "get_agent_client",
                         lambda *a, **k: ("fake-model", "openai")),
            patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage",
                         self._fake_stream),
        ]
        for p in self.patchers:
            p.start()
        # 结算判定这一幕收尾了没有。每条用例自己改
        self.wrapped = True
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[],
                time_slots=["早", "中", "晚"], slot_budget=2, chat_nudge=0,
                free_costs_slot=True,
            )
            db.add(module)
            await db.commit()
            db.add(RpgAction(module_id=module.id, name="加班", effects={"精力": -10}))
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats=init_stats(STAT_DEFS),
                location="办公室", slot="早", day=1, status="alive",
                slot_actions=0, slot_chats=0,
            )
            db.add_all([sess])
            await db.commit()
            self.module_id, self.session_id = module.id, sess.id
            self.action_id = (await db.execute(
                select(RpgAction).where(RpgAction.module_id == module.id)
            )).scalars().first().id

    async def asyncTearDown(self):
        for p in self.patchers:
            p.stop()
        await self.engine.dispose()

    # ── 替身 ──
    async def _fake_context(self, *args, **kwargs):
        return [{"role": "user", "content": "x"}], {"npcs_here": [], "npcs_onstage": []}

    async def _fake_settle(self, *args, **kwargs):
        return {
            "warnings": [], "state": {"stats": {}, "day": 1, "slot": "早"},
            "settlement": {}, "suggestions": [], "discoveries": [],
            "scene_wrapped": self.wrapped,
            "aux_input_tokens": 0, "aux_output_tokens": 0,
        }

    async def _noop(self, *args, **kwargs):
        return None

    async def _fake_stream(self, *args, **kwargs):
        yield "他推门走了出去。"
        yield ("他推门走了出去。", 10, 20)

    # ── 工具 ──
    async def _turn(self, **kwargs):
        """跑一轮，返回 (事件名 → 数据列表)。"""
        async with self.sessions() as db:
            row = RpgMessage(session_id=self.session_id, role="user", content="她多大了")
            db.add(row)
            await db.commit()
            user_message_id = row.id
        events: dict[str, list] = {}
        async for name, data in rpg_turn.run_turn(
            self.session_id, user_message_id, "她多大了", **kwargs
        ):
            events.setdefault(name, []).append(data)
        return events

    async def _reload(self):
        async with self.sessions() as db:
            return await db.get(RpgSession, self.session_id)

    async def _set_switch(self, on):
        async with self.sessions() as db:
            module = await db.get(RpgModule, self.module_id)
            module.free_costs_slot = on
            await db.commit()

    # ── 用例 ──
    async def test_the_switch_off_is_the_old_behaviour_to_the_letter(self):
        # 回归保护：老模组读出来就是这个形状，收尾也只点亮按钮
        await self._set_switch(False)
        events = await self._turn()
        self.assertEqual(events["slot_hint"], ["这一幕看着收尾了"])
        sess = await self._reload()
        self.assertEqual(sess.slot_actions, 0)
        self.assertEqual(sess.slot, "早")

    async def test_it_needs_a_budget_to_actually_move_the_clock(self):
        """只开这个开关、没配行动上限 = 记账照走，时钟一格不动。

        同 slot_budget = 0 那一整块：spend_slot_action 自己拦住了。所以
        作者只勾了这一个框也不会把老模组玩坏，最多是白记一个数。
        """
        async with self.sessions() as db:
            module = await db.get(RpgModule, self.module_id)
            module.slot_budget = 0
            await db.commit()
        await self._turn()
        sess = await self._reload()
        self.assertEqual(sess.slot_actions, 1)
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 1)

    async def test_chatting_without_wrapping_up_spends_nothing(self):
        # 这是整条设计的重点：「聊得久」不等于世界该变，只有「一幕演完了」算
        self.wrapped = False
        events = await self._turn()
        self.assertNotIn("slot_hint", events)
        self.assertEqual((await self._reload()).slot_actions, 0)

    async def test_wrapping_up_a_scene_spends_one_slot(self):
        events = await self._turn()
        sess = await self._reload()
        self.assertEqual(sess.slot_actions, 1)
        self.assertEqual(sess.slot, "早")
        # 推完必须再发一条 state，否则侧栏那排格子要等整页重拉才更新
        self.assertEqual(len(events["state"]), 2)

    async def test_the_second_wrapped_scene_turns_the_page(self):
        await self._turn()
        events = await self._turn()
        sess = await self._reload()
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.slot_actions, 0)
        # 翻篇那句话要并进提示里，否则时段看着像自己乱跳
        self.assertTrue(any("这个时段" in hint for hint in events["slot_hint"]))

    async def test_rolling_over_to_a_new_day_recovers_stats(self):
        # 最后一格推过去就是新的一天，跨天恢复跟着发生。这条是把
        # spend_slot_action → advance_slot → reset_daily 整条链钉住
        async with self.sessions() as db:
            sess = await db.get(RpgSession, self.session_id)
            sess.slot, sess.slot_actions = "晚", 1
            sess.stats = {**sess.stats, "精力": 10}
            await db.commit()
        await self._turn()
        sess = await self._reload()
        self.assertEqual(sess.day, 2)
        self.assertEqual(sess.slot, "早")
        # 恢复到上限的七成，不是回满
        self.assertEqual(sess.stats["精力"], 70)
        self.assertTrue(sess.chronicle)

    async def test_clicking_an_action_is_not_charged_twice(self):
        # _resolve_engine 已经记过一格了。这里再记就是一轮扣两格
        events = await self._turn(action_id=self.action_id)
        self.assertEqual((await self._reload()).slot_actions, 1)
        self.assertEqual(events["slot_hint"], ["这一幕看着收尾了"])

    async def test_it_leaves_a_save_you_can_rewind_to(self):
        """推完时钟这条剧情就重结算不了了，所以必须留一张能倒回来的档。

        rpg_settlement 的冲突守卫比的是 [day, slot, turn_count]，而这张档
        进了 SNAPSHOT_FIELDS 的那三项，读回去正好解开那道守卫。
        """
        await self._turn()
        async with self.sessions() as db:
            saves = (await db.execute(
                select(RpgSave).where(RpgSave.session_id == self.session_id)
            )).scalars().all()
        self.assertTrue(saves)
        self.assertEqual(saves[-1].state["slot_actions"], 0)


if __name__ == "__main__":
    unittest.main()
