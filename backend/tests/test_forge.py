"""熔炉：字段映射、creator_note 不进 prompt、归属校验、三种导出。直接调路由函数，不起 HTTP。"""
import types
import unittest

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, llm_usage, glossary_entry, user, text_replace_backup, tavern, sensitive_word, rpg, style_profile, chapter_version, author_note, word_day, memo, forge  # noqa: F401
from app.api.routes import forge as routes
from app.models.character import Character
from app.models.forge import ForgeCharacter
from app.models.novel import Novel
from app.models.rpg import RpgModule, RpgNpc
from app.models.tavern import TavernCard
from app.prompts.loader import render
from app.schemas.forge import ForgeCharacterCreate, ForgeExportIn, ForgeFuseIn, ForgeSourceRef
from app.services import forge_mapping

SENTINEL = "SENTINEL_CREATOR_NOTE_不许进提示词"


def _card(**kw):
    base = dict(
        user_id=1, name="雪", creator_note=SENTINEL, personality="嘴硬心软",
        opening_scene="OPENING_SCENE_X", system_instruction="SYSTEM_INSTRUCTION_X",
        description="北境剑客", dialogue_examples=[{"user": "你好", "assistant": "哼。"}],
        profile_sections={"appearance": "白发", "background": "孤儿", "abilities": "剑术"},
    )
    base.update(kw)
    return TavernCard(**base)


class MappingTests(unittest.TestCase):
    def test_tavern_to_neutral_drops_private_and_runtime_fields(self):
        n = forge_mapping.to_neutral("tavern", _card())
        flat = repr(n)
        self.assertNotIn(SENTINEL, flat)
        self.assertNotIn("OPENING_SCENE_X", flat)
        self.assertNotIn("SYSTEM_INSTRUCTION_X", flat)
        self.assertEqual((n["appearance"], n["background"], n["abilities"]), ("白发", "孤儿", "剑术"))

    def test_creator_note_never_reaches_rendered_prompt(self):
        n = forge_mapping.to_neutral("tavern", _card())
        prompt = render("forge_fuse.jinja2", sources=[{**n, "weight": 70, "instruction": "取嘴硬"}], goal="")
        self.assertNotIn(SENTINEL, prompt)
        self.assertIn("嘴硬心软", prompt)
        self.assertIn("主体", prompt)

    def test_npc_legacy_english_sections_are_read_back(self):
        npc = RpgNpc(
            name="阿宁", age="十七", persona="活泼", appearance="",
            profile_sections={"appearance": "短发", "background": "学生", "关系网络": "同桌"},
        )
        n = forge_mapping.to_neutral("npc", npc)
        self.assertEqual((n["personality"], n["appearance"], n["background"], n["relationships"]),
                         ("活泼", "短发", "学生", "同桌"))

    def test_novel_skills_list_joined_and_split_back(self):
        ch = Character(name="韩", age="30", description="刀客", full_sheet={
            "personality": "沉默", "skills": ["刀法", "轻功"], "appearance": "疤", "speech_style": "寡言",
        })
        n = forge_mapping.to_neutral("novel", ch)
        self.assertEqual(n["abilities"], "刀法、轻功")
        out = forge_mapping.to_novel({**n, "background": "边军出身", "relationships": "", "name": "新人"})
        self.assertEqual(out["full_sheet"]["skills"], ["刀法", "轻功"])
        self.assertIn("边军出身", out["description"])

    def test_age_truncated_to_column_width(self):
        n = {"name": "x", "age": "一二三四五六七八九十一二三四五六七八九十一二三", "dialogue_examples": []}
        self.assertEqual(len(forge_mapping.to_npc(n)["age"]), 20)
        self.assertEqual(len(forge_mapping.to_novel(n)["age"]), 20)


class ForgeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.alice = types.SimpleNamespace(id=1)
        self.bob = types.SimpleNamespace(id=2)

        self.db.add_all([_card(), _card(name="别人的", user_id=2)])
        mod = RpgModule(user_id=1, name="学院")
        nov = Novel(user_id=1, title="北境")
        self.db.add_all([mod, nov])
        await self.db.flush()
        self.module_id, self.novel_id = mod.id, nov.id
        self.db.add(RpgNpc(module_id=mod.id, name="阿宁", persona="活泼"))
        self.db.add(Character(novel_id=nov.id, name="韩", full_sheet={"personality": "沉默"}))
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _saved(self):
        return await routes.create_character(
            ForgeCharacterCreate(
                name="新人", personality="嘴硬", speech_style="短句", appearance="白发",
                background="孤儿", abilities="剑术、轻功", relationships="无",
                dialogue_examples=[{"user": "喂", "assistant": "嗯。"}],
            ),
            self.alice, self.db,
        )

    async def test_sources_only_lists_own_characters(self):
        items = await routes.list_sources(self.alice, self.db)
        self.assertEqual(sorted((i.kind, i.name) for i in items),
                         [("novel", "韩"), ("npc", "阿宁"), ("tavern", "雪")])
        self.assertEqual({i.group for i in items}, {"酒馆", "小说：北境", "模组：学院"})

    async def test_fuse_rejects_other_users_source_before_calling_model(self):
        other = (await self.db.execute(select(TavernCard).where(TavernCard.user_id == 2))).scalar_one()
        with self.assertRaises(HTTPException) as raised:
            await routes.fuse(ForgeFuseIn(sources=[ForgeSourceRef(kind="tavern", id=other.id)]),
                              self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 404)

    async def test_cannot_touch_other_users_forge_character(self):
        saved = await self._saved()
        with self.assertRaises(HTTPException) as raised:
            await routes.delete_character(saved.id, self.bob, self.db)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(await routes.list_characters(self.bob, self.db), [])

    async def test_export_tavern(self):
        saved = await self._saved()
        out = await routes.export_character(saved.id, ForgeExportIn(target="tavern"), self.alice, self.db)
        card = await self.db.get(TavernCard, out.id)
        self.assertEqual(card.user_id, 1)
        self.assertIn("说话风格：短句", card.personality)
        self.assertEqual(card.profile_sections["background"], "孤儿")
        self.assertEqual(card.creator_note, "")

    async def test_export_npc_needs_owned_module(self):
        saved = await self._saved()
        with self.assertRaises(HTTPException) as raised:
            await routes.export_character(saved.id, ForgeExportIn(target="npc"), self.alice, self.db)
        self.assertEqual(raised.exception.status_code, 400)
        with self.assertRaises(HTTPException) as raised:
            await routes.export_character(
                saved.id, ForgeExportIn(target="npc", module_id=self.module_id), self.bob, self.db)
        self.assertEqual(raised.exception.status_code, 404)
        out = await routes.export_character(
            saved.id, ForgeExportIn(target="npc", module_id=self.module_id), self.alice, self.db)
        npc = await self.db.get(RpgNpc, out.id)
        self.assertEqual(npc.profile_sections, {"背景故事": "孤儿", "能力特长": "剑术、轻功", "关系网络": "无"})
        self.assertEqual(npc.appearance, "白发")

    async def test_export_novel_keeps_sheet_and_skips_llm(self):
        saved = await self._saved()
        out = await routes.export_character(
            saved.id, ForgeExportIn(target="novel", novel_id=self.novel_id), self.alice, self.db)
        char = await self.db.get(Character, out.id)
        self.assertEqual(char.full_sheet["skills"], ["剑术", "轻功"])
        self.assertIn("孤儿", char.description)
        # 导出是新建一行，不动熔炉成品
        self.assertEqual(len((await self.db.execute(select(ForgeCharacter))).scalars().all()), 1)


if __name__ == "__main__":
    unittest.main()
