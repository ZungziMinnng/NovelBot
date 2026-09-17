"""RPG 上下文装配。

四条底线，破了任何一条这个模式就不成立：
creator_note 不能进 prompt；判定块必须贴在玩家那句话的最前面；
引擎算出的事实必须压过判定块；【你】段必须排在世界设定之前。
"""
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.rpg import (
    RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSession, RpgSkill,
    RpgWorldEntry,
)
from app.services.rpg_context import (
    build_rpg_messages, here_npcs, onstage_npcs, triggered_entries,
)
from app.services.rpg_state import EFFECT_CHARS

SENTINEL = "哨兵串勿入提示词XYZZY"


class _Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            # 道具表和技能表是【道具与技能】那一块要查的，即使这些用例一条都不建，
            # 表也得在——build_rpg_messages 每轮都会整表取一次
            for model in (
                RpgModule, RpgWorldEntry, RpgNpc, RpgSession, RpgMessage, RpgLocation,
                RpgItem, RpgSkill,
            ):
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
            npc_notes={},
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

    async def _build(
        self, text, judgement=None, history=None, facts=None,
        mode="group", private_with=None,
    ):
        """history 就是全部历史。原先这里还要传 thread_id 和 scene_history
        （这一轮归哪条线、把场面线借给角色线），线拆掉之后两个概念都没了。"""
        return await build_rpg_messages(
            self.db, self.module, self.sess, history or [], text, judgement, facts,
            mode, private_with,
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

    async def test_a_private_aside_narrows_all_three_places_at_once(self):
        """把一个人叫到一边：在场名单、人设卡、记忆归属**一起**收窄。

        只收窄记忆那一处的话，模型看见屋里还站着 Bob 就会让他插话，而那句话
        按私聊记进 Alice 名下——Bob 说过的话 Bob 自己不记得。
        """
        alice = await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", description="ALICE_CARD",
            persona="ALICE_PERSONA", location="地窖",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="Bob", description="BOB_CARD",
            persona="BOB_PERSONA", location="地窖",
        ))
        messages, diag = await self._build(
            "Alice，借一步说话", mode="private", private_with=alice.id,
        )
        system = messages[0]["content"]
        self.assertIn("ALICE_CARD", system)
        self.assertNotIn("BOB_CARD", system)
        self.assertNotIn("Bob", system)
        self.assertIn("叫到一边", system)
        self.assertEqual(diag["private_with"], alice.id)
        self.assertEqual([n["name"] for n in diag["npcs_here"]], ["Alice"])

    async def test_a_group_turn_gives_everyone_in_the_room_their_card(self):
        # 群聊时同屋的每个人都要拿到自己的设定，否则模型只能现编他的性格。
        # 这里原先按「玩家在面包屑上点了谁」筛，和历史按在场筛是两套口径
        await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", description="ALICE_CARD",
            location="地窖",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="Bob", description="BOB_CARD",
            location="地窖",
        ))
        system = (await self._build("你们都听着"))[0][0]["content"]
        self.assertIn("ALICE_CARD", system)
        self.assertIn("BOB_CARD", system)
        self.assertIn("这是群戏", system)

    async def test_acting_alone_does_not_hide_you_from_the_room(self):
        """「独自行动」不等于「没人看见」。

        她眼睁睁看着你从箱底翻出剑谱。判成没人在场的话，下一轮她不知道你有
        剑谱——那是失忆 bug 的镜像版，一样难查。
        """
        alice = await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", description="ALICE_CARD",
            location="地窖",
        ))
        messages, diag = await self._build("我翻箱底", mode="solo")
        system = messages[0]["content"]
        self.assertIn("在旁边看着", system)
        self.assertIn("没有在跟谁说话", system)
        # 在场名单一个人都没少：这段记忆照样记给她
        self.assertEqual([n["id"] for n in diag["npcs_here"]], [alice.id])


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
        # relation_enabled 默认是 False（关系数值默认关），不打开的话
        # check_condition 一律判「没有追踪关系数值」，这条阈值永远不成立
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            relation_enabled=True, relation_stat_names=["好感"],
        ))
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
    async def test_current_place_roster_survives_location_whitespace(self):
        await self._add(RpgNpc(
            module_id=self.module.id, name="园丁甲", location="灵药园　",
            persona="负责照料灵药。",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="园丁乙", location="灵药园",
            persona="正在清点药材。",
        ))
        self.sess.location = " 灵药园 "
        messages, diag = await self._build("我走进这里")
        self.assertEqual([n["name"] for n in diag["npcs_here"]], ["园丁甲", "园丁乙"])
        system = messages[0]["content"]
        self.assertIn("地点角色名册", system)
        self.assertIn("园丁甲(ID:", system)
        self.assertIn("园丁乙(ID:", system)

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

    async def test_the_gm_is_told_what_the_npc_is_carrying_right_now(self):
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖", persona="警惕，话少。"
        ))
        self.sess.npc_notes = {str(npc.id): {"伤势": "左肩中刀", "身上带着": "一把猎枪"}}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("伤势 左肩中刀", system)
        self.assertIn("身上带着 一把猎枪", system)

    async def test_an_npc_without_notes_gets_no_extra_line(self):
        await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertNotIn("眼下：", system)

    async def test_the_notes_line_does_not_reuse_the_label_from_the_you_block(self):
        # _compose_state 已经用「此刻：」表示「你正在和谁单独说话」。两块隔着
        # 几百字，同一个词两个意思，模型分不清
        npc = await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        self.sess.npc_notes = {str(npc.id): {"伤势": "左肩中刀"}}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertEqual(system.count("此刻："), 1)

    async def test_every_npc_keeps_his_name_when_the_block_overflows(self):
        # 截断是从尾部切的，切掉的是整整一个人——而 mark_met 不看他的文字有没有
        # 活下来，于是那个人的外貌从此再也不会注入。所以要先砍示例和档案段
        for i in range(3):
            await self._add(RpgNpc(
                module_id=self.module.id, name=f"矿工{i}", location="地窖",
                description="塌方那天活下来的人。" * 20,
                profile_sections={"背景故事": "他在矿上待了二十年。" * 20},
                dialogue_examples=[{"user": "你还好吗", "assistant": "别问了。" * 20}],
            ))
        self.sess.npc_notes = {}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        for i in range(3):
            self.assertIn(f"矿工{i}", system)

    def test_keyword_match_is_case_insensitive(self):
        npc = RpgNpc(module_id=1, name="Rook", location="", keywords="秃鹫")
        self.assertEqual(onstage_npcs([npc], "", "那只秃鹫又来了"), [npc])
        self.assertEqual(onstage_npcs([npc], "", "ROOK 在等你"), [npc])

    def test_here_npcs_needs_a_matching_place(self):
        here = RpgNpc(module_id=1, name="老兵", location="地窖")
        away = RpgNpc(module_id=1, name="老板娘", location="酒馆")
        nowhere = RpgNpc(module_id=1, name="路人", location="")
        self.assertEqual(here_npcs([here, away, nowhere], "地窖"), [here])
        # 玩家还没落脚时谁都不算在跟前
        self.assertEqual(here_npcs([here, away], ""), [])

    async def test_being_mentioned_is_not_being_here(self):
        # 「这一轮拿到设定」和「在跟前」是两件事：前者把资料递给模型，
        # 后者才决定算不算见过面。混成一个，被提到一句的人的外貌就永远
        # 等不到该出现的那一次
        await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        await self._add(RpgNpc(module_id=self.module.id, name="老板娘", location="酒馆"))

        _, diag = await self._build("老板娘刚才说了什么")
        self.assertEqual(
            [n["name"] for n in diag["npcs_onstage"]], ["老兵", "老板娘"]
        )
        self.assertEqual([n["name"] for n in diag["npcs_here"]], ["老兵"])

    async def test_protagonist_template_is_never_treated_as_an_npc(self):
        # 主角模板是开局时预填玩家自己的那张卡。前端一直不把它当 NPC
        # （condition.ts 的 knownNpcs），后端也不能把它塞进【在场】——
        # 塞进去模型就会把它当另一个角色来演
        await self._add(RpgNpc(
            module_id=self.module.id, name="阿隼", role="protagonist",
            location="地窖", persona="逃出矿场的挖工。", appearance="个子很高。",
        ))
        await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))

        # 名字就写在玩家这句话里，地点也和玩家相同，两条路都堵死
        messages, diag = await self._build("阿隼这个名字我记着")
        self.assertEqual([n["name"] for n in diag["npcs_onstage"]], ["老兵"])
        self.assertEqual([n["name"] for n in diag["npcs_here"]], ["老兵"])
        self.assertNotIn("个子很高。", "\n".join(m["content"] for m in messages))


