"""RPG 的滚动概要。**一个格子一份**：玩家一份，每个 NPC 各一份。

格子的定义在 rpg_context.message_slots：一条消息**永远**记进玩家格（那是发生在
你眼前的事），另外按它写下那一刻的在场名单记进在场每个人的格子。于是「你亲身
经历过的全部」和「和柳如烟之间的那些事」各压各的，她在跟前时才注入她那一份。

玩家格装全部是有来历的：原先它只收「没有别人在场」的消息，一场 1v1 的戏只躺
在对方名下，走到别的地点就两头落空——原文不进窗口、对方那份概要也不注入，
模型转头从更早的状态重讲。

玩家格装全部**不等于**她们互相知道：各 NPC 格仍然只收她自己在场的那些。

这里钉三件事：窗口和压缩用同一把尺子（`slot_window`）、指针只在真压出东西时
才动、私聊的内容不许漏进**别的 NPC** 那一份。

顺带钉住那个最容易漏的地方：新列必须进快照表，否则读档之后概要里还留着「未来」的剧情。
"""
import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS
from app.database import Base
from app.models import novel as _novel, chapter as _chapter, character as _character, memory as _memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume as _volume, worldview_change, world_rule, story_thread, glossary_entry, user as _user, tavern as _tavern, rpg as _rpg  # noqa: F401
from app.models.rpg import RpgMessage, RpgModule, RpgSession
from app.services.rpg_context import history_window


def _sess(**kwargs):
    base = {"stats": {}, "location": "", "summary": "", "summarized_upto_id": 0}
    base.update(kwargs)
    return RpgSession(module_id=1, char_name="阿隼", **base)


class WindowTests(unittest.TestCase):
    def test_the_window_cuts_by_the_pointer(self):
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=20,
        )
        sess = _sess(summarized_upto_id=2)
        history = [
            RpgMessage(id=i, session_id=1, role="user", content=str(i))
            for i in (1, 2, 3)
        ]
        # 压进概要的那两条不再发原文，指针之后的照发
        self.assertEqual([m.id for m in history_window(module, sess, history, None)], [3])

    def test_the_window_keeps_the_most_recent_turns(self):
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=2,
        )
        sess = _sess()
        history = [
            RpgMessage(id=i, session_id=1, role="user", content=str(i))
            for i in range(1, 8)
        ]
        # context_turns=2 → 留最后 4 条
        self.assertEqual(
            [m.id for m in history_window(module, sess, history, None)], [4, 5, 6, 7]
        )


