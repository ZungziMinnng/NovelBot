"""通用套装库（数值 / 动作预设）。用户级独立库，形状照 rpg_rules。

守三条：别人的套装一律 404（不能靠 detail 区分「不是你的」和「不存在」）；
只改名字不会把 stat_defs 清空；两张表里都不存在任何模组 id——套用是拷贝一次
就断开的，这件事在数据层就该是铁的。
"""
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg import (
    _get_owned_action_preset, _get_owned_stat_preset,
    create_action_preset, create_stat_preset,
    delete_stat_preset, list_stat_presets, update_stat_preset,
)
# 导入路由会连带拉起 Novel 那批 mapper，少一个 relationship 的对端就 InvalidRequestError
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgActionPreset, RpgStatPreset
from app.schemas.rpg import (
    RpgActionPresetCreate, RpgStatPresetCreate, RpgStatPresetUpdate,
)

ME = SimpleNamespace(id=1)
OTHER = SimpleNamespace(id=2)

BAR = {"name": "精力", "initial": 50, "min": 0, "max": 100, "display": "条"}
SEED = {
    "name": "打工", "prompt_hint": "你去便利店上了一个班。",
    "effects": {"精力": -30, "资金": 200}, "relation_effects": {}, "needs_target": False,
}


class PresetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            for model in (RpgStatPreset, RpgActionPreset):
                await connection.run_sync(model.__table__.create)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_defaults_are_empty_not_null(self):
        # 只给名字建一套：老库/新库拿到的都得是 [] 和 ''，前端 map 才不会炸
        made = await create_stat_preset(RpgStatPresetCreate(name="都市那套"), ME, self.db)
        self.assertEqual(made.stat_defs, [])
        self.assertEqual(made.relation_stat_defs, [])
        self.assertEqual(made.note, "")
        self.assertEqual(made.sort_order, 0)

        act = await create_action_preset(RpgActionPresetCreate(name="社交那组"), ME, self.db)
        self.assertEqual(act.actions, [])

    async def test_payload_round_trips_verbatim(self):
        # 套用就是整份拷过去，中间不做转换——存进去和取出来必须逐字相同
        made = await create_stat_preset(
            RpgStatPresetCreate(name="都市那套", note="卡时间和钱", stat_defs=[BAR]), ME, self.db,
        )
        self.assertEqual(made.stat_defs, [BAR])
        act = await create_action_preset(
            RpgActionPresetCreate(name="社交那组", actions=[SEED]), ME, self.db,
        )
        self.assertEqual(act.actions, [SEED])

    async def test_blank_name_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            await create_stat_preset(RpgStatPresetCreate(name="   "), ME, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx2:
            await create_action_preset(RpgActionPresetCreate(name=""), ME, self.db)
        self.assertEqual(ctx2.exception.status_code, 400)

    async def test_rename_does_not_wipe_the_stats(self):
        # exclude_none 的行为：PATCH 只带 name 时，没传的列一个都不该被动
        made = await create_stat_preset(
            RpgStatPresetCreate(name="旧名", stat_defs=[BAR]), ME, self.db,
        )
        after = await update_stat_preset(
            made.id, RpgStatPresetUpdate(name="新名"), ME, self.db,
        )
        self.assertEqual(after.name, "新名")
        self.assertEqual(after.stat_defs, [BAR])

    async def test_other_users_preset_is_404_and_indistinguishable(self):
        theirs = await create_stat_preset(RpgStatPresetCreate(name="别人的"), OTHER, self.db)
        with self.assertRaises(HTTPException) as mine_ctx:
            await _get_owned_stat_preset(self.db, theirs.id, ME)
        with self.assertRaises(HTTPException) as gone_ctx:
            await _get_owned_stat_preset(self.db, 99999, ME)
        self.assertEqual(mine_ctx.exception.status_code, 404)
        # detail 也得一样，否则 404 白做了：调用方照样能枚举出哪些 id 真的存在
        self.assertEqual(mine_ctx.exception.detail, gone_ctx.exception.detail)

        theirs_act = await create_action_preset(RpgActionPresetCreate(name="别人的"), OTHER, self.db)
        with self.assertRaises(HTTPException) as act_ctx:
            await _get_owned_action_preset(self.db, theirs_act.id, ME)
        self.assertEqual(act_ctx.exception.status_code, 404)

    async def test_list_only_shows_my_own(self):
        await create_stat_preset(RpgStatPresetCreate(name="我的", sort_order=1), ME, self.db)
        await create_stat_preset(RpgStatPresetCreate(name="别人的"), OTHER, self.db)
        rows = await list_stat_presets(ME, self.db)
        self.assertEqual([r.name for r in rows], ["我的"])

    async def test_delete_leaves_nothing_to_clean_up(self):
        made = await create_stat_preset(RpgStatPresetCreate(name="用完就删"), ME, self.db)
        await delete_stat_preset(made.id, ME, self.db)
        self.assertEqual(await list_stat_presets(ME, self.db), [])

    async def test_tables_hold_no_module_reference(self):
        # 拷贝一次就断开：两张表里不该出现任何模组 id。有一列都会被将来的人
        # 当成活链接，照着它写「改库同步到已有模组」——那会悄悄改坏正在玩的局
        for model in (RpgStatPreset, RpgActionPreset):
            columns = set(model.__table__.columns.keys())
            self.assertNotIn("module_id", columns)
            self.assertFalse(
                {c for c in columns if "module" in c},
                f"{model.__tablename__} 出现了模组相关列",
            )


if __name__ == "__main__":
    unittest.main()
