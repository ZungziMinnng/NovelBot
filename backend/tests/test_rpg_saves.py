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
    create_save, delete_npc_note, delete_save, list_saves, restore_save,
)
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSave, RpgSession
from app.models.user import User
from app.schemas.rpg import RpgNoteDeleteIn, RpgSaveCreate


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

    def test_the_clock_rewinds_with_everything_else(self):
        """时段和天数也随回合变，所以也必须进快照。

        漏了它不会报错，只会在读档之后留下一个不还原的时钟——玩家看到的
        是「回到三小时前，但天还是黑的」，而且怎么查都查不出原因。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            sess.time_slots = ["早", "中", "晚"]
            sess.slot = "早"
            sess.day = 1
            await db.commit()
            save = await create_save(sess.id, RpgSaveCreate(label="第一天早上"), user, db)

            sess.slot = "晚"
            sess.day = 4
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.slot, "早")
            self.assertEqual(restored.day, 1)

        self._run(scenario)

    def test_an_old_snapshot_without_a_clock_falls_back_to_the_defaults(self):
        """本次改动之前存下的快照里根本没有这三个字段。

        读档时按 SNAPSHOT_DEFAULTS 补，否则读一个老档会把当前时钟留在原地
        ——看着像是回到了过去，天却还是今天的天。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            save = await _take_save(db, sess, "manual", "老档")
            # 模拟老快照：把三个新字段从 state 里摘掉
            save.state = {
                k: v for k, v in save.state.items()
                if k not in ("time_slots", "slot", "day")
            }
            await db.commit()

            sess.time_slots = ["早", "中", "晚"]
            sess.slot = "晚"
            sess.day = 9
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.time_slots, [])
            self.assertEqual(restored.slot, "")
            self.assertEqual(restored.day, 1)

        self._run(scenario)

    def test_the_chronicle_rewinds_with_everything_else(self):
        """大事记也随回合变，所以也必须进快照。

        读档之后它还留着「未来」传开的事，玩家就会遇到没发生过的事被人提起——
        和摘要没回滚是同一类 bug，而且更难看出来（它不像剧情那样一眼可查）。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            sess.chronicle = ["后山挖出了尸首"]
            await db.commit()
            save = await create_save(sess.id, RpgSaveCreate(label="案发前"), user, db)

            sess.chronicle = ["后山挖出了尸首", "你半夜翻进了他家"]
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.chronicle, ["后山挖出了尸首"])

        self._run(scenario)

    def test_the_fog_rewinds_with_everything_else(self):
        """去过哪儿也随回合变，所以也必须进快照。

        不回滚的话，读档回到出发前，地图上那片还没探过的区域却已经亮着——
        玩家看到的是「我还没去过，但地图知道那儿有什么」。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            sess.visited = ["出租屋"]
            await db.commit()
            save = await create_save(sess.id, RpgSaveCreate(label="出门前"), user, db)

            sess.visited = ["出租屋", "地窖"]
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.visited, ["出租屋"])

        self._run(scenario)

    def test_an_old_snapshot_without_a_fog_log_falls_back_to_an_empty_one(self):
        """加这个字段之前存下的快照里没有它，按 SNAPSHOT_DEFAULTS 补空。

        代价是读老档会把地图整片关掉；反过来（留着当前的）就是把存档之后
        才探到的地方漏回过去，那正是这套默认值在防的事。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            save = await _take_save(db, sess, "manual", "老档")
            save.state = {k: v for k, v in save.state.items() if k != "visited"}
            await db.commit()

            sess.visited = ["出租屋", "地窖"]
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.visited, [])

        self._run(scenario)

    def test_the_npc_notes_rewind_with_everything_else(self):
        """GM 记下的 NPC 近况也随回合变，所以也必须进快照。

        不回滚的话，读档回到挨刀之前，模型手上却还留着「她左肩中刀」，
        于是她捂着一个还没发生的伤口说话。
        """
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            sess.npc_notes = {"1": {"伤势": "毫发无伤"}}
            await db.commit()
            save = await create_save(sess.id, RpgSaveCreate(label="动手前"), user, db)

            sess.npc_notes = {"1": {"伤势": "左肩中刀"}}
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.npc_notes, {"1": {"伤势": "毫发无伤"}})

        self._run(scenario)

    def test_an_old_snapshot_without_npc_notes_falls_back_to_an_empty_table(self):
        """加这个字段之前存下的快照里没有它，按 SNAPSHOT_DEFAULTS 补空。"""
        async def scenario():
            db, user, _other, sess, _npc = await self._setup()

            save = await _take_save(db, sess, "manual", "老档")
            save.state = {k: v for k, v in save.state.items() if k != "npc_notes"}
            await db.commit()

            sess.npc_notes = {"1": {"伤势": "左肩中刀"}}
            await db.commit()

            restored = await restore_save(save.id, user, db)
            self.assertEqual(restored.npc_notes, {})

        self._run(scenario)

    def test_crossing_out_one_note_is_the_way_out_that_is_not_a_rewind(self):
        """这条路由存在的全部理由：不用把这之后玩的都扔掉也能改掉一条错记录。

        所以它测在这儿——它是读档的替代品。只动点掉的那一条，别的不许碰。
        """
        async def scenario():
            db, user, _other, sess, npc = await self._setup()

            sess.npc_notes = {str(npc.id): {"身份": "其实是幕后凶手", "伤势": "左肩中刀"}}
            await db.commit()

            out = await delete_npc_note(
                sess.id, npc.id, RpgNoteDeleteIn(key="身份"), user, db
            )
            self.assertEqual(out.npc_notes[str(npc.id)], {"伤势": "左肩中刀"})

        self._run(scenario)

    def test_someone_else_cannot_cross_out_your_notes(self):
        async def scenario():
            db, user, other, sess, npc = await self._setup()
            sess.npc_notes = {str(npc.id): {"伤势": "左肩中刀"}}
            await db.commit()

            with self.assertRaises(HTTPException) as ctx:
                await delete_npc_note(
                    sess.id, npc.id, RpgNoteDeleteIn(key="伤势"), other, db
                )
            self.assertEqual(ctx.exception.status_code, 404)

        self._run(scenario)

    def test_reading_back_restores_each_line_to_its_own_length(self):
        """线是消息的派生结果，按 id 删完消息自然回到那一刻。

        这是「不建线程表」最直接的好处：不需要任何额外的清理，
        也不会留下一堆点不开的空对话。
        """
        async def scenario():
            db, user, _other, sess, npc = await self._setup()

            await self._play(db, sess, 2, npc.id)
            sess.chronicle = ["聊过一轮"]
            await db.commit()
            save = await create_save(sess.id, RpgSaveCreate(label=""), user, db)

            # 之后又跟老兵聊了两句，场面线也加了一句
            for text in ("对老兵说的", "老兵的回答", "场面上的一句"):
                db.add(RpgMessage(session_id=sess.id, role="user", content=text,
                                  thread_id=None if text.startswith("场") else npc.id))
            await db.commit()

            await restore_save(save.id, user, db)

            left = (await db.execute(
                select(RpgMessage).where(RpgMessage.session_id == sess.id)
            )).scalars().all()
            self.assertEqual([m.content for m in left], ["第1轮", "旁白", "第2轮", "旁白"])
            self.assertEqual(sess.chronicle, ["聊过一轮"])

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

            for i in range(AUTO_SAVE_KEEP + 5):
                # 每轮都得先有一条新消息：自动档按 before_message_id 去重，
                # 同一个位置只留一张（见 test_an_auto_save_is_not_taken_twice...）
                db.add(RpgMessage(session_id=sess.id, role="user", content=f"第{i}句"))
                await db.flush()
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

    def test_an_auto_save_is_not_taken_twice_at_the_same_spot(self):
        """同一个消息位置只留最早那一张自动档。

        时钟和瞬移不产生消息，连点十次就是十张 before_message_id 完全相同
        的快照，把 30 张的窗口灌满、真正的回合档被挤掉。手动档不去重：
        玩家自己按的那下就是意图。
        """
        async def scenario():
            db, user, _other, sess, npc = await self._setup()
            await self._play(db, sess, 1, npc.id)

            first = await _take_save(db, sess, "auto", "")
            await db.commit()
            again = await _take_save(db, sess, "auto", "")
            await db.commit()
            self.assertEqual(first.id, again.id)

            hand = await create_save(sess.id, RpgSaveCreate(label="手动"), user, db)
            hand2 = await create_save(sess.id, RpgSaveCreate(label="手动"), user, db)
            self.assertNotEqual(hand.id, hand2.id)

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
