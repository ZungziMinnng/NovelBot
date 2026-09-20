import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import rpg_turn
from app.api.routes.rpg import SNAPSHOT_DEFAULTS, SNAPSHOT_FIELDS, stream_turn
from app.database import Base
from app.models import novel, chapter, character, memory, model_library, writer_preset, prompt_rule, world_entity, location, api_provider, novel_note, faction, technique, volume, worldview_change, world_rule, story_thread, glossary_entry, user, tavern, rpg
from app.models.rpg import RpgLocation, RpgMessage, RpgModule, RpgNpc, RpgSave, RpgSession
from app.schemas.rpg import RpgTurnRequest


class MovementTargetTests(unittest.TestCase):
    def test_explicit_movement_can_precede_other_sentences(self):
        places = [RpgLocation(name="藏经阁"), RpgLocation(name="藏经阁偏殿")]
        for content in (
            "走进藏经阁偏殿，关上门，表示一大早看到你，这火气就上来了",
            "走进藏经阁偏殿,关上门",
            "走进「藏经阁偏殿」，关上门",
            "走进藏经阁偏殿。关上门。",
            "走进藏经阁偏殿；关上门",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, places), "藏经阁偏殿")

    def test_movement_does_not_have_to_lead_the_sentence(self):
        # 「走吧」只是个语气词，真正动身的是第二句。从前只试第一个分句，这种
        # 说法整句认不出来：人留在原地，GM 却照着写一段已经到了的剧情
        places = [RpgLocation(name="织云阁"), RpgLocation(name="织云阁地下密室")]
        for content in (
            "走吧，去密室，让她们俩陪着",
            "走吧，去密室",
            "好了，我们回织云阁，路上说",
        ):
            with self.subTest(content=content):
                self.assertEqual(
                    rpg_turn.movement_target(content, places), "织云阁地下密室"
                    if "密室" in content else "织云阁",
                )

    def test_multiple_clauses_do_not_bypass_movement_guards(self):
        places = [RpgLocation(name="藏经阁"), RpgLocation(name="藏经阁偏殿")]
        for content in (
            "不走进藏经阁偏殿，站在门口",
            "她走进藏经阁偏殿，关上门",
            "走进藏经阁偏殿吗？关上门",
            "走进藏经阁偏殿后院，关上门",
            "走进藏经阁偏殿，然后回到藏经阁",
            "藏经阁偏殿，随后返回藏经阁",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, places), "")

    def setUp(self):
        self.locations = [
            RpgLocation(name="灵药园柴房"), RpgLocation(name="灵药园"),
            RpgLocation(name="灵药园"),
        ]

    def test_explicit_commands_resolve_to_the_exact_place(self):
        for content in ("灵药园", "前往灵药园", "我去灵药园", "我要进入灵药园。", "走到「灵药园」！"):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.locations), "灵药园")
        self.assertEqual(rpg_turn.movement_target("回到灵药园柴房", self.locations), "灵药园柴房")

    def test_mentions_questions_negation_and_unknown_places_do_not_move(self):
        for content in (
            "灵药园里有谁", "去灵药园吗？", "灵药园？", "我不去灵药园", "不要前往灵药园",
            "她前往灵药园", "我问他灵药园在哪里", "等天亮再去灵药园", "前往灵药园并回到柴房",
            "去灵药园后院", "前往不存在的地方",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.locations), "")


