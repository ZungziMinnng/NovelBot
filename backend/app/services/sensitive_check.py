"""投稿过审预检：在稿件里找可能触发平台审核的词。

刻意做成手动触发、默认全关：这个项目也用来写 NSFW 内容，检查绝不能挂到生成链路上
去拦正文或改提示词。它只读章节、只报位置，不修改任何数据。
"""
import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_BASELINE_PATH = Path(__file__).resolve().parents[1] / "data" / "sensitive_words.json"
_CONTEXT_PAD = 12
_MAX_HITS_PER_WORD = 20


@lru_cache(maxsize=1)
def load_baseline() -> dict[str, dict]:
    """读基线词库。文件损坏时返回空表并告警——预检不该拖垮别的功能。"""
    try:
        raw = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
        return raw.get("categories", {})
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("基线敏感词库读取失败，预检将只用自定义词: %s", e)
        return {}


def category_meta() -> list[dict]:
    """给前端渲染类别开关用。"""
    return [
        {"key": key, "label": val.get("label", key), "hint": val.get("hint", ""),
         "word_count": len(val.get("words", []))}
        for key, val in load_baseline().items()
    ]


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(0, start - _CONTEXT_PAD)
    prefix = "…" if left > 0 else ""
    suffix = "…" if end + _CONTEXT_PAD < len(text) else ""
    return f"{prefix}{text[left:end + _CONTEXT_PAD]}{suffix}".replace("\n", " ")


def build_wordlist(categories: list[str], custom_words: list[str]) -> list[tuple[str, str]]:
    """按勾选的类别拼出 (词, 类别) 列表。自定义词恒定参与，类别记为 custom。"""
    baseline = load_baseline()
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in categories:
        for word in baseline.get(key, {}).get("words", []):
            if word and word not in seen:
                seen.add(word)
                pairs.append((word, key))
    for word in custom_words:
        word = word.strip()
        if word and word not in seen:
            seen.add(word)
            pairs.append((word, "custom"))
    return pairs


def scan_text(text: str, wordlist: list[tuple[str, str]]) -> list[dict]:
    """在单章正文里找命中。纯字符串查找，不做分词——网文里生造词多，分词反而漏。"""
    hits: list[dict] = []
    for word, category in wordlist:
        start = text.find(word)
        count = 0
        while start != -1 and count < _MAX_HITS_PER_WORD:
            hits.append({
                "word": word,
                "category": category,
                "position": start,
                "excerpt": _excerpt(text, start, start + len(word)),
            })
            count += 1
            start = text.find(word, start + len(word))
    return hits
