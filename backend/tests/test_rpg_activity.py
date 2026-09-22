"""AI 调度：这一轮没被提到的角色，自己过日子。

四条底线：

1. **没勾就是一次调用都没有**。勾了才有，而且勾了的人全在同一轮里就会被
   一次调用写完（一人一次 = 玩家为 N 次往返付钱等时间）。
2. 这一轮在场或被提到的人**不调度**——他们归叙事模型管，两边各写一份，
   玩家下回见到的会和自己刚经历的对不上。
3. 调度出来的句子只落在这个人身上，不进大事记、不动数值；随机移动由引擎执行。
4. 生成失败不能拖垮这一轮（它排在 done 之前，抛出去整轮就报错了）。
"""
import asyncio
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
from app.services.rpg_state import (
    ACTIVITY_CHARS, ACTIVITY_LOG_LINES, apply_npc_activity, npc_activity,
)

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


class ActivityStateTests(unittest.TestCase):
    """纯函数那一层：一个角色只有一句，清和写走同一条路。"""

    def _sess(self, **kw):
        return RpgSession(
            module_id=1, char_name="阿隼", npc_activities=kw.pop("acts", {}),
            npc_activity_log=kw.pop("log", {}),
            day=kw.pop("day", 1), slot=kw.pop("slot", "早"),
        )

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