class MovementTargetLooseningTests(unittest.TestCase):
    """三类从前必漏的说法：尾词不在白名单、否定/推迟字离得远、裸「回」。

    漏认本身不致命（整句交回 AI 结算），但 AI 兜底时灵时不灵，「回宿舍」这种
    最常见的说法十次有几次不动身，所以收紧到引擎里来。
    """

    def setUp(self):
        self.places = [RpgLocation(name=n) for n in ("酒馆", "后山", "客栈", "宿舍")]

    def test_activity_tails_return_and_suggestions_all_move(self):
        for content, expect in (
            ("去酒馆买酒", "酒馆"),
            ("我去酒馆买点东西", "酒馆"),
            ("我去酒馆喝一杯", "酒馆"),
            ("去后山采药", "后山"),
            ("先去酒馆", "酒馆"),
            # 「要不…吧 / 不如…」是提议不是否定
            ("要不我们去酒馆吧", "酒馆"),
            ("不如去酒馆", "酒馆"),
            # 「再」不再按字拦——这句只有一个目的地
            ("我想再去酒馆", "酒馆"),
            # 裸「回」进 _MOVE_VERBS
            ("回宿舍", "宿舍"),
            ("一路走回宿舍", "宿舍"),
            # 否定字离动词够远（>4 字）就不该再误伤
            ("我不想再谈这个了，去酒馆", "酒馆"),
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), expect)

    def test_the_loosened_rules_still_refuse_what_they_should(self):
        for content in (
            # 否定紧邻动词，照旧拦
            "我不去酒馆", "我不太想去酒馆", "不要回宿舍",
            # 主语不是玩家（含「都/还」这类副词插在中间的）
            "他回宿舍了", "她回酒馆", "他还是回宿舍了",
            # 一句里两个目的地：认不出前一段就整句交回 AI，绝不只认后半句
            "先回宿舍，再去酒馆",
            # 「回」后面那截必须是个登记地名，否则「回答」「回想」都会中招
            "我回答他", "我回想起后山",
            # 尾词仍在白名单外 = 当成更长的地名，不认
            "去酒馆后院",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), "")

    def test_work_activities_after_a_destination_are_movement_commands(self):
        places = [RpgLocation(name="工位"), RpgLocation(name="办公室"), RpgLocation(name="会议室")]
        for content, expected in (
            ("回工位上班", "工位"),
            ("回工位工作", "工位"),
            ("去办公室办公", "办公室"),
            ("回办公室值班", "办公室"),
            ("去办公室打卡", "办公室"),
            ("去会议室开会", "会议室"),
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, places), expected)

    def test_work_movement_still_rejects_non_commands_and_unknown_subplaces(self):
        places = [RpgLocation(name="工位")]
        for content in ("不回工位上班", "回工位上班吗？", "她回工位上班", "回工位上层", "回工位上方"):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, places), "")


class PerceptionWordingTests(unittest.TestCase):
    """「我看见赫敏去客栈」这类句子不是玩家在动身。

    _MOVE_DENY 从前只有否定字和单字代词，而「赫敏」是个具名角色、「看见 / 听说」
    也不在表里，于是整句被认成玩家要去客栈——玩家被平白挪走，而这一轮里她根本
    没动。错认比漏认贵得多，所以感知和转述动词并进了那张表。
    """

    def setUp(self):
        self.places = [RpgLocation(name=n) for n in ("客栈", "酒馆")]

    def test_perception_and_relay_words_before_the_move_verb_are_not_moves(self):
        for content in (
            "我看见赫敏去客栈", "我看到赫敏去客栈", "我瞧见赫敏去客栈",
            "我听说赫敏去客栈了", "我听见赫敏去客栈", "我得知赫敏去客栈",
            "我知道赫敏去客栈", "我告诉赫敏去客栈", "我提到赫敏去客栈",
            "我以为赫敏去客栈", "我觉得赫敏去客栈",
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), "")

    def test_the_players_own_move_is_untouched(self):
        # 裸「说」刻意不在表里：单字太常见，这几句都是玩家真要动身
        for content, expect in (
            ("去客栈", "客栈"), ("我去客栈", "客栈"), ("去客栈买酒", "客栈"),
            ("跟掌柜说一声再去酒馆", "酒馆"),
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), expect)


