"""NPC 跟随 / 带人走 / 派人去：这三件事原先一件都做不到。

原先玩家想让 NPC 换个地方只有一条路：点一个勾了「召见」的动作按钮。除此之外
全靠结算模型自己想起来写一条 npc_places——写不写是概率。于是三件小说里天天
发生的事在游戏里都做不到：

1. 「我带她一起去后山」——玩家自己会走过去，她却留在原地。更糟的是这句话被
   引擎的否定表判成「不是玩家在动身」，连玩家自己的移动都不生效。
2. 「你去客栈等我」——没有任何入口，只能指望 AI。
3. 「一直跟着你」——npc_places 推一个时段就整张清空，连表达都表达不出来。

这一批给「她在哪儿」的取值链加了一层：本局剧情（npc_places）→ 跟随名单
（解析成玩家此刻的位置）→ 作息表 → 常驻地。和作息表、常驻地不同，跟随名单
是**玩家**说的话——打了一句「带她一起走」，或者点了侧栏那个叉——所以它跨
时段存活，和 npc_states / npc_notes 一族同寿。

和它相对的是 npc_places：那是一格剧情里模型随手写的一笔，推一个时段就整张
清空，作息表重新说了算。这两条寿命不一样是有意的，SlotResetTests 把它写死。

三件事全部走**打字识别**，不加动作字段：引擎只在无歧义时出手，认不出整句
交回 AI。猜错的代价是把人凭空挪走，比不认贵得多——这条纪律贯穿整份识别，
同 movement_target 那条 len(hits) == 1。

结算模型一个字都不许碰 npc_followers。它不是 STATE_FIELDS 里的一项，也不在
任何 DOMAIN 里，所以模型输出里就算写了这个键也没有落地的分支——否则模型就能
给人永久加/减同伴，而那正是 npc_places 那条「随手一笔永久生效」的镜像错误，
只是代价更贵。
"""
import unittest
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import database
from app.agents.rpg_turn import GROUP_MODE, PRIVATE_MODE, parse_company
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg, sensitive_word, text_replace_backup, llm_usage  # noqa: F401
from app.models.rpg import RpgLocation, RpgModule, RpgNpc, RpgSession
from app.services.rpg_context import here_npcs, npc_place, present_ids, turn_present
from app.services.rpg_settlement import DOMAINS, STATE_FIELDS
from app.services.rpg_state import advance_slot, apply_npc_followers


def _npc(npc_id=3, name="赫敏", location="宿舍", **kwargs):
    return RpgNpc(id=npc_id, module_id=1, name=name, location=location, **kwargs)


def _sess(**kwargs):
    base = {
        "location": "校长办公室", "slot": "晚", "day": 1,
        "npc_places": {}, "npc_followers": [],
        "npc_notes": {}, "npc_states": {},
        "stats": {}, "inventory": [], "flags": {}, "chronicle": [],
    }
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


def _places(*names):
    return [RpgLocation(name=n) for n in names]


# ── A. 取值链 ─────────────────────────────────────────────────────────────


