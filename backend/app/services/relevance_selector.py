import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import Chapter
from app.services import vector_store
from app.services.summarizer import strip_plot_suggestions


@dataclass
class SelectionResult:
    items: list[Any]
    source: str


def cfg_top_k(cfg: dict, key: str, default: int) -> int:
    try:
        return max(0, int(cfg.get(key, default)))
    except (TypeError, ValueError):
        return default


# 多召回倍数：先取 top_k*OVERFETCH 候选再按重要性重排，让"重要但不太相似"的也有机会入选
OVERFETCH = 4


def recency_factor(source_chapter, current_chapter) -> float:
    """时间衰减因子：越近的章节越接近 1.0，久远章节渐降到 0.7 封底。
    设 0.7 下限是为了不把高重要度的早期伏笔彻底压没。缺章节信息时不衰减。"""
    try:
        dist = int(current_chapter) - int(source_chapter)
    except (TypeError, ValueError):
        return 1.0
    if dist <= 0:
        return 1.0
    return 0.7 + 0.3 / (1.0 + dist / 100.0)


def rerank_by_importance(hits: list[dict], top_k: int, current_chapter: int | None = None) -> list[dict]:
    """按 相似度×重要性（×时间衰减）重排并截断。distance 越小越相似，importance 缺省按 3（中性）。
    传入 current_chapter 时对历史章节命中做温和的时间衰减。"""
    def score(hit: dict) -> float:
        meta = hit.get("metadata") or {}
        imp = meta.get("importance")
        try:
            imp = float(imp)
        except (TypeError, ValueError):
            imp = 3.0
        similarity = max(0.0, 1.0 - float(hit.get("distance", 1.0)))
        base = similarity * (imp or 3.0)
        if current_chapter is not None:
            base *= recency_factor(meta.get("chapter_number"), current_chapter)
        return base

    return sorted(hits, key=score, reverse=True)[:top_k]