class EngineMoveWordingTests(unittest.TestCase):
    """「你前往织云阁。」——移动按钮替玩家写进正文的那句文案（前端 moveByTurn）。

    玩家手打或重发这一句说的是**自己**要走，可句首那个「你」本来会被 _MOVE_DENY
    当成「在跟别人说话」而整句作废：人留在原地，GM 却照着写了一段已经到了的剧情，
    结算只能报「剧情地点与引擎地点冲突」。
    """

    def setUp(self):
        self.places = [RpgLocation(name=n) for n in ("织云阁", "灵药园柴房", "灵药园")]

    def test_the_button_wording_moves_the_player(self):
        for content, expect in (
            ("你前往织云阁。", "织云阁"),
            ("你前往织云阁", "织云阁"),
            ("你赶往织云阁", "织云阁"),
            ("你移动到织云阁", "织云阁"),
            # 尾段简称照旧认（同 PlaceShortNameTests）
            ("你前往柴房", "灵药园柴房"),
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), expect)

    def test_anything_after_the_place_name_is_an_order_not_a_move(self):
        # 多一个尾巴就是在支使跟前那个人，归 _parse_send 管，玩家自己不动
        for content in ("你前往织云阁等我", "你前往织云阁吧", "你前往织云阁看看"):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), "")

    def test_the_colloquial_wording_is_still_not_a_move(self):
        # 「你去客栈」是真人支使人的说法，不是引擎文案，照旧不认
        self.assertEqual(rpg_turn.movement_target("你去织云阁", self.places), "")


class PlaceShortNameTests(unittest.TestCase):
    """登记的是「灵药园柴房」，玩家嘴上说的是「柴房」。

    同 match_npc 那条纪律：只认**尾段**（前缀那头正是「去灵药园后院」要防的
    方向），短的那头至少两个字，而且必须唯一点名。
    """

    def setUp(self):
        self.places = [RpgLocation(name=n) for n in ("灵药园柴房", "灵药园", "后山")]

    def test_a_tail_short_name_finds_the_registered_place(self):
        for content, expect in (
            ("回到柴房", "灵药园柴房"),
            ("去柴房", "灵药园柴房"),
            ("柴房", "灵药园柴房"),
            ("去柴房看看", "灵药园柴房"),
            ("我回柴房", "灵药园柴房"),
            ("去药园", "灵药园"),
        ):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, self.places), expect)

    def test_the_longer_registered_name_still_wins(self):
        # 「灵药园柴房」在册时，「回灵药园」不该被后缀规则拽到柴房去
        self.assertEqual(rpg_turn.movement_target("回灵药园", self.places), "灵药园")
        self.assertEqual(rpg_turn.movement_target("回灵药园柴房", self.places), "灵药园柴房")

    def test_a_short_name_is_refused_when_two_places_share_it(self):
        two = [RpgLocation(name=n) for n in ("灵药园柴房", "后山柴房", "灵药园")]
        for content in ("回柴房", "去柴房", "柴房"):
            with self.subTest(content=content):
                self.assertEqual(rpg_turn.movement_target(content, two), "")

    def test_a_short_name_never_matches_the_front_half(self):
        # 「灵药园」是「灵药园柴房」的头三个字，但前缀那头不认；「后院」也不在
        # _MOVE_TAIL 里，所以这句照旧原地不动——认成「灵药园」就是送错地方
        self.assertEqual(rpg_turn.movement_target("去灵药园后院", self.places), "")


class MovementTurnTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite://")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = SimpleNamespace(id=1)
        module = RpgModule(user_id=1, name="移动测试", check_mode="never")
        self.db.add(module)
        await self.db.flush()
        self.garden = RpgLocation(module_id=module.id, name="灵药园", description="两位园丁正在照料药草。")
        self.npcs = [
            RpgNpc(module_id=module.id, name="园丁甲", location="灵药园", persona="沉稳"),
            RpgNpc(module_id=module.id, name="园丁乙", location="灵药园", persona="热情"),
        ]
        self.db.add_all([
            self.garden, *self.npcs,
            RpgLocation(module_id=module.id, name="灵药园柴房", connections=["灵药园"]),
        ])
        self.sess = RpgSession(
            module_id=module.id, char_name="旅人", location="灵药园柴房", slot="清晨",
            stats={"精力": 50}, status="alive", turn_count=0,
        )
        self.db.add(self.sess)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _turn(self, content, delta=None, **kwargs):
        captured = []

        async def stream(messages, **options):
            captured.extend(messages)
            yield "你来到药园，与园丁甲和园丁乙打了个招呼。"
            yield ("usage", 1, 1)

        with (
            patch.object(rpg_turn, "AsyncSessionLocal", self.sessions),
            patch.object(rpg_turn.llm_client, "get_agent_client", return_value=("model", "openai")),
            patch.object(rpg_turn.llm_client, "dispatch_chat_stream_with_usage", stream),
            patch.object(rpg_turn, "call_json", AsyncMock(return_value=(delta or {}, 1, 1))),
            patch.object(rpg_turn, "_maybe_summarize", AsyncMock()),
            patch.object(rpg_turn, "idle_npc_activities", AsyncMock()),
        ):
            response = await stream_turn(
                self.sess.id, RpgTurnRequest(content=content, **kwargs), self.user, self.db,
            )
            events = []
            async for chunk in response.body_iterator:
                text = chunk.decode() if isinstance(chunk, bytes) else chunk
                payload = json.loads(text.removeprefix("data: ").strip())
                events.append((payload["event"], payload["data"]))
        self.assertFalse([data for event, data in events if event == "error"])
        await self.db.refresh(self.sess)
        return events, captured

    async def test_free_movement_updates_state_context_and_both_message_snapshots(self):
        events, messages = await self._turn("前往灵药园")
        self.assertEqual(self.sess.location, "灵药园")
        self.assertIn("灵药园", self.sess.visited)
        first_state = next(data for event, data in events if event == "state")
        self.assertEqual(first_state["location"], "灵药园")
        first_state_index = next(index for index, (event, _) in enumerate(events) if event == "state")
        first_token_index = next(index for index, (event, _) in enumerate(events) if event == "token")
        self.assertLess(first_state_index, first_token_index)
        meta = next(data for event, data in events if event == "meta" and "npcs_here" in data)
        expected_ids = {npc.id for npc in self.npcs}
        self.assertEqual({npc["id"] for npc in meta["npcs_here"]}, expected_ids)
        self.assertTrue(all(self.sess.npc_states[str(npc.id)]["met"] for npc in self.npcs))
        self.assertIn("园丁甲", messages[0]["content"])
        self.assertIn("园丁乙", messages[0]["content"])
        rows = list((await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == self.sess.id).order_by(RpgMessage.id)
        )).scalars())
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row.location, "灵药园")
            self.assertEqual(set(row.present), expected_ids)
        saved = (await self.db.execute(select(RpgSave).where(RpgSave.session_id == self.sess.id))).scalars().first()
        self.assertEqual(saved.state["location"], "灵药园柴房")

    async def test_a_private_chat_does_not_swallow_the_players_own_move(self):
        """私聊里说自己要走，照走。

        私聊本来不替玩家挪窝（那一句是在跟对面那个人说话）。但明说了要走就是
        要走：吞掉的下场是人留在原地、GM 却照着那句话写一段已经到了的剧情，
        结算只能报「剧情地点与引擎地点冲突」。认出来就当场散场，按群聊走——
        人都走了，私聊的前提（两个人在同一个地方）已经没了。
        """
        keeper = RpgNpc(
            module_id=self.sess.module_id, name="柴房老仆", location="灵药园柴房", persona="寡言",
        )
        self.db.add(keeper)
        await self.db.commit()
        await self._turn("你前往灵药园。", mode="private", private_with=keeper.id)
        self.assertEqual(self.sess.location, "灵药园")
        row = (await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == self.sess.id).order_by(RpgMessage.id)
        )).scalars().first()
        # 散场了：在场名单是新地点的所有人，没有被收窄到单独说话的那一个
        self.assertEqual(set(row.present), {npc.id for npc in self.npcs})

    async def test_a_bare_place_name_moves_without_a_location_delta(self):
        await self._turn("灵药园")
        self.assertEqual(self.sess.location, "灵药园")

    async def test_movement_before_a_comma_updates_player_and_message_locations(self):
        self.db.add(RpgLocation(module_id=self.sess.module_id, name="藏经阁偏殿"))
        await self.db.commit()
        events, messages = await self._turn("走进藏经阁偏殿，关上门，向里面的人打招呼", mode="solo")
        self.assertEqual(self.sess.location, "藏经阁偏殿")
        self.assertIn("来到了藏经阁偏殿", messages[-1]["content"])
        self.assertTrue(any(event == "state" and data["location"] == "藏经阁偏殿" for event, data in events))
        rows = list((await self.db.execute(select(RpgMessage).where(
            RpgMessage.session_id == self.sess.id,
        ))).scalars())
        self.assertTrue(all(row.location == "藏经阁偏殿" for row in rows))

    async def test_arrival_settlement_does_not_move_a_waiting_npc_away(self):
        narration = "你来到药园，与园丁甲和园丁乙打了个招呼。"
        data = {
            "checks": {domain: "changed" if domain == "scene" else "unchanged"
                       for domain in ("scene", "stats", "inventory", "characters", "flags", "memory")},
            "events": [{"kind": "move", "quote": narration, "domains": ["scene"], "participants": []}],
            "location": "灵药园", "npc_places": {"园丁甲": "灵药园柴房"},
        }
        events, _ = await self._turn("前往灵药园", data)
        self.assertEqual(self.sess.location, "灵药园")
        self.assertNotIn(str(self.npcs[0].id), self.sess.npc_places)
        report = next(data["report"] for event, data in events if event == "settlement")
        self.assertEqual(report["domains"]["scene"]["status"], "needs_review")
        self.assertTrue(any("实际离场" in warning for warning in report["warnings"]))

    async def test_existing_session_can_return_to_a_new_workplace_for_work(self):
        await self._turn("看看周围")
        async with self.sessions() as editor:
            editor.add(RpgLocation(module_id=self.sess.module_id, name="工位"))
            await editor.commit()
        events, messages = await self._turn("回工位上班")
        self.assertEqual(self.sess.location, "工位")
        self.assertTrue(any(event == "state" and data["location"] == "工位" for event, data in events))
        self.assertIn("来到了工位", messages[-1]["content"])
        latest = list((await self.db.execute(
            select(RpgMessage).where(RpgMessage.session_id == self.sess.id)
            .order_by(RpgMessage.id.desc()).limit(2)
        )).scalars())
        self.assertTrue(all(row.location == "工位" for row in latest))

    async def test_settlement_cannot_undo_the_engine_movement(self):
        await self._turn("前往灵药园", {"location": "灵药园柴房"})
        self.assertEqual(self.sess.location, "灵药园")

    async def test_enter_requirements_are_enforced_even_if_settlement_claims_arrival(self):
        self.garden.enter_requires = {"stats": {"精力": {"op": ">=", "value": 200}}}
        await self.db.commit()
        events, _ = await self._turn("前往灵药园", {"location": "灵药园"})
        self.assertEqual(self.sess.location, "灵药园柴房")
        meta = next(data for event, data in events if event == "meta" and "npcs_here" in data)
        self.assertEqual(meta["npcs_here"], [])

    async def test_a_short_name_for_the_place_you_are_already_in_does_not_move(self):
        # 人在灵药园柴房，说「回柴房」：简称认得出是同一个地方，但**不该再走
        # 一遍 _move**——那会写下「你离开灵药园柴房，来到了灵药园柴房」
        events, messages = await self._turn("回柴房")
        self.assertEqual(self.sess.location, "灵药园柴房")
        self.assertNotIn("你离开灵药园柴房", "".join(str(m) for m in messages))

    async def test_a_place_mentioned_in_conversation_does_not_move(self):
        await self._turn("灵药园里有谁")
        self.assertEqual(self.sess.location, "灵药园柴房")

    async def test_explicit_move_field_uses_the_same_destination_snapshots(self):
        await self._turn("出发", move_to="灵药园")
        rows = list((await self.db.execute(select(RpgMessage))).scalars())
        self.assertTrue(all(row.location == "灵药园" for row in rows))


