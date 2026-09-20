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
    build_rpg_messages, here_npcs, onstage_npcs, ref_roster, triggered_entries,
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
            npc_appearance={},
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
        mode="group", private_with=None, action_time=None,
    ):
        """history 就是全部历史。原先这里还要传 thread_id 和 scene_history
        （这一轮归哪条线、把场面线借给角色线），线拆掉之后两个概念都没了。"""
        return await build_rpg_messages(
            self.db, self.module, self.sess, history or [], text, judgement, facts,
            mode, private_with, action_time=action_time,
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

    async def test_appearance_stays_on_the_card_after_the_first_meeting(self):
        # 原先按 met 只在首次见面时给。代价是见过面之后人去了别处、又被提到时
        # 模型手上没有长相，只能现编；而截断把整张卡切掉时 met 照样会被标记，
        # 那个人的长相就永远不会再出现。长相是认出一个人的最低要求，不拿去换 token
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            persona="警惕，话少。", appearance="左眼一道旧疤。",
        ))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("左眼一道旧疤。", system)

        self.sess.npc_states = {str(npc.id): {"met": True, "好感": 1}}
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("左眼一道旧疤。", system)
        # 关系数值有上限就写成 1/100，模型得看到分母才知道这算高还是低
        self.assertIn("好感 1/100", system)

    async def test_a_rewritten_appearance_lands_right_after_the_authors_own_text(self):
        # 作者那段写着「身量单薄」，药剂改造之后模型还照着它写——因为它看起来
        # 像设定、而「眼下：」那行看起来像细节，二选一时模型挑设定。
        # 所以覆盖必须**紧贴**原文之后，并明说以它为准
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="温眠", location="地窖",
            appearance="身量单薄，胸口平坦。",
        ))
        system = (await self._build("我看看她"))[0][0]["content"]
        self.assertIn("身量单薄，胸口平坦。", system)
        self.assertNotIn("外貌已被改写", system)

        self.sess.npc_appearance = {str(npc.id): {"胸部": "服丰元玉乳散后长出"}}
        system = (await self._build("我看看她"))[0][0]["content"]
        self.assertIn("外貌已被改写", system)
        self.assertIn("胸部 服丰元玉乳散后长出", system)
        # 顺序是这块的全部意义：原文在前、推翻它的那句在后
        self.assertLess(system.index("身量单薄，胸口平坦。"), system.index("外貌已被改写"))

    async def test_the_rewrite_is_not_folded_into_the_plain_notes_line(self):
        # 「眼下」那行是这一局补记的近况，外貌改写是**推翻作者设定**。
        # 混在一起的话，「伤势 左肩中刀」和「胸部 已定形」看起来一样要紧，
        # 而模型需要一个明确的信号才知道哪一条压过上面那段长相
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="温眠", location="地窖", appearance="胸口平坦。",
        ))
        self.sess.npc_notes = {str(npc.id): {"伤势": "左肩中刀"}}
        self.sess.npc_appearance = {str(npc.id): {"胸部": "已定形"}}
        system = (await self._build("我看看她"))[0][0]["content"]
        self.assertIn("眼下：伤势 左肩中刀", system)
        self.assertIn("外貌已被改写（以此为准，作者的设定已被推翻）：胸部 已定形", system)

    async def test_a_mentioned_npc_brings_his_own_share_of_history(self):
        # 你知道跟一个女人的关系数值，却不知道你俩之间发生过什么，模型就只能
        # 现编一段「上次她……」。被提到的人因此也要有他自己那一格
        away = await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆",
        ))
        self.sess.summary = "你在地窖里待了很久。"
        self.sess.thread_summaries = {str(away.id): "她在柜台后面给你留了半壶酒。"}
        system = (await self._build("老板娘最近怎么样"))[0][0]["content"]
        self.assertIn("（与老板娘）", system)
        self.assertIn("她在柜台后面给你留了半壶酒。", system)

    async def test_a_mentioned_npc_does_not_shrink_the_people_in_the_room(self):
        # aside 那几份不参与均分：提到一个旧相好，不该把你自己那格和正在跟你
        # 说话那个人那格的额度一起稀释掉。这里那 400 字在均分下会被截（4 份
        # 各 500 token），只有不参与均分才活得下来
        here = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
        ))
        full = "他" * 400
        self.sess.summary = "你在地窖里待了很久。"
        self.sess.thread_summaries = {str(here.id): full}
        for name in ("老板娘", "矿头", "阿七"):
            away = await self._add(RpgNpc(
                module_id=self.module.id, name=name, location="酒馆",
            ))
            self.sess.thread_summaries[str(away.id)] = "旧事一桩。" * 60
        system = (await self._build("老兵、老板娘、矿头、阿七"))[0][0]["content"]
        self.assertIn(full, system)

    async def test_an_offstage_npc_still_gets_his_name_listed(self):
        """不在场、这一轮也没被提到的人，名字和一句简介仍然要给模型。

        没有这条，模型写到他时只有称谓可用（「太玄天宗宗主」），而称谓和真名
        一个字都不重叠——结算的去重名单认不出这是已登记的人，他会被当成
        新角色报上来。**一行只有名字和简介，完整设定还是归【在场】那一块**。
        """
        await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆",
            description="酒馆的老板，镇上没有她不知道的事。",
            persona="TAVERN_PERSONA",
        ))
        system = (await self._build("我回想那天的事"))[0][0]["content"]
        self.assertIn("老板娘", system)
        self.assertIn("常在酒馆", system)
        self.assertIn("酒馆的老板，镇上没有她不知道的事。", system)
        self.assertNotIn("TAVERN_PERSONA", system)

    async def test_every_name_survives_when_the_roster_overflows(self):
        # 简介先砍、名字最后留。掉一个名字，那个人就回到了「模型只能拿称谓
        # 称呼他」的老样子——而这正是这一块存在的理由，所以名字是底线
        for i in range(40):
            await self._add(RpgNpc(
                module_id=self.module.id, name=f"长老{i}", location="后山",
                description="在后山闭关多年的长老。" * 12,
            ))
        system = (await self._build("我回想那天的事"))[0][0]["content"]
        for i in range(40):
            self.assertIn(f"长老{i}", system)

    async def test_the_roster_stays_out_of_a_private_aside(self):
        # 私聊那一刻的规矩是「屋里只有你们俩」，连第三个人的名字都不该露脸
        alice = await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", location="地窖",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆",
        ))
        system = (await self._build(
            "Alice，借一步说话", mode="private", private_with=alice.id,
        ))[0][0]["content"]
        self.assertNotIn("老板娘", system)

    async def test_a_private_aside_still_hands_over_anyone_you_name(self):
        # 私聊收窄的只是「按地点算的在场」——屋里只该有你们俩。但你在私聊里
        # **主动提到**的人照样给卡，否则模型只有称谓可用、只能现编他。
        # 而同地点、这一轮又没被提到的第三人仍然不发，封闭感就是这么保住的
        alice = await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", location="地窖",
            persona="ALICE_PERSONA",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆",
            persona="TAVERN_PERSONA",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="同屋的", location="地窖",
            persona="ROOMMATE_PERSONA",
        ))
        system = (await self._build(
            "Alice，我姐老板娘刚才找过我", mode="private", private_with=alice.id,
        ))[0][0]["content"]
        self.assertIn("TAVERN_PERSONA", system)
        self.assertNotIn("ROOMMATE_PERSONA", system)

    async def test_a_ref_pulls_a_card_the_text_never_names(self):
        # 「回想自己的身世」字面上一个名字都没有，触发词也命中不了——光靠字面
        # 匹配，模型手上只有世界观那两句，只能现编。裁决看着角色名单知道这句话
        # 说的是生母，把名字报在 refs 里，这一轮就得把她的整张卡发出去
        await self._add(RpgNpc(
            module_id=self.module.id, name="澹台红绡", location="紫霄阁",
            profile_sections={"背景故事": "她把儿子丢在孤儿院门口。"},
        ))
        plain = (await self._build("回想自己的身世"))[0][0]["content"]
        self.assertNotIn("她把儿子丢在孤儿院门口。", plain)
        rolled = (await self._build(
            "回想自己的身世", _roll(refs=["澹台红绡"]),
        ))[0][0]["content"]
        self.assertIn("她把儿子丢在孤儿院门口。", rolled)

    async def test_a_half_name_in_the_refs_finds_the_full_card(self):
        # 玩家嘴里很少叫全名。onstage_npcs 那边是全名子串匹配，「红绡」两个字
        # 匹配不上「澹台红绡」——收敛这一步得把半个名字还原过来
        await self._add(RpgNpc(
            module_id=self.module.id, name="澹台红绡", location="紫霄阁",
            persona="TAITAI_PERSONA",
        ))
        messages, diag = await self._build("问问我娘的旧事", _roll(refs=["红绡"]))
        self.assertIn("TAITAI_PERSONA", messages[0]["content"])
        self.assertEqual(diag["refs_used"], ["澹台红绡"])

    async def test_a_ref_the_module_never_registered_is_dropped(self):
        # 白名单。模型多报一个名字，那一轮就凭空多出一张卡，更糟的是那个编出来
        # 的名字会被叙事模型当成真人写进正文
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖", persona="LAO_PERSONA",
        ))
        _, diag = await self._build("我问他", _roll(refs=["查无此人"]))
        self.assertEqual(diag["refs_used"], [])

    async def test_the_adjudicators_roster_keeps_the_same_discipline(self):
        # 裁决看的那份名单和【角色总表】认同一套规矩：一行一个，主角模板不算
        lao = await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", description="矿场最后一个活着出来的人。",
        ))
        player = await self._add(RpgNpc(
            module_id=self.module.id, name="杂役弟子", role="protagonist",
        ))
        roster = ref_roster([lao, player])
        self.assertIn("- 老兵：矿场最后一个活着出来的人。", roster)
        self.assertNotIn("杂役弟子", roster)

    async def test_the_protagonist_card_is_not_on_the_roster(self):
        # 主角模板是开局预填玩家自己的那张卡，不登场（同 world_npcs 的口径）
        await self._add(RpgNpc(
            module_id=self.module.id, name="杂役弟子", role="protagonist",
        ))
        system = (await self._build("我回想那天的事"))[0][0]["content"]
        self.assertNotIn("杂役弟子", system)

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

    async def test_an_english_keyed_card_still_reaches_the_model_in_chinese(self):
        # 键就是拼进提示词的标签。向导早期版本存的是英文键（照酒馆那套写的），
        # 归一放在读的这一头，所以老模组在这里也得是中文标签
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            profile_sections={
                "background": "他在塌方那天失去了整支班组。",
                "abilities": "会看矿脉。",
            },
        ))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertIn("背景故事：他在塌方那天失去了整支班组。", system)
        self.assertIn("能力特长：会看矿脉。", system)
        self.assertNotIn("background：", system)

    async def test_a_face_is_described_once(self):
        # 外貌有自己的字段。向导两处都填的时候，分栏那份原先会被当成一格
        # 「外貌身材」再发一遍——同一张脸在卡上出现两次，措辞还不一样
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            appearance="左脸一道疤。",
            profile_sections={"appearance": "左脸一道疤，缺了半只耳朵。"},
        ))
        system = (await self._build("我打个招呼"))[0][0]["content"]
        self.assertEqual(system.count("左脸一道疤"), 1)
        self.assertNotIn("外貌身材", system)

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
        # 名字是底线：掉一个名字，那个人就回到了「模型只能拿称谓称呼他」的
        # 老样子，而称谓骗得过结算的去重名单。这一批其实装得下，真正把降级链
        # 逼出来的是下面那条 test_an_overflow_never_touches_the_person_in_the_room
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

    async def test_an_overflow_never_touches_the_person_in_the_room(self):
        # 原先那版是**连坐**：超预算先把全体的说话示例砍掉、再砍全体的四栏档案，
        # 正在跟你说话的那个人一起挨刀。现在从队尾（最不相关的那个）逐个降级，
        # 站在跟前的人档案和示例一份都不该少
        await self._add(RpgNpc(
            module_id=self.module.id, name="老兵", location="地窖",
            description="HERE_DESC",
            profile_sections={"背景故事": "HERE_PROFILE"},
            dialogue_examples=[{"user": "你还好吗", "assistant": "HERE_EXAMPLE"}],
        ))
        for name in ("矿工甲", "矿工乙", "矿工丙"):
            await self._add(RpgNpc(
                module_id=self.module.id, name=name, location="后山",
                description="塌方那天活下来的人。" * 400,
                profile_sections={f"背景故事_{name}": "旧事" * 400},
            ))
        system = (await self._build("矿工甲、矿工乙、矿工丙说过什么"))[0][0]["content"]
        self.assertIn("HERE_PROFILE", system)
        self.assertIn("HERE_EXAMPLE", system)
        # 被牺牲的是队尾：排在最后那个人的档案整个丢光了，
        # 而站在跟前的人一句没少——这就是「弃车保帅」和「连坐」的差别
        self.assertNotIn("背景故事_矿工丙", system)

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

    def test_the_appearance_overrides_are_snapshotted(self):
        # 同 npc_notes / place_notes：漏进 SNAPSHOT_FIELDS 不会报错，只会在读档
        # 之后留下一个不还原的字段——读档回到服药之前，她的卡上还写着「已长出」
        from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS
        self.assertIn("npc_appearance", SNAPSHOT_FIELDS)
        self.assertEqual(SNAPSHOT_DEFAULTS["npc_appearance"], {})


