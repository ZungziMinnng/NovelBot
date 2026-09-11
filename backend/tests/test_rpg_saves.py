"""存档回溯。

要守的是「五样一起回去」：消息、玩家数值、关系数值、背包、摘要。漏掉摘要
最难查——剧情看着回到了第 3 回合，模型却还记得第 8 回合发生过什么。
"""
import asyncio
import unittest

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg import (
    AUTO_SAVE_KEEP, _prune_auto_saves, _take_save,
    create_save, delete_save, list_saves, restore_save,
)
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSave, RpgSession
from app.models.user import User
from app.schemas.rpg import RpgSaveCreate


class RpgSaveTests(unittest.TestCase):
    def _run(self, scenario):
        asyncio.run(scenario())

    async def _setup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        db = async_sessionmaker(engine, expire_on_commit=False)()

        user = User(username="alice", password_hash="x")
        other = User(username="bob", password_hash="x")
        db.add_all([user, other])
        await db.flush()

        module = RpgModule(user_id=user.id, name="测试模组")
        db.add(module)
        await db.flush()

        npc = RpgNpc(module_id=module.id, name="赫敏")
        db.add(npc)
        await db.flush()

        sess = RpgSession(
            module_id=module.id,
            char_name="阿隼",
            stats={"精力": 100, "资金": 300},
            inventory=[{"name": "铁钥匙", "qty": 1}],
            npc_states={str(npc.id): {"好感": 10, "met": True}},
            location="出租屋",
        )
        db.add(sess)
        await db.commit()
        return db, user, other, sess, npc

    async def _play(self, db, sess, turns, npc_id):
        """跑 turns 个回合：每回合两条消息 + 一点状态变化。"""
        for _ in range(turns):
            sess.turn_count += 1
            db.add(RpgMessage(session_id=sess.id, role="user", content=f"第{sess.turn_count}轮"))
            db.add(RpgMessage(session_id=sess.id, role="assistant", content="旁白"))
            sess.stats = {**sess.stats, "精力": sess.stats["精力"] - 5}
            sess.npc_states = {
                str(npc_id): {**sess.npc_states[str(npc_id)], "好感": sess.npc_states[str(npc_id)]["好感"] + 3}
            }
            sess.summary = f"到第 {sess.turn_count} 回合为止"
            await db.commit()

    def test_restore_rewinds_all_five(self):
        async def scenario():
            db, user, _other, sess, npc = await self._setup()

            await self._play(db, sess, 3, npc.id)
            snapshot = dict(
                stats=dict(sess.stats),
                relation=dict(sess.npc_states[str(npc.id)]),
                inventory=[dict(i) for i in sess.inventory],
                summary=sess.summary,
                turn_count=sess.turn_count,
            )
            save = await create_save(sess.id, RpgSaveCreate(label="第三回合"), user, db)

            # 再往后玩 5 轮，顺手改背包和地点
            await self._play(db, sess, 5, npc.id)
            sess.inventory = [{"name": "铁钥匙", "qty": 1}, {"name": "药水", "qty": 2}]
            sess.location = "地窖"
            await db.commit()
            self.assertEqual(sess.turn_count, 8)

            restored = await restore_save(save.id, user, db)

            self.assertEqual(restored.stats, snapshot["stats"])
            self.assertEqual(restored.npc_states[str(npc.id)], snapshot["relation"])
            self.assertEqual(restored.inventory, snapshot["inventory"])
            self.assertEqual(restored.summary, snapshot["summary"])
            self.assertEqual(restored.turn_count, snapshot["turn_count"])
            self.assertEqual(restored.location, "出租屋")

            messages = (await db.execute(
                select(RpgMessage).where(RpgMessage.session_id == sess.id).order_by(RpgMessage.id)
            )).scalars().all()
            self.assertEqual(len(messages), 6)
            self.assertEqual(messages[-2].content, "第3轮")

        self._run(scenario)

    def test_snapshot_is_deep_copied(self):
        """状态是 JSON 列，存的是引用。本轮再就地改就会把存档一起改脏。"""
        async def scenario():
            db, user, _other, sess, npc = await self._setup()
            save = await create_save(sess.id, RpgSaveCreate(label=""), user, db)

            sess.stats["精力"] = 1
            sess.inventory[0]["qty"] = 99
            await db.commit()

            self.assertEqual(save.state["stats"]["精力"], 100)
            self.assertEqual(save.state["inventory"][0]["qty"], 1)

        self._run(scenario)

    def test_later_saves_are_dropped(self):
        """比读回的这张更晚的存档都指向已经不存在的消息，留着只会误导。"""
        async def scenario():
            db, user, _other, sess, npc = await self._setup()
            await self._play(db, sess, 2, npc.id)
            early = await create_save(sess.id, RpgSaveCreate(label="早"), user, db)
            await self._play(db, sess, 2, npc.id)
            late = await create_save(sess.id, RpgSaveCreate(label="晚"), user, db)

            await restore_save(early.id, user, db)

            left = [s.id for s in await list_saves(sess.id, user, db)]
            self.assertIn(early.id, left)
            self.assertNotIn(late.id, left)

        self._run(scenario)

    def test_auto_saves_capped_manual_kept(self):
        async def scenario():
            db, user, _other, sess, npc = await self._setup()
            keeper = await create_save(sess.id, RpgSaveCreate(label="手动"), user, db)

            for _ in range(AUTO_SAVE_KEEP + 5):
                await _take_save(db, sess, "auto", "")
                await _prune_auto_saves(db, sess.id)
                await db.commit()

            rows = (await db.execute(
                select(RpgSave).where(RpgSave.session_id == sess.id)
            )).scalars().all()
            autos = [r for r in rows if r.kind == "auto"]
            self.assertEqual(len(autos), AUTO_SAVE_KEEP)
            self.assertIn(keeper.id, [r.id for r in rows])

        self._run(scenario)

    def test_other_user_gets_404(self):
        async def scenario():
            db, user, other, sess, npc = await self._setup()
            save = await create_save(sess.id, RpgSaveCreate(label=""), user, db)

            for call in (
                lambda: list_saves(sess.id, other, db),
                lambda: restore_save(save.id, other, db),
                lambda: delete_save(save.id, other, db),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await call()
                self.assertEqual(ctx.exception.status_code, 404)

        self._run(scenario)


if __name__ == "__main__":
    unittest.main()