class ActivityLogTests(unittest.TestCase):
    """被盖掉的那句话按时段留的底。

    存在的理由就是玩家按一串「结束时段」时看到的那个「诡异」：调度每格都刷
    「最近」，而经历只有结算写、结算只写在场的人，于是档案里一片空白。
    """

    def _sess(self, **kw):
        return RpgSession(
            module_id=1, char_name="阿隼", npc_activities=kw.pop("acts", {}),
            npc_activity_log=kw.pop("log", {}),
            day=kw.pop("day", 1), slot=kw.pop("slot", "早"),
        )

    def test_writing_a_line_stamps_it_with_the_clock(self):
        sess = self._sess(day=3, slot="晚")
        apply_npc_activity(sess, 3, "在图书馆翻旧报纸")
        self.assertEqual(sess.npc_activity_log, {
            "3": [{"day": 3, "slot": "晚", "content": "在图书馆翻旧报纸"}],
        })

    def test_a_new_slot_appends_instead_of_replacing(self):
        # 「最近」被盖掉了，但那一格她做过的事不该跟着消失——这一整列就是为此存在
        sess = self._sess(day=3, slot="中")
        apply_npc_activity(sess, 3, "在图书馆")
        sess.slot = "晚"
        apply_npc_activity(sess, 3, "在靶场练箭")
        self.assertEqual(sess.npc_activities, {"3": "在靶场练箭"})
        self.assertEqual([row["slot"] for row in sess.npc_activity_log["3"]], ["中", "晚"])

    def test_the_same_slot_keeps_only_the_last_line(self):
        # 回合那条路上调度每轮都跑，一格里能跑好几次。不去重的话一天就撑满窗口
        sess = self._sess(day=3, slot="晚")
        apply_npc_activity(sess, 3, "在图书馆")
        apply_npc_activity(sess, 3, "改主意去了靶场")
        self.assertEqual(sess.npc_activity_log["3"], [
            {"day": 3, "slot": "晚", "content": "改主意去了靶场"},
        ])

    def test_the_same_slot_on_a_different_day_is_a_different_row(self):
        sess = self._sess(day=3, slot="晚")
        apply_npc_activity(sess, 3, "在图书馆")
        sess.day = 4
        apply_npc_activity(sess, 3, "还在图书馆")
        self.assertEqual([row["day"] for row in sess.npc_activity_log["3"]], [3, 4])

    def test_the_window_drops_the_oldest(self):
        sess = self._sess()
        for day in range(1, ACTIVITY_LOG_LINES + 4):
            sess.day = day
            apply_npc_activity(sess, 3, f"第 {day} 天在忙")
        rows = sess.npc_activity_log["3"]
        self.assertEqual(len(rows), ACTIVITY_LOG_LINES)
        self.assertEqual(rows[0]["day"], 4)  # 前三天被挤掉了
        self.assertEqual(rows[-1]["day"], ACTIVITY_LOG_LINES + 3)

    def test_clearing_the_current_line_leaves_the_log_alone(self):
        # 划掉「最近」是说「别再拿它编下去」，不是说那几天没发生过。
        # 跟着清的话玩家手一抖就把一整段流水删了，而且没有撤销
        sess = self._sess(day=3, slot="晚")
        apply_npc_activity(sess, 3, "在图书馆")
        apply_npc_activity(sess, 3, "")
        self.assertEqual(sess.npc_activities, {})
        self.assertEqual(len(sess.npc_activity_log["3"]), 1)

    def test_two_people_keep_separate_lines(self):
        sess = self._sess(day=3, slot="晚")
        apply_npc_activity(sess, 3, "在图书馆")
        apply_npc_activity(sess, 4, "在靶场")
        self.assertEqual(sorted(sess.npc_activity_log), ["3", "4"])

    def test_the_log_never_lands_in_the_prompt(self):
        # 这一列是模型凭人设编的，没有正文依据。喂回去等于让它把自己编的
        # 背景当成发生过的事实接着编。改注入那一段时这条会红
        from app.services import rpg_context
        import inspect
        self.assertNotIn("npc_activity_log", inspect.getsource(rpg_context))


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

    async def _setup(
        self, *npcs, location="校长办公室", slot="晚", random_movement=False, places=(),
        random_places=(),
    ):
        """npcs 是 (名字, 常驻地点, ai_scheduled) 或 (名字, 常驻地, 调度, role)。

        places 是模组里有哪些地点，random_places 是随机移动的白名单（空 = 不限制）。
        """
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
                    random_movement_places=list(random_places),
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

    async def _run(self, session_id, text="赫敏：在图书馆翻旧报纸", engaged=(), from_clock=False):
        """跑一次调度，返回（写入的表, 模型收到的 prompt 列表）。"""
        prompts = []

        async def fake_dispatch(messages=None, **kwargs):
            prompts.append(messages[0]["content"])
            return text

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            got = await rpg_turn.idle_npc_activities(
                session_id, set(engaged), from_clock=from_clock,
            )
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
        _, prompts = await self._run(session_id, text="赫敏：图书馆｜在图书馆翻旧报纸")
        # 候选摆在模型面前，而且只有这个模组的地点（空白名过滤掉，别的模组不串）。
        # **只认名单里有谁，不认次序**：候选顺序每次洗过（见 idle_npc_activities
        # 里 random.shuffle 那段），原来这里写死了「图书馆、寝室」，于是这条
        # 测试有一半概率自己红给你看
        line = next(l for l in prompts[0].splitlines() if "。可去：" in l)
        self.assertEqual(
            sorted(line.split("。可去：")[1].split("、")), sorted(["图书馆", "寝室"]),
        )
        self.assertNotIn("其他世界", prompts[0])
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            npc = await db.get(RpgNpc, npc_id)
            self.assertEqual(sess.npc_places, {str(npc_id): "图书馆"})
            self.assertEqual(npc_place(npc, sess.slot, sess.npc_places), "图书馆")
            self.assertEqual(here_npcs([npc], "图书馆", sess.slot, sess.npc_places), [npc])
            self.assertEqual(rpg_turn._state_payload(sess)["npc_places"], sess.npc_places)
            self.assertEqual(npc.location, "")
        # 第二轮她已经在图书馆了，候选里就不该再有图书馆
        _, prompts = await self._run(session_id, text="赫敏：寝室｜在寝室补觉")
        self.assertIn("可去：寝室", prompts[0])
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
        _got, prompts = await self._run(session_id, engaged=[identities[0]])
        # 一个「可去」都不给 = 模型根本没有挪人的入口
        self.assertNotIn("。可去：", prompts[0])
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places,
                {str(identities[2]): "寝室"},
            )

    async def test_the_clock_does_not_reuse_the_last_narrative_as_a_shield(self):
        # 按按钮不产生正文，last 会一直停在同一条消息上。回合那条路拿它当
        # 「刚露过面的人别瞬移」的名单是对的，时钟这条路上它是粘住的：
        # 不放开的话，上一轮点过名的人连按几格都动不了
        _, session_id, (npc_id,) = await self._setup(
            ("正文人物", "寝室", True), random_movement=True, places=("图书馆",),
        )
        async with self.sessions() as db:
            db.add(RpgMessage(session_id=session_id, role="assistant", content="正文人物走出了房间。"))
            await db.commit()
        await self._run(session_id, text="正文人物：图书馆｜在图书馆看书", from_clock=True)
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places, {str(npc_id): "图书馆"},
            )

    async def test_the_clock_still_leaves_followers_and_present_npcs_alone(self):
        # 放开的只有「正文里点过名」这一条。跟着走的人和站在玩家跟前的人
        # 照旧不挪——把他们挪走等于当着玩家的面凭空消失
        _, session_id, identities = await self._setup(
            ("跟随的人", "寝室", True), ("在场的人", "校长办公室", True),
            random_movement=True, places=("图书馆",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_followers = [identities[0]]
            sess.npc_places = {str(identities[0]): "寝室"}
            await db.commit()
        _got, prompts = await self._run(session_id, text="赫敏：无", from_clock=True)
        self.assertNotIn("。可去：", prompts[0])
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places,
                {str(identities[0]): "寝室"},
            )

    async def test_someone_who_promised_to_wait_is_not_moved(self):
        """她答应了等你，按一下结束时段就被扔到公园去，那个约当场作废。

        **拦在引擎这一层**：候选地点是引擎给的，许过约的人一个候选都拿不到，
        模型也就没有挪走她的入口——光靠提示词里那句「和承诺对得上」不够，
        那是一句可以被无视的话。
        """
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "家", True), random_movement=True, places=("公园",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_notes = {str(npc_id): {"约定": "答应了等你回来吃午饭"}}
            await db.commit()
        # 就算模型自作主张写了地点也白写：她没有候选，那半句不予采信
        _got, prompts = await self._run(session_id, text="赫敏：公园｜在公园散步", from_clock=True)
        self.assertNotIn("。可去：", prompts[0])
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})
        # 那个约也摆在模型面前了，否则它照旧会写一句和它冲突的话
        self.assertIn("答应了等你回来吃午饭", prompts[0])

    async def test_an_ordinary_note_does_not_pin_her_down(self):
        # 只有「等你 / 答应」这类话才算约。伤势、情绪这些近况占大多数，
        # 一并当成约的话勾了随机移动的人基本就再也不动了
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "家", True), random_movement=True, places=("公园",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_notes = {str(npc_id): {"伤势": "左肩还在流血", "情绪": "有点紧张"}}
            await db.commit()
        await self._run(session_id, text="赫敏：公园｜在公园长椅上歇着", from_clock=True)
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places, {str(npc_id): "公园"},
            )

    async def test_notes_reach_the_scheduler_at_all(self):
        # 这个洞就是「调度不读正文、也没拿到近况」。承诺记在近况里，
        # 不给的话它只知道她的性格和位置
        _, session_id, (npc_id,) = await self._setup(("赫敏", "家", True))
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_notes = {str(npc_id): {"伤势": "左肩还在流血"}}
            await db.commit()
        _got, prompts = await self._run(session_id)
        self.assertIn("左肩还在流血", prompts[0])

    async def test_the_model_picks_the_destination_from_its_own_shortlist(self):
        """去处由模型挑，引擎只发候选。

        从前是 `random.choice(候选)`，它没有任何是非判断——公园、厕所、
        女子浴室在它眼里等价，真实存档里出现过「她被挪到菜市场厕所」。
        模型手上有她的人设和近况，挑得出说得通的那个。
        """
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林", "厕所"),
        )
        got, prompts = await self._run(session_id, text="赫敏：图书馆｜在图书馆翻旧报纸")
        # 三个都摆出来，让它自己挑
        for name in ("图书馆", "禁林", "厕所"):
            self.assertIn(name, prompts[0])
        self.assertEqual(got, {str(npc_id): "在图书馆翻旧报纸"})
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            # 位置和那句话是同一行写出来的，天然对得上
            self.assertEqual(sess.npc_places, {str(npc_id): "图书馆"})
            # 账本也要记：到期规则靠它认出「这条覆盖是调度写的」
            self.assertEqual(sess.npc_random_places, {str(npc_id): "图书馆"})

    async def test_the_shortlist_order_is_shuffled_so_one_place_is_not_always_first(self):
        """候选顺序每次洗一遍。

        白名单是按模组地点表排的，每一格给模型的是同一份、同一个顺序的名单，
        它手上另外那几样（人设、位置、上次那句）也几乎不变——于是它每次都挑
        同一个，玩家看到的是「一直在那几个地方」。同样的输入本该得到同样的
        输出，随机性得由我们给。洗顺序而不是替它抽签：抽签抽不出「厕所和
        公园不一样」，那正是当初把 random.choice 拿掉的理由。
        """
        _, session_id, _ = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=tuple(f"地点{i}" for i in range(12)),
        )
        firsts = set()
        for _ in range(12):
            _got, prompts = await self._run(session_id, text="赫敏：在寝室看书")
            # 认名单那一行，不是开头讲写法那段（它里头也有「可去：甲、乙、丙」，
            # 取第一条匹配会永远读到那句样例）
            line = next(l for l in prompts[0].splitlines() if "。可去：" in l)
            firsts.add(line.split("。可去：")[1].split("、")[0])
        # 12 个候选洗 12 次还只出现过一个排头，那就是没洗
        self.assertGreater(len(firsts), 1)

    async def test_she_is_told_where_she_went_last_time_so_she_moves_on(self):
        """上一格被挪去的地方要告诉模型，否则它没有理由让她换地方。

        洗牌只去掉「天生排第一」，可她此刻就在上次那个地方，模型照人设推，
        最说得通的往往还是留下——「一直在那几个地方」的另一半原因在这儿。
        用的是 npc_random_places（账本本来就记着），不新存一份。
        """
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True, places=("图书馆", "禁林"),
        )
        # 断言只看名单那一行：开头讲写法那段也提了「上次去的」
        def roster(prompt):
            return next(l for l in prompt.splitlines() if "。可去：" in l)

        # 第一格：她还没被挪过，这一行不该出现「上次去的」
        _got, prompts = await self._run(session_id, text="赫敏：图书馆｜在翻旧报纸")
        self.assertNotIn("上次去的", roster(prompts[0]))
        # 第二格：账本里已经有图书馆了，就得摆出来让它换一个
        _got, prompts = await self._run(session_id, text="赫敏：禁林｜在林边走走")
        self.assertIn("上次去的：图书馆", roster(prompts[0]))
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            self.assertEqual(sess.npc_random_places, {str(npc_id): "禁林"})

    async def test_choosing_to_stay_put_writes_nothing(self):
        # 模型判断她该留在原地就别写地点。这时候不该有任何位置写入——
        # 写一条「她在寝室」的覆盖等于把作息表永久盖掉
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True, places=("图书馆",),
        )
        got, _p = await self._run(session_id, text="赫敏：在寝室整理笔记")
        self.assertEqual(got, {str(npc_id): "在寝室整理笔记"})
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            self.assertEqual(sess.npc_places, {})
            self.assertEqual(sess.npc_random_places, {})

    async def test_a_dangling_separator_is_not_taken_as_a_move(self):
        # 竖线一侧空着 = 半句话。拿它换一次位置改动不划算，当它只写了活动
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True, places=("图书馆",),
        )
        for said in ("赫敏：图书馆｜", "赫敏：｜在图书馆看书"):
            with self.subTest(said=said):
                await self._run(session_id, text=said)
                async with self.sessions() as db:
                    self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})

    async def test_a_half_width_bar_works_too(self):
        # 全角竖线是模板要求的写法，半角是模型自己换的，两种都收（同冒号）
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True, places=("图书馆",),
        )
        await self._run(session_id, text="赫敏：图书馆|在图书馆看书")
        async with self.sessions() as db:
            self.assertEqual(
                (await db.get(RpgSession, session_id)).npc_places, {str(npc_id): "图书馆"},
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
                await self._run(session_id, text="赫敏：寝室｜在寝室补觉")
                async with self.sessions() as db:
                    sess = await db.get(RpgSession, session_id)
                    # 她已经在寝室了，两种情况候选都是空的 → 一个字都不写
                    self.assertEqual(sess.npc_places, {})

    async def test_random_movement_stays_inside_the_place_whitelist(self):
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林", "寝室"), random_places=("图书馆",),
        )
        # 候选只给白名单里那一个，禁林/寝室连露脸的机会都没有
        _got, prompts = await self._run(session_id, text="赫敏：禁林｜在禁林转了转")
        self.assertIn("可去：图书馆", prompts[0])
        self.assertNotIn("禁林", prompts[0])
        # 模型硬写一个不在候选里的地名 → 那半句作废，人不动
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})

    async def test_a_whitelist_of_only_her_own_place_keeps_her_put(self):
        # 白名单只勾了她此刻所在的地方：候选为空，等于不准动。
        # **绝不能退回全量地点表**——那是个不报错的静默破功
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林", "寝室"), random_places=("寝室",),
        )
        _got, prompts = await self._run(session_id, text="赫敏：图书馆｜在图书馆看书")
        self.assertNotIn("。可去：", prompts[0])
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})

    async def test_a_fully_stale_whitelist_moves_nobody(self):
        # 地点改名/删了之后白名单整张对不上。滤完候选为空 → 不动，
        # 比「退回全量地点表」安全
        _, session_id, _ = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林"), random_places=("早就删了的密室",),
        )
        _got, prompts = await self._run(session_id, text="赫敏：图书馆｜在图书馆看书")
        self.assertNotIn("。可去：", prompts[0])
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgSession, session_id)).npc_places, {})

    async def test_moving_a_place_out_of_the_whitelist_expires_the_override(self):
        # 作者事后改白名单：她上次被挪去图书馆，现在图书馆不在名单里了，
        # 那条覆盖当场过期，位置落回作息表 / 常驻地点
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林"), random_places=("禁林",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_places = {str(npc_id): "图书馆"}
            sess.npc_random_places = {str(npc_id): "图书馆"}
            await db.commit()
        await self._run(session_id, text="赫敏：禁林｜在禁林采药")
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            # 过期之后这一轮又重新挑了一次，落点只可能在白名单里
            self.assertNotEqual(sess.npc_places.get(str(npc_id)), "图书馆")
            self.assertNotIn("图书馆", (sess.npc_random_places or {}).values())

    async def test_a_hanging_model_gives_up_instead_of_holding_the_whole_session(self):
        # 底层 httpx 没设超时，OpenAI SDK 的默认值是 read 600 秒 × 最多 3 次尝试。
        # 这一次跑在 exclusive_session 的租约里、心跳会替它一直续期，所以不夹
        # 一刀的话卡住的不是这一下而是整局：玩家再点什么都是 409
        _m, session_id, _n = await self._setup(("赫敏", "格兰芬多塔", True))

        async def never_answers(*args, **kwargs):
            await asyncio.sleep(3600)

        # 走真的 wait_for，只把上限调小——上限本身是 60 秒，等得起的用例等不出
        # 这个行为，而换掉 wait_for 就只是在验证 mock 自己
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", never_answers), \
             patch.object(rpg_turn, "AUX_CALL_TIMEOUT", 0.05):
            got = await rpg_turn.idle_npc_activities(session_id, set())
        self.assertEqual(got, {})
        self.assertEqual(await self._saved(session_id), {})
        # 60 秒这个值本身也钉一下：写成 600 等于没夹，写成 6 会把正常调用切掉
        self.assertEqual(rpg_turn.AUX_CALL_TIMEOUT, 60)

    async def test_a_failed_call_leaves_everyone_where_they_were(self):
        """模型没开口 = 这一格没人动。

        去处和活动是同一次调用的两半，不再像从前那样「引擎先挪人、模型补一句
        话」。所以失败的代价从「挪了人却没有话」变成了「什么都没发生」——
        后者才是能自圆其说的那个：位置和那句话永远配套。
        """
        for fail in (RuntimeError("模型失败"), TimeoutError()):
            with self.subTest(fail=type(fail).__name__):
                _, session_id, (npc_id,) = await self._setup(
                    ("赫敏", "寝室", True), random_movement=True, places=("图书馆",),
                )
                with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
                     patch.object(rpg_turn.llm_client, "dispatch_chat_complete", side_effect=fail):
                    self.assertEqual(await rpg_turn.idle_npc_activities(session_id, set()), {})
                async with self.sessions() as db:
                    sess = await db.get(RpgSession, session_id)
                    self.assertEqual(sess.npc_places, {})
                    self.assertEqual(sess.npc_activities, {})

    async def test_a_stale_override_still_expires_when_the_call_fails(self):
        # 过期清理是在调模型**之前**提交的，和那次调用的成败无关：
        # 不然模型一失败，已经不该生效的覆盖就会一直挂着
        _, session_id, (npc_id,) = await self._setup(
            ("赫敏", "寝室", True), random_movement=True,
            places=("图书馆", "禁林"), random_places=("禁林",),
        )
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            sess.npc_places = {str(npc_id): "图书馆"}
            sess.npc_random_places = {str(npc_id): "图书馆"}
            await db.commit()
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", side_effect=RuntimeError("模型失败")):
            self.assertEqual(await rpg_turn.idle_npc_activities(session_id, set()), {})
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            self.assertEqual(sess.npc_places, {})
            self.assertEqual(sess.npc_random_places, {})


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
        # triggered 和 npcs_here 一样是 run_turn 硬取的键，替身少一个就 KeyError
        return [{"role": "user", "content": "x"}], {
            "npcs_here": [], "npcs_onstage": [], "triggered": [],
        }

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

    async def test_the_place_whitelist_migration_defaults_to_unrestricted(self):
        # 老库拿到 '[]' = 不限制，行为和加这一列之前逐字一致
        async with self.engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE rpg_npcs DROP COLUMN random_movement_places")
            )
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        async with self.sessions() as db:
            self.assertEqual((await db.get(RpgNpc, self.npc.id)).random_movement_places, [])

    async def test_the_place_whitelist_survives_the_round_trip(self):
        self.assertEqual(RpgNpcCreate(name="赫敏").random_movement_places, [])
        npc = await self._patch(random_movement=True, random_movement_places=["图书馆", "禁林"])
        self.assertEqual(RpgNpcOut.model_validate(npc).random_movement_places, ["图书馆", "禁林"])
        # 清空要清得掉：空列表不是 None，过不了 exclude_none 那道就等于白名单锁死
        self.assertEqual((await self._patch(random_movement_places=[])).random_movement_places, [])

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