class MeaningTests(_Base):
    """数值的「影响」。

    作者写的说明和分档是给模型看的：只给 62 它不知道这是高还是低、该用什么
    态度说话。守两条：存量模组一个字都不多出来；说明整轮只发一遍。
    """

    async def test_a_module_without_effects_says_nothing_extra(self):
        # 存量模组的回归线。这几个定义一个 effect、一个 tiers 都没有
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertNotIn("【数值的含义】", system)

    async def test_the_effect_and_the_bands_reach_the_model(self):
        self.module.stat_defs = [
            {"name": "精力", "initial": 80, "max": 100, "effect": "熬夜和打架都掉它",
             "tiers": [{"at": 0, "label": "脱力", "note": "手在抖"}, {"at": 41, "label": "尚可"}]},
        ]
        self.sess.stats = {"精力": 45}
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("【数值的含义】", system)
        self.assertIn("精力：熬夜和打架都掉它", system)
        self.assertIn("0 起 脱力=手在抖", system)

    async def test_the_current_band_rides_along_with_the_number(self):
        self.module.stat_defs = [
            {"name": "精力", "initial": 45, "max": 100,
             "tiers": [{"at": 0, "label": "脱力"}, {"at": 61, "label": "充沛"}]},
        ]
        self.sess.stats = {"精力": 45}
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("精力 45/100（脱力）", system)

    async def test_the_band_note_stays_out_of_the_number_line(self):
        # 关系定义是全体 NPC 共用的一份。把解释跟在数字后面就等于同一句话
        # 按在场人数重复，而【在场】那块只有 800 字上下的预算
        self.module.relation_stat_defs = [
            {"name": "好感", "min": -100, "max": 100,
             "tiers": [{"at": 61, "label": "亲近", "note": "会主动替你出头"}]},
        ]
        await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        self.sess.npc_states = {"1": {"好感": 62}}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("好感 62/100（亲近）", system)
        self.assertNotIn("好感 62/100（亲近，会主动替你出头）", system)

    async def test_the_effect_is_stated_once_no_matter_how_many_npcs_are_here(self):
        # 这条锁的是那个设计决定：共用定义只在【数值的含义】里说一遍
        self.module.relation_stat_defs = [
            {"name": "好感", "min": -100, "max": 100, "effect": "决定她愿不愿意帮你"},
        ]
        for i in range(3):
            await self._add(RpgNpc(module_id=self.module.id, name=f"矿工{i}", location="地窖"))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertEqual(system.count("决定她愿不愿意帮你"), 1)

    async def test_a_hidden_stat_explains_itself_too(self):
        # 同 _compose_state 的既定理由：隐藏只是不给玩家看，GM 得知道
        # 怀疑度到 80 了会发生什么
        self.module.stat_defs = [
            {"name": "怀疑度", "initial": 30, "max": 100, "display": "隐藏",
             "effect": "到 80 就有人来敲门"},
        ]
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("怀疑度：到 80 就有人来敲门", system)

    async def test_the_meaning_block_sits_before_the_numbers_it_explains(self):
        # 被尾部截断切掉的话，模型看到的就又是一串没有意思的数字
        self.module.stat_defs = [
            {"name": "精力", "initial": 80, "max": 100, "effect": "熬夜和打架都掉它"},
        ]
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertLess(system.index("【数值的含义】"), system.index("【你】"))

    async def test_an_over_long_effect_is_trimmed_rather_than_dropped(self):
        # 作者可以从别处粘一大段进来。截断而不是整条丢掉，否则这个数值
        # 在提示词里就彻底没有解释了
        self.module.stat_defs = [
            {"name": "精力", "initial": 80, "max": 100, "effect": "懒" * 200},
        ]
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("精力：" + "懒" * EFFECT_CHARS, system)
        self.assertNotIn("懒" * (EFFECT_CHARS + 1), system)

    async def test_a_def_with_only_a_label_and_no_effect_still_shows_up(self):
        self.module.relation_stat_defs = [
            {"name": "好感", "min": -100, "max": 100, "tiers": [{"at": 0, "label": "冷淡"}]},
        ]
        system = (await self._build("我看看四周"))[0][0]["content"]
        self.assertIn("0 起 冷淡", system)


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

    async def test_the_clock_reaches_the_model(self):
        # 模型看不见时间就会自己编「不知不觉天黑了」，而这局可能还停在早上
        self.sess.slot = "晚"
        self.sess.day = 3
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("时间：第 3 天 · 晚", system)

    async def test_a_module_without_a_clock_says_nothing_about_time(self):
        # 一句「时间：第 1 天 · 」比不写更糟——模型会拿这个半截值去编
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertNotIn("时间：", system)

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