class FollowChainTests(unittest.TestCase):
    """取值链。优先级：剧情 → 跟随 → 作息表 → 常驻地。

    它同时是后端和前端（condition.npcPlace）的口径——两边一起改，否则会出现
    「面板上站在你面前、提示词里没这个人」。
    """

    def test_no_followers_lets_the_schedule_speak(self):
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(npc_place(npc, "晚", {}, [], "校长办公室"), "宿舍")

    def test_followers_override_the_schedule(self):
        # 她跟着你走：解析出来就是你此刻站的地方。**这里没有任何同步写入**——
        # 玩家一走动她就在那儿了，不可能和 sess.location 分叉
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(npc_place(npc, "晚", {}, [3], "校长办公室"), "校长办公室")

    def test_the_scene_still_beats_the_followers(self):
        # 「你在这儿等我」那种：剧情把她单独挪到别处，跟随让位给剧情
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(
            npc_place(npc, "晚", {"3": "后山"}, [3], "校长办公室"), "后山"
        )

    def test_clearing_the_followers_falls_back_to_the_schedule(self):
        # 「别跟着了」走的就是这条路：名单清空，作息表重新替她算。
        # **必须真的过一遍 apply_npc_followers**——直接手写一个空名单进去，
        # 断言的就只是「空名单不生效」（上面那条已经断过了），解除那一步
        # 到底有没有把人从名单里摘掉根本没测到
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        sess = _sess(location="校长办公室", slot="晚", npc_followers=[3])
        self.assertEqual(
            npc_place(npc, "晚", {}, sess.npc_followers, "校长办公室"), "校长办公室"
        )
        self.assertTrue(apply_npc_followers(sess, 3, False))
        self.assertEqual(sess.npc_followers, [])
        self.assertEqual(
            npc_place(npc, "晚", {}, sess.npc_followers, "校长办公室"), "宿舍"
        )

    def test_an_empty_here_does_not_use_the_followers(self):
        # here 是空的（模组一个地点都没建、或调用方不传），跟随那一层就不该
        # 吃——没地方可跟，落回作息表
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(npc_place(npc, "晚", {}, [3], ""), "宿舍")


class FollowConsumersTests(unittest.TestCase):
    """三条「在场」路径必须一起跟着跟随名单走。

    第二十四节立的那条规矩：在场只有一个定义。分叉的那一次就是「侧栏说她在
    跟前、提示词里没这个人」。这一批把 here_npcs / present_ids / turn_present
    三条路都摆出来，谁漏了谁自己红。
    """

    def test_here_npcs_follows_the_list(self):
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(here_npcs([npc], "校长办公室", "晚", {}, []), [])
        self.assertEqual(here_npcs([npc], "校长办公室", "晚", {}, [3]), [npc])

    def test_present_ids_follows_the_list(self):
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        self.assertEqual(present_ids([npc], "校长办公室", "晚", {}, []), [])
        self.assertEqual(present_ids([npc], "校长办公室", "晚", {}, [3]), [3])

    def test_turn_present_reads_the_list_from_the_session(self):
        # turn_present 收的是整个 sess，名单就得从 sess.npc_followers 读——
        # 不给它传名单参数，这是调用点唯一能保证两处不分叉的写法
        npc = _npc(slot_locations={"晚": "宿舍"}, location="宿舍")
        sess = _sess(location="校长办公室", slot="晚", npc_followers=[])
        self.assertEqual(turn_present([npc], sess, GROUP_MODE, None), [])
        sess.npc_followers = [3]
        self.assertEqual(turn_present([npc], sess, GROUP_MODE, None), [npc])


# ── B. 寿命 ───────────────────────────────────────────────────────────────


class ApplyFollowersTests(unittest.TestCase):
    """加人 / 移人 / 重复操作：返回值是「真的变了没有」。

    调用方靠它决定要不要报一句「赫敏跟上了你」——没变的事不必报一遍。
    """

    def test_adding_someone_new(self):
        sess = _sess()
        self.assertTrue(apply_npc_followers(sess, 3, True))
        self.assertEqual(sess.npc_followers, [3])

    def test_removing_someone_who_is_on_the_list(self):
        sess = _sess(npc_followers=[3])
        self.assertTrue(apply_npc_followers(sess, 3, False))
        self.assertEqual(sess.npc_followers, [])

    def test_adding_again_is_a_noop(self):
        sess = _sess(npc_followers=[3])
        self.assertFalse(apply_npc_followers(sess, 3, True))
        self.assertEqual(sess.npc_followers, [3])

    def test_removing_someone_who_was_never_on_the_list_is_a_noop(self):
        sess = _sess()
        self.assertFalse(apply_npc_followers(sess, 3, False))
        self.assertEqual(sess.npc_followers, [])

    def test_a_non_numeric_id_is_refused(self):
        sess = _sess()
        self.assertFalse(apply_npc_followers(sess, "赫敏", True))
        self.assertEqual(sess.npc_followers, [])


