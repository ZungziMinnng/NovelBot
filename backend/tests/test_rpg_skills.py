import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import stream_turn
from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg
from app.models.rpg import RpgModule, RpgSession, RpgSkill
from app.schemas.rpg import RpgTurnRequest
from app.services.rpg_state import starting_skills


class StartingSkillsTests(unittest.TestCase):
    def test_only_start_with_skills_are_learned_and_duplicates_collapse(self):
        skills = [
            SimpleNamespace(name="听风辨位", start_with=True),
            SimpleNamespace(name="控火诀", start_with=False),
            SimpleNamespace(name=" 听风辨位 ", start_with=True),
            SimpleNamespace(name="", start_with=True),
        ]
        self.assertEqual(
            starting_skills(skills), [{"name": "听风辨位", "cooldown_left": 0}]
        )


class SkillTurnTests(unittest.IsolatedAsyncioTestCase):
    """技能在一整轮里的行为：条件、效果、冷却。走真实的 stream_turn，
    因为冷却递减发生在 run_turn 的开头，单测 _use_skill 看不到那一半。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        module = RpgModule(
            user_id=1, name="技能测试", check_mode="never",
            stat_defs=[
                {"name": "精力", "initial": 50, "min": 0, "max": 100},
                {"name": "内力", "initial": 3, "min": 0, "max": 10},
            ],
        )
        self.db.add(module)
        await self.db.flush()
        self.module_id = module.id
        self.db.add_all([
            RpgSkill(
                module_id=module.id, name="听风辨位", category="主动",
                effects={"精力": -10}, cooldown=2, start_with=True,
            ),
            RpgSkill(
                module_id=module.id, name="御火", category="主动",
                effects={"精力": -5},
                requires={"stats": {"内力": {"op": ">=", "value": 5}}},
                start_with=True,
            ),
        ])
        self.sess = RpgSession(
            module_id=module.id, char_name="旅人", location="山道", slot="清晨",
            stats={"精力": 50, "内力": 3}, status="alive", turn_count=0,
            skills=[
                {"name": "听风辨位", "cooldown_left": 0},
                {"name": "御火", "cooldown_left": 0},
            ],
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _turn(self, content, **kwargs):
        async def stream(messages, **options):
            yield "你依言而动。"
            yield ("usage", 1, 1)

        with (
            patch.object(rpg_turn, "AsyncSessionLocal", self.sessions),
            patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")),
            patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage", stream),
            patch.object(rpg_turn, "call_json", AsyncMock(return_value=({}, 1, 1))),
            patch.object(rpg_turn, "_maybe_summarize", AsyncMock()),
            patch.object(rpg_turn, "idle_npc_activities", AsyncMock()),
        ):
            response = await stream_turn(
                self.sess.id, RpgTurnRequest(content=content, **kwargs), self.user, self.db,
            )
            events = []
            async for chunk in response.body_iterator:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                payload = json.loads(text.removeprefix("data: ").strip())
                events.append((payload["event"], payload["data"]))
        self.assertFalse([data for event, data in events if event == "error"])
        await self.db.refresh(self.sess)
        return events

    def _cooldown(self, name):
        return next(
            int(s["cooldown_left"]) for s in self.sess.skills if s["name"] == name
        )

    async def test_using_a_skill_applies_effects_and_starts_the_cooldown(self):
        await self._turn("施展听风辨位", skill_name="听风辨位")
        self.assertEqual(self.sess.stats["精力"], 40)
        # cooldown=2 存成 3：这一轮开头的递减已经发生过，下一轮和再下一轮
        # 各减一次，第三轮才归零
        self.assertEqual(self._cooldown("听风辨位"), 3)

    async def test_cooldown_ticks_down_each_turn_and_blocks_reuse_until_zero(self):
        await self._turn("施展听风辨位", skill_name="听风辨位")
        for expected in (2, 1):
            await self._turn("再来一次", skill_name="听风辨位")
            # 冷却中：数值不动，只递减
            self.assertEqual(self.sess.stats["精力"], 40)
            self.assertEqual(self._cooldown("听风辨位"), expected)
        await self._turn("再来一次", skill_name="听风辨位")
        self.assertEqual(self.sess.stats["精力"], 30)
        self.assertEqual(self._cooldown("听风辨位"), 3)

    async def test_unmet_requirement_changes_nothing(self):
        await self._turn("御火", skill_name="御火")
        self.assertEqual(self.sess.stats["精力"], 50)
        self.assertEqual(self._cooldown("御火"), 0)

    async def test_met_requirement_lets_it_through(self):
        self.sess.stats = {**self.sess.stats, "内力": 6}
        await self.db.commit()
        await self._turn("御火", skill_name="御火")
        self.assertEqual(self.sess.stats["精力"], 45)

    async def test_insufficient_skill_cost_changes_nothing(self):
        self.sess.stats = {**self.sess.stats, "精力": 4}
        await self.db.commit()
        await self._turn("施展听风辨位", skill_name="听风辨位")
        self.assertEqual(self.sess.stats["精力"], 4)
        self.assertEqual(self._cooldown("听风辨位"), 0)

    async def test_unknown_skill_warns_and_leaves_state_alone(self):
        events = await self._turn("乱按", skill_name="没这招")
        self.assertTrue([d for e, d in events if e == "warning" and "没这招" in str(d)])
        self.assertEqual(self.sess.stats["精力"], 50)


if __name__ == "__main__":
    unittest.main()
