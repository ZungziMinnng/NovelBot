"""时段（分幕）：玩家自己拨的时钟，以及跨天回满。

时钟是纯手动的——只有 advance_slot 能推动它，模型连提议的通道都没有
（结算 JSON 里没有时间字段）。所以这里要钉住的就两件事：推进的边界在哪，
以及「新的一天」到底重置了什么。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.rpg import create_session
from app.database import Base, _backfill_rpg_clock, _repair_concatenated_clock
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgModule, RpgSession
from app.models.user import User
from app.schemas.rpg import RpgSessionCreate
from app.services.rpg_state import advance_slot, init_stats, reset_daily, slot_table

STAT_DEFS = [
    # 精力勾了跨天回满，上限 100
    {"name": "精力", "initial": 100, "min": 0, "max": 100,
     "display": "条", "reset_daily": True},
    # 资金没勾，花掉就是花掉了
    {"name": "资金", "initial": 300, "min": 0, "max": None, "display": "数字"},
    # 勾了但没有上限：回满这件事没有定义，跳过
    {"name": "声望", "initial": 0, "min": 0, "max": None,
     "display": "数字", "reset_daily": True},
    # 有上限但没勾：不动
    {"name": "怀疑度", "initial": 0, "min": 0, "max": 100, "display": "隐藏"},
]


def _module(**kwargs):
    base = {"stat_defs": STAT_DEFS, "relation_stat_defs": []}
    base.update(kwargs)
    return RpgModule(user_id=1, name="测试模组", **base)


def _sess(**kwargs):
    base = {
        "stats": init_stats(STAT_DEFS),
        "time_slots": ["早", "中", "晚"],
        "slot": "早",
        "day": 1,
        "status": "alive",
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class AdvanceTests(unittest.TestCase):
    def test_it_walks_the_slots_in_order(self):
        sess = _sess()
        self.assertEqual(advance_slot(_module(), sess), ["现在是中"])
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.day, 1)

    def test_the_last_slot_rolls_over_into_a_new_day(self):
        sess = _sess(slot="晚")
        facts = advance_slot(_module(), sess)
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 2)
        # 翻篇要告诉玩家，否则「回到早」看着像是按错了
        self.assertTrue(any("第 2 天" in f for f in facts))

    def test_a_module_without_a_clock_does_nothing(self):
        # 模组没设时段时按钮本来就不该出现，真按了也不能有任何后果
        sess = _sess(time_slots=[], slot="")
        self.assertEqual(advance_slot(_module(), sess), [])
        self.assertEqual(sess.slot, "")
        self.assertEqual(sess.day, 1)

    def test_a_slot_that_is_no_longer_in_the_table_starts_over(self):
        # 建局之后模组改了时段表，老局会停在一个表里没有的名字上。
        # 从第一格重新数起，而不是崩在 index() 上；也不翻页——
        # 名字对不上就凭空多一天，玩家会觉得时钟坏了
        sess = _sess(time_slots=["上午", "下午"], slot="晚")
        self.assertEqual(advance_slot(_module(), sess), ["现在是上午"])
        self.assertEqual(sess.day, 1)

    def test_the_day_only_advances_on_rollover(self):
        sess = _sess(time_slots=["早", "晚"], slot="早")
        advance_slot(_module(), sess)
        self.assertEqual(sess.day, 1)
        advance_slot(_module(), sess)
        self.assertEqual(sess.day, 2)


class ResetDailyTests(unittest.TestCase):
    def test_it_refills_to_the_ceiling_not_the_initial_value(self):
        # 「回满」只在有上限时才成立。用 initial 的话，建局时把初始值改过的
        # 玩家会得到一个既不是初始也不是满的怪数字
        sess = _sess(stats={"精力": 12, "资金": 300, "声望": 5, "怀疑度": 80})
        notes = reset_daily(_module(), sess)
        self.assertEqual(sess.stats["精力"], 100)
        self.assertIn("精力", " ".join(notes))

    def test_uncapped_and_unchecked_stats_are_left_alone(self):
        sess = _sess(stats={"精力": 12, "资金": 300, "声望": 5, "怀疑度": 80})
        reset_daily(_module(), sess)
        self.assertEqual(sess.stats["资金"], 300)      # 没勾
        self.assertEqual(sess.stats["声望"], 5)        # 勾了但没有上限
        self.assertEqual(sess.stats["怀疑度"], 80)     # 有上限但没勾

    def test_an_already_full_stat_is_not_reported(self):
        # 满着的时候不该冒一句「精力回到 100」，那是噪音
        sess = _sess(stats={"精力": 100, "资金": 300, "声望": 0, "怀疑度": 0})
        self.assertEqual(reset_daily(_module(), sess), [])

    def test_stats_the_definition_does_not_know_are_untouched(self):
        # 老局里可能留着模组已经删掉的数值，别顺手清掉它们
        sess = _sess(stats={"精力": 12, "旧数值": 7})
        reset_daily(_module(), sess)
        self.assertEqual(sess.stats["旧数值"], 7)

    def test_rollover_drives_the_refill(self):
        # 两件事必须串起来：这才是「花掉精力 → 睡一觉 → 回满」的循环
        sess = _sess(slot="晚", stats={"精力": 3, "资金": 300, "声望": 0, "怀疑度": 0})
        facts = advance_slot(_module(), sess)
        self.assertEqual(sess.stats["精力"], 100)
        self.assertTrue(any("精力" in f for f in facts))


class CreateSessionTests(unittest.IsolatedAsyncioTestCase):
    """时段表归模组管，这一局只记「我停在第几格」。

    玩家建局时改过的那一份才存进局里，并且从此不追溯（理由同 default_location）。
    没改过的存空 = 跟模组走，模组后来调整时段表会跟着变。
    """

    async def asyncSetUp(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(engine, expire_on_commit=False)()
        self.user = User(username="alice", password_hash="x")
        self.db.add(self.user)
        await self.db.commit()

    async def _module(self, **kwargs):
        module = RpgModule(
            user_id=self.user.id, name="测试模组",
            stat_defs=STAT_DEFS, relation_stat_defs=[], **kwargs,
        )
        self.db.add(module)
        await self.db.commit()
        return module

    async def test_the_clock_is_not_copied_but_followed(self):
        # 没定制过的局只记「我在第几格」，不存表。存了表就等于把这一局冻住，
        # 模组后来把时段拆细，已开的局纹丝不动——作者会以为模组改坏了
        module = await self._module(time_slots=["早", "中", "晚"])
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        self.assertEqual(sess.time_slots, [])
        # 开局就站在第一格上，否则首轮的状态块里时间是空的，界面也不出时钟
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 1)

    async def test_a_module_edit_reaches_a_session_that_never_customised(self):
        module = await self._module(time_slots=["早中晚"])
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        # 作者发现时段该拆开，改了模组
        module.time_slots = ["早", "中", "晚"]
        await self.db.commit()
        self.assertEqual(slot_table(module, sess), ["早", "中", "晚"])

    async def test_the_player_can_set_their_own_table(self):
        module = await self._module(time_slots=["早", "中", "晚"])
        sess = await create_session(
            module.id,
            RpgSessionCreate(char_name="阿隼", time_slots=["白天", "夜里"]),
            self.user, self.db,
        )
        self.assertEqual(sess.time_slots, ["白天", "夜里"])
        self.assertEqual(sess.slot, "白天")

    async def test_an_empty_list_falls_back_to_the_module(self):
        # 留空 = 跟模组走，不是「这一局不要时钟」。「不要时钟」只有模组本身
        # 没设时段才能表达——空和「没配过」在这里必须是同一个意思
        module = await self._module(time_slots=["早", "中", "晚"])
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼", time_slots=[]),
            self.user, self.db,
        )
        self.assertEqual(sess.time_slots, [])
        self.assertEqual(slot_table(module, sess), ["早", "中", "晚"])
        self.assertEqual(sess.slot, "早")

    async def test_blank_names_are_dropped_rather_than_becoming_a_slot(self):
        # 前端把一行逗号文本切成数组，尾随逗号会留下空串；空串不能变成一个时段名
        module = await self._module()
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼", time_slots=["", "早", "  "]),
            self.user, self.db,
        )
        self.assertEqual(sess.time_slots, ["早"])

    async def test_a_clock_added_after_the_fact_is_usable(self):
        # 建局时模组还没有时段，作者后来才加上。这一局的 slot 永远是空的，
        # 所以界面上的时钟不能拿 slot 当开关（拿它当开关的后果就是时钟永远
        # 出不来，连带所有按时段设门槛的内容无声锁死）。按一下就落到第一格
        module = await self._module()
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        self.assertEqual(sess.slot, "")

        module.time_slots = ["早", "中", "晚"]
        await self.db.commit()
        self.assertEqual(slot_table(module, sess), ["早", "中", "晚"])
        self.assertEqual(advance_slot(module, sess), ["现在是早"])
        self.assertEqual(sess.day, 1)

    async def test_a_module_without_a_clock_stays_without_one(self):
        module = await self._module()
        sess = await create_session(
            module.id, RpgSessionCreate(char_name="阿隼"), self.user, self.db
        )
        self.assertEqual(sess.time_slots, [])
        self.assertEqual(sess.slot, "")


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    """老局补时钟：这批改动之前开的局拿到的是 '[]' 和 ''，得让它们跟上模组。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _pair(self, module_slots, session_slots, slot=""):
        module = RpgModule(
            user_id=1, name="测试模组", stat_defs=STAT_DEFS,
            relation_stat_defs=[], time_slots=module_slots,
        )
        self.db.add(module)
        await self.db.commit()
        sess = RpgSession(
            module_id=module.id, char_name="阿隼", stats={},
            time_slots=session_slots, slot=slot,
        )
        self.db.add(sess)
        await self.db.commit()
        return sess

    async def _backfill(self, *sessions):
        """补一遍档，再把传进来的会话从库里重新读出来。

        必须显式 refresh：补档走的是另一条连接上的裸 SQL，ORM 手上还是旧值；
        而 expire_all() 只是把对象标脏，下一次读属性会在同步的断言里触发 IO
        （MissingGreenlet）。
        """
        await _backfill_rpg_clock(self.engine)
        for sess in sessions:
            await self.db.refresh(sess)

    async def test_an_old_session_is_given_a_starting_slot(self):
        sess = await self._pair(["早", "中", "晚"], [])
        await self._backfill(sess)
        # 只补「我在第几格」，**不把表拷进局里**——拷了就永久冻住，
        # 模组后来改对了这一局也不会动
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.time_slots, [])
        self.assertEqual(sess.day, 1)

    async def test_the_field_really_is_clockless_before_the_backfill(self):
        # 上面那条的前提：没有 slot 就没有时钟，界面整块都不出现
        sess = await self._pair(["早", "中", "晚"], [])
        self.assertEqual(sess.slot, "")

    async def test_a_session_that_already_started_is_not_reset(self):
        # 已经按过「结束这个时段」的局不能被拽回第一格
        sess = await self._pair(["早", "中", "晚"], [], slot="夜里")
        await self._backfill(sess)
        self.assertEqual(sess.slot, "夜里")

    async def test_a_module_without_a_clock_leaves_the_session_alone(self):
        sess = await self._pair([], [])
        await self._backfill(sess)
        self.assertEqual(sess.time_slots, [])
        self.assertEqual(sess.slot, "")

    async def test_it_is_idempotent(self):
        # 每次启动都会跑一遍，第二次不能把已经补好的东西再动一次
        sess = await self._pair(["早", "中", "晚"], [])
        await self._backfill(sess)
        sess.slot = "晚"
        sess.day = 4
        await self.db.commit()
        await self._backfill(sess)
        self.assertEqual(sess.slot, "晚")
        self.assertEqual(sess.day, 4)