class SlotResetTests(unittest.TestCase):
    """推时段：跟随名单活下来，npc_places 照样清空。

    这一条是这轮设计的核心。两张表的寿命不一样，差别在于它们的写入者：
    npc_places 写的是**模型**随手一笔（不清的话它会永久盖掉作者排的作息表，
    那是他唯一的排期手段），npc_followers 写的是**玩家**明说的话——玩家压过
    作者排的班表是天经地义的事。这两句显式断言放在一起，改哪一个都要来这看一眼。
    """

    def _module(self):
        return RpgModule(name="魔法学院", time_slots=["早", "中", "晚"])

    def test_followers_survive_and_places_are_cleared(self):
        module = self._module()
        sess = _sess(
            slot="中", npc_places={"3": "校长办公室"}, npc_followers=[3, 4],
        )
        advance_slot(module, sess)
        self.assertEqual(sess.slot, "晚")
        self.assertEqual(sess.npc_followers, [3, 4])
        self.assertEqual(sess.npc_places, {})

    def test_rolling_over_to_a_new_day_still_keeps_the_followers(self):
        module = self._module()
        sess = _sess(
            slot="晚", day=3, npc_places={"3": "校长办公室"}, npc_followers=[3],
        )
        advance_slot(module, sess)
        self.assertEqual(sess.day, 4)
        self.assertEqual(sess.npc_followers, [3])
        self.assertEqual(sess.npc_places, {})


# ── C~J. 认意图 ───────────────────────────────────────────────────────────


class _CompanyScenario:
    """携带 / 派遣 / 解除 / 反例 / 歧义 / 私聊共用的场景搭建。

    默认：玩家在酒馆，赫敏也在酒馆（跟前站着）。姓名用中文名字，是为了让
    match_npc 的三级放宽有东西可对，而不是两个化名自己跟自己匹配。
    """

    def setUp(self):
        self.locations = _places("酒馆", "后山", "客栈", "宿舍")
        self.npcs = [_npc(npc_id=3, name="赫敏", location="酒馆")]
        self.sess = _sess(location="酒馆", slot="晚")

    def _four(self, content, **kwargs):
        c = parse_company(
            content, self.locations, self.npcs, self.sess, **kwargs,
        )
        return (c.move_to, c.follow, c.unfollow, c.dispatch)


class CarryTests(_CompanyScenario, unittest.TestCase):
    """携带：follow 有值，move_to 是玩家自己的去向。

    「带人走」原先死在 _MOVE_DENY 上（「去」前面有「她」），连玩家自己的移动
    都不生效。这一批的处理是：把携带短语剥掉、再拿剩下的跑原来那套，所以
    去向仍由玩家说了算，「谁跟着你」被单独记进 npc_followers。
    """

    def test_verbs_that_say_carry_you_with_me(self):
        for content in (
            "我带她一起去后山",
            "我和赫敏一起去后山",
            "带上赫敏去后山",
            "带着赫敏去后山",
            "带上赫敏一起去后山",
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("后山", (3,), (), ()))

    def test_going_to_another_place_still_works(self):
        self.assertEqual(self._four("叫上赫敏去客栈"), ("客栈", (3,), (), ()))

    def test_group_words_take_everybody_in_the_room(self):
        # 「我们」= 屋里的人都带上（产品口径定的）
        self.assertEqual(self._four("我们一起去后山"), ("后山", (3,), (), ()))

    def test_group_words_without_a_destination(self):
        # 「我们走吧」玩家没指名去哪儿，去向交回 AI——但「谁跟着你」认得出
        self.assertEqual(self._four("我们走吧"), ("", (3,), (), ()))

    def test_bare_hui_counts_as_a_movement_verb_too(self):
        # 这条从前写的是「裸『回』不算移动动词，去向交回 AI 更安全」。实测反了：
        # AI 兜底时灵时不灵，「回宿舍」这类说法十次有几次不动身，所以裸「回」
        # 并进了 _MOVE_VERBS。误判风险各有人挡——说别人（「他回宿舍了」）归
        # _MOVE_DENY，「我回答他 / 我回想起」归「回后面那截必须是登记地名」，
        # 见 MovementTargetLooseningTests.test_the_loosened_rules_still_refuse_what_they_should
        self.assertEqual(self._four("我们回宿舍"), ("宿舍", (3,), (), ()))

    def test_plural_pronouns_take_everyone_here(self):
        """「带上她们去密室」= 把跟前的人都带上，口径同上面那条「我们」。

        不修的话这句整条携带认不出来：玩家自己走了，谁都没跟上，而 GM 照着
        写了一段大家都到了的剧情。
        """
        self.npcs.append(_npc(npc_id=4, name="罗恩", location="酒馆"))
        ids = tuple(npc.id for npc in self.npcs)
        for content in ("带上她们去后山", "带他们一起去后山", "领着她们去后山"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("后山", ids, (), ()))

    def test_a_plural_pronoun_falls_back_to_the_one_person_who_is_here(self):
        """跟前只站着一个人还说「她们」：复数这条路不认，退回原来那条单数的。

        **刻意不在这里拦一道**。「跟前不够两个人」听着像该整句不认，但退回去
        的那条路（逐字加长 + 单数代词的唯一性判据）只可能挑中**在场**的人，
        凭空拽人那种错它犯不了；拦了反而把「带上她们走」变成谁都没跟上、
        玩家也没动
        """
        self.assertEqual(self._four("带上她们去后山"), ("后山", (3,), (), ()))


