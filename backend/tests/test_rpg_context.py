"""RPG 上下文装配。

四条底线，破了任何一条这个模式就不成立：
creator_note 不能进 prompt；判定块必须贴在玩家那句话的最前面；
引擎算出的事实必须压过判定块；【你】段必须排在世界设定之前。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.rpg import (
    RpgMessage, RpgModule, RpgNpc, RpgSession, RpgWorldEntry,
)
from app.services.rpg_context import build_rpg_messages, onstage_npcs, triggered_entries

SENTINEL = "哨兵串勿入提示词XYZZY"


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            for model in (RpgModule, RpgWorldEntry, RpgNpc, RpgSession, RpgMessage):
                await connection.run_sync(model.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        self.module = RpgModule(
            user_id=1,
            name="锈湖地窖",
            genre="潮湿的悬疑",
            creator_note=SENTINEL,
            worldview="一座被水淹了一半的旧矿镇。",
            system_instruction="语气冷硬，少用形容词。",
            narration_sample="雨还在下。你数着台阶往下走。",
            stat_defs=[
                {"name": "敏捷", "initial": 14, "for_check": True},
                {"name": "精力", "initial": 80, "max": 100},
                {"name": "怀疑度", "initial": 30, "max": 100, "display": "隐藏"},
            ],
            relation_stat_defs=[{"name": "好感", "min": -100, "max": 100}],
        )
        self.db.add(self.module)
        await self.db.commit()

        self.sess = RpgSession(
            module_id=self.module.id,
            char_name="阿隼",
            char_desc="逃出矿场的挖工。",
            stats={"敏捷": 14, "精力": 80, "怀疑度": 30},
            inventory=[{"name": "火把", "qty": 1, "note": "还剩半截"}],
            location="地窖",
            flags={},
            npc_states={},
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _add(self, obj):
        self.db.add(obj)
        await self.db.commit()
        return obj

    async def _build(self, text, judgement=None, history=None, facts=None):
        return await build_rpg_messages(
            self.db, self.module, self.sess, history or [], text, judgement, facts
        )


def _roll(**kwargs):
    base = {
        "need_check": True, "attr": "敏捷", "band": "hard",
        "rate": 51, "dice": 62, "outcome": "narrow",
        "intent": "用铁丝撬开生锈的铁锁",
    }
    base.update(kwargs)
    return base


class SafetyTests(_Base):
    async def test_creator_note_never_reaches_the_model(self):
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="锁", content="矿镇的锁都是同一批货。"
        ))
        messages, _ = await self._build("我撬开那把锁", _roll())
        blob = "\n".join(m["content"] for m in messages)
        self.assertNotIn(SENTINEL, blob)


class OrderTests(_Base):
    async def test_you_block_comes_before_the_world_settings(self):
        await self._add(RpgWorldEntry(
            module_id=self.module.id, constant=True, content="地窖终年积水。"
        ))
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertLess(system.index("【你】"), system.index("【世界设定】"))
        # 世界观是静态背景，也该排在状态前面
        self.assertLess(system.index("【世界观】"), system.index("【你】"))

    async def test_genre_reaches_the_gm(self):
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("潮湿的悬疑", system)

    async def test_judgement_wraps_the_player_line_head_and_tail(self):
        messages, _ = await self._build("我撬开那把锁", _roll())
        last = messages[-1]["content"]
        self.assertTrue(last.startswith("【本回合判定"))
        self.assertIn("我撬开那把锁", last)
        head = last.split("我撬开那把锁")[0]
        self.assertIn("险胜", head)
        # 玩家看得懂成功率，看不懂「D20+2 对抗 16」
        self.assertIn("成功率 51%", head)
        self.assertTrue(last.rstrip().endswith("）"))
        self.assertIn("再次确认", last.split("我撬开那把锁")[1])

    async def test_judgement_outranks_a_depth_one_world_entry(self):
        # depth=1 的词条也落在玩家这条消息上。判定块必须压在它前面，
        # 否则模型先读到的是背景设定而不是「这次成没成」
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="锁", content="矿镇的锁都是同一批货。", depth=1
        ))
        messages, _ = await self._build("我撬开那把锁", _roll())
        last = messages[-1]["content"]
        self.assertLess(last.index("【本回合判定"), last.index("【世界设定】"))

    async def test_no_judgement_block_when_the_turn_needs_no_roll(self):
        for judgement in (None, _roll(need_check=False), {"intent": "打量四周"}):
            with self.subTest(judgement=judgement):
                messages, _ = await self._build("我打量四周", judgement)
                self.assertEqual(messages[-1]["content"], "我打量四周")


class FactsTests(_Base):
    """引擎算出的死数字必须排在判定块之前：它比概率更硬。"""

    async def test_engine_facts_lead_the_player_line(self):
        messages, _ = await self._build("我喝药水", facts=["你用掉了「药水」", "因此 精力+20"])
        last = messages[-1]["content"]
        self.assertTrue(last.startswith("【本回合已定事实"))
        self.assertIn("你用掉了「药水」", last)
        self.assertIn("我喝药水", last)

    async def test_facts_outrank_the_judgement_block(self):
        messages, _ = await self._build("我撬锁", _roll(), facts=["门本来就是开着的"])
        last = messages[-1]["content"]
        self.assertLess(last.index("【本回合已定事实"), last.index("【本回合判定"))

    async def test_no_block_without_facts(self):
        messages, _ = await self._build("我往前走", facts=[])
        self.assertEqual(messages[-1]["content"], "我往前走")


class GuidanceTests(_Base):
    async def test_a_price_is_demanded_only_when_the_roll_went_badly(self):
        messages, _ = await self._build("我撬锁", _roll(outcome="narrow"))
        self.assertIn("代价要具体", messages[-1]["content"])
        messages, _ = await self._build("我说服他", _roll(outcome="fail"))
        self.assertIn("代价要具体", messages[-1]["content"])

    async def test_clean_success_is_told_not_to_add_a_price(self):
        messages, _ = await self._build("我撬锁", _roll(outcome="success"))
        self.assertIn("不要额外加代价", messages[-1]["content"])
        self.assertNotIn("代价要具体", messages[-1]["content"])


class ScanTests(_Base):
    async def test_intent_widens_the_keyword_hit(self):
        # 玩家写「我撬门」，词条关键词是「锁」，直接匹配不上；
        # 裁决归一化出的 intent 能命中——这是那次调用顺手买到的检索召回
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="铁锁", content="矿镇的锁都是同一批货。"
        ))
        _, diag = await self._build("我撬门")
        self.assertEqual(diag["triggered"], [])
        messages, diag = await self._build("我撬门", _roll())
        self.assertEqual(len(diag["triggered"]), 1)
        self.assertEqual(diag["intent_used"], "用铁丝撬开生锈的铁锁")
        self.assertIn("同一批货", messages[0]["content"])

    async def test_constant_entries_ignore_keywords(self):
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="不会出现的词", constant=True, content="常驻。"
        ))
        _, diag = await self._build("随便说点什么")
        self.assertEqual(len(diag["triggered"]), 1)

    async def test_disabled_and_empty_entries_are_skipped(self):
        entries = [
            RpgWorldEntry(module_id=1, keywords="锁", content="关了的", enabled=False),
            RpgWorldEntry(module_id=1, keywords="锁", content="   ", enabled=True),
            RpgWorldEntry(module_id=1, keywords="锁、钥匙", content="留下的", enabled=True),
        ]
        hits = triggered_entries(entries, "我撬开那把锁")
        self.assertEqual([e.content for e in hits], ["留下的"])


class ThresholdTests(_Base):
    """世界书兼任事件系统：常驻 + 数值条件 = 跨过某条线就解锁新内容。"""

    async def test_a_constant_entry_waits_for_the_threshold(self):
        await self._add(RpgWorldEntry(
            module_id=self.module.id, constant=True, content="你累得站不稳了。",
            trigger_condition={"stats": {"精力": {"op": "<=", "value": 20}}},
        ))
        _, diag = await self._build("我往前走")
        self.assertEqual(diag["triggered"], [])

        self.sess.stats = {**self.sess.stats, "精力": 15}
        messages, diag = await self._build("我往前走")
        self.assertEqual(len(diag["triggered"]), 1)
        self.assertIn("你累得站不稳了。", messages[0]["content"])

    async def test_a_relation_threshold_reads_that_npcs_own_numbers(self):
        npc = await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        await self._add(RpgWorldEntry(
            module_id=self.module.id, constant=True, content="他开始把你当自己人。",
            trigger_condition={
                "relations": [{"npc": "老兵", "stat": "好感", "op": ">=", "value": 50}]
            },
        ))
        _, diag = await self._build("我打个招呼")
        self.assertEqual(diag["triggered"], [])

        self.sess.npc_states = {str(npc.id): {"好感": 62}}
        _, diag = await self._build("我打个招呼")
        self.assertEqual(len(diag["triggered"]), 1)

    async def test_a_keyword_entry_still_needs_its_keyword(self):
        # 条件是附加约束，不是替代关键词
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="钥匙", content="钥匙上刻着编号。",
            trigger_condition={"stats": {"精力": {"op": ">=", "value": 10}}},
        ))
        _, diag = await self._build("我往前走")
        self.assertEqual(diag["triggered"], [])
        _, diag = await self._build("我摸出那把钥匙")
        self.assertEqual(len(diag["triggered"]), 1)


class NpcTests(_Base):
    async def test_npc_in_the_same_place_is_onstage(self):
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖", persona="警惕，话少。"
        ))
        messages, diag = await self._build("我打个招呼")
        self.assertEqual([n["name"] for n in diag["npcs_onstage"]], ["老兵"])
        self.assertIn("警惕，话少。", messages[0]["content"])

    async def test_npc_elsewhere_is_pulled_in_when_mentioned(self):
        # 人不在这儿但这一轮聊到了他。没有这条，玩家问「老兵说过什么」时
        # 模型手上没有老兵的任何设定，只能现编
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="酒馆", persona="警惕，话少。"
        ))
        _, diag = await self._build("我想起老兵说的话")
        self.assertEqual([n["name"] for n in diag["npcs_onstage"]], ["老兵"])
        _, diag = await self._build("我往前走")
        self.assertEqual(diag["npcs_onstage"], [])

    async def test_appearance_is_spent_only_on_the_first_meeting(self):
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            persona="警惕，话少。", appearance="左眼一道旧疤。",
        ))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("左眼一道旧疤。", system)

        self.sess.npc_states = {str(npc.id): {"met": True, "好感": 1}}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertNotIn("左眼一道旧疤。", system)
        # 关系数值有上限就写成 1/100，模型得看到分母才知道这算高还是低
        self.assertIn("好感 1/100", system)

    async def test_card_fields_reach_the_model(self):
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            description="矿场最后一个活着出来的人。",
            profile_sections={"背景故事": "他在塌方那天失去了整支班组。"},
            dialogue_examples=[{"user": "你还好吗", "assistant": "别问。"}],
        ))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("矿场最后一个活着出来的人。", system)
        self.assertIn("背景故事：他在塌方那天失去了整支班组。", system)
        self.assertIn("别问。", system)

    def test_keyword_match_is_case_insensitive(self):
        npc = RpgNpc(module_id=1, name="Rook", location="", keywords="秃鹫")
        self.assertEqual(onstage_npcs([npc], "", "那只秃鹫又来了"), [npc])
        self.assertEqual(onstage_npcs([npc], "", "ROOK 在等你"), [npc])


class StateBlockTests(_Base):
    async def test_state_block_carries_what_the_player_watches(self):
        self.sess.flags = {"地窖门已开": True, "火把还亮着": None}
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("敏捷 14", system)
        self.assertIn("精力 80/100", system)
        # 隐藏项玩家看不见，但 GM 得知道怀疑度已经多少了
        self.assertIn("怀疑度 30/100", system)
        self.assertIn("所在：地窖", system)
        self.assertIn("火把×1（还剩半截）", system)
        self.assertIn("地窖门已开：是", system)
        # 值为 null 的 flag 表示「这条不再成立」，不该出现在上下文里
        self.assertNotIn("火把还亮着", system)

    async def test_a_bloated_backpack_is_trimmed_before_anything_else(self):
        self.sess.inventory = [
            {"name": f"杂物{i}", "qty": i, "note": "在背包底下压着的一件旧东西" * 6}
            for i in range(1, 60)
        ]
        messages, diag = await self._build("我翻背包")
        system = messages[0]["content"]
        # 数值必须活下来：截断的刀只能落在背包上
        self.assertIn("敏捷 14", system)
        self.assertIn("精力 80/100", system)
        self.assertIn("件杂物", system)
        self.assertLessEqual(diag["state_tokens"], 800)
        # 按数量降序保留，数量最多的那件一定在
        self.assertIn("杂物59", system)


class HistoryTests(_Base):
    async def test_summarized_messages_are_not_sent_again(self):
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="第一句"),
            RpgMessage(id=2, session_id=self.sess.id, role="assistant", content="第二句"),
            RpgMessage(id=3, session_id=self.sess.id, role="user", content="第三句"),
        ]
        self.sess.summarized_upto_id = 2
        self.sess.summary = "阿隼进了地窖。"
        messages, diag = await self._build("第四句", history=history)
        self.assertEqual(diag["history_count"], 1)
        self.assertEqual([m["content"] for m in messages[1:]], ["第三句", "第四句"])
        self.assertIn("【此前剧情】", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
