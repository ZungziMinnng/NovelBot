import unittest
from types import SimpleNamespace

from app.models.rpg import RpgMessage
from app.services import rpg_vectors
from app.services.rpg_memory import event_memory, text_revision


def _settled(mid: int, content: str, facts: list[dict], present=None) -> RpgMessage:
    return RpgMessage(
        id=mid, role="assistant", content=content, present=present,
        settlement={"status": "done", "revision": text_revision(content), "facts": facts},
    )


class VectorArmTests(unittest.TestCase):
    """向量那一路接进 event_memory 的两条硬约束。

    这两条错了，后果一个比一个难查：闸门漏了是把私密事实讲给不该知道的人，
    而这种错要等玩家看见「她怎么知道的」才会暴露；豁免没做则是这条路白接——
    向量要补的短板正好是词面对不上的那些。
    """

    def test_a_vector_hit_cannot_bypass_the_witness_gate(self):
        """向量命中一条她不该知道的事实，照样不许出现在回忆块里。

        闸门只有候选池那一处：向量回来的只是一串 key，认领不到就自然消失。
        """
        content = "药园失火那晚只有她看见了纵火的人。"
        row = _settled(11, content, [{
            "kind": "promise", "quote": content, "witnesses": [3], "visibility": "witnessed",
        }], present=[3, 5])
        # key 就是 quote（见 rpg_vectors._docs），照最理想的情况喂给它
        self.assertEqual(
            event_memory([row], {5}, "完全不沾边的问题", vector_keys=[content]), "",
        )
        self.assertIn(
            "药园失火", event_memory([row], {3}, "完全不沾边的问题", vector_keys=[content]),
        )

    def test_a_vector_hit_cannot_bypass_the_presence_roster(self):
        row = RpgMessage(id=7, role="assistant", content="药园失火那晚我们都在场。",
                         present=[7])
        self.assertEqual(
            event_memory([row], {9}, "毫不相干", vector_keys=["msg:7"]), "",
        )
        self.assertIn(
            "药园失火", event_memory([row], {7}, "毫不相干", vector_keys=["msg:7"]),
        )

    def test_a_vector_hit_exempts_an_excerpt_from_the_keyword_floor(self):
        """词面一个字都对不上时，只有向量这条路能把它捞回来。

        这正是接向量的全部理由：换了称呼、换了说法的旧事，字面永远匹配不到。
        """
        row = RpgMessage(id=3, role="assistant", content="那一夜，苗圃被人点了。")
        query = "药园失火是谁干的"
        self.assertEqual(event_memory([row], set(), query), "")
        self.assertIn("#3", event_memory([row], set(), query, vector_keys=["msg:3"]))

    def test_an_unclaimed_key_changes_nothing(self):
        """向量库里留着的旧 doc（消息删了、事实改稿作废了）认领不到，静默消失。"""
        row = RpgMessage(id=3, role="assistant", content="药园失火是有人投毒。")
        plain = event_memory([row], set(), "回忆药园失火")
        self.assertEqual(
            event_memory([row], set(), "回忆药园失火",
                         vector_keys=["msg:999", "早就不存在的引文"]),
            plain,
        )

    def test_no_vector_keys_is_byte_identical_to_before(self):
        """没配嵌入模型时 search 返回空列表，这一路必须一个字都不改变结果。"""
        rows = [
            RpgMessage(id=3, role="assistant", content="药园失火是有人投毒。"),
            _settled(5, "园丁甲答应帮你查药草。", [{
                "kind": "promise", "quote": "园丁甲答应帮你查药草。",
                "summary": "园丁甲答应帮忙", "witnesses": [], "visibility": "public",
            }]),
        ]
        query = "还记得药园失火和那个承诺吗"
        self.assertEqual(
            event_memory(rows, set(), query),
            event_memory(rows, set(), query, vector_keys=[]),
        )
        self.assertEqual(
            event_memory(rows, set(), query),
            event_memory(rows, set(), query, vector_keys=None),
        )


