"""动作按钮：分栏、时间开销和地点限定。

这三个字段是模拟器那套「点一个功能吃一格时间」的节奏所依赖的东西，而在它们
加进来之前，RpgAction 和 _run_action 整个没有测试覆盖。所以这里连老行为一起钉：

1. 老动作（cost_slot=False、at_location=""）一格时间都不多花、随处可用。加这三列
   之前的模组读出来就是这个形状，行为必须逐字不变。
2. cost_slot 真的推时段，而且跨天时 reset_daily 的回满不能把这个动作自己的消耗抹掉
   ——那是 _run_action 里「推时段放最后」那一行的全部理由。
3. at_location 对不上时一个数值都不许动。它和 requires 一样是「做不做得成」，
   拦在 apply_stats 之前。
"""
import unittest

from app.agents.rpg_turn import _run_action
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgAction, RpgModule, RpgSession
from app.services.rpg_state import init_stats

STAT_DEFS = [
    # 精力勾了跨天回满，用来验证 reset_daily 和动作消耗的先后
    {"name": "精力", "initial": 100, "min": 0, "max": 100,
     "display": "条", "reset_daily": True},
    {"name": "资金", "initial": 300, "min": 0, "max": None, "display": "数字"},
]


def _module(**kwargs):
    base = {"stat_defs": STAT_DEFS, "relation_stat_defs": []}
    base.update(kwargs)
    return RpgModule(user_id=1, name="总裁模拟器", **base)


def _sess(**kwargs):
    base = {
        "stats": init_stats(STAT_DEFS),
        "time_slots": ["早", "中", "晚"],
        "slot": "早",
        "day": 1,
        "location": "办公室",
        "status": "alive",
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


def _action(**kwargs):
    base = {"name": "处理商业", "prompt_hint": "", "effects": {}, "relation_effects": {},
            "requires": {}, "needs_target": False, "group": "", "cost_slot": False,
            "at_location": ""}
    base.update(kwargs)
    return RpgAction(module_id=1, **base)


class CostSlotTests(unittest.TestCase):
    def test_an_old_action_does_not_move_the_clock(self):
        # 加这一列之前建的动作读出来 cost_slot=False，时间必须一格都不动
        sess = _sess()
        facts, _ = _run_action(_module(), sess, _action(effects={"资金": 50}), None)
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.day, 1)
        self.assertNotIn("现在是中", facts)

    def test_it_advances_one_slot(self):
        sess = _sess()
        facts, _ = _run_action(_module(), sess, _action(cost_slot=True), None)
        self.assertEqual(sess.slot, "中")
        self.assertEqual(sess.day, 1)
        self.assertIn("现在是中", facts)

    def test_a_module_without_a_clock_just_runs_the_action(self):
        # 没配时段的模组勾了 cost_slot 也不该炸，advance_slot 自己会空转
        sess = _sess(time_slots=[], slot="")
        facts, _ = _run_action(
            _module(time_slots=[]), sess, _action(cost_slot=True, effects={"资金": -20}), None
        )
        self.assertEqual(sess.stats["资金"], 280)
        self.assertEqual(sess.day, 1)

    def test_the_daily_recovery_runs_after_this_actions_cost(self):
        # 最后一格上勾了 cost_slot：推进会跨天，reset_daily 把精力抬到七成（70）。
        #
        # 起手故意压到 50 而不是用满值：满值时恢复本身是空操作，两种顺序都得 70，
        # 这条断言就永真了。50 起手能把两种顺序分开——
        #   先扣再恢复（对的）：50-30=20 → 抬到 70
        #   先恢复再扣（错的）：50→70 → -30 = 40
        # 断言 70 就钉住了「这一格的账结在旧的一天，新的一天从恢复线起步」
        sess = _sess(slot="晚", stats={"精力": 50, "资金": 300})
        _run_action(_module(), sess, _action(cost_slot=True, effects={"精力": -30}), None)
        self.assertEqual(sess.day, 2)
        self.assertEqual(sess.slot, "早")
        self.assertEqual(sess.stats["精力"], 70)

    def test_a_mid_day_action_keeps_its_cost(self):
        # 同一个动作不跨天时，消耗当然要留着——上一条的对照
        sess = _sess(slot="早")
        _run_action(_module(), sess, _action(cost_slot=True, effects={"精力": -30}), None)
        self.assertEqual(sess.day, 1)
        self.assertEqual(sess.stats["精力"], 70)


class AtLocationTests(unittest.TestCase):
    def test_an_empty_value_means_anywhere(self):
        sess = _sess(location="天台")
        _run_action(_module(), sess, _action(effects={"资金": 50}), None)
        self.assertEqual(sess.stats["资金"], 350)

    def test_the_right_place_passes(self):
        sess = _sess(location="办公室")
        _run_action(
            _module(), sess, _action(at_location="办公室", effects={"资金": 50}), None
        )
        self.assertEqual(sess.stats["资金"], 350)

    def test_the_wrong_place_changes_nothing(self):
        sess = _sess(location="天台")
        facts, _ = _run_action(
            _module(), sess,
            _action(at_location="办公室", effects={"资金": 50}, cost_slot=True), None,
        )
        self.assertEqual(sess.stats["资金"], 300)
        # 拦下来的动作也不许推时间
        self.assertEqual(sess.slot, "早")
        self.assertIn("办公室", facts[0])

    def test_the_match_ignores_spacing(self):
        # 全项目的地点引用都按 norm_name 比，这里不能是例外
        sess = _sess(location=" 办公室 ")
        _run_action(
            _module(), sess, _action(at_location="办公室", effects={"资金": 50}), None
        )
        self.assertEqual(sess.stats["资金"], 350)


class GroupTests(unittest.TestCase):
    def test_the_group_never_reaches_the_model(self):
        # 分栏纯粹是界面的事。它要是漏进事实句，模型就会在旁白里念「经营」
        sess = _sess()
        facts, _ = _run_action(
            _module(), sess, _action(group="经营", effects={"资金": 50}), None
        )
        self.assertNotIn("经营", "".join(facts))


if __name__ == "__main__":
    unittest.main()
