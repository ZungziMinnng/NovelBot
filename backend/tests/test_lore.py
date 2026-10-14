"""设定库：字段映射、九种导出落点、归属校验、提示词渲染。直接调路由函数，不起 HTTP。"""
import types
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, llm_usage, glossary_entry, user, text_replace_backup, tavern, sensitive_word, rpg, style_profile, chapter_version, author_note, word_day, memo, forge, lore  # noqa: F401
from app.agents import lore_agent
from app.api.routes import lore as routes
from app.models.lore import LoreEntry
from app.models.novel import Novel
from app.models.rpg import RpgItem, RpgModule, RpgRule, RpgSkill
from app.models.tavern import TavernCard, TavernRule, TavernWorldEntry
from app.models.technique import Technique
from app.models.world_entity import WorldEntity
from app.models.world_rule import WorldRule
from app.prompts.loader import render
from app.schemas.lore import LoreEntryCreate, LoreEntryUpdate, LoreExportIn, LoreFuseIn, LoreSourceRef
from app.services import lore_mapping


class MappingTests(unittest.TestCase):
    def test_lore_to_neutral_passes_through(self):
        entry = LoreEntry(
            user_id=1, kind="skill", name="火球", category="主动", level="稀有",
            description="丢一个火球", detail="冷却三回合",
        )
        n = lore_mapping.to_neutral("lore", "skill", entry)
        self.assertEqual(n, {
            "name": "火球", "category": "主动", "level": "稀有",
            "description": "丢一个火球", "detail": "冷却三回合",
        })

    def test_novel_item_reads_properties(self):
        obj = WorldEntity(
            novel_id=1, type="item", name="青囊", description="药囊", function="回血",
            properties={"类别": "消耗品", "稀有度": "稀有"},
        )
        n = lore_mapping.to_neutral("novel", "item", obj)
        self.assertEqual((n["category"], n["level"], n["detail"]), ("消耗品", "稀有", "回血"))

    def test_novel_skill_uses_practitioners_as_detail(self):
        t = Technique(novel_id=1, name="剑法", type="外功", power_level="一流",
                      description="快", practitioners="韩、宁")
        n = lore_mapping.to_neutral("novel", "skill", t)
        self.assertEqual((n["category"], n["level"]), ("外功", "一流"))
        self.assertEqual(n["detail"], "修习者：韩、宁")

    def test_novel_skill_without_practitioners_has_empty_detail(self):
        t = Technique(novel_id=1, name="剑法", type="外功", description="快")
        self.assertEqual(lore_mapping.to_neutral("novel", "skill", t)["detail"], "")

    def test_novel_rule_title_content(self):
        r = WorldRule(novel_id=1, kind="rule", title="灵气稀薄", content="法力恢复减半")
        n = lore_mapping.to_neutral("novel", "rule", r)
        self.assertEqual((n["name"], n["description"]), ("灵气稀薄", "法力恢复减半"))

    def test_rpg_item_joins_usable_and_consumable(self):
        item = RpgItem(module_id=1, name="面包", category="消耗品", description="顶饿",
                       usable=True, consumable=True)
        n = lore_mapping.to_neutral("rpg", "item", item)
        self.assertEqual(n["detail"], "可用；用后消耗")

    def test_rpg_item_without_flags_has_empty_detail(self):
        item = RpgItem(module_id=1, name="石头")
        self.assertEqual(lore_mapping.to_neutral("rpg", "item", item)["detail"], "")

    def test_rpg_skill_cooldown(self):
        s = RpgSkill(module_id=1, name="斩", category="主动", description="劈", cooldown=3)
        n = lore_mapping.to_neutral("rpg", "skill", s)
        self.assertEqual(n["detail"], "冷却 3 回合")

    def test_rpg_rule_and_tavern_rule(self):
        r = RpgRule(user_id=1, name="禁魔", content="不能施法")
        self.assertEqual(lore_mapping.to_neutral("rpg", "rule", r)["description"], "不能施法")
        t = TavernRule(user_id=1, name="礼貌", content="不要粗口")
        self.assertEqual(lore_mapping.to_neutral("tavern", "rule", t)["name"], "礼貌")

    def test_unknown_combination_raises(self):
        with self.assertRaises(ValueError):
            lore_mapping.to_neutral("tavern", "item", object())

    def test_fuse_prompt_renders_sources_and_weight(self):
        prompt = render("lore_fuse.jinja2", kind="item", sources=[{
            "name": "青囊", "category": "消耗品", "level": "稀有", "description": "药囊",
            "detail": "回血", "weight": 70, "instruction": "保留回血",
        }], goal="")
        self.assertIn("青囊", prompt)
        self.assertIn("主体", prompt)
        self.assertIn("保留回血", prompt)

    def test_fuse_prompt_rule_branch_asks_empty_level(self):
        prompt = render("lore_fuse.jinja2", kind="rule", sources=[{
            "name": "灵气稀薄", "category": "", "level": "", "description": "法力恢复减半",
            "detail": "", "weight": 50, "instruction": "",
        }], goal="")
        self.assertIn("灵气稀薄", prompt)
        self.assertIn("规则", prompt)
        self.assertIn("留空字符串", prompt)


