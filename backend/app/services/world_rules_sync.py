"""世界观核心规则/特殊元素：结构化表 <-> core_setting 镜像段落 的同步逻辑。

world_rules 表是编辑真源；启用中的条目回写进 novel.core_setting 的
`## 核心规则` / `## 特殊元素` 段落，供不便查表的旧读取点直读（零回归）。
"""
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.novel import Novel
from app.models.world_rule import WorldRule

# kind -> core_setting 段落标题
KIND_HEADING = {"rule": "核心规则", "element": "特殊元素"}
HEADING_KIND = {v: k for k, v in KIND_HEADING.items()}

_SECTION_ORDER = ["时代背景", "核心规则", "特殊元素", "补充备注"]
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d+[.、)])\s*")


def _parse_sections(text: str) -> dict[str, str]:
    """按 `## 标题` 拆分为 {标题: 正文}；无标题则整段归入 时代背景。"""
    if not text:
        return {}
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return {"时代背景": text.strip()}
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[heading] = text[start:end].strip()
    return sections


def _row_line(row: WorldRule) -> str:
    content = (row.content or "").strip()
    title = (row.title or "").strip()
    if title:
        return f"- 【{title}】{content}"
    return f"- {content}"


def _render_section(rows: list[WorldRule]) -> str:
    lines = [_row_line(r) for r in rows if (r.content or "").strip() or (r.title or "").strip()]
    return "\n".join(lines)


async def sync_core_setting(session: AsyncSession, novel: Novel) -> None:
    """用启用中的 world_rules 条目重建 core_setting 的规则/元素镜像段落。

    保留 时代背景/补充备注 及任何未知段落；不 commit（由调用方统一提交）。
    """
    result = await session.execute(
        select(WorldRule)
        .where(WorldRule.novel_id == novel.id, WorldRule.enabled == True)  # noqa: E712
        .order_by(WorldRule.importance.desc(), WorldRule.id)
    )
    rows = result.scalars().all()
    by_kind: dict[str, list[WorldRule]] = {"rule": [], "element": []}
    for r in rows:
        by_kind.setdefault(r.kind, []).append(r)

    sections = _parse_sections(novel.core_setting or "")
    sections["核心规则"] = _render_section(by_kind.get("rule", []))
    sections["特殊元素"] = _render_section(by_kind.get("element", []))

    ordered = list(_SECTION_ORDER)
    ordered += [h for h in sections if h not in ordered]

    parts = [
        f"## {h}\n{sections[h].strip()}"
        for h in ordered
        if sections.get(h, "").strip()
    ]
    novel.core_setting = "\n\n".join(parts)


async def seed_or_sync(session: AsyncSession, novel: Novel) -> None:
    """创建/生成期调用：表为空则从 core_setting blob 拆分种子，否则用表重建镜像。

    避免在已有条目的小说上重复拆分导致重复条目。不 commit。
    """
    count = (await session.execute(
        select(WorldRule.id).where(WorldRule.novel_id == novel.id).limit(1)
    )).first()
    if count is None:
        await split_core_setting_into_rules(session, novel)
    else:
        await sync_core_setting(session, novel)


def _split_section_to_entries(text: str) -> list[tuple[str, str]]:
    """把一段自由文本规则/元素拆成 [(title, content)]。

    优先按行（去列表符号）拆；单行内 `【X】` 或前置 `X：` 提取标题。
    """
    entries: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = _BULLET_RE.sub("", raw).strip()
        if not line:
            continue
        m = re.match(r"^【(.+?)】\s*(.*)$", line)
        if m:
            entries.append((m.group(1).strip(), m.group(2).strip()))
            continue
        m = re.match(r"^(.{1,20}?)[：:]\s*(.+)$", line)
        if m and m.group(2).strip():
            entries.append((m.group(1).strip(), m.group(2).strip()))
            continue
        entries.append(("", line))
    return entries


async def split_core_setting_into_rules(session: AsyncSession, novel: Novel) -> int:
    """解析 core_setting 的 核心规则/特殊元素 段落，拆成 world_rule 行插入，然后重建镜像。

    返回新增条目数。用于启动迁移与创建期生成后的落表。不 commit。
    """
    sections = _parse_sections(novel.core_setting or "")
    added = 0
    for heading, kind in HEADING_KIND.items():
        body = sections.get(heading, "").strip()
        if not body:
            continue
        for title, content in _split_section_to_entries(body):
            if not (title or content):
                continue
            session.add(WorldRule(
                novel_id=novel.id, kind=kind,
                title=title, content=content,
                importance=3, enabled=True,
            ))
            added += 1
    await session.flush()
    await sync_core_setting(session, novel)
    return added