class KeywordContextTests(_Base):
    async def test_keyword_recalls_the_characters_uncompressed_history(self):
        self.module.context_turns = 1
        self.module.scan_depth = 1
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆",
            keywords="掌柜、红袖；Innkeeper", persona="她认得每位旧客。",
        ))
        self.sess.thread_summaries = {str(npc.id): "她曾替你保管行李。"}
        history = [
            RpgMessage(id=1, role="user", content="把铜钥匙交给你。", present=[npc.id]),
            RpgMessage(id=2, role="assistant", content="她将钥匙藏进柜底。", present=[npc.id]),
            RpgMessage(id=3, role="user", content="我走到山路。", present=[]),
            RpgMessage(id=4, role="assistant", content="山路上落着雨。", present=[]),
        ]
        messages, diag = await self._build("看看山路", history=history)
        self.assertEqual([message["content"] for message in messages[1:-1]],
                         [message.content for message in history[-2:]])
        self.assertEqual(diag["npcs_onstage"], [])
        for keyword in ("掌柜", "红袖", "INNKEEPER"):
            with self.subTest(keyword=keyword):
                messages, diag = await self._build(f"回想{keyword}的事", history=history)
                self.assertIn("她认得每位旧客。", messages[0]["content"])
                self.assertIn("她曾替你保管行李。", messages[0]["content"])
                self.assertEqual([message["content"] for message in messages[1:-1]],
                                 [message.content for message in history])
                self.assertEqual(diag["npcs_here"], [])
                self.assertEqual(diag["history_count"], 4)

        self.sess.summarized_upto_id = 4
        self.sess.thread_upto = {str(npc.id): 1}
        messages, diag = await self._build("想起掌柜", history=history)
        self.assertEqual([message["content"] for message in messages[1:-1]],
                         [history[1].content])
        self.assertIn("她曾替你保管行李。", messages[0]["content"])
        self.assertEqual(diag["history_count"], 1)
        self.assertEqual([message.present for message in history],
                         [[npc.id], [npc.id], [], []])

    async def test_recalled_history_does_not_trigger_more_characters_or_entries(self):
        self.module.context_turns = 1
        self.module.scan_depth = 1
        npc = await self._add(RpgNpc(
            module_id=self.module.id, name="老板娘", location="酒馆", keywords="掌柜",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="铁匠", location="铁铺",
            keywords="铁锤", persona="UNRELATED_PERSONA",
        ))
        await self._add(RpgWorldEntry(
            module_id=self.module.id, keywords="铁锤", content="UNRELATED_ENTRY",
        ))
        history = [
            RpgMessage(id=1, role="assistant", content="她收下了铁锤。", present=[npc.id]),
            RpgMessage(id=2, role="user", content="我走到山路。", present=[]),
            RpgMessage(id=3, role="assistant", content="山路上落着雨。", present=[]),
        ]
        messages, diag = await self._build("想起掌柜", history=history)
        self.assertIn("她收下了铁锤。", [message["content"] for message in messages])
        self.assertNotIn("UNRELATED_PERSONA", messages[0]["content"])
        self.assertNotIn("UNRELATED_ENTRY", messages[0]["content"])
        self.assertEqual([npc["name"] for npc in diag["npcs_onstage"]], ["老板娘"])

    async def test_private_keyword_recalls_a_local_third_person_without_adding_a_speaker(self):
        alice = await self._add(RpgNpc(
            module_id=self.module.id, name="Alice", location="地窖", persona="ALICE_PERSONA",
        ))
        bob = await self._add(RpgNpc(
            module_id=self.module.id, name="Bob", location="地窖",
            keywords="守门人", persona="BOB_PERSONA",
        ))
        await self._add(RpgNpc(
            module_id=self.module.id, name="Carol", location="地窖", persona="CAROL_PERSONA",
        ))
        self.sess.thread_summaries = {str(bob.id): "他借过你一把伞。"}
        messages, diag = await self._build(
            "Alice，守门人之前说过什么", mode="private", private_with=alice.id,
        )
        self.assertIn("BOB_PERSONA", messages[0]["content"])
        self.assertIn("他借过你一把伞。", messages[0]["content"])
        self.assertNotIn("CAROL_PERSONA", messages[0]["content"])
        self.assertEqual([npc["name"] for npc in diag["npcs_here"]], ["Alice"])
        roster = next(line for line in messages[0]["content"].splitlines()
                      if line.startswith("地点角色名册："))
        self.assertIn("Alice", roster)
        self.assertNotIn("Bob", roster)


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
        # 跟着常量走，免得以后调额度还要回头改这个数
        from app.services.rpg_context import STATE_TOKEN_BUDGET

        self.assertLessEqual(diag["state_tokens"], STATE_TOKEN_BUDGET)
        # 按数量降序保留，数量最多的那件一定在
        self.assertIn("杂物59", system)

    async def test_the_player_sheet_is_marked_as_his_own(self):
        # 背包/技能/手上的事本来就该给 GM，但 GM 同时在写所有 NPC 的台词。
        # 没有这句话，路人就会张口问「你送信送到哪了」
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("是他自己的底细", system)

    async def test_the_private_note_leaves_the_door_open(self):
        # 锁的是那三个口子。规矩一旦被收紧成「NPC 一律不知道」，就会把镜像那个
        # 老 bug 放回来——她亲眼看着你翻出剑谱，下一轮却不知道你有
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("亲眼", system)
        self.assertIn("说过", system)
        self.assertIn("交代", system)

    async def test_the_gm_is_told_not_to_leak_the_sheet(self):
        # 和上面那句是一对：那句贴在底细旁边，这条写在规矩清单里，模型落笔写
        # 台词时回头看的是这一节。哪一头掉了都会漏
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("不要让 NPC 张口就知道", system)

    async def test_waiting_confirmations_are_named_so_the_gm_does_not_replay_them(self):
        # 报上来还没被点头的那些每轮都还挂在侧栏上。不说的话 GM 会把同一件事
        # 当新的再报一遍（发现按名字去重，于是永远进不来），或者替玩家把道具
        # 认下来、把差事收了线——那两件事只能玩家点头
        self.sess.item_claims = [{"name": "铁钥匙", "qty": 1}]
        self.sess.discoveries = [{"kind": "npc", "name": "老周"}, {"kind": "place", "name": "地窖"}]
        self.sess.task_proposals = [{"name": "去后巷见老周"}]
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertIn("待确认", system)
        self.assertIn("铁钥匙", system)
        self.assertIn("人物 老周", system)
        self.assertIn("地点 地窖", system)
        self.assertIn("去后巷见老周", system)

    async def test_nothing_is_said_when_nothing_is_waiting(self):
        # 绝大多数轮次这三样都是空的，那就一个字都不该多出来
        system = (await self._build("我往前走"))[0][0]["content"]
        self.assertNotIn("待确认", system)


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
    async def test_action_elapsed_time_is_narrated_before_the_ending_clock(self):
        self.sess.time_jump_from = "第 1 天 · 早"
        self.sess.slot = "午"
        messages, _ = await self._build(
            "工作", facts=["行动效果：精力-10（80 → 70）"],
            action_time=("第 1 天 · 早", "第 1 天 · 午"),
        )
        last = messages[-1]["content"]
        self.assertIn("本轮行动从「第 1 天 · 早」开始，到「第 1 天 · 午」结束", last)
        self.assertIn("执行过程和已结算的结果", last)
        self.assertNotIn("中间这段空白没人描写过", last)
        self.assertIn("本轮行动结束时间", messages[0]["content"])
        self.assertNotIn("玩家本轮开始时位于", messages[0]["content"])

    async def test_manual_gap_is_distinct_from_the_following_action(self):
        self.sess.time_jump_from = "第 1 天 · 早"
        self.sess.slot = "晚"
        messages, _ = await self._build("工作", action_time=("第 1 天 · 午", "第 1 天 · 晚"))
        last = messages[-1]["content"]
        self.assertIn("此前已从「第 1 天 · 早」跳到「第 1 天 · 午」", last)
        self.assertIn("本轮行动从「第 1 天 · 午」开始，到「第 1 天 · 晚」结束", last)

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
        self.assertIn("本轮最终地点由系统确定为「太玄白玉广场」", system)
        self.assertIn("不要继续替玩家进入另一处地点", system)
        self.assertIn("在场角色与玩家处于同一地点", system)

    async def test_a_time_jump_tells_the_model_the_gap_was_never_narrated(self):
        # 推时段是纯引擎、不调模型，中间那一段天然没有叙事。不写这一句，模型只
        # 看到那个新时段名，会把它当成紧接着的下一幕，接着上一轮的场景往下写
        self.sess.time_jump_from = "第 1 天 · 早"
        self.sess.slot = "午"
        messages, _ = await self._build("我推门进去")
        last = messages[-1]["content"]
        self.assertIn("上一幕结束于「第 1 天 · 早」", last)
        self.assertIn("现在是「第 1 天 · 午」", last)
        self.assertIn("中间这段空白没人描写过", last)

    async def test_the_time_jump_rides_on_the_players_line_not_the_system(self):
        # 埋在 system 末尾压不过对话流里上一幕那整段正文——那正是模型
        # 照着旧时刻往下写的原因。必须贴在玩家那句话前面
        self.sess.time_jump_from = "第 1 天 · 早"
        self.sess.slot = "午"
        messages, _ = await self._build("我推门进去")
        self.assertNotIn("【时间已推进", messages[0]["content"])

    async def test_no_pending_jump_says_nothing_about_time(self):
        # 没推过时段就一个字都不说，和加这一列之前逐字一致
        self.assertFalse(self.sess.time_jump_from)
        messages, _ = await self._build("我推门进去")
        self.assertNotIn("【时间已推进", "\n".join(m["content"] for m in messages))

    async def test_a_teleport_tells_the_model_the_last_scene_is_over(self):
        # 地点总览的瞬移是纯引擎、不产生任何消息，这次离开在历史里一个字都不留。
        # 不写这一句，模型只看到上一幕那整段正文，接着它的场面往下演
        self.sess.scene_break_from = "柴房"
        messages, _ = await self._build("我推门进去")
        last = messages[-1]["content"]
        self.assertIn("上一幕发生在「柴房」", last)
        self.assertIn("现在在「地窖」", last)
        self.assertIn("那一幕已经结束", last)

    async def test_leaving_and_coming_back_says_you_returned(self):
        # 走开又回到同一个地方：地点没变，但那一幕照样断了。说成「现在在地窖」
        # 会读着像没动过，正是要避免的那个意思
        self.sess.scene_break_from = "地窖"
        messages, _ = await self._build("我推门进去")
        self.assertIn("你离开过那里，现在又回到了这里", messages[-1]["content"])

    async def test_the_scene_break_rides_on_the_players_line_not_the_system(self):
        # 同时间跳跃：埋在 system 末尾压不过对话流里上一幕那整段正文
        self.sess.scene_break_from = "柴房"
        messages, _ = await self._build("我推门进去")
        self.assertNotIn("【场景已切换", messages[0]["content"])

    async def test_no_pending_break_says_nothing_about_the_scene(self):
        # 没瞬移过就一个字都不说，和加这一列之前逐字一致
        self.assertFalse(self.sess.scene_break_from)
        messages, _ = await self._build("我推门进去")
        self.assertNotIn("【场景已切换", "\n".join(m["content"] for m in messages))

    async def test_a_window_spanning_places_is_divided_at_the_switch(self):
        # 没有这道分隔，三天前在铁匠铺说的话会被读成眼前这场对话
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="第一句", location="铁匠铺"),
            RpgMessage(id=2, session_id=self.sess.id, role="assistant", content="第二句", location="铁匠铺"),
            RpgMessage(id=3, session_id=self.sess.id, role="user", content="第三句", location="地窖"),
        ]
        messages, _ = await self._build("第四句", history=history)
        self.assertEqual([m["content"] for m in messages[1:]], [
            "（以下发生在「铁匠铺」）\n第一句", "第二句",
            "（以下发生在「地窖」）\n第三句", "第四句",
        ])

    async def test_a_single_place_window_is_left_alone(self):
        # 绝大多数老局和一直待在一个地方的玩家：prompt 一个字不变
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="第一句", location="地窖"),
            RpgMessage(id=2, session_id=self.sess.id, role="assistant", content="第二句", location="地窖"),
        ]
        messages, _ = await self._build("第三句", history=history)
        self.assertEqual([m["content"] for m in messages[1:]], ["第一句", "第二句", "第三句"])

    async def test_messages_without_a_place_never_trigger_a_divider(self):
        # 空 = 「不知道」（迁移过来的老消息），当成「换到了无名地点」会在老存档里
        # 凭空刷一串分隔；而它夹在两条同地点的消息之间时也不该误报第二次切换
        history = [
            RpgMessage(id=1, session_id=self.sess.id, role="user", content="第一句", location="铁匠铺"),
            RpgMessage(id=2, session_id=self.sess.id, role="assistant", content="第二句", location=""),
            RpgMessage(id=3, session_id=self.sess.id, role="user", content="第三句", location="铁匠铺"),
            RpgMessage(id=4, session_id=self.sess.id, role="assistant", content="第四句", location="地窖"),
        ]
        messages, _ = await self._build("第五句", history=history)
        self.assertEqual([m["content"] for m in messages[1:]], [
            "（以下发生在「铁匠铺」）\n第一句", "第二句", "第三句",
            "（以下发生在「地窖」）\n第四句", "第五句",
        ])

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
