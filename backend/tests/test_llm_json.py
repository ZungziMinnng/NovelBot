import asyncio
import json
import unittest

from app.services.llm_json import JsonCallError, call_json, repair_json


class RepairJsonTests(unittest.TestCase):
    def test_plain_object_passthrough(self):
        raw = '{"a": 1}'
        self.assertEqual(json.loads(repair_json(raw)), {"a": 1})

    def test_strips_markdown_fence(self):
        raw = '```json\n{"a": 1}\n```'
        self.assertEqual(json.loads(repair_json(raw)), {"a": 1})

    def test_strips_surrounding_prose(self):
        raw = '好的，以下是结果：\n{"a": 1}\n希望对你有帮助。'
        self.assertEqual(json.loads(repair_json(raw)), {"a": 1})

    def test_removes_line_comments(self):
        raw = '{\n"a": 1 // 注释\n}'
        self.assertEqual(json.loads(repair_json(raw)), {"a": 1})

    def test_removes_trailing_commas(self):
        raw = '{"a": [1, 2,], "b": 3,}'
        self.assertEqual(json.loads(repair_json(raw)), {"a": [1, 2], "b": 3})

    def test_escapes_bare_newlines_in_strings(self):
        raw = '{"a": "第一行\n第二行"}'
        self.assertEqual(json.loads(repair_json(raw)), {"a": "第一行\n第二行"})

    def test_keeps_existing_escapes(self):
        raw = '{"a": "他说：\\"你好\\""}'
        self.assertEqual(json.loads(repair_json(raw)), {"a": '他说："你好"'})

    def test_closes_truncated_object(self):
        raw = '{"a": [1, 2], "b": {"c": 3'
        self.assertEqual(json.loads(repair_json(raw)), {"a": [1, 2], "b": {"c": 3}})

    def test_closes_truncated_string(self):
        raw = '{"a": "被截断的内容'
        parsed = json.loads(repair_json(raw))
        self.assertEqual(parsed, {"a": "被截断的内容"})

    def test_extracts_array_when_expect_array(self):
        raw = '以下是数组：\n[{"chapter": 1, "content": "x"}]\n完毕'
        parsed = json.loads(repair_json(raw, expect="array"))
        self.assertEqual(parsed, [{"chapter": 1, "content": "x"}])

    def test_expect_array_does_not_grab_inner_object(self):
        raw = '```\n[{"a": 1}, {"b": 2}]\n```'
        parsed = json.loads(repair_json(raw, expect="array"))
        self.assertEqual(parsed, [{"a": 1}, {"b": 2}])

    def test_closes_truncated_array(self):
        raw = '[{"chapter": 1, "content": "x"}, {"chapter": 2, "content": "y'
        parsed = json.loads(repair_json(raw, expect="array"))
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[1]["chapter"], 2)


class CallJsonTests(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_first_attempt_success(self):
        async def dispatch(**kwargs):
            return '{"ok": true}', 10, 5

        parsed, in_tok, out_tok = self._run(
            call_json([], "m", "openai", dispatch=dispatch)
        )
        self.assertEqual(parsed, {"ok": True})
        self.assertEqual((in_tok, out_tok), (10, 5))

    def test_retries_on_bad_json_then_succeeds(self):
        calls = []

        async def dispatch(**kwargs):
            calls.append(kwargs["temperature"])
            if len(calls) == 1:
                return "这不是 JSON", 10, 5
            return '{"ok": 1}', 20, 8

        parsed, in_tok, out_tok = self._run(
            call_json([], "m", "openai", temperatures=(0.3, 0.1), dispatch=dispatch)
        )
        self.assertEqual(parsed, {"ok": 1})
        self.assertEqual(calls, [0.3, 0.1])
        self.assertEqual((in_tok, out_tok), (30, 13))

    def test_retries_on_wrong_top_level_type(self):
        calls = []

        async def dispatch(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                return '[1, 2]', 1, 1
            return '{"a": 1}', 1, 1

        parsed, _, _ = self._run(
            call_json([], "m", "openai", dispatch=dispatch)
        )
        self.assertEqual(parsed, {"a": 1})
        self.assertEqual(len(calls), 2)

    def test_retries_on_dispatch_exception(self):
        calls = []

        async def dispatch(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("provider down")
            return '{"a": 1}', 5, 5

        parsed, in_tok, out_tok = self._run(
            call_json([], "m", "openai", dispatch=dispatch)
        )
        self.assertEqual(parsed, {"a": 1})
        self.assertEqual((in_tok, out_tok), (5, 5))

    def test_all_attempts_fail_raises_with_accumulated_tokens(self):
        async def dispatch(**kwargs):
            return "not json", 10, 5

        with self.assertRaises(JsonCallError) as ctx:
            self._run(
                call_json([], "m", "openai", temperatures=(0.3, 0.1), dispatch=dispatch)
            )
        self.assertEqual(ctx.exception.input_tokens, 20)
        self.assertEqual(ctx.exception.output_tokens, 10)
        self.assertIn("not json", ctx.exception.raw)

    def test_expect_array(self):
        async def dispatch(**kwargs):
            return '```json\n[{"a": 1}]\n```', 1, 1

        parsed, _, _ = self._run(
            call_json([], "m", "openai", expect="array", dispatch=dispatch)
        )
        self.assertEqual(parsed, [{"a": 1}])


if __name__ == "__main__":
    unittest.main()