class DocShapeTests(unittest.TestCase):
    """嵌进库里的 doc 必须和 event_memory 的候选逐字对齐——key 对不上，
    search 回来的东西就永远认领不到，整条路静默失灵而不报错。"""

    def test_a_settled_message_becomes_one_doc_per_fact(self):
        content = "园丁甲答应帮你查药草，他还提到了药园那把火。"
        row = _settled(5, content, [
            {"quote": "园丁甲答应帮你查药草", "summary": "承诺帮忙"},
            {"quote": "他还提到了药园那把火", "summary": "提到失火"},
            # 引文不在原文里 = 改过稿，event_memory 也是这么丢的
            {"quote": "根本没说过的话", "summary": "幻觉"},
        ])
        docs = rpg_vectors._docs(row)
        self.assertEqual([d[0] for d in docs], ["fact_5_0", "fact_5_1"])
        self.assertEqual([d[2]["key"] for d in docs],
                         ["园丁甲答应帮你查药草", "他还提到了药园那把火"])
        # 文本 = summary + quote，和候选池里的 searchable 一致
        self.assertEqual(docs[0][1], "承诺帮忙园丁甲答应帮你查药草")

    def test_an_unsettled_message_becomes_one_excerpt_doc(self):
        row = RpgMessage(id=3, role="assistant", content="那一夜，苗圃被人点了。")
        self.assertEqual(
            rpg_vectors._docs(row),
            [("msg_3", "那一夜，苗圃被人点了。",
              {"kind": "excerpt", "mid": 3, "key": "msg:3"})],
        )

    def test_an_edited_message_falls_back_to_the_excerpt(self):
        """原文改过稿、revision 对不上：事实全部作废，退回原文候选。
        和 event_memory 里那三道判据是同一套。"""
        row = _settled(5, "旧约定", [{"quote": "旧约定", "summary": "约定"}])
        row.content = "新约定"
        self.assertEqual([d[0] for d in rpg_vectors._docs(row)], ["msg_5"])

    def test_an_empty_message_produces_nothing(self):
        self.assertEqual(rpg_vectors._docs(RpgMessage(id=1, role="user", content="  ")), [])


class PointerTests(unittest.TestCase):
    """指针推到哪。推过头 = 那几条从此搜不到，推不动 = 每轮重嵌一条长尾巴。"""

    def _rows(self, count: int, unsettled_at: int | None = None):
        rows = []
        for index in range(1, count + 1):
            row = RpgMessage(id=index, role="assistant", content="话")
            row.settlement = None if index == unsettled_at else {"status": "done"}
            rows.append(row)
        return rows

    def test_the_pointer_stops_before_an_unsettled_reply(self):
        """结算还没落定的 assistant 行将来会长出事实，越过去它就再也嵌不上。"""
        rows = self._rows(5, unsettled_at=3)
        self.assertEqual([r.id for r in rpg_vectors._up_to_settled(rows)], [1, 2])

    def test_a_user_row_never_stalls_the_pointer(self):
        rows = self._rows(3)
        rows[1].role = "user"
        rows[1].settlement = None
        self.assertEqual([r.id for r in rpg_vectors._up_to_settled(rows)], [1, 2, 3])

    def test_an_old_failed_settlement_stops_stalling(self):
        """一次永久失败的结算不能把指针永远钉在原地——那比漏掉一轮更糟。"""
        rows = self._rows(rpg_vectors.STALL_WINDOW + 10, unsettled_at=2)
        self.assertEqual(len(rpg_vectors._up_to_settled(rows)), len(rows))


class SwitchedOffTests(unittest.IsolatedAsyncioTestCase):
    """空 embedding_model_ref = 整条路关着，一次网络都不发。"""

    def setUp(self):
        self.module = SimpleNamespace(embedding_model_ref="")
        self.sess = SimpleNamespace(id=1, vector_upto_id=0)

    async def test_search_returns_nothing_without_a_model(self):
        self.assertEqual(await rpg_vectors.search(self.sess, self.module, "问点什么", None), [])

    async def test_search_returns_nothing_for_an_empty_query(self):
        self.module.embedding_model_ref = "7"
        self.assertEqual(await rpg_vectors.search(self.sess, self.module, "   ", None), [])

    async def test_forgetting_is_a_no_op_without_a_model(self):
        self.sess.vector_upto_id = 99
        await rpg_vectors.forget_after(self.sess, self.module, 10)
        await rpg_vectors.forget_message(self.sess, self.module, 10)
        self.assertEqual(self.sess.vector_upto_id, 99)

    async def test_rewinding_pulls_the_pointer_back(self):
        self.module.embedding_model_ref = "7"
        self.sess.vector_upto_id = 99
        calls = []

        async def fake_delete(key_id, where, namespace):
            calls.append((key_id, where, namespace))

        original = rpg_vectors.vector_store.adelete_where
        rpg_vectors.vector_store.adelete_where = fake_delete
        try:
            await rpg_vectors.forget_after(self.sess, self.module, 10)
        finally:
            rpg_vectors.vector_store.adelete_where = original
        self.assertEqual(calls, [(1, {"mid": {"$gt": 10}}, "rpg")])
        self.assertEqual(self.sess.vector_upto_id, 10)


if __name__ == "__main__":
    unittest.main()
