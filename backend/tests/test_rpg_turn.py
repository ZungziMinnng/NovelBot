"""RPG 编排里能脱离 LLM 之外单独测的那部分：「帮我想想」。

整轮 run_turn 要打桩流式接口、引擎落库和结算三处，成本高收益低，
这里只钉住 suggest_actions：窗口怎么切、prompt 里有什么、模型输出怎么洗、
标签怎么对上白名单、出错怎么办。
"""
import unittest
from unittest.mock import patch

from app.agents import rpg_turn
from app.models.rpg import (
    RpgAction, RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession,
    RpgSkill,
)
from app.services.rpg_context import (
    SUGGEST_PLACES_BUDGET, SUGGEST_TAG_GUIDE, SUGGEST_TOKEN_BUDGET,
)
from app.services.rpg_suggestions import SuggestSources

SENTINEL = "哨兵串勿入提示词XYZZY"


def _module(**over):
    base = dict(id=1, user_id=1, name="锈湖地窖", creator_note=SENTINEL, context_turns=20)
    base.update(over)
    return RpgModule(**base)


def _session(**over):
    base = dict(
        id=1, module_id=1, char_name="阿隼", location="地窖", summary="", summarized_upto_id=0
    )
    base.update(over)
    return RpgSession(**base)


def _history(*pairs):
    """(role, content) 变 RpgMessage，id 从 1 递增。"""
    return [
        RpgMessage(id=i, session_id=1, role=role, content=content)
        for i, (role, content) in enumerate(pairs, start=1)
    ]


def _item(name, usable=True):
    return RpgItem(id=1, module_id=1, name=name, usable=usable)


def _skill(name, usable=True):
    return RpgSkill(id=1, module_id=1, name=name, usable=usable)


def _place(name, enter_requires=None, description="", connections=None):
    return RpgLocation(
        id=1, module_id=1, name=name, description=description,
        enter_requires=enter_requires or {}, connections=connections or [],
    )


def _action(id_, name, needs_target=False, target_anywhere=False, at_location="",
            requires=None):
    return RpgAction(
        id=id_, module_id=1, name=name, prompt_hint="",
        requires=requires or {}, needs_target=needs_target,
        target_anywhere=target_anywhere, at_location=at_location,
    )


def _needs_trust(who="柳如烟", value=50):
    """「对某人的好感 ≥ N」——带对象的动作最典型的一条前置。"""
    return {"relations": [{"npc": who, "stat": "好感", "op": ">=", "value": value}]}


def _npc(id_, name, role="npc"):
    return RpgNpc(id=id_, module_id=1, name=name, role=role)


def _sources(**over):
    base = dict(npcs=[], items=[], skills=[], locations=[], actions=[])
    base.update(over)
    return SuggestSources(**base)


class _Base(unittest.IsolatedAsyncioTestCase):
    async def _suggest(
        self, reply="", history=None, module=None, sess=None, sources=None,
        here_ids=None,
    ):
        """跑一次 suggest_actions，把发给模型的 messages 和调用次数捞出来。"""
        captured = {"calls": 0}

        async def fake_dispatch(messages, **kwargs):
            captured["calls"] += 1
            captured["prompt"] = messages[0]["content"]
            captured["kwargs"] = kwargs
            return reply

        with patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")), \
             patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake_dispatch):
            # here_ids=None：这一组钉的是窗口怎么切和 prompt 里有什么，
            # 在场筛选由 test_rpg_summary.py 的 WindowTests 单独钉
            result, diag = await rpg_turn.suggest_actions(
                module or _module(), sess or _session(), history or [],
                here_ids, sources or _sources(),
            )
        captured["diag"] = diag
        return result, captured


