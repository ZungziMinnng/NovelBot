import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.chapter import Chapter
from app.models.memory_item import MemoryItem
from app.models.novel import Novel


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _brief_evidence(chapter: Chapter, summary: str = "") -> str:
    text = (summary or chapter.summary or "").strip()
    if text:
        return text[:500]
    content = (chapter.content or "").strip()
    return content[:500]


async def snapshot_character_states(
    session: AsyncSession,
    novel_id: int,
) -> dict[str, dict]:
    result = await session.execute(
        select(Character).where(Character.novel_id == novel_id)
    )
    return {
        character.name: dict(character.current_state or {})
        for character in result.scalars().all()
    }


async def _upsert_memory_item(
    session: AsyncSession,
    *,
    novel_id: int,
    chapter_id: int | None,
    chapter_number: int,
    category: str,
    subject: str,
    field: str,
    value: str,
    old_value: str = "",
    evidence: str = "",
    importance: int = 3,
    due_chapter: int | None = None,
    payload: dict | None = None,
) -> str:
    value = value.strip()
    if not value:
        return "skipped_empty"

    result = await session.execute(
        select(MemoryItem)
        .where(
            MemoryItem.novel_id == novel_id,
            MemoryItem.category == category,
            MemoryItem.subject == subject,
            MemoryItem.field == field,
            MemoryItem.status == "active",
        )
        .order_by(MemoryItem.id.desc())
    )
    active_items = result.scalars().all()
    latest_active = active_items[0] if active_items else None

    if latest_active and latest_active.value == value:
        latest_active.chapter_id = chapter_id
        latest_active.chapter_number = chapter_number
        latest_active.evidence = evidence or latest_active.evidence
        latest_active.importance = importance
        latest_active.due_chapter = due_chapter
        if payload is not None:
            latest_active.payload = payload
        return "unchanged"

    for item in active_items:
        item.status = "outdated"

    if latest_active and not old_value:
        old_value = latest_active.value

    session.add(
        MemoryItem(
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            category=category,
            subject=subject,
            field=field,
            value=value,
            old_value=old_value,
            status="active",
            importance=importance,
            due_chapter=due_chapter,
            evidence=evidence,
            payload=payload or {},
        )
    )
    return "created"


async def write_basic_memory_items(
    session: AsyncSession,
    novel: Novel,
    chapter: Chapter,
    *,
    before_character_states: dict[str, dict] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """Write first-pass structured facts after chapter memory projections.

    This intentionally covers only stable, low-ambiguity buckets:
    character_state and timeline. Richer buckets such as open_loop and
    reader_promise should be extracted by a dedicated prompt later.
    """
    evidence = _brief_evidence(chapter, summary)
    stats: dict[str, Any] = {
        "character_state": {"created": 0, "unchanged": 0, "skipped_empty": 0},
        "timeline": {"created": 0, "unchanged": 0, "skipped_empty": 0},
    }

    timeline_value = (summary or chapter.summary or "").strip()
    if timeline_value:
        action = await _upsert_memory_item(
            session,
            novel_id=novel.id,
            chapter_id=chapter.id,
            chapter_number=chapter.number,
            category="timeline",
            subject=f"第{chapter.number}章",
            field="summary",
            value=timeline_value,
            evidence=evidence,
            payload={"volume": chapter.volume, "title": chapter.title},
        )
        stats["timeline"][action] = stats["timeline"].get(action, 0) + 1

    before_character_states = before_character_states or {}
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    for character in characters:
        before = before_character_states.get(character.name, {}) or {}
        current = character.current_state or {}
        if not isinstance(current, dict):
            continue
        for field, raw_value in current.items():
            value = _stringify_value(raw_value)
            old_value = _stringify_value(before.get(field))
            if old_value == value:
                continue
            action = await _upsert_memory_item(
                session,
                novel_id=novel.id,
                chapter_id=chapter.id,
                chapter_number=chapter.number,
                category="character_state",
                subject=character.name,
                field=str(field),
                value=value,
                old_value=old_value,
                evidence=evidence,
                payload={"character_id": character.id},
            )
            stats["character_state"][action] = stats["character_state"].get(action, 0) + 1

    return stats
