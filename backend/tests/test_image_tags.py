"""convert() 的两趟循环：第一趟出脏词，拿词表核，核不上的带候选回炉重挑。

不碰真模型、不碰真数据：把 llm_json.call_json 和 get_agent_client 都换成桩，
桩按「第几趟」返回不同的假 tag，检验 convert 会不会把未命中的词二次送审、
以及命中的词按输入顺序原样返回。
"""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import image_tags


class Fake:
    """按调用次数吐不同的 tags，记录每次收到的 prompt。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.prompts = []
        self.n = 0

    async def call_json(self, *, messages, model, api_format, max_tokens):
        self.prompts.append(messages[0]["content"])
        data = self.rounds[self.n]
        self.n += 1
        return {"tags": data}, 0, 0


def run(coro):
    return asyncio.run(coro)


class TestConvert(unittest.TestCase):
    def setUp(self):
        # 这两个桩必须**还原**，不能直接赋值。llm_client / llm_json 是进程级单例，
        # 而 image_tags.llm_json 和 rpg_wizard.llm_json 拿到的是同一个模块对象，
        # 直接赋值等于全局改一次、之后所有测试都吃这个桩。症状很绕：本文件排在最前
        # 面，跑完才轮到后面两个，于是 test_model_resolution 和 test_rpg_wizard
        # 单独跑全绿、一起跑挂 11 个，报错栈还指向生产代码 rpg_wizard.py
        patcher = patch.object(
            image_tags.llm_client, "get_agent_client", lambda *a, **k: ("m", "openai")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _patch(self, fake):
        patcher = patch.object(image_tags.llm_json, "call_json", fake.call_json)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_source_short_circuits(self):
        # 空串不该调模型
        called = Fake([])
        self._patch(called)
        hits, unknown = run(image_tags.convert("  "))
        self.assertEqual((hits, unknown), ([], []))
        self.assertEqual(called.n, 0)

    def test_all_hits_stops_after_one_round(self):
        # 第一趟全命中就不该有第二趟
        fake = Fake([["1girl", "long_hair"]])
        self._patch(fake)
        hits, unknown = run(image_tags.convert("一个长发女孩"))
        self.assertEqual(unknown, [])
        self.assertIn("1girl", hits)
        self.assertEqual(fake.n, 1)

    def test_unknown_word_gets_a_second_round_with_candidates(self):
        # 第一趟吐个真词表里没有的，第二趟换成真词 → 该走两趟且最终干净
        fake = Fake([["1girl", "totally_fake_xyz"], ["1girl", "cross-section"]])
        self._patch(fake)
        hits, unknown = run(image_tags.convert("子宫透视图"))
        self.assertEqual(fake.n, 2)
        self.assertEqual(unknown, [])
        self.assertIn("cross-section", hits)
        # 第二趟的 prompt 必须带上第一趟没命中的词，否则模型没法重挑
        self.assertIn("totally_fake_xyz", fake.prompts[1])

    def test_still_unknown_after_max_rounds_is_returned_not_dropped(self):
        # 两趟都命不中：原样词交回上层，绝不偷偷扔
        fake = Fake([["totally_fake_xyz"], ["still_fake_abc"]])
        self._patch(fake)
        hits, unknown = run(image_tags.convert("无法表达的东西"))
        self.assertEqual(fake.n, image_tags._MAX_ROUNDS)
        self.assertIn("still_fake_abc", unknown)


if __name__ == "__main__":
    unittest.main()