class PresenceFilterTests(unittest.TestCase):
    """窗口 = 你那一格，加此刻在跟前的人那一格。

    这里钉两个玩家报过的失忆 bug：

    1. 筛选依据曾经是 `focus_npc_id`（玩家在面包屑上点了谁），没点时只留
       `present` 为 null 或人数 > 1 的「群戏」。而「看全部」本来就是默认态，
       于是跟她一对一聊十轮（`present=[7]`）之后随口再说一句，模型眼前只剩
       开场白。点谁是界面上的筛选，不该决定模型看得见什么。
    2. 改完 ① 之后判据变成「**此刻**谁在跟前」，而一场 1v1 的戏只记在对方名下
       ——一走开，那个人那一格整个不进，原文和她那份概要两头落空，模型转头
       从更早的状态重讲。所以玩家格改成装**全部**消息（见 `message_slots`），
       在场的人那一格只是额外把**她自己的**更早记忆也捞进来。

    她们那些人之间仍然是隔离的：跟老兵说的那些，老板娘在跟前时不会进窗口。
    """

    def setUp(self):
        self.module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=20,
        )
        self.sess = _sess()
        self.history = [
            RpgMessage(id=1, session_id=1, role="assistant", content="开场白", present=None),
            RpgMessage(id=2, session_id=1, role="user", content="一个人翻箱子", present=[]),
            RpgMessage(id=3, session_id=1, role="user", content="只跟老兵说的话", present=[7]),
            RpgMessage(id=4, session_id=1, role="user", content="只跟老板娘说的话", present=[9]),
            RpgMessage(id=5, session_id=1, role="assistant", content="三个人的群戏", present=[7, 9]),
        ]

    def _ids(self, here):
        return [m.id for m in history_window(self.module, self.sess, self.history, here)]

    def test_the_player_keeps_everything_they_were_there_for(self):
        # 你在场就是你的事：不管此刻谁站在跟前，你自己刚经历过的几轮一条都不能少。
        # 原先跟老兵说话时，「你背着老兵跟老板娘说的那句」会被筛掉——你自己
        # 刚做过的事，你和叙述你的 GM 都看不见
        for here in (set(), {7}, {9}, {7, 9}):
            with self.subTest(here=here):
                self.assertEqual(self._ids(here), [1, 2, 3, 4, 5])

    def test_the_scene_you_just_left_does_not_vanish(self):
        """扶她回房那整场戏，走到别的地点不该整个消失。

        玩家报的那个 bug 的最小复现：一场 1v1 的戏（`present=[7]`）之后挪到
        别处，此刻跟前的是另一个人。窗口原先按**此刻**在跟前的人筛，那场戏
        只记在 7 名下，于是整个不进；7 那份概要也只在她在跟前时才注入——
        原文和概要两头落空，模型从更早的状态重讲。
        """
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=1,
        )
        history = [
            RpgMessage(id=1, session_id=1, role="assistant", content="开场白", present=None),
            RpgMessage(id=2, session_id=1, role="user", content="你扶她回主卧", present=[7]),
            RpgMessage(id=3, session_id=1, role="assistant", content="主卧那场戏", present=[7]),
            RpgMessage(id=4, session_id=1, role="user", content="你走到千手酒馆", present=[9]),
        ]
        # 窗口只有 1 轮×2 = 2 条，但那两条必须是**刚发生**的，不是开场白
        self.assertEqual(
            [m.id for m in history_window(module, self.sess, history, {9})], [3, 4]
        )

    def test_being_with_her_also_reaches_back_into_her_older_memories(self):
        # 在她跟前时，她那一格会把你自己的窗口够不到的更早那几轮也捞回来
        module = RpgModule(
            user_id=1, name="m", stat_defs=[], relation_stat_defs=[], context_turns=2,
        )
        history = [
            RpgMessage(id=i, session_id=1, role="user", content=str(i),
                       present=[7] if i <= 4 else [9])
            for i in range(1, 9)
        ]
        # 你自己那格只留最后 2 轮×2 = 4 条，老兵那格把他那 4 条旧事捞回来
        self.assertEqual(
            [m.id for m in history_window(module, self.sess, history, {7})],
            [1, 2, 3, 4, 5, 6, 7, 8],
        )
        # 换成老板娘在跟前，老兵那几条不跟过来——她们之间仍然是隔着的
        self.assertEqual(
            [m.id for m in history_window(module, self.sess, history, {9})], [5, 6, 7, 8]
        )

    def test_an_empty_room_and_a_missing_roster_now_agree(self):
        """空集（屋里没人）和 None（拿不到名单）现在是同一件事。

        区分它们本来有意义——「筛」那一支会筛掉玩家的东西。玩家格改成装全部
        之后没什么可筛的了。参数留着是因为各调用方拿到的东西不一样，不是因为
        行为还有差别。
        """
        self.assertEqual(self._ids(set()), self._ids(None))
        self.assertEqual(self._ids(set()), [1, 2, 3, 4, 5])

    def test_old_messages_without_a_present_column_are_always_visible(self):
        # 老存档绝大多数消息这一列是 null。判成「只有玩家」的话，整段历史会
        # 从每个人眼前消失——放宽错了少一点隐私，收紧错了是丢记忆
        self.assertIn(1, self._ids({7}))
        self.assertIn(1, self._ids(set()))

    def test_your_own_scenes_never_drop_out(self):
        # present=[] 是你一个人做的事。旁白得知道你从哪来、拿到了什么，
        # 这一条掉了连「你」都叙述不了
        for here in (set(), {7}, {9}, {7, 9}):
            with self.subTest(here=here):
                self.assertIn(2, self._ids(here))


class SummaryInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.module = RpgModule(user_id=1, name="测试模组", stat_defs=[], relation_stat_defs=[])
        self.db.add(self.module)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_the_summary_reaches_the_prompt(self):
        # 摘要是长期记忆的唯一载体。它要是没进 system，几十轮之前的剧情就断了
        from app.services.rpg_context import build_rpg_messages

        sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={}, location="",
            summary="你在密室里告诉老兵你杀了人",
        )
        self.db.add(sess)
        await self.db.commit()

        messages, _ = await build_rpg_messages(self.db, self.module, sess, [], "嗯")
        self.assertIn("你杀了人", messages[0]["content"])

    async def test_her_own_summary_only_shows_up_when_she_is_here(self):
        """NPC 那一份长期记忆跟着人走。

        这是「和角色的对话单独存」在 prompt 这一端的落点：跟她在藏经阁说的那些
        话压成的那一份，走回演武场就不该再出现在眼前——师兄不该知道。
        反过来更要紧：她在跟前时那一份必须在，不然她一开口又是第一次见面。
        """
        from app.services.rpg_context import build_rpg_messages
        from app.models.rpg import RpgNpc

        npc = RpgNpc(module_id=self.module.id, name="柳如烟", location="藏经阁")
        self.db.add(npc)
        await self.db.commit()
        sess = RpgSession(
            module_id=self.module.id, char_name="阿隼", stats={}, location="藏经阁",
            summary="你独自翻完了半架书",
            thread_summaries={str(npc.id): "她告诉你二十年前那桩事"},
        )
        self.db.add(sess)
        await self.db.commit()

        messages, _ = await build_rpg_messages(self.db, self.module, sess, [], "接着说")
        system = messages[0]["content"]
        self.assertIn("二十年前", system)
        self.assertIn("柳如烟", system)
        # 玩家自己那一份永远在：旁白得知道你从哪来
        self.assertIn("翻完了半架书", system)

        sess.location = "演武场"
        messages, _ = await build_rpg_messages(self.db, self.module, sess, [], "我练剑")
        self.assertNotIn("二十年前", messages[0]["content"])
        self.assertIn("翻完了半架书", messages[0]["content"])