class CarryNeedsGoingTests(_CompanyScenario, unittest.TestCase):
    """贴身动作不是动身：「扶她起来」不该把人登记成永久跟随。

    线上真出过：玩家在藏剑阁打了「扶她起来，别再跪着」和「趁机扶上她的腰」，
    两句都被认成携带，人进了 npc_followers。跟随名单是跨时段存活的，往后
    玩家走到哪儿 npc_place 就把她算在哪儿——半天之后推开另一个地方的门，
    她已经站在屋子中央了，而中间没有任何一句话让她跟来。

    判据是这句**在不在动身**：认得出地名，或者明说了「走吧」。两个都不中的
    「扶 / 拉 / 牵 / 拽」是原地动作，整句交回 AI。
    """

    def test_touching_in_place_is_not_carrying(self):
        for content in (
            "扶她起来",
            "扶她起来，别再跪着",
            "拉她的手",
            "牵着她坐下",
            "趁机扶上赫敏的腰",
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (), ()))

    def test_the_same_verbs_still_carry_when_you_are_going_somewhere(self):
        # 说了去哪儿（或者说了「走吧」）就还是携带——这一组动词本身没被废掉
        self.assertEqual(self._four("扶着赫敏去后山"), ("后山", (3,), (), ()))
        self.assertEqual(self._four("拉着赫敏一起去客栈"), ("客栈", (3,), (), ()))
        # 没点地名但明说了动身也算。**不拿「扶着赫敏走吧」当例子**：点了名
        # 再加一句「走吧」，解除那一支先认走了（「赫敏，走吧」= 支使她走），
        # 那是既有口径，不归这条管
        self.assertEqual(self._four("该出发了，扶着赫敏"), ("", (3,), (), ()))

    def test_we_alone_is_talk_not_travel(self):
        # 「我们」两个字在对话里太常见，光有它不算招呼同行。从前这两句会把
        # 屋里所有人一次性写进跟随名单
        for content in ("我们聊聊", "我们之间的事还没完"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (), ()))


