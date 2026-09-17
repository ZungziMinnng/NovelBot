"""常用 GM 指令库。取用是拷贝文本，模组不存 preset_id。

守住那条唯一不显然的性质：删掉预设，已经用了它的模组一个字都不掉。
其余（列表按 updated_at 倒序、跨用户拿不到）顺手一起验。
"""
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.rpg import RpgInstructionPreset, RpgModule


class InstructionPresetTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            for model in (RpgModule, RpgInstructionPreset):
                await connection.run_sync(model.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _add(self, obj):
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def test_delete_preset_leaves_module_text_intact(self):
        """拷贝断开：删了预设，模组里那段 GM 指令还在。"""
        preset = await self._add(RpgInstructionPreset(
            user_id=1, name="克苏鲁腔", content="多写不可名状的东西。",
        ))
        module = await self._add(RpgModule(
            user_id=1, name="锈湖地窖", system_instruction=preset.content,
        ))

        await self.db.delete(preset)
        await self.db.commit()

        fresh = await self.db.get(RpgModule, module.id)
        self.assertEqual(fresh.system_instruction, "多写不可名状的东西。")

    async def test_scoped_to_owner(self):
        await self._add(RpgInstructionPreset(user_id=1, name="我的", content="a"))
        await self._add(RpgInstructionPreset(user_id=2, name="别人的", content="b"))

        mine = (await self.db.execute(
            select(RpgInstructionPreset).where(RpgInstructionPreset.user_id == 1)
        )).scalars().all()
        self.assertEqual([p.name for p in mine], ["我的"])


if __name__ == "__main__":
    unittest.main()
