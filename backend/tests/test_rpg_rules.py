"""RPG 写作规则。照酒馆那套做的独立规则库：按 id 拼、无兜底、空即空。

守两条：勾选的规则要真的进 system；creator_note 依旧不进 prompt。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.rpg import (
    RpgMessage, RpgModule, RpgNpc, RpgRule, RpgSession, RpgWorldEntry,
)
from app.services.rpg_context import build_rpg_messages, resolve_rules

SENTINEL = "哨兵串勿入提示词XYZZY"


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            for model in (RpgModule, RpgRule, RpgWorldEntry, RpgNpc, RpgSession, RpgMessage):
                await connection.run_sync(model.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        self.module = RpgModule(
            user_id=1,
            name="锈湖地窖",
            genre="潮湿的悬疑",
            creator_note=SENTINEL,
            worldview="一座被水淹了一半的旧矿镇。",
        )
        self.db.add(self.module)
        await self.db.commit()

        self.sess = RpgSession(
            module_id=self.module.id,
            char_name="阿隼",
            stats={},
            inventory=[],
            location="地窖",
            flags={},
            npc_states={},
            npc_notes={},
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _add(self, obj):
        self.db.add(obj)
        await self.db.commit()
        return obj


class ResolveTests(_Base):
    async def test_enabled_rules_are_joined_by_id(self):
        a = await self._add(RpgRule(user_id=1, name="套话", content="禁止 AI 腔套话。", sort_order=1))
        b = await self._add(RpgRule(user_id=1, name="节奏", content="别急着推进剧情。", sort_order=2))
        text = await resolve_rules(self.db, 1, [a.id, b.id])
        self.assertEqual(text, "禁止 AI 腔套话。\n\n别急着推进剧情。")

    async def test_disabled_rules_are_skipped(self):
        a = await self._add(RpgRule(user_id=1, name="开", content="开着的。", enabled=True))
        b = await self._add(RpgRule(user_id=1, name="关", content="关掉的。", enabled=False))
        text = await resolve_rules(self.db, 1, [a.id, b.id])
        self.assertEqual(text, "开着的。")

    async def test_empty_ids_return_empty(self):
        await self._add(RpgRule(user_id=1, name="套话", content="禁止 AI 腔套话。"))
        self.assertEqual(await resolve_rules(self.db, 1, []), "")

    async def test_stale_ids_are_dropped(self):
        # 规则被删后，模组里留着的失效 id 解析时自然跳过，不报错
        a = await self._add(RpgRule(user_id=1, name="活的", content="还在的规则。"))
        text = await resolve_rules(self.db, 1, [a.id, 99999])
        self.assertEqual(text, "还在的规则。")

    async def test_only_the_owners_rules_are_visible(self):
        mine = await self._add(RpgRule(user_id=1, name="我的", content="我的规则。"))
        theirs = await self._add(RpgRule(user_id=2, name="别人的", content="别人的规则。"))
        text = await resolve_rules(self.db, 1, [mine.id, theirs.id])
        self.assertEqual(text, "我的规则。")


class InjectionTests(_Base):
    async def _build(self, text):
        return await build_rpg_messages(self.db, self.module, self.sess, [], text)

    async def test_selected_rule_reaches_the_system_prompt(self):
        rule = await self._add(RpgRule(user_id=1, name="套话", content="禁止使用『嘴角上扬』。"))
        self.module.enabled_rule_ids = [rule.id]
        messages, diag = await self._build("我看看四周")
        self.assertIn("禁止使用『嘴角上扬』。", messages[0]["content"])
        self.assertTrue(diag["rules_used"])

    async def test_no_rules_no_injection(self):
        await self._add(RpgRule(user_id=1, name="套话", content="禁止使用『嘴角上扬』。"))
        # 模组没勾任何规则，默认 [] 不注入
        messages, diag = await self._build("我看看四周")
        self.assertNotIn("禁止使用『嘴角上扬』。", messages[0]["content"])
        self.assertFalse(diag["rules_used"])

    async def test_creator_note_never_reaches_the_model(self):
        rule = await self._add(RpgRule(user_id=1, name="套话", content="禁止使用『嘴角上扬』。"))
        self.module.enabled_rule_ids = [rule.id]
        messages, _ = await self._build("我看看四周")
        blob = "\n".join(m["content"] for m in messages)
        self.assertNotIn(SENTINEL, blob)


if __name__ == "__main__":
    unittest.main()