class FollowMeTests(_CompanyScenario, unittest.TestCase):
    """「你跟着我」——这是「让 NPC 跟随」最自然的一种说法。

    裸「跟」进不了携带动词表（「我跟他去客栈」是玩家随他走，方向正好反着），
    所以它单独成一支，判据是**跟的对象必须是「我 / 我们」**。落在两人同时在
    场的时候，「你」指谁不明——照旧不出手，交回 AI。
    """

    def test_you_follow_me(self):
        self.assertEqual(self._four("你跟着我"), ("", (3,), (), ()))

    def test_the_destination_after_it_still_works(self):
        # 「你跟着我去后山」：剥掉「你跟着我」之后，「去后山」照常认出来
        self.assertEqual(self._four("你跟着我去后山"), ("后山", (3,), (), ()))

    def test_naming_her(self):
        self.assertEqual(self._four("赫敏跟着我"), ("", (3,), (), ()))

    def test_no_subject_means_the_whole_room(self):
        self.assertEqual(self._four("跟着我"), ("", (3,), (), ()))

    def test_walking_with_him_is_not_him_following_you(self):
        # 「我跟他去客栈」是**玩家**随他走，方向反着。移动那条线被 _MOVE_DENY
        # 里的「他」拦着（既有口径），跟随那条线也不许把他登记进来
        self.assertEqual(self._four("我跟他去客栈"), ("", (), (), ()))

    def test_the_negated_form_is_a_dismissal_not_a_follow(self):
        # 「你别跟着我」是打发她走。解除排在识别链最前，就是防这条被当成跟随
        self.assertEqual(self._four("你别跟着我"), ("", (), (3,), ()))


class DispatchTests(_CompanyScenario, unittest.TestCase):
    """派遣：dispatch 有值，move_to 必须是空——玩家自己不挪窝。

    「你回宿舍去」这句出现在对话里太自然了，很容易被也当成「玩家自己回去」。
    四元组一起断言，就是不让这种连累发生。
    """

    def test_explicit_commands(self):
        for content, place in (
            ("你回宿舍去", "宿舍"),
            ("你去客栈等我", "客栈"),
            ("麻烦你去客栈等我", "客栈"),
            ("派赫敏去客栈", "客栈"),
            ("赫敏去客栈", "客栈"),
            ("让赫敏回宿舍", "宿舍"),
            ("打发赫敏去客栈", "客栈"),
        ):
            with self.subTest(content=content):
                self.assertEqual(
                    self._four(content),
                    ("", (), (), ((3, place),)),
                )


class UnfollowTests(_CompanyScenario, unittest.TestCase):
    """解除：unfollow 有值，其余三个字段全空。

    解除排在识别链最前：它是唯一一条反向的，被别的规则先吃掉就成了「越说越
    跟得紧」。这一个类同时钉住「四元组一起动」这条底线——认出解除之后不该
    有别的字段也跟着动。
    """

    def test_all_dismissals(self):
        for content in (
            "你别跟着了",
            "你回去吧",
            "你去忙你的吧",
            "别跟着了",
            "都别跟着了",
            "赫敏别跟着我",
            "你们不用跟着",
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (3,), ()))

    def test_a_bare_lets_go_with_a_destination_is_departure_not_dismissal(self):
        """「走吧，去后山」是招呼着一起动身，不是叫人散了。

        不拦的话这句连人带去向一起被吞掉：人被解散、玩家留在原地，而 GM 照着
        那句话写一段已经到了的剧情。口径同「我们走吧」——屋里的人都带上。
        """
        for content in ("走吧，去后山", "走吧，去后山，路上说", "走吧，我们去后山"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("后山", (3,), (), ()))

    def test_it_is_still_a_dismissal_when_a_person_is_named_or_no_place_is_given(self):
        # 点了名的是在支使人回去；没说去哪儿的照旧是打发人
        for content, expect in (
            ("你们走吧，回宿舍", ("", (), (3,), ())),
            ("赫敏走吧", ("", (), (3,), ())),
            ("别跟着我了，走吧", ("", (), (3,), ())),
            ("走吧", ("", (), (3,), ())),
            ("走吧，别再来了", ("", (), (3,), ())),
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), expect)


