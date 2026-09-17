import unittest
from types import SimpleNamespace

from app.services.rpg_settlement import filter_discoveries


NARRATION = (
    "老周把刀横过来教了你一式「listen风辨位」，说学会了夜里就不怕人摸上来。"
    "临走他又托你一桩事，叫「送信给老周」——把信交到镇西的柳娘子手上。"
)

# 正文里真出现过的那两个名字。中英混排纯粹是为了避开分词的边界情况
SKILL = "listen风辨位"
TASK = "送信给老周"


def _row(name):
    return SimpleNamespace(name=name)


class DiscoverSkillsAndTasksTests(unittest.TestCase):
    """技能和任务走的是和角色/地点/道具同一条发现链，所以三道关一模一样：
    名字要在正文里真出现过、hint 要是正文原话、登记过的一律不再报。

    只有任务例外，不查名字——它的名字是模型自己起的标签，见下面那两条。"""

    def _run(self, **kw):
        data = {"discoveries": {
            "skills": [{"name": SKILL, "hint": "老周把刀横过来教了你一式"}],
            "tasks": [{"name": TASK, "hint": "临走他又托你一桩事"}],
        }}
        return filter_discoveries(data, NARRATION, [], [], [], [], 7, **kw)

    def test_a_new_skill_and_task_are_both_reported(self):
        got = self._run()
        self.assertEqual(
            [(entry["kind"], entry["name"]) for entry in got],
            [("skill", SKILL), ("task", TASK)],
        )

    def test_a_hint_that_is_not_a_verbatim_quote_is_dropped(self):
        got = filter_discoveries(
            {"discoveries": {"skills": [{"name": SKILL, "hint": "他好像教了你什么招式"}]}},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual(got, [])

    def test_a_name_that_never_appears_in_the_narration_is_dropped(self):
        got = filter_discoveries(
            {"discoveries": {"skills": [{"name": "破军刀法", "hint": "临走他又托你一桩事"}]}},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual(got, [])

    def test_a_task_name_does_not_have_to_appear_in_the_narration(self):
        """任务名是模型自己起的一句标签，正文里几乎不会有这么一串。

        真实case：雏田开口「能陪我一起去集市吗」、玩家点头答应，模型报的是
        「陪雏田去集市」——逐字对不上，于是每一桩差事都在名字这道关上被静默
        丢掉，外面看起来就像模型压根没认出来。它的依据是 hint 那一道关。
        """
        got = filter_discoveries(
            {"discoveries": {"tasks": [{"name": "把信交到柳娘子手上",
                                        "hint": "临走他又托你一桩事"}]}},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual([entry["name"] for entry in got], ["把信交到柳娘子手上"])

    def test_a_task_still_needs_a_verbatim_hint(self):
        """名字那道关放开了，hint 这道就是任务唯一的依据，不能跟着松。"""
        got = filter_discoveries(
            {"discoveries": {"tasks": [{"name": "把信交到柳娘子手上",
                                        "hint": "他好像让你帮个忙"}]}},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual(got, [])

    def test_a_module_definition_alone_does_not_hide_it(self):
        """模组里有定义、但这一局还没学会/接下——**照样要报**。

        技能和任务光有模组行这一局用不了，得另外学会/接下。两个条件当一个用的话
        「模组有行、这一局没拿到」就出不去了：发现报不上来，于是永远没人去学它。
        真实case：蚀骨春引建了定义，学会那一回合的结算崩了，从此这一招消失。
        """
        got = self._run(skills=[_row(SKILL)], tasks=[_row(TASK)])
        self.assertEqual(
            [(entry["kind"], entry["name"]) for entry in got],
            [("skill", SKILL), ("task", TASK)],
        )

    def test_a_module_definition_still_blocks_the_other_kinds(self):
        """但同名的**别的**类别还是该拦：技能叫这名字，就不该再建一件同名道具。"""
        got = filter_discoveries(
            {"discoveries": {"items": [{"name": SKILL, "hint": "老周把刀横过来教了你一式"}]}},
            NARRATION, [], [], [], [], 7, skills=[_row(SKILL)],
        )
        self.assertEqual(got, [])

    def test_something_already_learned_or_taken_this_run_is_not_reported_again(self):
        """模组里还没这一行，但这一局已经会了 / 已经接下了——同样不该再报，
        否则每回合都会重新冒出来一条一模一样的发现。"""
        owned = [{"name": SKILL, "cooldown_left": 0}, {"name": TASK, "status": "open"}]
        self.assertEqual(self._run(owned=owned), [])

    def test_a_place_may_be_named_with_an_owner_the_narration_only_implies(self):
        """地名常得带个归属才认得出是哪儿，而正文里写的是代词。

        真实case：正文「你半拖半抱地将她带到了她的公寓门前」，模型报「纲手的
        公寓」——逐字查名字就查不着，于是这一路的地点一个都建不起来。
        """
        narration = "你半拖半抱地将她带到了她的公寓门前。你从她身上摸出钥匙，拧开房门。"
        got = filter_discoveries(
            {"discoveries": {"places": [{"name": "纲手的公寓",
                                         "hint": "你半拖半抱地将她带到了她的公寓门前。"}]}},
            narration, [], [], [], [], 7,
        )
        self.assertEqual([entry["name"] for entry in got], ["纲手的公寓"])

    def test_a_place_pulled_out_of_thin_air_is_still_dropped(self):
        """放宽只放到「半个名字也得在正文里」为止。正文压根没提的地方照旧要拦，
        否则模型顺手造一个地名，模组里就多一行谁也不认识的地点。"""
        got = filter_discoveries(
            {"discoveries": {"places": [{"name": "紫云洞",
                                         "hint": "临走他又托你一桩事"}]}},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual(got, [])

    def test_an_item_already_waiting_in_the_backpack_queue_is_not_also_a_discovery(self):
        """一件东西该走哪条路是二选一的：拿走了的挂「道具栏待确认」，没拿走的才
        进「新发现」。两边都报的话一件东西出两条待办，得点两次。

        模板里写明了不许两边都报，但被认领的那几件在进背包之前就从 delta 里摘掉了，
        所以它们不在 working.inventory 里——光靠提示词管不住，这里得复核。
        """
        narration = "你从几份泛黄的医疗报告下面，摸出了一个黑色漆器木盒。"
        data = {"discoveries": {"items": [{"name": "黑色漆器木盒",
                                           "hint": "你从几份泛黄的医疗报告下面，摸出了一个黑色漆器木盒。"}]}}
        self.assertEqual(
            [entry["name"] for entry in
             filter_discoveries(data, narration, [], [], [], [], 7)],
            ["黑色漆器木盒"],
        )
        self.assertEqual(
            filter_discoveries(data, narration, [], [], [], [], 7,
                               claims=[{"name": "黑色漆器木盒", "qty": 1}]),
            [],
        )

    def test_the_item_reading_of_a_name_wins_over_the_skill_reading(self):
        """同一个名字既报成道具又报成技能时只留一行——DISCOVERY_KINDS 的顺序
        就是优先级，道具在技能前面。建错一行删掉就是了，建出两行才难收拾。"""
        got = filter_discoveries(
            {"discoveries": {
                "items": [{"name": SKILL, "hint": "老周把刀横过来教了你一式"}],
                "skills": [{"name": SKILL, "hint": "老周把刀横过来教了你一式"}],
            }},
            NARRATION, [], [], [], [], 7,
        )
        self.assertEqual([entry["kind"] for entry in got], ["item"])


if __name__ == "__main__":
    unittest.main()
