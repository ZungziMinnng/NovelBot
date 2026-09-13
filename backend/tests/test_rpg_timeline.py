"""统一时间线：消息自带地点和在场名单。

原先「这一轮归哪条线」由 thread_id 一列同时承担三件事——历史分区键、隐私边界、
界面视图。三件事绑在一个值上，于是每次让一件对了另两件就错。现在拆开：

- 历史只剩一条物理时间线，所有消息按 id 排在一处
- 隐私由消息上的 `present`（写入时快照的在场 NPC 名单）承担
- 界面视图是读时筛选，不落库

这批只钉「快照」这一半：**写入时记，不是读时回查**。理由是不动快照的话，
作息表推时段会清空 npc_places、剧情会把人物挪走，事后拿 sess 回查算出来的是
「现在谁在」，而不是「当时谁在」——同一段群戏会在不同人的视图里各缺一半。
"""
import unittest

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import create_session
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgMessage, RpgModule, RpgNpc, RpgSession
from app.models.user import User
from app.schemas.rpg import RpgSessionCreate
from app.services.rpg_context import present_ids

STAT_DEFS = [{"name": "精力", "initial": 100, "min": 0, "max": 100}]


def _npc(npc_id, name, location):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location)


class PresentSnapshotTests(unittest.TestCase):
    """在场名单怎么算。它和 onstage_npcs 的差别正是这里要钉的差别。"""

    def test_present_is_who_stands_here(self):
        npcs = [_npc(7, "老兵", "地窖"), _npc(9, "老板娘", "酒馆")]
        self.assertEqual(present_ids(npcs, "地窖"), [7])

    def test_everyone_in_a_group_scene_is_present(self):
        # 群戏就是「在场名单里有多个」。写一次，两个人的视图里同时出现，
        # 靠的是这条消息本身就记着两个人在场，不需要往各条历史里复制
        npcs = [_npc(7, "老兵", "地窖"), _npc(9, "老板娘", "地窖")]
        self.assertEqual(sorted(present_ids(npcs, "地窖")), [7, 9])

    def test_nobody_present_is_an_empty_list_not_none(self):
        # 空列表和 None 含义不同：[] = 确定只有玩家一个人（不进任何 NPC 的
        # 视图），None = 不知道（老消息，当所有人可见）。混成一个会让老存档
        # 里所有群戏对 NPC 集体失忆，或者让玩家独处做的事泄露给所有人
        npcs = [_npc(7, "老兵", "铁匠铺")]
        self.assertEqual(present_ids(npcs, "地窖"), [])

    def test_a_module_without_locations_puts_everyone_in_one_scene(self):
        # 模组一个地点都没建时 here_npcs 恒为空。不兜底的话这类纯对话模组的每条
        # 消息都成了「只有玩家一个人」，每个 NPC 的视图全空。这条读法照抄
        # _settle 里那一份（「没有地点就意味着所有人都在同一个场面里」）
        self.assertEqual(present_ids([_npc(7, "老兵", "地窖")], ""), [7])

    def test_the_schedule_decides_like_everywhere_else(self):
        # 在场只有一个定义（here_npcs），作息表参与的方式不该在这里被绕过
        npc = _npc(7, "老兵", "地窖")
        npc.slot_locations = {"夜": "酒馆"}
        self.assertEqual(present_ids([npc], "酒馆", "夜"), [7])
        self.assertEqual(present_ids([npc], "地窖", "夜"), [])


class OpeningNarrationTests(unittest.IsolatedAsyncioTestCase):
    """开场白也是一条普通消息，它同样要记下当时谁在场。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = User(username="alice", password_hash="x")
        self.db.add(self.user)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _module(self, **kwargs):
        module = RpgModule(
            user_id=self.user.id, name="测试模组",
            stat_defs=STAT_DEFS, relation_stat_defs=[], **kwargs,
        )
        self.db.add(module)
        await self.db.commit()
        return module

    async def _rows(self, sess):
        return (await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == sess.id)
            .order_by(RpgMessage.id)
        )).scalars().all()

    async def test_the_opening_records_who_was_there(self):
        module = await self._module(
            default_location="校长办公室", opening_scene="校长办公室里，赫敏就在跟前。",
        )
        self.db.add(RpgNpc(module_id=module.id, name="赫敏", location="校长办公室"))
        await self.db.commit()

        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        rows = await self._rows(sess)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].location, "校长办公室")
        self.assertEqual(len(rows[0].present or []), 1)

    async def test_an_empty_scene_records_nobody(self):
        # 没写开场白的模组：一条消息都不该有，免得开场白那格被一条空旁白占住
        module = await self._module(default_location="地窖")
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        self.assertEqual(await self._rows(sess), [])


class StoredReplyTests(unittest.IsolatedAsyncioTestCase):
    """assistant 行要照抄路由快照的那一份，不在自己这边重算。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        module = RpgModule(
            user_id=1, name="测试模组", stat_defs=STAT_DEFS, relation_stat_defs=[]
        )
        self.db.add(module)
        await self.db.commit()
        self.sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="地窖")
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_the_reply_keeps_the_snapshot_it_was_handed(self):
        # 结算会把人物挪走（apply_npc_activity / move_npcs）。这里传的名单是
        # 这一轮**开始时**算的，落库时要原样保留——重算会让一问一答分进两拨
        # 在场名单，同一次对话在两个人的视图里各缺一半
        own = rpg_turn.AsyncSessionLocal
        rpg_turn.AsyncSessionLocal = self.sessions
        try:
            await rpg_turn._store_reply(
                self.sess.id, "老兵哼了一声。", 10, 20, [7], "地窖"
            )
        finally:
            rpg_turn.AsyncSessionLocal = own
        rows = (await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == self.sess.id)
        )).scalars().all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].present, [7])
        self.assertEqual(rows[0].location, "地窖")


