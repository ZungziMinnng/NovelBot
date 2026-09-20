import unittest
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg import resolve_tasks, set_task_state
from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg
from app.models.rpg import RpgModule, RpgSession, RpgTask
from app.schemas.rpg import RpgTaskResolveIn, RpgTaskStateIn
from app.services.rpg_settlement import filter_task_updates
from app.services.rpg_state import DAILY_TASK_CATEGORY, reset_daily_tasks, starting_tasks


NARRATION = "你把那封信递过去，老周就着灯看了两眼，点点头收进怀里。"


class StartingTasksTests(unittest.TestCase):
    def test_only_auto_start_tasks_are_taken_and_carry_the_goal(self):
        tasks = [
            SimpleNamespace(id=1, name="送信给老周", description="镖头托的",
                            objective="把信交到老周手上", auto_start=True),
            SimpleNamespace(id=2, name="打听镖局的事", description="",
                            objective="", auto_start=False),
            SimpleNamespace(id=3, name=" 送信给老周 ", description="",
                            objective="", auto_start=True),
        ]
        rows = starting_tasks(tasks)
        self.assertEqual([row["name"] for row in rows], ["送信给老周"])
        self.assertEqual(rows[0]["goal"], "把信交到老周手上")
        self.assertEqual(rows[0]["status"], "open")
        self.assertEqual(rows[0]["task_id"], 1)


class DailyTaskTests(unittest.TestCase):
    def test_starting_tasks_keep_the_daily_category(self):
        rows = starting_tasks([SimpleNamespace(
            id=1, name="daily", description="", objective="",
            category=DAILY_TASK_CATEGORY, auto_start=True,
        )])
        self.assertEqual(rows[0]["category"], DAILY_TASK_CATEGORY)

    def test_finished_daily_tasks_reopen_when_a_new_day_starts(self):
        sess = SimpleNamespace(
            turn_count=8,
            tasks=[
                {"name": "daily done", "category": DAILY_TASK_CATEGORY,
                 "status": "done", "opened_turn": 1, "closed_turn": 7},
                {"name": "daily failed", "category": DAILY_TASK_CATEGORY,
                 "status": "failed", "opened_turn": 1, "closed_turn": 7},
                {"name": "side quest", "category": "side",
                 "status": "done", "opened_turn": 1, "closed_turn": 7},
            ],
        )

        self.assertTrue(reset_daily_tasks(sess))
        self.assertEqual(sess.tasks[0]["status"], "open")
        self.assertEqual(sess.tasks[1]["status"], "open")
        self.assertEqual(sess.tasks[0]["opened_turn"], 8)
        self.assertEqual(sess.tasks[0]["closed_turn"], 0)
        self.assertEqual(sess.tasks[2]["status"], "done")


class FilterTaskUpdatesTests(unittest.TestCase):
    """模型只有提名权，而且提名要经得起复核：名字必须在清单上、
    理由必须是正文原话。三道关任意一道不过，这一条就不该弹到玩家跟前。"""

    def _run(self, updates, pending=()):
        return filter_task_updates(
            {"task_updates": updates}, NARRATION, ["送信给老周"], 7, pending,
        )

    def test_a_clean_update_becomes_a_proposal(self):
        got = self._run([{"name": "送信给老周", "action": "done",
                          "reason": "老周就着灯看了两眼，点点头收进怀里"}])
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "送信给老周")
        self.assertEqual(got[0]["action"], "done")
        self.assertEqual(got[0]["message_id"], 7)

    def test_reason_that_is_not_a_verbatim_quote_is_dropped(self):
        self.assertEqual(self._run([{
            "name": "送信给老周", "action": "done", "reason": "看样子信已经送到了",
        }]), [])

    def test_a_task_that_is_not_on_the_open_list_is_dropped(self):
        self.assertEqual(self._run([{
            "name": "替镖局出头", "action": "done",
            "reason": "老周就着灯看了两眼",
        }]), [])

    def test_an_unknown_action_is_dropped(self):
        self.assertEqual(self._run([{
            "name": "送信给老周", "action": "半成", "reason": "老周就着灯看了两眼",
        }]), [])

    def test_a_task_already_waiting_for_confirmation_is_not_proposed_again(self):
        self.assertEqual(self._run(
            [{"name": "送信给老周", "action": "done", "reason": "老周就着灯看了两眼"}],
            pending=[{"name": "送信给老周"}],
        ), [])


class ResolveTasksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        module = RpgModule(
            user_id=1, name="任务测试", check_mode="never",
            stat_defs=[{"name": "银钱", "initial": 0, "min": 0, "max": 100}],
        )
        self.db.add(module)
        await self.db.flush()
        task = RpgTask(
            module_id=module.id, name="送信给老周", description="镖头托的",
            objective="把信交到老周手上", effects={"银钱": 10}, auto_start=True,
        )
        self.db.add(task)
        await self.db.flush()
        self.sess = RpgSession(
            module_id=module.id, char_name="旅人", location="巷口", status="alive",
            stats={"银钱": 0}, turn_count=3,
            tasks=[
                {"name": "送信给老周", "desc": "镖头托的", "goal": "把信交到老周手上",
                 "status": "open", "task_id": task.id, "source": "module",
                 "opened_turn": 0, "closed_turn": 0},
                {"name": "打听镖局的事", "desc": "", "goal": "", "status": "open",
                 "task_id": None, "source": "story", "opened_turn": 2, "closed_turn": 0},
            ],
            task_proposals=[
                {"id": "aaa", "name": "送信给老周", "action": "done",
                 "reason": "老周点点头收进怀里", "message_id": 7},
                {"id": "bbb", "name": "打听镖局的事", "action": "done",
                 "reason": "你在茶棚坐了半晌", "message_id": 7},
            ],
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def _status(self, name):
        return next(t["status"] for t in self.sess.tasks if t["name"] == name)

    async def test_only_accepted_proposals_change_state_and_all_are_cleared(self):
        await resolve_tasks(self.sess.id, RpgTaskResolveIn(accepts=[
            {"id": "aaa", "accept": True},
            {"id": "bbb", "accept": False},
        ]), self.user, self.db)
        self.assertEqual(self._status("送信给老周"), "done")
        # 没勾的那条仍在进行中，但也从待确认里消失了——否则每回合都会再弹一次
        self.assertEqual(self._status("打听镖局的事"), "open")
        self.assertEqual(self.sess.task_proposals, [])
        self.assertEqual(self.sess.stats["银钱"], 10)

    async def test_the_reward_is_paid_only_once(self):
        await resolve_tasks(self.sess.id, RpgTaskResolveIn(
            accepts=[{"id": "aaa", "accept": True}]), self.user, self.db)
        # 玩家又在任务格里手动点了一遍「完成」
        await set_task_state(self.sess.id, RpgTaskStateIn(
            name="送信给老周", status="done"), self.user, self.db)
        self.assertEqual(self.sess.stats["银钱"], 10)

    async def test_manual_completion_pays_the_reward_and_drops_the_proposal(self):
        await set_task_state(self.sess.id, RpgTaskStateIn(
            name="送信给老周", status="done"), self.user, self.db)
        self.assertEqual(self._status("送信给老周"), "done")
        self.assertEqual(self.sess.stats["银钱"], 10)
        self.assertEqual([p["id"] for p in self.sess.task_proposals], ["bbb"])

    async def test_a_task_can_be_crossed_off_entirely(self):
        await set_task_state(self.sess.id, RpgTaskStateIn(
            name="打听镖局的事", status=""), self.user, self.db)
        self.assertEqual([t["name"] for t in self.sess.tasks], ["送信给老周"])


if __name__ == "__main__":
    unittest.main()