class SceneTests(_Base):
    """【场面】：眼前这一幕**在消息里没有**的那些信息。

    历史统一成一条之后，这一块不再是「把场面线的原文借给别的线」——模型本来
    就看得见全部消息，开场白和你刚做的事都在同一条时间线上。它只补两样：地点
    长什么样、谁站在这里（§31）。

    它是**读时拼的**：只进 system，一个字都不落进任何消息。
    """

    async def _here(self, name="赫敏"):
        return await self._add(RpgNpc(module_id=self.module.id, name=name, location="地窖"))

    async def test_it_carries_the_place_and_who_is_here(self):
        await self._add(RpgLocation(
            module_id=self.module.id, name="地窖", description="一半泡在水里的旧矿井。",
        ))
        await self._here()
        messages, diag = await self._build("我往前走")
        system = messages[0]["content"]
        self.assertIn("【场面】", system)
        # 地点描述作者写好了却从来没进过上下文，这一块就是为它开的
        self.assertIn("地点：地窖", system)
        self.assertIn("一半泡在水里的旧矿井。", system)
        self.assertIn("在场：赫敏", system)
        self.assertGreater(diag["scene_tokens"], 0)

    async def test_what_the_player_did_to_the_room_shows_up_under_the_description(self):
        # 地点描述是作者写死的原样，被玩家改过的部分只在这一句里。它单独一行：
        # 混进描述里模型就分不清哪句是设定、哪句是这一局才成立的
        await self._add(RpgLocation(
            module_id=self.module.id, name="地窖", description="一半泡在水里的旧矿井。",
        ))
        self.sess.place_notes = {"地窖": "门被你踹坏了，合不上"}
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("一半泡在水里的旧矿井。", system)
        self.assertIn("现在：门被你踹坏了，合不上", system)

    async def test_another_places_note_stays_where_it_belongs(self):
        # 一个地方一格。串了的话你站在地窖，模型却在写酒馆掀翻的桌子
        await self._add(RpgLocation(module_id=self.module.id, name="地窖"))
        self.sess.place_notes = {"酒馆": "桌子掀了一地"}
        self.assertNotIn("桌子掀了一地", (await self._build("我往前走"))[0][0]["content"])

    async def test_an_empty_room_says_so(self):
        # 「没有别人」和「没提」对模型是两回事：不写的话它会照着上下文里的
        # 角色自己安排一个站到跟前
        await self._add(RpgLocation(module_id=self.module.id, name="地窖"))
        messages, _ = await self._build("我往前走")
        self.assertIn("在场：只有你一个人", messages[0]["content"])

    async def test_a_module_without_a_place_gets_no_block(self):
        # 纯对话模组一个地点都没建：位置是空的，这块整个不拼，不要留个空壳
        self.sess.location = ""
        messages, diag = await self._build("我往前走")
        self.assertNotIn("【场面】", messages[0]["content"])
        self.assertEqual(diag["scene_tokens"], 0)

    async def test_the_block_sits_right_after_the_chronicle(self):
        self.sess.chronicle = ["〔开场〕你睁开眼，地窖里只有一盏摇晃的灯。"]
        messages, _ = await self._build("我往前走")
        system = messages[0]["content"]
        self.assertIn("【外场】", system)
        self.assertLess(system.index("【外场】"), system.index("【场面】"))

    async def test_the_place_description_is_never_scanned_for_keywords(self):
        # 地点描述不许参与关键词扫描：写地窖的模组每进一次地窖就命中那条词条，
        # 而模型自己写的旁白又会让它下一轮再命中，自己喂自己
        await self._add(RpgLocation(
            module_id=self.module.id, name="地窖", description="墙上挂着一盏摇晃的灯。",
        ))
        await self._add(RpgWorldEntry(
            module_id=self.module.id,
            content="那盏灯是个暗号。", keywords="摇晃的灯",
        ))
        messages, _ = await self._build("我往前走")
        self.assertIn("墙上挂着一盏摇晃的灯。", messages[0]["content"])
        self.assertNotIn("那盏灯是个暗号。", messages[0]["content"])

    async def test_it_is_assembled_at_read_time(self):
        # 一条消息都不许多出来，否则「读时拼」就变成了写进历史
        await self._add(RpgLocation(
            module_id=self.module.id, name="地窖", description="一半泡在水里的旧矿井。",
        ))
        plain, _ = await self._build("我往前走")
        messages, _ = await self._build("我往前走", history=[
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="我盯着老兵的靴子看"),
        ])
        self.assertEqual(len(messages), len(plain) + 1)
        blob = "\n".join(m["content"] for m in messages[1:])
        self.assertNotIn("一半泡在水里的旧矿井。", blob)

    async def test_the_block_cannot_starve_the_rest(self):
        # 这一块排在 system 中段，而整体截断是从尾部切的。它再大也不能把玩家
        # 自己和作者写的东西挤掉——那一挤，玩家会以为是新加的块把记忆弄没了
        from app.services.rpg_context import SCENE_TOKEN_BUDGET

        await self._add(RpgLocation(
            module_id=self.module.id, name="地窖", description="又下了一夜的雨。" * 200,
        ))
        self.sess.summary = "场面上的往事。" * 20
        self.module.narration_sample = "雨还在下。" * 40
        messages, diag = await self._build("我往前走")
        system = messages[0]["content"]
        # 额度：这一块的预算就是它自己的上限（末尾那个省略号也算字，留一点余量）
        self.assertLessEqual(diag["scene_tokens"], SCENE_TOKEN_BUDGET + 5)
        self.assertIn("【你】", system)
        self.assertIn("场面上的往事。", system)