class SuggestTests(_Base):
    async def test_the_prompt_carries_the_player_and_never_the_creator_note(self):
        _, captured = await self._suggest(
            "看看四周",
            history=_history(("user", "我推开门"), ("assistant", "门后是黑的。")),
        )
        self.assertIn("阿隼", captured["prompt"])
        self.assertIn("地窖", captured["prompt"])
        self.assertIn("我推开门", captured["prompt"])
        self.assertIn("GM：门后是黑的。", captured["prompt"])
        # creator_note 是只给作者看的备注，任何提示词里都不能出现。
        # 断言的是**整条 prompt**（现在含追加的资料段），所以这条同时管着
        # suggest_blocks 那六个块别把 creator_note 抄进去
        self.assertNotIn(SENTINEL, captured["prompt"])

    async def test_the_model_is_asked_for_six_short_lines(self):
        _, captured = await self._suggest(
            "看看四周", history=_history(("user", "我推开门")),
        )
        # 六行（三条能做的 + 三句台词）得给够位置，所以是 900 不是 600。
        # 温度也钉住：低了几条会是同一件事的几种说法，那就白搭了
        self.assertEqual(captured["kwargs"]["temperature"], 0.95)
        self.assertEqual(captured["kwargs"]["max_tokens"], 900)

    async def test_numbering_quotes_and_bullets_are_stripped(self):
        result, _ = await self._suggest(
            "1. 撬开那把铁锁\n- 「问老兵」\n• 往东边走走\n4. 多出来的第四条",
            history=_history(("user", "我推开门")),
        )
        self.assertEqual([s["text"] for s in result], ["撬开那把铁锁", "问老兵", "往东边走走"])

    async def test_a_number_without_a_separator_survives(self):
        # 编号必须带 . 、 ) ） 之一才剥，否则「3天后再回来」会被吃掉开头的数字
        result, _ = await self._suggest(
            "3天后再回来看看", history=_history(("user", "我推开门")),
        )
        self.assertEqual([s["text"] for s in result], ["3天后再回来看看"])

    async def test_blank_lines_do_not_become_suggestions(self):
        result, _ = await self._suggest(
            "推门进去\n\n  \n问老兵\n", history=_history(("user", "我推开门")),
        )
        self.assertEqual([s["text"] for s in result], ["推门进去", "问老兵"])

    async def test_an_empty_session_does_not_call_the_model(self):
        # 刚开局、还没有任何消息时按灯泡，不该为「什么都不知道」付一次调用
        result, captured = await self._suggest("推门进去", history=[])
        self.assertEqual(result, [])
        self.assertEqual(captured["calls"], 0)

    async def test_summarized_messages_are_not_sent_again(self):
        history = _history(
            ("user", "很久以前的一句"), ("assistant", "很久以前的回答"), ("user", "刚说的一句"),
        )
        _, captured = await self._suggest(
            "推门进去", history=history, sess=_session(summarized_upto_id=2),
        )
        self.assertNotIn("很久以前的一句", captured["prompt"])
        self.assertIn("刚说的一句", captured["prompt"])

    async def test_only_the_recent_tail_is_sent(self):
        history = _history(*[("user", f"第{i}句") for i in range(1, 13)])
        _, captured = await self._suggest("推门进去", history=history)
        self.assertNotIn("第1句", captured["prompt"])
        self.assertIn("第12句", captured["prompt"])

    async def test_a_misconfigured_model_reaches_the_route(self):
        # 路由靠这个 ValueError 转成 400。吞掉它的话，模型配错时前端
        # 只会看到「没想出来」，找不到真正的毛病
        with patch.object(rpg_turn.llm_client, "get_agent_client", side_effect=ValueError("模型不存在")):
            with self.assertRaises(ValueError):
                await rpg_turn.suggest_actions(
                    _module(), _session(), _history(("user", "我推开门")), None, _sources(),
                )


