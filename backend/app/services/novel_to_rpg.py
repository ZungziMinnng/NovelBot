"""把小说的初始设定拼成一段文本，喂给 RPG 构思向导的分步抽取。

只取「开书时的设定」：世界观、规则、地点、势力、功法、角色卡。不取
current_state、章节摘要、时间线、剧情设计和结局——游戏是平行线、全部初始化，
带进去会把原著剧情进度写进开局。
"""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.character import Character
from app.models.faction import Faction
from app.models.location import Location
from app.models.novel import Novel
from app.models.technique import Technique
from app.models.world_entity import WorldEntity
from app.models.world_rule import WorldRule

TOTAL_CHARS = 30000
MAX_CHARACTERS = 30
_SHEET_CHARS = 1200
_ITEM_CHARS = 400
_ROLE_ORDER = {"主角": 0, "反派": 1}


def _clip(value, limit: int) -> str:
    s = str(value or "").strip()
    return s[:limit] + "…" if len(s) > limit else s


def _sheet(value: dict) -> str:
    if not value:
        return ""
    return _clip(json.dumps(value, ensure_ascii=False), _SHEET_CHARS)


def _line(label: str, value) -> str:
    text = _clip(value, _ITEM_CHARS)
    return f"{label}：{text}" if text else ""


async def build_novel_source(db: AsyncSession, novel: Novel) -> tuple[str, list[str]]:
    """返回 (设定文本, 提示). 提示会并进向导的 dropped，让作者知道哪里被截了。"""
    notes: list[str] = []

    async def rows(model, *order):
        result = await db.execute(
            select(model).where(model.novel_id == novel.id).order_by(*order)
        )
        return list(result.scalars())

    rules = [r for r in await rows(WorldRule, WorldRule.importance.desc(), WorldRule.id) if r.enabled]
    entities = await rows(WorldEntity, WorldEntity.importance.desc(), WorldEntity.id)
    places = await rows(Location, Location.importance.desc(), Location.id)
    place_names = {p.id: p.name for p in places}
    factions = await rows(Faction, Faction.importance.desc(), Faction.id)
    techniques = await rows(Technique, Technique.importance.desc(), Technique.id)
    characters = sorted(
        await rows(Character, Character.id),
        key=lambda c: _ROLE_ORDER.get(c.role, 2),
    )
    if len(characters) > MAX_CHARACTERS:
        notes.append(f"小说有 {len(characters)} 个角色，只取了前 {MAX_CHARACTERS} 个（主角、反派优先）")
        characters = characters[:MAX_CHARACTERS]

    sections: list[tuple[str, list[str]]] = [
        ("基本信息", [
            _line("书名", novel.title), _line("题材", novel.genre), _line("简介", novel.premise),
        ]),
        ("世界观", [_clip(novel.core_setting, 6000)]),
        ("世界规则与特殊元素", [
            f"- {r.title or '未命名'}（{'特殊元素' if r.kind == 'element' else '规则'}）：{_clip(r.content, _ITEM_CHARS)}"
            for r in rules
        ]),
        ("物品与体系", [
            f"- {e.name}（{e.type}）：{_clip(e.description, _ITEM_CHARS)}"
            + (f" 功能：{_clip(e.function, _ITEM_CHARS)}" if e.function else "")
            for e in entities
        ]),
        ("地点", [
            f"- {p.name}（{p.type}" + (f"，属于「{place_names[p.parent_id]}」" if p.parent_id in place_names else "")
            + f"）：{_clip(p.description, _ITEM_CHARS)}"
            for p in places
        ]),
        ("势力", [
            f"- {f.name}：{_clip(f.description, _ITEM_CHARS)}"
            + (f" 目标：{_clip(f.goals, _ITEM_CHARS)}" if f.goals else "")
            for f in factions
        ]),
        ("功法与技艺", [
            f"- {t.name}（{t.type}）：{_clip(t.description, _ITEM_CHARS)}" for t in techniques
        ]),
        ("角色", [
            f"- {c.name}（{c.role}" + (f"，{c.age}" if c.age else "") + f"）：{_clip(c.description, _ITEM_CHARS)}"
            + (f"\n  角色卡：{_sheet(c.full_sheet)}" if c.full_sheet else "")
            for c in characters
        ]),
    ]
    parts = []
    for title, lines in sections:
        body = "\n".join(line for line in lines if line)
        if body:
            parts.append(f"## {title}\n{body}")
    text = "\n\n".join(parts)
    if len(text) > TOTAL_CHARS:
        text = text[:TOTAL_CHARS]
        notes.append(f"小说设定超过 {TOTAL_CHARS} 字，后面的部分被截掉了")
    return text, notes