class LegacyBackfillTests(unittest.IsolatedAsyncioTestCase):
    """老库回填：按线记的消息，在场名单就是那一个人。

    场面线（thread_id 为 NULL）当年是群戏和独处混在一条线上，分不出来，保持
    NULL = 所有人可见。**不能图省事填成 []**——那等于宣布老存档里所有群戏都是
    玩家一个人干的，每个 NPC 对共同经历集体失忆。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _legacy_db(self):
        """造一个加列之前形状的库：只有 thread_id，没有 location / present。"""
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE rpg_sessions (id INTEGER PRIMARY KEY, summarized_upto_id INTEGER DEFAULT 0)"
            ))
            await conn.execute(text(
                "CREATE TABLE rpg_messages ("
                "id INTEGER PRIMARY KEY, session_id INTEGER, role VARCHAR(20),"
                "content TEXT, thread_id INTEGER)"
            ))
            await conn.execute(text(
                "INSERT INTO rpg_messages (id, session_id, role, content, thread_id) VALUES"
                "(1, 1, 'assistant', '开场白', NULL),"
                "(2, 1, 'user', '对老兵说的', 7),"
                "(3, 1, 'user', '对老板娘说的', 9),"
                "(4, 1, 'user', '一个人在场面上做的事', NULL)"
            ))
            await conn.execute(text(
                "INSERT INTO rpg_sessions (id, summarized_upto_id) VALUES (1, 3), (2, 0)"
            ))

    async def _add_columns(self):
        """加列那一步。真库里 ALTER 重复执行会被 _is_expected_migration_error
        吞掉，这里不模拟那层宽容——重复加列本身就是错的。"""
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE rpg_messages ADD COLUMN location VARCHAR(100) DEFAULT ''"
            ))
            await conn.execute(text(
                "ALTER TABLE rpg_messages ADD COLUMN present JSON DEFAULT NULL"
            ))

    async def _backfill(self):
        """回填那一步，每次启动都跑。"""
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "UPDATE rpg_messages SET present = '[' || thread_id || ']' "
                "WHERE thread_id IS NOT NULL AND present IS NULL"
            ))

    async def _present(self):
        async with self.engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT id, present FROM rpg_messages ORDER BY id"
            ))).all()
        return {r[0]: r[1] for r in rows}

    async def test_a_line_message_gets_its_owner(self):
        await self._legacy_db()
        await self._add_columns()
        await self._backfill()
        present = await self._present()
        self.assertEqual(present[2], "[7]")
        self.assertEqual(present[3], "[9]")

    async def test_a_scene_message_stays_unknown(self):
        await self._legacy_db()
        await self._add_columns()
        await self._backfill()
        present = await self._present()
        self.assertIsNone(present[1])
        self.assertIsNone(present[4])

    async def test_the_backfill_is_idempotent(self):
        # 这串 SQL 每次启动都跑，不能把新消息也卷进去
        await self._legacy_db()
        await self._add_columns()
        await self._backfill()
        first = await self._present()
        await self._backfill()
        self.assertEqual(await self._present(), first)


class SummaryPointerResetTests(unittest.IsolatedAsyncioTestCase):
    """老库的概要指针要归零，但只归一次。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE rpg_sessions (id INTEGER PRIMARY KEY, summarized_upto_id INTEGER DEFAULT 0)"
            ))
            await conn.execute(text(
                "INSERT INTO rpg_sessions (id, summarized_upto_id) VALUES (1, 500), (2, 0)"
            ))

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _upto(self):
        async with self.engine.begin() as conn:
            rows = (await conn.execute(text(
                "SELECT id, summarized_upto_id FROM rpg_sessions ORDER BY id"
            ))).all()
        return {r[0]: r[1] for r in rows}

    async def test_a_legacy_db_is_recognised_before_the_column_is_added(self):
        # 判据必须在这里问：加列迁移一跑它就恒为假，回填就永远不触发了
        from app.database import _rpg_timeline_is_legacy

        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE TABLE rpg_messages (id INTEGER PRIMARY KEY)"))
            self.assertTrue(await _rpg_timeline_is_legacy(conn))
            await conn.execute(text(
                "ALTER TABLE rpg_messages ADD COLUMN location VARCHAR(100) DEFAULT ''"
            ))
            self.assertFalse(await _rpg_timeline_is_legacy(conn))

    async def test_the_pointer_is_cleared_for_legacy_sessions(self):
        # 那个指针记的是**场面线**压到哪。统一之后，它之前、属于角色线的消息
        # 从没被压进任何概要，却会被当成「已经压过了」跳过——早期私聊的内容
        # 就这么静默消失。归零让它们重新发原文
        from app.database import _backfill_rpg_timeline

        await _backfill_rpg_timeline(self.engine)
        self.assertEqual(await self._upto(), {1: 0, 2: 0})