class NegativeTests(_CompanyScenario, unittest.TestCase):
    """反例：四个字段一个都不许动。

    识别一旦越界，代价是把人凭空挪到错的地方。这一批把「不是命令」的各种
    写法摆齐：陈述他人的动作、回顾、被动、问句、骂人的话、认不出的人名、
    祈使但没指名——任何一条漏认都是这轮最贵的一类 bug。
    """

    def test_nothing_recognised(self):
        for content in (
            "他去后山了",
            "我和他不一样",
            "我带她去过那里",
            "她被他带走了",
            "你去客栈吗？",
            "你去死吧",
            "带上两个手下",
            "我们别去后山了",
            "派赫敏去隔壁老王家",
            "你自己去后山",
            "打发她走",
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (), ()))

    def test_a_sword_is_not_a_person(self):
        # 「我带着剑去后山」玩家自己当然要动，但 follow 里绝不能出现「剑」——
        # 携带识别不许把物件当人。四元组一起断言，就是不让「剑」钻进来
        self.assertEqual(self._four("我带着剑去后山"), ("后山", (), (), ()))

    def test_watching_her_leave_is_not_ordering_her(self):
        # 这一条真正要钉的是 dispatch 必须空：引擎不能把一句陈述当成命令。
        #
        # move_to 那一格从前是「客栈」——玩家在讲别人的事，引擎却把**玩家自己**
        # 挪去了客栈。根子是 _MOVE_DENY 只拦单字代词，「赫敏」是具名角色、
        # 「看见」也不在表里。现在感知和转述动词进了那张表，四格全空
        self.assertEqual(self._four("我看见赫敏去客栈"), ("", (), (), ()))


class AmbiguityTests(_CompanyScenario, unittest.TestCase):
    """歧义：屋里站着两个人时不出手。

    「你」「她」指谁不明确，这句就交回 AI。尤其「你去客栈」——不能因为派遣
    那条路认不出人，就掉到 movement_target 上把玩家自己挪走。四元组一起断言，
    就是钉住这一点。
    """

    def setUp(self):
        super().setUp()
        self.npcs.append(_npc(npc_id=4, name="德拉科", location="酒馆"))

    def test_a_pronoun_with_two_people_in_the_room(self):
        self.assertEqual(self._four("带她走"), ("", (), (), ()))

    def test_second_person_with_two_people_leaves_the_player_too(self):
        # 玩家自己也不动：认不出「谁去」就不该把玩家替她挪走
        self.assertEqual(self._four("你去客栈"), ("", (), (), ()))

    def test_an_imperative_tail_does_not_resolve_the_ambiguity(self):
        self.assertEqual(self._four("你去客栈等我"), ("", (), (), ()))

    def test_naming_her_resolves_it(self):
        # 点了名就不歧义
        self.assertEqual(self._four("带赫敏一起去后山"), ("后山", (3,), (), ()))

    def test_everybody_means_everybody(self):
        self.assertEqual(self._four("你们别跟着了"), ("", (), (3, 4), ()))

    def test_you_follow_me_is_ambiguous_too(self):
        # 两个人都在场时「你」指谁不明——「你跟着我」也不出手
        self.assertEqual(self._four("你跟着我"), ("", (), (), ()))


class WholeRoomTests(_CompanyScenario, unittest.TestCase):
    """群体说法 = 屋里的人**都**带上 / 都打发走（产品口径定的）。

    这一类必须有两个人在场才算测到。只有一个人时「全员」和「那一个」结果
    一模一样，断言看着是绿的，其实分不出引擎到底取的是名单还是碰巧那一个
    ——文档里那几行「屋里全员」就是这么变成没验证过的断言的。

    注意这几句和 AmbiguityTests 里「你去客栈」的区别：群体说法本身不歧义，
    「我们」「你们」「都」指的就是全体，所以两个人在场时照样要出手。
    """

    def setUp(self):
        super().setUp()
        self.npcs.append(_npc(npc_id=4, name="德拉科", location="酒馆"))

    def test_group_words_carry_everyone(self):
        for content, dest in (
            ("我们一起去后山", "后山"),
            ("我们走吧", ""),
            ("跟着我", ""),
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), (dest, (3, 4), (), ()))

    def test_dismissals_without_a_name_clear_everyone(self):
        for content in ("别跟着了", "都别跟着了", "你们不用跟着"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (3, 4), ()))


