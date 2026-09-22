"""外场简报：推时段时给大事记补一句「别处在发生什么」。

这是整个玩法里唯一一次「玩家没说话却调模型」，所以三件事必须钉死：

1. **开关关着就是一次调用都没有**。「结束时段不花玩家的钱」是写在文档和按钮
   提示里的承诺，加了新功能之后它不能变成假话。
2. 只写玩家见过的人。没见过的人进了大事记，等于所有对话线都能随口提起一个
   玩家还不该知道的名字。
3. 生成失败**或卡住**不能拖垮时钟本身。卡住比失败更坏：这一次跑在
   exclusive_session 的租约里，心跳会替它一直续期，于是整局都点不动。
"""
import asyncio
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import advance_time
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession
from app.services.rpg_state import OFFSCREEN_CHARS, OFFSCREEN_TAG

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


class OffscreenBriefTests(unittest.IsolatedAsyncioTestCase):
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

    async def _setup(self, brief=True, met=True, slot="晚", home="格兰芬多塔", **npc_kw):
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="魔法学院", stat_defs=STAT_DEFS,
                relation_stat_defs=[], time_slots=["早", "中", "晚"],
                offscreen_brief=brief,
            )
            db.add(module)
            await db.commit()
            npc = RpgNpc(
                module_id=module.id, name="赫敏", location=home,
                persona="好胜", **npc_kw,
            )
            db.add(npc)
            await db.commit()
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={"精力": 100},
                location="校长办公室", slot=slot, day=3, chronicle=[],
                npc_states={str(npc.id): {"met": met}} if met else {},
            )
            db.add(sess)
            await db.commit()
            return module.id, sess.id, npc.id

    async def _run(self, session_id, text="赫敏在图书馆待到闭馆", from_slot="中", **kw):
        """跑一次简报，返回（写入的行, 模型收到的 prompt 列表）。"""
        prompts = []

        async def fake_dispatch(messages=None, **kwargs):
            prompts.append(messages[0]["content"])
            return text

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            lines = await rpg_turn.offscreen_brief(session_id, from_slot)
        return lines, prompts

    async def _chronicle(self, session_id):
        async with self.sessions() as db:
            return list((await db.get(RpgSession, session_id)).chronicle or [])

    async def test_off_by_default_costs_nothing(self):
        _m, session_id, _n = await self._setup(brief=False)
        lines, prompts = await self._run(session_id)
        self.assertEqual(lines, [])
        self.assertEqual(prompts, [])
        self.assertEqual(await self._chronicle(session_id), [])

    async def test_someone_never_met_is_not_news(self):
        _m, session_id, _n = await self._setup(met=False)
        lines, prompts = await self._run(session_id)
        self.assertEqual(lines, [])
        self.assertEqual(prompts, [])

    async def test_nobody_is_away_means_nobody_to_write_about(self):
        # 唯一那个见过的人此刻就站在玩家所在的地点，名单是空的
        _m, session_id, _n = await self._setup(home="校长办公室")
        lines, prompts = await self._run(session_id)
        self.assertEqual(lines, [])
        self.assertEqual(prompts, [])

    async def test_a_line_lands_in_the_chronicle_with_day_and_slot(self):
        _m, session_id, _n = await self._setup()
        lines, prompts = await self._run(session_id)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(f"{OFFSCREEN_TAG}第 3 天·晚 "))
        self.assertIn("赫敏在图书馆待到闭馆", lines[0])
        self.assertEqual(await self._chronicle(session_id), lines)
        # 名单里给了她此刻在哪，模型才有东西可写
        self.assertIn("格兰芬多塔", prompts[0])
        self.assertIn("刚过去的时段是「中」", prompts[0])

    async def test_silence_is_allowed(self):
        # 模型说没什么可写。硬编一条比少一条糟得多
        _m, session_id, _n = await self._setup()
        for said in ("无", "None", "（无）", ""):
            with self.subTest(said=said):
                lines, _p = await self._run(session_id, text=said)
                self.assertEqual(lines, [])
        self.assertEqual(await self._chronicle(session_id), [])

    async def test_a_chatty_model_is_clamped(self):
        _m, session_id, _n = await self._setup()
        lines, _p = await self._run(session_id, text="1. " + "很长" * 200 + "\n- 第二句\n- 第三句")
        self.assertEqual(len(lines), 2)
        # 单行硬夹：大事记是一行一条的硬事实，一条长文会常驻吃掉外场预算
        self.assertLessEqual(len(lines[0]), OFFSCREEN_CHARS + len(OFFSCREEN_TAG) + 20)

    async def test_a_failing_model_does_not_break_the_clock(self):
        _m, session_id, _n = await self._setup()
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete",
                          side_effect=RuntimeError("炸了")):
            lines = await rpg_turn.offscreen_brief(session_id, "中")
        self.assertEqual(lines, [])
        self.assertEqual(await self._chronicle(session_id), [])

    async def test_a_hanging_model_gives_up_instead_of_holding_the_whole_session(self):
        # 底层 httpx 没设超时，OpenAI SDK 的默认值是 read 600 秒 × 最多 3 次尝试。
        # 这一次跑在 exclusive_session 的租约里、心跳会替它一直续期，所以不夹
        # 一刀的话卡住的不是这一下而是整局：玩家再点什么都是 409
        _m, session_id, _n = await self._setup()

        async def never_answers(*args, **kwargs):
            await asyncio.sleep(3600)

        # 走真的 wait_for，只把上限调小：换掉 wait_for 就只是在验证 mock 自己
        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", never_answers), \
             patch.object(rpg_turn, "AUX_CALL_TIMEOUT", 0.05):
            lines = await rpg_turn.offscreen_brief(session_id, "中")
        self.assertEqual(lines, [])
        self.assertEqual(await self._chronicle(session_id), [])


