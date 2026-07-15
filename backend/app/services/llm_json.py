"""统一的「LLM 输出 JSON」修复与调用工具。

repair_json: 修复 LLM 常见的 JSON 格式问题（markdown 栅栏、注释、尾逗号、
裸换行、截断），支持顶层对象与顶层数组两种形态。

call_json: 按温度序列调用 LLM 并解析 JSON，任一轮成功即返回；
全部失败抛 JsonCallError（携带累计 token 供调用方计数）。
失败后怎么办（返回空列表 / 报 HTTP 错误 / 记 warning）由各调用方自行决定。
"""
import json
import logging
import re
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class JsonCallError(ValueError):
    """call_json 全部尝试失败。input_tokens/output_tokens 为已消耗的累计量。"""

    def __init__(self, message: str, *, input_tokens: int = 0, output_tokens: int = 0, raw: str = ""):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.raw = raw


def repair_json(raw: str, expect: str = "object") -> str:
    """尝试修复 LLM 常见的 JSON 格式问题。

    expect="object" 提取最外层 {...}；expect="array" 提取最外层 [...]。
    """
    text = raw.strip()
    # 去除 markdown 代码块包裹
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text.strip())
    # 提取最外层 { ... } 或 [ ... ]
    open_ch, close_ch = ("[", "]") if expect == "array" else ("{", "}")
    start = text.find(open_ch)
    end = text.rfind(close_ch) + 1
    if start == -1:
        return text
    if end <= start:
        # 有开括号但无闭括号（输出被截断），保留尾部让后面的补齐逻辑闭合
        text = text[start:]
    else:
        text = text[start:end]
    # 去除行尾 // 注释
    text = re.sub(r'//[^\n]*', '', text)
    # 去除尾部逗号: ,} 或 ,]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # 修复字符串值内的裸换行符（JSON 标准不允许字符串里有未转义换行）
    # 逐字符扫描：在引号内部时将 \n \r \t 替换为转义形式
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string and i + 1 < len(text):
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
        i += 1
    text = ''.join(result)
    # 修复未闭合的字符串（LLM 截断导致引号不配对）
    unescaped_quotes = re.findall(r'(?<!\\)"', text)
    if len(unescaped_quotes) % 2 != 0:
        text += '"'
    # 截断修复：如果 JSON 未闭合，补齐缺失的闭合符号
    open_brackets = text.count('[') - text.count(']')
    open_braces = text.count('{') - text.count('}')
    if expect == "array":
        if open_braces > 0:
            text += '}' * open_braces
        if open_brackets > 0:
            text += ']' * open_brackets
    else:
        if open_brackets > 0:
            text += ']' * open_brackets
        if open_braces > 0:
            text += '}' * open_braces
    return text


async def call_json(
    messages: list[dict],
    model: str,
    api_format: str,
    *,
    temperatures: tuple[float, ...] = (0.3, 0.1),
    max_tokens: int = 2000,
    expect: str = "object",
    dispatch: Callable[..., Awaitable[tuple[str, int, int]]] | None = None,
) -> tuple[Any, int, int]:
    """按温度序列重试调用 LLM 并解析 JSON。

    每轮：调用 → repair_json → json.loads → 校验顶层类型（object=dict / array=list）；
    任一环失败（含 LLM 调用异常）换下一档温度重试。
    返回 (parsed, 累计input_tokens, 累计output_tokens)；全败抛 JsonCallError。
    """
    if dispatch is None:
        from app.services import llm_client
        dispatch = llm_client.dispatch_chat_complete_with_usage

    expected_type = list if expect == "array" else dict
    total_in, total_out = 0, 0
    last_raw = ""
    last_error: Exception | None = None
    for temperature in temperatures:
        try:
            raw, in_tok, out_tok = await dispatch(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            total_in += in_tok
            total_out += out_tok
            last_raw = raw
            parsed = json.loads(repair_json(raw, expect))
            if isinstance(parsed, expected_type):
                return parsed, total_in, total_out
            last_error = ValueError(f"顶层类型不是 {expect}")
        except Exception as e:
            last_error = e
            logger.warning("call_json 尝试失败 (temp=%s): %s", temperature, e)
    raise JsonCallError(
        f"LLM JSON 调用失败（已重试 {len(temperatures)} 次）: {last_error}",
        input_tokens=total_in,
        output_tokens=total_out,
        raw=last_raw[:500],
    ) from last_error