class TaggedLineTests(_Base):
    """标签 → 结构化。名字对不上就整条降级，正文一个字不丢。"""

    async def test_a_tagged_skill_becomes_structured(self):
        result, _ = await self._suggest(
            "[技|暗影步] 绕到他背后",
            history=_history(("user", "我推开门")),
            sess=_session(skills=[{"name": "暗影步", "cooldown_left": 0}]),
            sources=_sources(skills=[_skill("暗影步")]),
        )
        self.assertEqual(result, [{
            "text": "绕到他背后", "kind": "skill", "name": "暗影步", "action_id": None,
        }])

    async def test_a_tagged_item_becomes_structured(self):
        result, _ = await self._suggest(
            "[物|止血草] 先把血止住",
            history=_history(("user", "我推开门")),
            sess=_session(inventory=[{"name": "止血草", "qty": 2}]),
            sources=_sources(items=[_item("止血草")]),
        )
        self.assertEqual(result[0]["kind"], "item")
        self.assertEqual(result[0]["name"], "止血草")

    async def test_a_skill_on_cooldown_degrades_to_free(self):
        """冷却中的招点了会弹黄条，所以降级；正文照样留着。"""
        result, _ = await self._suggest(
            "[技|暗影步] 再用一次",
            history=_history(("user", "我推开门")),
            sess=_session(skills=[{"name": "暗影步", "cooldown_left": 2}]),
            sources=_sources(skills=[_skill("暗影步")]),
        )
        self.assertEqual(result[0], {
            "text": "再用一次", "kind": "free", "name": "", "action_id": None,
        })

    async def test_a_skill_missing_from_the_module_degrades_to_free(self):
        """剧情里学到的名字，模组表里没有 —— 点了必然「不是能主动施展的本事」。"""
        result, _ = await self._suggest(
            "[技|野路子] 试试",
            history=_history(("user", "我推开门")),
            sess=_session(skills=[{"name": "野路子", "cooldown_left": 0}]),
            sources=_sources(skills=[_skill("暗影步")]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_an_item_at_zero_quantity_degrades_to_free(self):
        result, _ = await self._suggest(
            "[物|止血草] 敷上",
            history=_history(("user", "我推开门")),
            sess=_session(inventory=[{"name": "止血草", "qty": 0}]),
            sources=_sources(items=[_item("止血草")]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_an_item_missing_from_the_module_degrades_to_free(self):
        result, _ = await self._suggest(
            "[物|神秘钥匙] 开门",
            history=_history(("user", "我推开门")),
            sess=_session(inventory=[{"name": "神秘钥匙", "qty": 1}]),
            sources=_sources(items=[_item("止血草")]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_moving_to_the_current_place_degrades_to_free(self):
        # 建议了当前地点，move_by_name 只会说「你已经在 X 了」，还白记一条大事记
        result, _ = await self._suggest(
            "[去|地窖] 回地窖去",
            history=_history(("user", "我推开门")),
            sess=_session(location="地窖"),
            sources=_sources(locations=[_place("地窖")]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_a_place_whose_condition_fails_degrades_to_free(self):
        result, _ = await self._suggest(
            "[去|后山] 上后山",
            history=_history(("user", "我推开门")),
            sess=_session(location="地窖", stats={"精力": 10}),
            sources=_sources(locations=[
                _place("后山", {"stats": {"精力": {"op": ">=", "value": 100}}}),
            ]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_a_reachable_place_becomes_structured(self):
        result, _ = await self._suggest(
            "[去|后山] 上后山看看",
            history=_history(("user", "我推开门")),
            sess=_session(location="地窖", stats={"精力": 90}),
            sources=_sources(locations=[
                _place("后山", {"stats": {"精力": {"op": ">=", "value": 50}}}),
            ]),
        )
        self.assertEqual(result[0], {
            "text": "上后山看看", "kind": "move", "name": "后山", "action_id": None,
        })

    async def test_a_tagged_action_carries_its_id(self):
        result, _ = await self._suggest(
            "[行|夸她] 夸她一句",
            history=_history(("user", "我推开门")),
            sources=_sources(actions=[_action(7, "夸她")]),
        )
        self.assertEqual(result[0], {
            "text": "夸她一句", "kind": "action", "name": "", "action_id": 7,
        })

    async def test_an_action_blocked_by_place_degrades_to_free(self):
        """_action_gate 是唯一的判据，地点限定它管，这里只信它。"""
        result, _ = await self._suggest(
            "[行|打坐] 就地打坐",
            history=_history(("user", "我推开门")),
            sess=_session(location="地窖"),
            sources=_sources(actions=[_action(9, "打坐", at_location="禅房")]),
        )
        self.assertEqual(result[0]["kind"], "free")

    async def test_an_action_that_no_longer_exists_degrades_to_free(self):
        """建议是模块改动之前生成的，动作可能已经被作者删了。"""
        result, _ = await self._suggest(
            "[行|已经删掉的动作] 试试",
            history=_history(("user", "我推开门")),
        )
        self.assertEqual(result[0]["kind"], "free")
        self.assertIsNone(result[0]["action_id"])

    async def test_a_json_blob_from_an_old_override_degrades_to_one_free_line(self):
        """覆写成 JSON 输出的老模板会和「三行加标签」的指令打架。

        退化是安全的（整段 JSON 被当成一行 → 一条自由文本），但不理想。
        这条测试是**行为记录**，别为了它去写双格式解析器：那比它脆得多
        """
        result, _ = await self._suggest(
            '{"suggestions": ["推门", "问老兵"]}',
            history=_history(("user", "我推开门")),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "free")


class UsableActionTests(_Base):
    """哪些作者定义的动作进得了建议。判据只有 _action_gate 一份，这里改量化方式。"""

    async def test_a_targeted_action_with_a_valid_target_is_listed(self):
        result, captured = await self._suggest(
            "[行|夸她] 夸她一句",
            history=_history(("user", "我推开门")),
            sess=_session(npc_states={"5": {"好感": 70}}),
            sources=_sources(
                npcs=[_npc(5, "柳如烟")],
                actions=[_action(7, "夸她", needs_target=True, requires=_needs_trust())],
            ),
            here_ids={5},
        )
        self.assertEqual(result[0]["kind"], "action")
        self.assertIn("【能用上的按钮】", captured["prompt"])

    async def test_a_targeted_action_with_nobody_qualifying_is_dropped(self):
        """在场的人一个都不达标 → 这个按钮此刻是死的，不许进建议。"""
        result, captured = await self._suggest(
            "[行|夸她] 夸她一句",
            history=_history(("user", "我推开门")),
            sess=_session(npc_states={"5": {"好感": 10}}),
            sources=_sources(
                npcs=[_npc(5, "柳如烟")],
                actions=[_action(7, "夸她", needs_target=True, requires=_needs_trust())],
            ),
            here_ids={5},
        )
        self.assertEqual(result[0]["kind"], "free")
        self.assertNotIn("【能用上的按钮】", captured["prompt"])

    async def test_a_remote_action_is_listed_even_with_nobody_here(self):
        """手机/传讯那类动作的意义就是人不在跟前也能发。"""
        result, _ = await self._suggest(
            "[行|发消息] 发个消息过去",
            history=_history(("user", "我推开门")),
            sess=_session(npc_states={"5": {"好感": 70}}),
            sources=_sources(
                npcs=[_npc(5, "柳如烟")],
                actions=[_action(
                    7, "发消息", needs_target=True, target_anywhere=True,
                    requires=_needs_trust(),
                )],
            ),
            here_ids=set(),
        )
        self.assertEqual(result[0]["kind"], "action")


class AppendedBlockTests(_Base):
    """追加段：块进没进 prompt、超没超预算、标签指令在不在最后。"""

    async def test_the_state_cast_and_places_blocks_reach_the_prompt(self):
        _, captured = await self._suggest(
            "推门进去",
            history=_history(("user", "我推开门")),
            sess=_session(
                location="地窖", stats={"精力": 42}, inventory=[{"name": "止血草", "qty": 1}],
                npc_states={"5": {"好感": 70}},
            ),
            sources=_sources(
                npcs=[_npc(5, "柳如烟", role="npc")],
                locations=[_place("后山", description="荒草没膝")],
            ),
            here_ids={5},
        )
        prompt = captured["prompt"]
        self.assertIn("【你】", prompt)
        self.assertIn("精力", prompt)
        self.assertIn("【在场】", prompt)
        self.assertIn("柳如烟", prompt)
        self.assertIn("【地方】", prompt)
        self.assertIn("后山", prompt)

    async def test_the_tag_guide_is_the_last_thing_in_the_prompt(self):
        # 资料段排在模板那句「只输出 3 行」之后，靠结尾这段指令扳回来。
        # 位置一挪，模型的注意力就跟着挪
        _, captured = await self._suggest(
            "推门进去", history=_history(("user", "我推开门")),
        )
        self.assertTrue(captured["prompt"].endswith(SUGGEST_TAG_GUIDE))

    async def test_the_blocks_stay_within_their_budget(self):
        """两百个地点也不许把追加段撑爆——预算常量就是干这个的。"""
        _, captured = await self._suggest(
            "推门进去",
            history=_history(("user", "我推开门")),
            sess=_session(location="地窖"),
            sources=_sources(locations=[
                _place(f"地点{i}", description="很长的描述" * 20) for i in range(200)
            ]),
        )
        diag = captured["diag"]
        self.assertLessEqual(diag["total"], SUGGEST_TOKEN_BUDGET)
        # 只留报告的两行，不是把两百行塞进去再靠总截断兜底
        self.assertLessEqual(diag["places"], SUGGEST_PLACES_BUDGET)

    async def test_a_huge_place_table_is_cut_line_by_line(self):
        block = rpg_turn.suggest_blocks(
            _module(), _session(location="地窖"),
            _sources(locations=[
                _place(f"地点{i}", description="很长的描述" * 20) for i in range(200)
            ]),
            [], "推门进去",
        )[0]
        self.assertIn("【地方】", block)
        self.assertNotIn("地点199", block)
        self.assertIn("【地方】\n现在在：地窖", block)

    async def test_the_diag_counts_what_the_model_structured(self):
        _, captured = await self._suggest(
            "[技|暗影步] 绕过去\n随口说一句\n再想想",
            history=_history(("user", "我推开门")),
            sess=_session(skills=[{"name": "暗影步", "cooldown_left": 0}]),
            sources=_sources(skills=[_skill("暗影步")]),
        )
        self.assertEqual(captured["diag"]["count"], 3)
        self.assertEqual(captured["diag"]["structured"], 1)
        self.assertIn("prompt_tokens", captured["diag"])


if __name__ == "__main__":
    unittest.main()
