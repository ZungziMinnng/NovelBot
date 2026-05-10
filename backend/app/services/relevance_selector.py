from dataclasses import dataclass
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


async def rag_hits_by_type(
    novel_id: int,
    query: str,
    doc_type: str,
    top_k: int,
) -> list[dict]:
    if top_k <= 0:
        return []
    return await vector_store.asearch_similar_with_meta(
        novel_id,
        query,
        top_k=top_k,
        where={"type": {"$eq": doc_type}},
    )


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
) -> SelectionResult:
    items = list(all_items)
    if not items:
        return SelectionResult([], "empty")

    effective_text = match_text or query
    name_matched = [
        item for item in items
        if (name := name_getter(item)) and name in effective_text
    ]

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