class PrivateModeTests(_CompanyScenario, unittest.TestCase):
    """私聊：对面那一个人的身份是零猜测的。

    玩家刚亲手点了「和赫敏说说」，这个锚点比句尾任何祈使词都硬——
    「你去客栈」不需要「等我」那种尾巴也算命令。这一条同时守着「私聊里
    『你』指的到底是谁」这件事，它是这一轮里唯一不靠猜的场合。
    """

    def _four(self, content):
        return super()._four(content, private_with=3, mode=PRIVATE_MODE)

    def test_you_without_an_imperative_tail_still_counts(self):
        self.assertEqual(
            self._four("你去客栈"), ("", (), (), ((3, "客栈"),))
        )

    def test_the_engine_move_wording_is_not_an_order(self):
        # 「你前往客栈。」是移动按钮替玩家写进正文的那句文案（前端 moveByTurn）。
        # 玩家照着它手打出来说的是**自己**要走，可私聊里代词主语必然解析成对面
        # 那个人——不拦的话这句会把正在对话的人支使到客栈，而玩家因为「私聊
        # 不替玩家挪窝」留在原地，看着就像她自己跟了过去。dispatch 必须是空
        for content in ("你前往客栈", "你前往客栈。", "你赶往客栈"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content)[3], ())

    def test_the_engine_wording_with_an_imperative_tail_is_still_an_order(self):
        # 书面动词只是不再**替代**祈使尾巴，不是从此认不出来：
        # 明说了「等我」，那就是在支使人
        self.assertEqual(
            self._four("你前往客栈等我"), ("", (), (), ((3, "客栈"),))
        )

    def test_dismissal_without_a_name(self):
        self.assertEqual(self._four("别跟着了"), ("", (), (3,), ()))


class OffstageTests(_CompanyScenario, unittest.TestCase):
    """人不在场：认不出携带部分，但玩家自己的移动不受连累。

    产品口径（用户已定）：不认这句的携带部分——不把她从宿舍拽过来——但玩家
    自己的移动照旧。两条腿分开走：识别层只认跟前的人，移动那条线一直是
    「玩家说了算」。
    """

    def setUp(self):
        super().setUp()
        # 赫敏在宿舍，玩家在酒馆——她不在跟前
        self.npcs = [_npc(npc_id=3, name="赫敏", location="宿舍")]

    def test_carry_silently_drops_the_offstage_part(self):
        self.assertEqual(
            self._four("带赫敏一起去后山"), ("后山", (), (), ())
        )

    def test_dispatch_to_someone_who_is_not_here(self):
        # 她不在跟前，派遣那三条路一条都不许动。**move_to 这一格从前是「客栈」**：
        # 识别层在「跟前一个人都没有」时整句退回 movement_target，而「派赫敏」里
        # 的人名不在否定表里，于是把**玩家自己**挪去了客栈——被支使的是她，走的
        # 却是玩家。现在 _moves_by_someone_else 在退回之前先拦一道，四格全空
        self.assertEqual(self._four("派赫敏去客栈"), ("", (), (), ()))

    def test_a_named_subject_is_not_the_player_moving(self):
        # 「赫敏去客栈」动身的是她。她在跟前时这句归 _parse_send（那边认得出
        # 是谁），不在跟前时那条路够不着，四格必须全空——不能掉到移动识别上
        # 把玩家挪去客栈
        for content in ("赫敏去客栈", "赫敏，去客栈", "赫敏回宿舍"):
            with self.subTest(content=content):
                self.assertEqual(self._four(content), ("", (), (), ()))

    def test_the_players_own_move_survives_someone_elses_name(self):
        """回归：句子里出现她的名字，不等于玩家的移动该被吞掉。

        「动身的是别人」那道闸只认两种形状——派遣短语 + 具名对象，或者移动
        动词前面**整个**就是一个名字。别的都不许拦，拦了就是玩家该走的时候
        留在原地。分句也各算各的：前一句安排她，后一句说自己去哪儿
        """
        for content, expect in (
            ("我去客栈找赫敏", "客栈"),
            ("带赫敏一起去后山", "后山"),
            ("我让赫敏先走，我去客栈", "客栈"),
        ):
            with self.subTest(content=content):
                self.assertEqual(self._four(content)[0], expect)