class HistoryTests(_Base):
    async def test_current_scene_anchor_overrides_stale_location_in_history(self):
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="assistant", content="你刚从柴房出来。"),
        ]
        self.sess.location = "太玄白玉广场"
        messages, _ = await self._build("打听消息", history=history)
        system = messages[0]["content"]
        self.assertTrue(system.endswith("当前没有登记在场角色。"))
        self.assertIn("【本轮当前场景 · 硬事实】", system)
        self.assertIn("太玄白玉广场", system)
        self.assertIn("历史消息中的地点属于过去", system)

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

    async def test_the_window_keeps_your_own_past_and_heres_too(self):
        """端到端钉住那两个失忆 bug，一路从 build_rpg_messages 走。

        ① 筛历史的依据是**在场名单**，不是玩家在面包屑上点了谁。原先没点人时
           走「只留群戏」那一支，于是跟她一对一聊十轮之后随口再说一句，模型
           眼前只剩开场白。错在**调用方选错了分支**，所以必须走整条路，单测
           history_window 拦不住。
        ② 判据改成「此刻谁在跟前」之后，一场 1v1 的戏会被地点切换整个甩掉
           （只记在对方名下，一走动那一格就整个不进）。所以玩家格现在装**全部**
           消息：你亲身经历过的，不管此刻谁站在跟前，都在窗口里。

        在场的人那一格是**额外**把她自己的更早记忆也捞进来；她们之间照旧隔开。
        """
        veteran = await self._add(RpgNpc(module_id=self.module.id, name="老兵", location="地窖"))
        keeper = await self._add(RpgNpc(module_id=self.module.id, name="老板娘", location="酒馆"))
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="开场白", present=None),
            RpgMessage(id=2, session_id=self.sess.id, role="user", content="一个人翻箱子", present=[]),
            RpgMessage(
                id=3, session_id=self.sess.id, role="user", content="只跟老兵说的",
                present=[veteran.id],
            ),
            RpgMessage(
                id=4, session_id=self.sess.id, role="user", content="只跟老板娘说的",
                present=[keeper.id],
            ),
        ]
        # 玩家在地窖，站在跟前的只有老兵。没有 focus_npc_id——这正是默认态
        messages, _ = await self._build("接着说", history=history)
        sent = [m["content"] for m in messages[1:]]
        # 你自己经历过的全在（含背着老兵跟老板娘说的那句——你自己做的事，
        # 你和叙述你的 GM 都得看得见），刚说的那句在最后
        self.assertEqual(
            sent,
            ["开场白", "一个人翻箱子", "只跟老兵说的", "只跟老板娘说的", "接着说"],
        )


if __name__ == "__main__":
    unittest.main()