def diversify_historical_hits(
    hits: list[dict],
    top_k: int,
    *,
    bucket_size: int = 5,
    max_per_bucket: int = 2,
) -> list[dict]:
    """Avoid filling historical context with adjacent chapters from one short period."""
    selected: list[dict] = []
    deferred: list[dict] = []
    bucket_counts: dict[int, int] = {}
    for hit in hits:
        chapter = (hit.get("metadata") or {}).get("chapter_number")
        try:
            bucket = max(0, (int(chapter) - 1) // bucket_size)
        except (TypeError, ValueError):
            bucket = -1
        if bucket_counts.get(bucket, 0) >= max_per_bucket:
            deferred.append(hit)
            continue
        selected.append(hit)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if len(selected) >= top_k:
            return selected
    if len(selected) < top_k:
        selected.extend(deferred[:top_k - len(selected)])
    return selected


_CJK_RUN = re.compile(r"[一-鿿]{4,}")
_KEYWORD_GRAM = 4
# 一个 gram 命中的摘要占比超过该值即视为高频词（主角名、口头禅等），不作为证据
_KEYWORD_DF_RATIO = 0.2


def keyword_hits(query_text: str, summaries: list[dict], top_k: int = 3) -> list[dict]:
    """中文 4 字滑窗精确匹配的补充检索。

    向量检索会把「月华顿悟」这类独特短语稀释在整段查询里，导致含它的老章节
    捞不回来；这里对查询文本与历史摘要做 4-gram 精确交集，命中即补进上下文。
    出现在过多摘要里的 gram（主角名等）按文档频率剔除，避免全书都算命中。
    summaries 元素需含 chapter_number / content。按命中 gram 数降序、章节号降序取 top_k。
    """
    if top_k <= 0 or not query_text or not summaries:
        return []
    grams = {
        run[i:i + _KEYWORD_GRAM]
        for run in _CJK_RUN.findall(query_text)
        for i in range(len(run) - _KEYWORD_GRAM + 1)
    }
    if not grams:
        return []

    matched: list[tuple[dict, set[str]]] = []
    df: Counter = Counter()
    for s in summaries:
        content = s.get("content") or ""
        hit_grams = {g for g in grams if g in content}
        if hit_grams:
            matched.append((s, hit_grams))
            df.update(hit_grams)
    if not matched:
        return []

    df_limit = max(3, len(summaries) * _KEYWORD_DF_RATIO)
    scored = []
    for s, hit_grams in matched:
        distinct = sum(1 for g in hit_grams if df[g] <= df_limit)
        if distinct:
            scored.append((distinct, s.get("chapter_number") or 0, s))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [s for _, _, s in scored[:top_k]]


async def rag_hits_by_type(
    novel_id: int,
    query: str,
    doc_type: str,
    top_k: int,
    query_embedding: list | None = None,
) -> list[dict]:
    if top_k <= 0:
        return []
    hits = await vector_store.asearch_similar_with_meta(
        novel_id,
        query,
        top_k=top_k * OVERFETCH,
        where={"type": {"$eq": doc_type}},
        query_embedding=query_embedding,
    )
    return rerank_by_importance(hits, top_k)


# 唯一片段匹配：实体名的连续片段长度范围。上限 4 配合全名精确匹配已覆盖常见缩写；
# 下限 2 才能救「戒尺」这类两字缩写，歧义靠"同批实体中唯一"过滤兜底
_FRAGMENT_MIN = 2
_FRAGMENT_MAX = 4
_AMBIGUOUS = object()


@lru_cache(maxsize=2)
def _text_grams(text: str) -> frozenset:
    """匹配文本的全部 2-4 字滑窗集合。同一次上下文构建中八路选取共用同一文本，缓存复用。"""
    grams = set()
    for n in range(_FRAGMENT_MIN, _FRAGMENT_MAX + 1):
        for i in range(len(text) - n + 1):
            grams.add(text[i:i + n])
    return frozenset(grams)


def unique_fragment_matches(
    items: list[Any],
    text: str,
    name_getter: Callable[[Any], str | None],
) -> list[Any]:
    """局部名称匹配：用户输入常用缩写（「极阴寒玉戒尺」写成「戒尺」），全名字面
    包含匹配不到。这里改为：名字的某个 2-4 字连续片段出现在文本、且该片段在
    同批实体中只属于它一个（「法则」属于十三条法则 → 歧义，不触发），即视为命中。
    误匹配的代价只是多注入一张实体卡，歧义片段则自动退回原有的 RAG 兜底路径。"""
    if not items or not text:
        return []
    owners: dict[str, Any] = {}
    for item in items:
        name = (name_getter(item) or "").strip()
        if len(name) < _FRAGMENT_MIN:
            continue
        seen: set[str] = set()
        for n in range(_FRAGMENT_MIN, min(len(name), _FRAGMENT_MAX) + 1):
            for i in range(len(name) - n + 1):
                frag = name[i:i + n]
                if frag in seen:
                    continue
                seen.add(frag)
                cur = owners.get(frag)
                if cur is None:
                    owners[frag] = item
                elif cur is not item:
                    owners[frag] = _AMBIGUOUS
    grams = _text_grams(text)
    hit_ids = {
        id(owner)
        for frag, owner in owners.items()
        if owner is not _AMBIGUOUS and frag in grams
    }
    return [item for item in items if id(item) in hit_ids]


def select_by_name_then_rag(
    all_items: Iterable[Any],
    hits: list[dict],
    query: str,
    *,
    name_getter: Callable[[Any], str | None] = lambda item: getattr(item, "name", None),
    id_getter: Callable[[Any], Any] = lambda item: getattr(item, "id", None),
    metadata_id_key: str = "entity_id",
    extra: list[Any] | None = None,
    match_text: str = "",
    allow_full: bool = True,
    fallback_limit: int = 0,
) -> SelectionResult:
    items = list(all_items)
    if not items:
        return SelectionResult([], "empty")

    effective_text = match_text or query
    name_matched = [
        item for item in items
        if (name := name_getter(item)) and name in effective_text
    ]
    matched_ids = {id(x) for x in name_matched}
    name_matched.extend(
        item for item in unique_fragment_matches(items, effective_text, name_getter)
        if id(item) not in matched_ids
    )

    if extra:
        seen = {id(x) for x in name_matched}
        name_matched.extend(x for x in extra if id(x) not in seen)

    if name_matched:
        return SelectionResult(name_matched, "name")

    hit_ids = {
        (hit.get("metadata") or {}).get(metadata_id_key)
        for hit in hits
        if (hit.get("metadata") or {}).get(metadata_id_key) is not None
    }
    if hit_ids:
        rag_matched = [item for item in items if id_getter(item) in hit_ids]
        if rag_matched:
            return SelectionResult(rag_matched, "rag")

    if allow_full:
        # 全量回退是"检索全落空"的兜底，百万字规模下实体成百上千，
        # 必须限量，否则一次兜底就塞满 prompt
        if fallback_limit > 0:
            return SelectionResult(items[:fallback_limit], "full")
        return SelectionResult(items, "full")
    return SelectionResult([], "rag")


def select_notes_by_title_then_rag(
    all_notes: Iterable[Any],
    hits: list[dict],
    query: str,
    *,
    match_text: str = "",
    allow_full: bool = True,
) -> SelectionResult:
    notes = list(all_notes)
    if not notes:
        return SelectionResult([], "empty")

    effective_text = match_text or query
    title_matched = [note for note in notes if getattr(note, "title", None) and note.title in effective_text]
    matched_ids = {id(x) for x in title_matched}
    title_matched.extend(
        note for note in unique_fragment_matches(notes, effective_text, lambda n: getattr(n, "title", None))
        if id(note) not in matched_ids
    )
    if title_matched:
        return SelectionResult(title_matched, "name")

    hit_ids = {
        (hit.get("metadata") or {}).get("note_id")
        for hit in hits
        if (hit.get("metadata") or {}).get("note_id") is not None
    }
    if hit_ids:
        rag_matched = [note for note in notes if note.id in hit_ids]
        if rag_matched:
            return SelectionResult(rag_matched, "rag")

    if allow_full:
        return SelectionResult(notes, "full")
    return SelectionResult([], "rag")


APPEARANCE_KEYWORDS = (
    "外貌", "容貌", "面容", "脸", "眼", "眸", "眉", "鼻", "唇", "头发", "发色",
    "发丝", "长发", "短发", "黑发", "白发", "银发", "青丝", "鬓",
    "身形", "身材", "体型", "衣", "袍", "裙", "甲", "装束", "穿着", "气质", "姿态",
)


def extract_character_appearance_snippets(
    content: str,
    character_name: str,
    *,
    max_snippets: int = 2,
    window: int = 220,
    require_keyword: bool = False,
) -> list[str]:
    clean = strip_plot_suggestions(content or "")
    if not clean or character_name not in clean:
        return []

    positions: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = clean.find(character_name, start)
        if idx < 0:
            break
        left = max(0, idx - window)
        right = min(len(clean), idx + len(character_name) + window)
        snippet = clean[left:right]
        score = sum(1 for kw in APPEARANCE_KEYWORDS if kw in snippet)
        positions.append((score, idx))
        start = idx + len(character_name)

    positions.sort(key=lambda pair: (-pair[0], pair[1]))
    snippets: list[str] = []
    used_ranges: list[tuple[int, int]] = []
    for score, idx in positions:
        if require_keyword and score <= 0:
            continue
        left = max(0, idx - window)
        right = min(len(clean), idx + len(character_name) + window)
        if any(not (right < a or left > b) for a, b in used_ranges):
            continue
        prefix = "..." if left > 0 else ""
        suffix = "..." if right < len(clean) else ""
        snippets.append(prefix + clean[left:right].strip() + suffix)
        used_ranges.append((left, right))
        if len(snippets) >= max_snippets:
            break
    return snippets


async def select_character_appearance_context(
    session: AsyncSession,
    novel_id: int,
    character_name: str,
    *,
    query: str = "",
    top_k: int = 8,
    max_chapters: int = 8,
) -> SelectionResult:
    if not character_name.strip():
        return SelectionResult([], "empty")

    exact_result = await session.execute(
        select(Chapter)
        .where(
            Chapter.novel_id == novel_id,
            Chapter.content.contains(character_name),
            Chapter.content != "",
        )
        .order_by(Chapter.volume.desc(), Chapter.number.desc())
        .limit(max_chapters)
    )
    exact_chapters = list(reversed(exact_result.scalars().all()))
    exact_name_snippets: list[str] = []
    if exact_chapters:
        exact_snippets = _chapters_to_snippets(
            exact_chapters,
            character_name,
            require_keyword=True,
        )
        if exact_snippets:
            return SelectionResult(exact_snippets, "name")
        exact_name_snippets = _chapters_to_snippets(exact_chapters, character_name)

    if top_k <= 0:
        if exact_name_snippets:
            return SelectionResult(exact_name_snippets, "name")
        return SelectionResult([], "empty")

    hits = await vector_store.asearch_similar_with_meta(
        novel_id,
        query or f"{character_name} 外貌 容貌 衣着 身形 气质",
        top_k=top_k,
        where={"type": {"$eq": "chapter_summary"}},
    )
    hit_refs: list[tuple[int | None, int]] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        chapter_number = meta.get("chapter_number")
        if chapter_number is None:
            continue
        try:
            number = int(chapter_number)
        except (TypeError, ValueError):
            continue
        volume = meta.get("volume")
        try:
            volume_number = int(volume) if volume is not None else None
        except (TypeError, ValueError):
            volume_number = None
        ref = (volume_number, number)
        if ref not in hit_refs:
            hit_refs.append(ref)

    if not hit_refs:
        if exact_name_snippets:
            return SelectionResult(exact_name_snippets, "name")
        return SelectionResult([], "empty")

    chapter_filters = [
        and_(Chapter.volume == volume, Chapter.number == number)
        if volume is not None else Chapter.number == number
        for volume, number in hit_refs
    ]
    chapter_result = await session.execute(
        select(Chapter)
        .where(
            Chapter.novel_id == novel_id,
            or_(*chapter_filters),
            Chapter.content != "",
        )
        .order_by(Chapter.volume.asc(), Chapter.number.asc())
    )
    chapters = chapter_result.scalars().all()
    snippets = _chapters_to_snippets(chapters, character_name, require_keyword=True)
    if snippets:
        return SelectionResult(snippets, "rag")
    name_snippets = _chapters_to_snippets(chapters, character_name)
    if name_snippets:
        return SelectionResult(name_snippets, "rag")

    fallback = [
        f"{_chapter_label(chapter)}《{chapter.title or ''}》摘要相关，但正文未直接提及角色名："
        f"{strip_plot_suggestions(chapter.content or '')[:500]}"
        for chapter in chapters[:max_chapters]
    ]
    if not fallback and exact_name_snippets:
        return SelectionResult(exact_name_snippets, "name")
    return SelectionResult(fallback, "rag")


def _chapters_to_snippets(
    chapters: Iterable[Chapter],
    character_name: str,
    *,
    require_keyword: bool = False,
) -> list[str]:
    snippets: list[str] = []
    for chapter in chapters:
        chapter_snippets = extract_character_appearance_snippets(
            chapter.content or "",
            character_name,
            require_keyword=require_keyword,
        )
        for snippet in chapter_snippets:
            snippets.append(f"{_chapter_label(chapter)}《{chapter.title or ''}》：{snippet}")
    return snippets


def _chapter_label(chapter: Chapter) -> str:
    if chapter.volume:
        return f"第{chapter.volume}卷第{chapter.number}章"
    return f"第{chapter.number}章"