class ConcatenatedClockTests(unittest.IsolatedAsyncioTestCase):
    """逗号被吃掉那阵子留下的脏数据：整张表存成了一个格子叫「早中晚」。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _pair(self, module_slots, session_slots, slot):
        module = RpgModule(
            user_id=1, name="测试模组", stat_defs=STAT_DEFS,
            relation_stat_defs=[], time_slots=module_slots,
        )
        self.db.add(module)
        await self.db.commit()
        sess = RpgSession(
            module_id=module.id, char_name="阿隼", stats={},
            time_slots=session_slots, slot=slot,
        )
        self.db.add(sess)
        await self.db.commit()
        return sess

    async def _repair(self, sess):
        await _repair_concatenated_clock(self.engine)
        await self.db.refresh(sess)

    async def test_the_smashed_table_is_dropped(self):
        sess = await self._pair(["早", "中", "晚"], ["早中晚"], "早中晚")
        await self._repair(sess)
        # 那份是历史遗留的拷贝，丢掉，退回跟模组走
        self.assertEqual(sess.time_slots, [])
        self.assertEqual(sess.slot, "早")
        self.assertEqual(slot_table(
            await self.db.get(RpgModule, sess.module_id), sess
        ), ["早", "中", "晚"])

    async def test_a_real_override_is_not_touched(self):
        # 玩家自己起的名字跟模组连写对不上，不能误伤
        sess = await self._pair(["早", "中", "晚"], ["白天"], "白天")
        await self._repair(sess)
        self.assertEqual(sess.time_slots, ["白天"])
        self.assertEqual(sess.slot, "白天")

    async def test_a_table_that_is_genuinely_one_slot_is_not_touched(self):
        # 模组本来就只有一格时，连写判据不成立（要求模组至少两格）
        sess = await self._pair(["早中晚"], ["早中晚"], "早中晚")
        await self._repair(sess)
        self.assertEqual(sess.time_slots, ["早中晚"])

    async def test_it_does_not_keep_firing(self):
        sess = await self._pair(["早", "中", "晚"], ["早中晚"], "早中晚")
        await self._repair(sess)
        sess.time_slots = ["白天", "夜里"]
        await self.db.commit()
        await self._repair(sess)
        self.assertEqual(sess.time_slots, ["白天", "夜里"])


if __name__ == "__main__":
    unittest.main()