class ExportFieldTests(unittest.TestCase):
    _n = {"name": "青囊", "category": "消耗品", "level": "稀有",
          "description": "药囊", "detail": "回血"}

    def test_novel_item(self):
        f = lore_mapping.export_fields("novel", "item", self._n)
        self.assertEqual((f["type"], f["function"]), ("item", "回血"))
        self.assertEqual(f["properties"], {"类别": "消耗品", "稀有度": "稀有"})

    def test_novel_item_drops_empty_properties(self):
        n = {"name": "x", "category": "", "level": "", "description": "", "detail": ""}
        self.assertEqual(lore_mapping.export_fields("novel", "item", n)["properties"], {})

    def test_novel_skill(self):
        f = lore_mapping.export_fields("novel", "skill", self._n)
        self.assertEqual(f, {"name": "青囊", "type": "消耗品", "description": "药囊",
                             "power_level": "稀有", "practitioners": ""})

    def test_novel_rule(self):
        n = {"name": "灵气稀薄", "category": "", "level": "", "description": "法力恢复减半", "detail": ""}
        self.assertEqual(lore_mapping.export_fields("novel", "rule", n),
                         {"kind": "rule", "title": "灵气稀薄", "content": "法力恢复减半"})

    def test_rpg_item_merges_text_and_keeps_known_category(self):
        f = lore_mapping.export_fields("rpg", "item", self._n)
        self.assertEqual(f["category"], "消耗品")
        self.assertEqual(f["description"], "药囊\n回血")
        self.assertEqual(f["effects"], {})

    def test_rpg_item_invalid_category_falls_back_to_consumable(self):
        n = {"name": "x", "category": "外功", "level": "", "description": "说明", "detail": "限制"}
        self.assertEqual(lore_mapping.export_fields("rpg", "item", n)["category"], "消耗品")

    def test_rpg_skill_passive_is_not_usable(self):
        n = {"name": "静心", "category": "被动", "level": "", "description": "回蓝", "detail": "冷却 2 回合"}
        f = lore_mapping.export_fields("rpg", "skill", n)
        self.assertEqual(f["category"], "被动")
        self.assertFalse(f["usable"])
        self.assertEqual(f["description"], "回蓝\n冷却 2 回合")
        self.assertEqual((f["effects"], f["requires"]), ({}, {}))

    def test_rpg_skill_invalid_category_falls_back_active(self):
        n = {"name": "剑法", "category": "外功", "level": "", "description": "", "detail": ""}
        f = lore_mapping.export_fields("rpg", "skill", n)
        self.assertEqual(f["category"], "主动")
        self.assertTrue(f["usable"])

    def test_rpg_rule(self):
        n = {"name": "禁魔", "category": "", "level": "", "description": "不能施法", "detail": ""}
        self.assertEqual(lore_mapping.export_fields("rpg", "rule", n),
                         {"name": "禁魔", "content": "不能施法"})

    def test_tavern_rule(self):
        n = {"name": "礼貌", "category": "", "level": "", "description": "不要粗口", "detail": ""}
        self.assertEqual(lore_mapping.export_fields("tavern", "rule", n),
                         {"name": "礼貌", "content": "不要粗口"})

    def test_tavern_entry_skips_empty_sections(self):
        f = lore_mapping.export_fields("tavern", "item", self._n)
        self.assertEqual(f["keywords"], "青囊")
        self.assertIn("【消耗品】青囊", f["content"])
        self.assertIn("回血", f["content"])
        self.assertEqual((f["constant"], f["depth"], f["enabled"]), (False, 0, True))

    def test_tavern_entry_name_only_when_rest_empty(self):
        n = {"name": "空地", "category": "", "level": "", "description": "", "detail": ""}
        f = lore_mapping.export_fields("tavern", "skill", n)
        self.assertEqual(f["content"], "空地")


class LoreRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.alice = types.SimpleNamespace(id=1)
        self.bob = types.SimpleNamespace(id=2)

        self.db.add_all([
            LoreEntry(user_id=1, kind="item", name="青囊", category="消耗品",
                      level="稀有", description="药囊", detail="回血"),
            LoreEntry(user_id=2, kind="item", name="别人的", category="",
                      level="", description="", detail=""),
        ])

        mod = RpgModule(user_id=1, name="学院")
        nov = Novel(user_id=1, title="北境")
        card = TavernCard(user_id=1, name="雪")
        self.db.add_all([mod, nov, card])
        await self.db.flush()
        self.module_id, self.novel_id, self.card_id = mod.id, nov.id, card.id

        self.db.add_all([
            WorldEntity(novel_id=nov.id, type="item", name="罗盘", description="指路",
                        function="寻物", properties={"类别": "关键道具", "稀有度": "传说"}),
            Technique(novel_id=nov.id, name="剑法", type="外功", description="快", power_level="一流"),
            WorldRule(novel_id=nov.id, kind="rule", title="灵气稀薄", content="法力恢复减半"),
            RpgItem(module_id=mod.id, name="面包", category="消耗品", description="顶饿",
                    usable=True, consumable=True),
            RpgSkill(module_id=mod.id, name="斩", category="主动", description="劈", cooldown=2),
            RpgRule(user_id=1, name="禁魔", content="不能施法"),
            TavernRule(user_id=1, name="礼貌", content="不要粗口"),
        ])

        bob_mod = RpgModule(user_id=2, name="别人的模组")
        bob_card = TavernCard(user_id=2, name="别人的卡")
        self.db.add_all([bob_mod, bob_card])
        await self.db.flush()
        self.bob_module_id, self.bob_card_id = bob_mod.id, bob_card.id
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _entry(self, kind="item", name="青囊"):
        return await routes.create_entry(LoreEntryCreate(
            kind=kind, name=name, category="消耗品", level="稀有",
            description="药囊", detail="回血",
        ), self.alice, self.db)

    async def test_sources_only_lists_own_rows(self):
        items = await routes.list_sources("item", self.alice, self.db)
        self.assertEqual(sorted(i.name for i in items), sorted(["面包", "罗盘", "青囊"]))
        groups = {i.name: i.group for i in items}
        self.assertEqual(groups["青囊"], "设定库")
        self.assertEqual(groups["罗盘"], "小说：北境")
        self.assertEqual(groups["面包"], "模组：学院")

    async def test_sources_skill_and_rule(self):
        skills = await routes.list_sources("skill", self.alice, self.db)
        self.assertEqual(sorted(i.name for i in skills), sorted(["剑法", "斩"]))
        rules = await routes.list_sources("rule", self.alice, self.db)
        self.assertEqual(sorted(i.name for i in rules), sorted(["灵气稀薄", "禁魔", "礼貌"]))
        self.assertEqual({i.group for i in rules if i.origin == "tavern"}, {"酒馆规则"})

    async def test_sources_rejects_unknown_kind(self):
        with self.assertRaises(HTTPException) as raised:
            await routes.list_sources("monster", self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)

    async def test_fuse_rejects_other_users_source_before_calling_model(self):
        other = (await self.db.execute(select(LoreEntry).where(LoreEntry.user_id == 2))).scalar_one()
        with self.assertRaises(HTTPException) as raised:
            await routes.fuse(LoreFuseIn(sources=[
                LoreSourceRef(origin="lore", kind="item", id=other.id),
                LoreSourceRef(origin="lore", kind="item", id=other.id),
            ]), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_fuse_rejects_mixed_kinds(self):
        item = (await self.db.execute(select(LoreEntry).where(LoreEntry.user_id == 1))).scalar_one()
        with self.assertRaises(HTTPException) as raised:
            await routes.fuse(LoreFuseIn(sources=[
                LoreSourceRef(origin="lore", kind="item", id=item.id),
                LoreSourceRef(origin="tavern", kind="rule", id=1),
            ]), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "只能融合同一类设定")

    async def test_fuse_passes_neutral_sources_to_agent(self):
        entry = (await self.db.execute(select(LoreEntry).where(LoreEntry.user_id == 1))).scalar_one()
        with patch.object(lore_agent, "fuse", new=AsyncMock(
                return_value={"name": "新道具"})) as mocked:
            out = await routes.fuse(LoreFuseIn(sources=[
                LoreSourceRef(origin="lore", kind="item", id=entry.id, weight=80, instruction="保留"),
                LoreSourceRef(origin="lore", kind="item", id=entry.id, weight=20),
            ], goal="救人"), self.alice, self.db)
        self.assertEqual(out, {"name": "新道具"})
        kind_arg, sources_arg, goal_arg, _model_ref = mocked.await_args.args
        self.assertEqual(kind_arg, "item")
        self.assertEqual(goal_arg, "救人")
        self.assertEqual((sources_arg[0]["weight"], sources_arg[0]["instruction"]), (80, "保留"))
        self.assertEqual(sources_arg[0]["name"], "青囊")

    async def test_entries_crud_and_ownership(self):
        created = await self._entry("skill", name="净心")
        self.assertEqual(created.kind, "skill")

        listed = await routes.list_entries(self.alice, None, self.db)
        self.assertEqual(len(listed), 2)
        listed = await routes.list_entries(self.alice, "skill", self.db)
        self.assertEqual([e.name for e in listed], ["净心"])

        updated = await routes.update_entry(
            created.id, LoreEntryUpdate(detail="冷却 5 回合"), self.alice, self.db)
        self.assertEqual(updated.detail, "冷却 5 回合")

        with self.assertRaises(HTTPException) as raised:
            await routes.update_entry(created.id, LoreEntryUpdate(name="x"), self.bob, self.db)
        self.assertEqual(raised.exception.status_code, 404)

        await routes.delete_entry(created.id, self.alice, self.db)
        self.assertIsNone(await self.db.get(LoreEntry, created.id))

    async def test_cannot_export_other_users_entry(self):
        other = (await self.db.execute(select(LoreEntry).where(LoreEntry.user_id == 2))).scalar_one()
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(
                other.id, LoreExportIn(target="tavern", card_id=self.card_id), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_export_novel_three_kinds(self):
        item = await self._entry("item")
        out = await routes.export_entry(
            item.id, LoreExportIn(target="novel", novel_id=self.novel_id), self.alice, self.db)
        row = await self.db.get(WorldEntity, out.id)
        self.assertEqual((row.type, row.function), ("item", "回血"))
        self.assertEqual(row.properties, {"类别": "消耗品", "稀有度": "稀有"})

        skill = await self._entry("skill")
        out = await routes.export_entry(
            skill.id, LoreExportIn(target="novel", novel_id=self.novel_id), self.alice, self.db)
        row = await self.db.get(Technique, out.id)
        self.assertEqual((row.type, row.power_level), ("消耗品", "稀有"))

        rule = await self._entry("rule")
        out = await routes.export_entry(
            rule.id, LoreExportIn(target="novel", novel_id=self.novel_id), self.alice, self.db)
        row = await self.db.get(WorldRule, out.id)
        self.assertEqual((row.kind, row.title, row.content), ("rule", "青囊", "药囊"))

    async def test_export_novel_needs_owned_novel(self):
        item = await self._entry("item")
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(item.id, LoreExportIn(target="novel"), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)

        bob_novel = Novel(user_id=2, title="别的书")
        self.db.add(bob_novel)
        await self.db.commit()
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(
                item.id, LoreExportIn(target="novel", novel_id=bob_novel.id), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_export_rpg_three_kinds(self):
        item = await self._entry("item")
        out = await routes.export_entry(
            item.id, LoreExportIn(target="rpg", module_id=self.module_id), self.alice, self.db)
        row = await self.db.get(RpgItem, out.id)
        self.assertEqual((row.module_id, row.category), (self.module_id, "消耗品"))
        self.assertEqual(row.effects, {})
        self.assertIn("回血", row.description)

        rule = await self._entry("rule")
        out = await routes.export_entry(
            rule.id, LoreExportIn(target="rpg", module_id=self.module_id), self.alice, self.db)
        row = await self.db.get(RpgRule, out.id)
        self.assertEqual((row.user_id, row.content), (1, "药囊"))

    async def test_export_rpg_needs_owned_module(self):
        item = await self._entry("item")
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(item.id, LoreExportIn(target="rpg"), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(
                item.id, LoreExportIn(target="rpg", module_id=self.bob_module_id),
                self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_export_tavern_rule_and_entry(self):
        rule = await self._entry("rule")
        out = await routes.export_entry(
            rule.id, LoreExportIn(target="tavern"), self.alice, self.db)
        row = await self.db.get(TavernRule, out.id)
        self.assertEqual((row.user_id, row.content), (1, "药囊"))

        item = await self._entry("item")
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(item.id, LoreExportIn(target="tavern"), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)
        with self.assertRaises(HTTPException) as raised:
            await routes.export_entry(
                item.id, LoreExportIn(target="tavern", card_id=self.bob_card_id),
                self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

        out = await routes.export_entry(
            item.id, LoreExportIn(target="tavern", card_id=self.card_id), self.alice, self.db)
        row = await self.db.get(TavernWorldEntry, out.id)
        self.assertEqual((row.card_id, row.keywords), (self.card_id, "青囊"))


if __name__ == "__main__":
    unittest.main()
