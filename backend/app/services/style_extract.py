"""文风库导入的确定性部分：解码、切章、抽样、统计、按类别粗筛。

不调模型。几百万字的书不可能整本喂进去，这里只负责挑出一小撮有代表性的
原文交给模型打标签；能用代码算准的统计（句长、对话占比……）也在这里算，
不让模型去估。

按类别提取另走一路：随机抽样覆盖不到「打斗」这种局部内容，所以全书每一块都切出来，
按类别的特征词打分，挑出候选块再交给模型摘原句。
"""
import random
import re

from app.services.relevance_selector import APPEARANCE_KEYWORDS

_CHAPTER_RE = re.compile(
    r"^[ \t　]*第[零〇一二两三四五六七八九十百千万\d]+[章回节][^\n]{0,30}$", re.M
)
# 没有「第X章」的书按这个字数切伪章节，抽样照样能铺满全书
_FALLBACK_CHAPTER_CHARS = 5000

# 抽样：全书均分成这么多份、每份抽一章；每章最多取这么多块
_SAMPLE_BUCKETS = 12
_CHUNKS_PER_CHAPTER = 4
# 一块 = 连续几个自然段拼起来。网文一行一段、一段常常只有二三十字，
# 单段太碎，看不出节奏
_CHUNK_MIN = 120
_CHUNK_MAX = 900

_QUOTE_RE = re.compile(r"[“「『\"][^”」』\"]*[”」』\"]")
_SENTENCE_END_RE = re.compile(r"[。！？!?…]+[”」』\"]?")

# 「对话」不靠特征词，按引号占比判
DIALOGUE = "对话"
PRESET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "外貌描写": tuple(APPEARANCE_KEYWORDS),
    "打斗": ("拳", "掌", "剑", "刀", "砍", "劈", "刺", "斩", "挡", "闪身", "躲", "击",
             "踢", "轰", "攻", "杀", "血", "招式", "震", "退后"),
    "环境描写": ("天空", "云", "风", "雨", "雪", "山", "树", "林", "月", "阳光", "夜色",
                 "街", "巷", "窗", "河", "湖", "石", "草", "雾", "远处", "四周"),
    "心理描写": ("心中", "心里", "暗道", "暗想", "想到", "想着", "念头", "犹豫", "不禁",
                 "忍不住", "心头", "害怕", "担心", "后悔", "疑惑", "意识到", "不知道"),
    "日常": ("吃", "饭", "茶", "睡", "洗", "买", "聊", "早上", "晚上", "家里", "屋里",
             "桌", "碗", "菜", "厨房"),
}
PRESET_CATEGORIES = (DIALOGUE, *PRESET_KEYWORDS)

_CANDIDATES_PER_CATEGORY = 12
# 同章最多两块：全挤在一章里，模型看到的就只有一种写法
_CANDIDATES_PER_CHAPTER = 2