class EmptyRoomTests(_CompanyScenario, unittest.TestCase):
    """空屋回归：屋里没有别人时，玩家照样走得动。

    这是一条修过的真 bug：识别整套如果搭在「跟前有谁」上，空屋那句
    「我去后山」会被判成「什么都不是」——玩家在一间空屋子里走不动路。
    退路就是那条不依赖在场的 movement_target。
    """

    def setUp(self):
        super().setUp()
        self.npcs = []

    def test_the_player_still_moves(self):
        self.assertEqual(self._four("我去后山"), ("后山", (), (), ()))

    def test_a_verb_tail_does_not_get_in_the_way(self):
        # 「看看」这种动作尾巴是 movement_target 的既有识别，_MOVE_TAIL 管它
        self.assertEqual(
            self._four("我要去客栈看看"), ("客栈", (), (), ())
        )

    def test_group_words_with_nobody_around(self):
        # 空屋里没有「我们」，去向也不清楚——除空以外一个字段都不许动
        self.assertEqual(self._four("我们走吧"), ("", (), (), ()))


# ── K. 迁移与快照 ─────────────────────────────────────────────────────────


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    """迁移：老库 drop 掉这一列也能补回来，连跑两次不炸。

    照 test_rpg_settlement.py 那条迁移测试的写法：在**测试自己的临时库**
    （不是真实存档）上 DROP COLUMN 造出老库局面，连跑两次 _run_migrations()，
    断老存档拿到 []。
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_a_repeat_run_is_safe_and_old_saves_get_an_empty_list(self):
        async with self.sessions() as store:
            module = RpgModule(name="迁移测试")
            store.add(module)
            await store.flush()
            sess = RpgSession(
                module_id=module.id, char_name="阿隼", stats={},
                location="酒馆", slot="晚", day=1, status="alive",
                npc_states={}, npc_notes={}, npc_places={}, chronicle=[],
            )
            store.add(sess)
            await store.commit()
            identity = sess.id
        async with self.engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE rpg_sessions DROP COLUMN npc_followers")
            )
        with patch.object(database, "engine", self.engine):
            await database._run_migrations()
            await database._run_migrations()
        async with self.sessions() as store:
            restored = await store.get(
                RpgSession, identity, populate_existing=True,
            )
            self.assertEqual(restored.npc_followers, [])


class SnapshotTests(unittest.TestCase):
    """快照：跟随名单必须进 SNAPSHOT_FIELDS。

    漏了不会报错，只会在读档之后留下一个不还原的字段——读完档她还跟着你，
    而那是「读档之前的你」才发生过的事。
    """

    def test_the_follow_list_is_snapshotted(self):
        self.assertIn("npc_followers", SNAPSHOT_FIELDS)
        self.assertEqual(SNAPSHOT_DEFAULTS["npc_followers"], [])


# ── L. 结算闸门 ───────────────────────────────────────────────────────────


class SettlementGateTests(unittest.TestCase):
    """闸门：结算模型一个字都不许碰 npc_followers。

    它只有两个写入者：玩家打字（引擎解析）、侧栏那个叉（专用接口）。结算就算
    在输出里写了这个键，apply_state_delta 里也没有处理它的分支——模型没法给
    人永久加/减同伴，而那正是 npc_places 那条「随手一笔永久生效」的镜像错误，
    只是代价更贵。
    """

    def test_it_is_not_a_settlement_field(self):
        self.assertNotIn("npc_followers", STATE_FIELDS)

    def test_it_is_not_in_any_domain(self):
        self.assertNotIn("npc_followers", DOMAINS)


if __name__ == "__main__":
    unittest.main()