class AdvanceRouteTests(unittest.IsolatedAsyncioTestCase):
    """路由那一层：简报要跑在写事务之外，而且新写的大事记要跟着这次响应回去。

    用文件库不用内存库，和 SilentMoveTests 同一个理由：写锁问题在共用一条连接的
    内存库上根本看不出来。
    """

    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.tmp}/t.db")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()

        module = RpgModule(
            user_id=1, name="魔法学院", stat_defs=STAT_DEFS, relation_stat_defs=[],
            time_slots=["早", "中", "晚"], offscreen_brief=True,
        )
        self.db.add(module)
        await self.db.commit()
        npc = RpgNpc(module_id=module.id, name="赫敏", location="格兰芬多塔")
        self.db.add(npc)
        await self.db.commit()
        sess = RpgSession(
            module_id=module.id, char_name="阿隼", stats={"精力": 100},
            location="校长办公室", slot="中", day=3, chronicle=[], status="alive",
            npc_states={str(npc.id): {"met": True}},
        )
        self.db.add(sess)
        await self.db.commit()
        self.session_id = sess.id

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.db.close()
        await self.engine.dispose()
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def test_the_brief_shows_up_in_the_same_response(self):
        async def fake_dispatch(messages=None, **kwargs):
            return "赫敏在图书馆待到闭馆"

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            out = await advance_time(self.session_id, self.user, self.db)

        self.assertEqual(out.session.slot, "晚")
        self.assertTrue(any(line.startswith(OFFSCREEN_TAG) for line in out.facts))
        # 简报是另开一条连接写进去的，路由手里这个对象必须被刷回来，
        # 否则玩家这一下看不到、下一轮却突然多出一条
        self.assertTrue(any(line.startswith(OFFSCREEN_TAG) for line in out.session.chronicle))

    async def test_the_scheduler_runs_first_so_the_brief_sees_the_new_places(self):
        """顺序有后果：随机移动是调度写的，简报的名单里要带上移动**之后**的位置。

        反过来的话同一格里大事记写着「她在家洗衬衫」、侧栏显示她在楼道——
        真实存档里出现过的那个「诡异」就是这么来的。
        """
        async with self.sessions() as db:
            npc = (await db.execute(select(RpgNpc))).scalars().one()
            npc.ai_scheduled = True
            npc.random_movement = True
            db.add(RpgLocation(module_id=npc.module_id, name="有求必应屋"))
            await db.commit()

        seen = []

        async def fake_dispatch(messages=None, **kwargs):
            seen.append(messages[0]["content"])
            return "赫敏：有求必应屋｜在翻旧报纸"

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            await advance_time(self.session_id, self.user, self.db)

        self.assertEqual(len(seen), 2, "调度和简报各一次")
        async with self.sessions() as db:
            sess = await db.get(RpgSession, self.session_id)
        # 去处是模型自己写的那一半（候选里只有这一个）
        self.assertEqual(list(sess.npc_random_places.values()), ["有求必应屋"])
        # 「刚过去的时段是」只有简报那份模板里有，拿它认出谁是第二次调用
        self.assertNotIn("刚过去的时段是", seen[0])
        self.assertIn("刚过去的时段是", seen[1])
        # 这才是这条测试要钉的：简报的名单上写的是移动之后的地方
        self.assertIn("有求必应屋", seen[1])
        self.assertNotIn("格兰芬多塔", seen[1])

    async def test_the_switch_off_route_still_never_calls_a_model(self):
        async with self.sessions() as db:
            module = await db.get(RpgModule, (await db.get(RpgSession, self.session_id)).module_id)
            module.offscreen_brief = False
            await db.commit()

        def boom(*_a, **_kw):
            raise AssertionError("开关关着的时候一次模型调用都不该发生")

        with patch.object(rpg_turn.llm_client, "get_agent_client", side_effect=boom), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", side_effect=boom):
            out = await advance_time(self.session_id, self.user, self.db)

        self.assertEqual(out.session.slot, "晚")
        self.assertEqual(out.session.chronicle, [])


if __name__ == "__main__":
    unittest.main()