def decode_text(raw: bytes) -> str:
    """网上下的 txt 大半是 GBK。gb18030 是 GBK 的超集，一个就够兜住。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_chapters(text: str) -> list[str]:
    """按「第X章/回/节」切。标题行本身丢掉，第一章之前的序言/简介也丢掉。

    切出来不到两章就当作没有章节标记，按字数在段落边界上切。
    """
    heads = list(_CHAPTER_RE.finditer(text))
    if len(heads) >= 2:
        chapters = []
        for i, m in enumerate(heads):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = text[m.end():end].strip()
            if body:
                chapters.append(body)
        return chapters

    chapters, buf, size = [], [], 0
    for para in _paragraphs(text):
        buf.append(para)
        size += len(para)
        if size >= _FALLBACK_CHAPTER_CHARS:
            chapters.append("\n".join(buf))
            buf, size = [], 0
    if buf:
        chapters.append("\n".join(buf))
    return chapters


def _paragraphs(text: str) -> list[str]:
    return [line.strip(" \t　") for line in text.split("\n") if line.strip(" \t　")]


def _chunks(chapter: str) -> list[str]:
    """把一章的自然段按顺序拼成 _CHUNK_MIN~_CHUNK_MAX 字的块。

    单段就超过上限的（大段描写）不拆，直接丢——拆开会把一段话切在句子中间。
    """
    out, buf, size = [], [], 0
    for para in _paragraphs(chapter):
        if len(para) > _CHUNK_MAX or size + len(para) > _CHUNK_MAX:
            if size >= _CHUNK_MIN:
                out.append("\n".join(buf))
            buf, size = [], 0
            if len(para) > _CHUNK_MAX:
                continue
        buf.append(para)
        size += len(para)
    if size >= _CHUNK_MIN:
        out.append("\n".join(buf))
    return out


def sample_chunks(chapters: list[str], seed: int | None = None) -> list[str]:
    """全书均分 _SAMPLE_BUCKETS 份、每份随机抽一章，每章在块里等距取几块。

    均分而不是只抽开头：网文前几章和中后期的写法常常不是一个样子。
    """
    rng = random.Random(seed)
    n = len(chapters)
    if n == 0:
        return []
    buckets = min(_SAMPLE_BUCKETS, n)
    picked = []
    for b in range(buckets):
        lo, hi = b * n // buckets, (b + 1) * n // buckets
        picked.append(chapters[rng.randrange(lo, hi)])

    out, seen = [], set()
    for chapter in picked:
        chunks = _chunks(chapter)
        if len(chunks) > _CHUNKS_PER_CHAPTER:
            step = len(chunks) / _CHUNKS_PER_CHAPTER
            chunks = [chunks[int(i * step)] for i in range(_CHUNKS_PER_CHAPTER)]
        for c in chunks:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def all_chunks(chapters: list[str]) -> list[tuple[int, str]]:
    """全书每一块，带上所在章号——粗筛要在全书上做，每章限额要用章号。"""
    return [(i, c) for i, chapter in enumerate(chapters) for c in _chunks(chapter)]


def keyword_score(text: str, keywords) -> float:
    """每百字命中几次。按字数归一，不然长块天然命中多，候选全是长块。"""
    total = len(re.sub(r"\s", "", text))
    if not total:
        return 0.0
    return sum(text.count(k) for k in keywords) * 100 / total


def dialogue_score(text: str) -> float:
    total = len(re.sub(r"\s", "", text))
    if not total:
        return 0.0
    return sum(len(m.group()) for m in _QUOTE_RE.finditer(text)) / total


def pick_candidates(
    pool: list[tuple[int, str]],
    score,
    limit: int = _CANDIDATES_PER_CATEGORY,
    per_chapter: int = _CANDIDATES_PER_CHAPTER,
) -> list[str]:
    """按分从高到低取候选块，零分的不要。score: text -> float。"""
    scored = [item for item in ((score(text), i, text) for i, text in pool) if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)  # 稳定排序：同分时靠前的块先取

    out: list[str] = []
    used: dict[int, int] = {}
    seen: set[str] = set()
    for _, chapter, text in scored:
        if len(out) >= limit:
            break
        if used.get(chapter, 0) >= per_chapter or text in seen:
            continue
        used[chapter] = used.get(chapter, 0) + 1
        seen.add(text)
        out.append(text)
    return out


def find_in(excerpt: str, texts: list[str]) -> bool:
    """摘录是不是某块里的连续原文。模型常把换行抹平或重排，比对前空白全去掉；字不许改。"""
    needle = re.sub(r"\s", "", excerpt)
    if not needle:
        return False
    return any(needle in re.sub(r"\s", "", text) for text in texts)


def apply_replacements(text: str, mapping: dict[str, str]) -> str:
    """按键长从长到短替换：「萧炎帝」必须先于「萧炎」换掉，否则会换出半截词。

    一趟换完：换出来的名字不能再被后面的键命中，否则互换（甲→乙、乙→甲）会换回原样。
    空键会往每个字符缝里塞替换文本，得跳过。
    """
    pairs = {key: value for key, value in mapping.items() if key and key != value}
    if not pairs:
        return text
    pattern = re.compile("|".join(re.escape(key) for key in sorted(pairs, key=len, reverse=True)))
    return pattern.sub(lambda m: pairs[m.group()], text)


def compute_stats(chunks: list[str]) -> dict:
    """在抽样块上算，不在全书上算：给模型看的统计要和它看到的原文对得上。

    person 只是粗判：引号外叙述层「我」多于「他/她」就算第一人称。
    """
    text = "\n".join(chunks)
    total = len(re.sub(r"\s", "", text))
    if not total:
        return {"avg_sentence_len": 0, "dialogue_ratio": 0, "avg_para_len": 0, "person": ""}

    quoted = sum(len(m.group()) for m in _QUOTE_RE.finditer(text))
    narration = _QUOTE_RE.sub("", text)
    sentences = [s for s in _SENTENCE_END_RE.split(re.sub(r"\s", "", text)) if s]
    paras = [p for c in chunks for p in _paragraphs(c)]

    first = narration.count("我")
    third = narration.count("他") + narration.count("她")
    return {
        "avg_sentence_len": round(total / max(len(sentences), 1)),
        "dialogue_ratio": round(quoted / total, 2),
        "avg_para_len": round(total / max(len(paras), 1)),
        "person": "第一人称" if first > third else "第三人称",
    }