class SceneBreakMarkerTests(unittest.TestCase):
    """地点总览的瞬移要记一笔「上一幕在哪」，留给下一轮的 prompt。

    这条路零 LLM、不产生任何消息，于是这次离开在对话历史里一个字都不留——
    不记的话下一轮模型眼前仍是「上一幕的长篇正文 + 玩家的下一句」，接着离开
    时那一幕的场面往下演。和 time_jump_from 是同一个病的两面。
    """

    def setUp(self):
        self.locations = [
            RpgLocation(name="织云阁"),
            RpgLocation(name="主殿"),
            RpgLocation(name="禁地", enter_requires={"flags": ["拿到钥匙"]}),
        ]

    def _sess(self, **kwargs):
        base = {"location": "织云阁", "flags": {}, "npc_states": {}, "stats": {}}
        base.update(kwargs)
        return RpgSession(module_id=1, char_name="阿隼", **base)

    def test_a_teleport_records_where_the_last_scene_happened(self):
        sess = self._sess()
        rpg_turn.move_by_name(sess, self.locations, [], "主殿")
        self.assertEqual(sess.scene_break_from, "织云阁")

    def test_leaving_and_coming_back_still_counts_as_a_break(self):
        # 玩家报的就是这个形状：在织云阁聊完 → 走到主殿 → 走回织云阁。
        # 中间一句话都没说，上一幕仍然是织云阁那一场，回来时必须断一次
        sess = self._sess()
        rpg_turn.move_by_name(sess, self.locations, [], "主殿")
        rpg_turn.move_by_name(sess, self.locations, [], "织云阁")
        self.assertEqual(sess.location, "织云阁")
        self.assertEqual(sess.scene_break_from, "织云阁")

    def test_a_second_teleport_keeps_the_first_starting_point(self):
        # 连着瞬移两次之间同样一句都没写过，上一幕仍是最初那个地点
        sess = self._sess()
        rpg_turn.move_by_name(sess, self.locations, [], "主殿")
        rpg_turn.move_by_name(sess, self.locations, [], "禁地")
        self.assertEqual(sess.scene_break_from, "织云阁")

    def test_a_blocked_move_records_nothing(self):
        # enter_requires 拦下时人还在原地，上一幕没有断。**不能拿 facts 非空
        # 当判据**：被拦时 _move 同样返回一句话
        sess = self._sess()
        rpg_turn.move_by_name(sess, self.locations, [], "禁地")
        self.assertEqual(sess.location, "织云阁")
        self.assertFalse(sess.scene_break_from)

    def test_moving_to_where_you_already_are_records_nothing(self):
        sess = self._sess()
        rpg_turn.move_by_name(sess, self.locations, [], "织云阁")
        self.assertFalse(sess.scene_break_from)

    def test_a_session_that_never_landed_anywhere_records_nothing(self):
        # 开局还没落地时没有「上一幕在哪」，编不出来就别编
        sess = self._sess(location="")
        rpg_turn.move_by_name(sess, self.locations, [], "主殿")
        self.assertEqual(sess.location, "主殿")
        self.assertFalse(sess.scene_break_from)

    def test_the_break_marker_is_snapshotted(self):
        # 它随回合自己变（瞬移时写、下一轮清），所以必须进快照表：漏了不报错，
        # 只会在读档回到瞬移之前时，下一轮 prompt 里还挂着一句「你离开过那儿」
        self.assertIn("scene_break_from", SNAPSHOT_FIELDS)
        self.assertEqual(SNAPSHOT_DEFAULTS["scene_break_from"], "")
