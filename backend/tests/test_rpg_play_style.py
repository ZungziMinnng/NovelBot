"""玩法类别：模拟 / 探索冒险 / 经营策略。

钉两件事：
1. 类别真的进了 system。它要是没进去，界面上选了半天、模型一个字都看不到，
   而且不报错——这正是「往 rpg_gm.jinja2 里塞变量」那个方案会出的事。
2. 未知值回落到默认类别。老库里这一列是空串，不能让它变成一句空规则。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgSession
from app.services.rpg_context import build_rpg_messages
from app.services.rpg_play_style import STYLE_LABELS, style_block, style_label


class StyleBlockTests(unittest.TestCase):
    def test_each_style_has_its_own_rules(self):
        blocks = {key: style_block(key) for key in STYLE_LABELS}
        self.assertEqual(len(set(blocks.values())), len(STYLE_LABELS))
        for key, text in blocks.items():
            with self.subTest(key=key):
                self.assertIn(STYLE_LABELS[key], text)

    def test_unknown_values_fall_back_to_the_default(self):
        # 老库这一列是空串；手改过库的还可能是别的东西。两种都不能变成空规则
        for value in ("", None, "   ", "roguelike"):
            with self.subTest(value=value):
                self.assertEqual(style_block(value), style_block("rpg"))
                self.assertEqual(style_label(value), STYLE_LABELS["rpg"])


class StyleInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _system(self, play_style):
        module = RpgModule(
            user_id=1, name="测试模组", stat_defs=[], relation_stat_defs=[],
            play_style=play_style,
        )
        self.db.add(module)
        await self.db.commit()
        sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="")
        self.db.add(sess)
        await self.db.commit()
        messages, _ = await build_rpg_messages(self.db, module, sess, [], "我看看四周")
        return messages[0]["content"]

    async def test_the_rules_reach_the_system_prompt(self):
        self.assertIn(style_block("slg"), await self._system("slg"))

    async def test_an_old_module_still_gets_the_default_rules(self):
        # 加这一列之前建的模组读出来是空串，行为必须和默认类别一模一样
        self.assertIn(style_block("rpg"), await self._system(""))