class MaybeSummarizeTests(unittest.IsolatedAsyncioTestCase):
    """压缩本身：够不够条数、指针停在哪、失败了会不会拖垮这一轮。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patcher = patch.object(rpg_turn, "AsyncSessionLocal", self.sessions)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.engine.dispose()

    async def _seed(self, count, context_turns=1):
        async with self.sessions() as db:
            module = RpgModule(
                user_id=1, name="测试模组", stat_defs=[], relation_stat_defs=[],
                context_turns=context_turns,
            )
            db.add(module)
            await db.commit()
            sess = RpgSession(module_id=module.id, char_name="阿隼", stats={}, location="")
            db.add(sess)
            await db.commit()
            db.add_all([
                RpgMessage(session_id=sess.id, role="user", content=f"第{i}句")
                for i in range(count)
            ])
            await db.commit()
            return sess.id

    async def _reload(self, session_id):
        async with self.sessions() as db:
            return await db.get(RpgSession, session_id)

    async def test_an_overlong_summary_is_clipped_to_the_hard_cap(self):
        """模板那句「500 字以内」撑不住，闸得在引擎这边。

        这是累积式概要：模型手里那份旧的可能已经一千多字，外加一句「不要丢掉
        旧信息」，出来就是一千多字。真实存档里实测过 1518 字和 1431 字的格子。
        """
        session_id = await self._seed(6)
        long = "第一件事发生了。" * 200  # 1600 字，远超上限

        async def fake(messages, **_kwargs):
            return long

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)

        saved = (await self._reload(session_id)).summary
        self.assertLessEqual(len(saved), rpg_turn.SUMMARY_CHARS)
        # 切在句号上，不留半句
        self.assertTrue(saved.endswith("。"))
        # 切尾巴而不是开头：开头那段旧事除了这份概要哪儿都没有
        self.assertTrue(saved.startswith("第一件事发生了。"))

    async def test_a_short_history_is_left_alone(self):
        session_id = await self._seed(2)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete") as call:
            self.assertFalse(await rpg_turn._maybe_summarize(session_id))
            call.assert_not_called()

    async def test_the_overflow_is_folded_into_the_summary(self):
        session_id = await self._seed(6)
        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "  老兵终于开口了  "

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))

        sess = await self._reload(session_id)
        self.assertEqual(sess.summary, "老兵终于开口了")
        # 留最后 context_turns*2 = 2 条，压掉前 4 条，指针停在第 4 条上
        self.assertEqual(sess.summarized_upto_id, 4)
        self.assertIn("第0句", seen["prompt"])
        self.assertNotIn("第5句", seen["prompt"])

    async def test_the_next_round_only_folds_what_is_new(self):
        # 指针的用处：第二次压缩要从上次那里接着压，不能把已经折进概要的
        # 那几条再压一遍——那会让同一段往事在概要里越滚越重
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)
        async with self.sessions() as db:
            db.add_all([
                RpgMessage(session_id=session_id, role="user", content=f"后{i}句")
                for i in range(6)
            ])
            await db.commit()

        seen = {}

        async def fake(messages, **_kwargs):
            seen["prompt"] = messages[0]["content"]
            return "新梗概"

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))
        self.assertNotIn("第0句", seen["prompt"])
        self.assertIn("后0句", seen["prompt"])

    async def test_a_big_backlog_is_folded_in_instalments(self):
        """老档积压几百条时分批压，不一次全塞进一个 prompt。

        玩家格装的是**全部**消息（见 message_slots），所以一个跑了上百回合的
        老存档第一次触发压缩时，overflow 可能是几百条：一次全塞进去又贵又容易
        糊成一句笼统的概要，中途失败还会每回合原样重试一遍。没压到的那些仍是
        pending，不会被指针越过，后面几回合接着压。
        """
        # context_turns=1 → 窗口 2 条 → 一次最多压两个窗口 = 4 条
        session_id = await self._seed(20)
        seen = []

        async def fake(messages, **_kwargs):
            seen.append(messages[0]["content"])
            return "梗概"

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)

        sess = await self._reload(session_id)
        # 20 条、窗口留最后 2 条 → 该压 18 条，这一轮只压掉前 4 条
        self.assertEqual(sess.summarized_upto_id, 4)
        self.assertEqual(len(seen), 1)
        self.assertIn("第0句", seen[0])
        self.assertNotIn("第4句", seen[0])

    async def test_the_summary_model_is_preferred_over_the_fast_one(self):
        session_id = await self._seed(6)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            module = await db.get(RpgModule, sess.module_id)
            module.fast_model_ref = "12"
            module.summary_model_ref = "34"
            await db.commit()

        with patch.object(
            rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"
        ):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ) as pick:
                await rpg_turn._maybe_summarize(session_id)
        self.assertEqual(pick.call_args.args, ("memory", "34"))

    async def test_an_empty_summary_model_falls_back_to_the_fast_one(self):
        # 老库这一列是空串，必须继续跟着裁决模型走，不能落到全局默认上
        session_id = await self._seed(6)
        async with self.sessions() as db:
            sess = await db.get(RpgSession, session_id)
            module = await db.get(RpgModule, sess.module_id)
            module.fast_model_ref = "12"
            await db.commit()

        with patch.object(
            rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"
        ):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ) as pick:
                await rpg_turn._maybe_summarize(session_id)
        self.assertEqual(pick.call_args.args, ("memory", "12"))

    async def test_a_blank_reply_does_not_move_the_pointer(self):
        # 空回复照样推指针的话，被压掉的那几条从此谁也看不到了
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="   "):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertFalse(await rpg_turn._maybe_summarize(session_id))
        sess = await self._reload(session_id)
        self.assertEqual(sess.summarized_upto_id, 0)

    async def test_a_solo_stretch_only_writes_the_player_slot(self):
        # 一个人赶路的那几轮谁的名下都不该记：NPC 格里多出一段她没在场的事，
        # 她下次开口就会引用自己根本不知道的东西
        session_id = await self._seed(6)
        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", return_value="梗概"):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                await rpg_turn._maybe_summarize(session_id)
        sess = await self._reload(session_id)
        self.assertEqual(sess.thread_summaries, {})
        self.assertEqual(sess.thread_upto, {})


    async def test_each_slot_folds_its_own_overflow(self):
        """一个格子一份概要，各压各的，一条都不许跳。

        私聊那四条进老兵那一份，**也进你自己那一份**（你当时就在场，那是你亲身
        经历的）；但一个字都不进老板娘那一份——她不该知道你背着她说过什么。
        玩家格装全部是有意的，见 rpg_context.message_slots。

        两边的判据必须是同一把尺子（`slot_window`）：压缩这边一旦跳过某几条，
        那几条就**既没进概要、又因为指针越过了它们而不再发原文**——静默丢记忆。
        """
        session_id = await self._seed(8)
        async with self.sessions() as db:
            messages = (await db.execute(
                select(RpgMessage).where(RpgMessage.session_id == session_id)
            )).scalars().all()
            for index, message in enumerate(messages):
                message.content = f"private-{index}" if index < 4 else f"public-{index}"
                message.present = [7] if index < 4 else [7, 9]
            await db.commit()
        seen = []

        async def fake(messages, **_kwargs):
            seen.append(messages[0]["content"])
            return "梗概"

        with patch.object(rpg_turn.llm_client, "dispatch_chat_complete", fake):
            with patch.object(
                rpg_turn.llm_client, "get_agent_client", return_value=("m", "openai")
            ):
                self.assertTrue(await rpg_turn._maybe_summarize(session_id))

        # 三个格子各压一次。context_turns=1 → 窗口 2 条，一次最多压两个窗口 = 4 条
        self.assertEqual(len(seen), 3)
        player = next(p for p in seen if "你亲身经历" in p)
        others = [p for p in seen if "你亲身经历" not in p]
        veteran = next(p for p in others if "private-0" in p)
        keeper = next(p for p in others if "private-0" not in p)
        # 你自己那份装的是你经历过的全部（这里压到的是前 4 条）
        self.assertIn("private-0", player)
        self.assertIn("private-3", player)
        # 老兵那份是「你和他之间的」
        self.assertIn("private-3", veteran)
        # 老板娘那份里只有她也在场的那几条
        self.assertNotIn("private-3", keeper)
        self.assertIn("public-4", keeper)

        sess = await self._reload(session_id)
        # 三个格子各推各的指针：你 4、老兵 4、老板娘 6（她只到第 4 条为止）
        self.assertEqual(sess.summary, "梗概")
        self.assertEqual(sess.summarized_upto_id, 4)
        self.assertEqual(set(sess.thread_summaries), {"7", "9"})
        self.assertEqual(sess.thread_upto["7"], 4)
        self.assertEqual(sess.thread_upto["9"], 6)


class SnapshotCoverageTests(unittest.TestCase):
    def test_the_summary_is_in_the_snapshot(self):
        """漏了不会报错，只会在读档之后留下一份还写着「未来」的概要。"""
        for field in (
            "summary", "summarized_upto_id", "thread_summaries", "thread_upto",
        ):
            with self.subTest(field=field):
                self.assertIn(field, SNAPSHOT_FIELDS)

    def test_every_snapshot_field_exists_on_the_model(self):
        for field in SNAPSHOT_FIELDS:
            with self.subTest(field=field):
                self.assertTrue(hasattr(RpgSession, field))


if __name__ == "__main__":
    unittest.main()
