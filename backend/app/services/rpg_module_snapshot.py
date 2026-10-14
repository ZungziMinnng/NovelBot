"""把模组编辑页里已经填好的内容拼成一段文字，给构思向导聊天参考。

只读库里的数据（不信前端传来的，那份可能过期）。故意不含 creator_note——
那是只给作者看的备注，永远不进 prompt。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rpg import (
    RpgAction, RpgItem, RpgLocation, RpgModule, RpgNpc, RpgSkill, RpgTask, RpgWorldEntry,
)


def _line(label: str, value) -> str:
    text = str(value or "").strip()
    return f"{label}：{text}" if text else ""


def _join(*lines: str) -> str:
    return "\n".join(x for x in lines if x)


def _stat_line(d: dict) -> str:
    bits = [str(d.get("name") or "").strip()]
    for key in ("initial", "min", "max"):
        if d.get(key) is not None:
            bits.append(f"{key}={d[key]}")
    note = str(d.get("description") or d.get("desc") or "").strip()
    return "· " + " ".join(b for b in bits if b) + (f"：{note}" if note else "")


def _effects(eff) -> str:
    if not isinstance(eff, dict) or not eff:
        return ""
    return "、".join(f"{k}{'+' if (v or 0) > 0 else ''}{v}" for k, v in eff.items())


async def build_module_snapshot(db: AsyncSession, module: RpgModule) -> str:
    """没填任何东西时返回空串。"""
    async def rows(model):
        return (await db.execute(
            select(model).where(model.module_id == module.id).order_by(model.sort_order, model.id)
        )).scalars().all()

    parts: list[str] = []

    base = _join(
        _line("模组名", module.name), _line("题材", module.genre),
        _line("玩法类别", module.play_style),
        _line("世界观", module.worldview), _line("开场旁白", module.opening_scene),
        _line("GM 规则", module.system_instruction), _line("叙事样例", module.narration_sample),
        _line("起始地点", module.default_location),
        _line("时段", "、".join(str(s) for s in (module.time_slots or []))),
    )
    if base:
        parts.append("【基本设定】\n" + base)

    stats = [_stat_line(d) for d in (module.stat_defs or []) if isinstance(d, dict) and d.get("name")]
    if stats:
        parts.append("【玩家数值】\n" + "\n".join(stats))
    rels = [_stat_line(d) for d in (module.relation_stat_defs or []) if isinstance(d, dict) and d.get("name")]
    if rels:
        parts.append("【关系数值（每个角色各一份）】\n" + "\n".join(rels))

    locs = await rows(RpgLocation)
    if locs:
        by_id = {l.id: l for l in locs}
        out = []
        for l in locs:
            parent = by_id.get(l.parent_id)
            head = f"· {l.name}" + ("（区域）" if l.is_region else "") + (f"，属于{parent.name}" if parent else "")
            tail = _join(
                _line("  描述", l.description),
                _line("  相通", "、".join(l.connections or [])),
            )
            out.append(head + ("\n" + tail if tail else ""))
        parts.append("【地点】\n" + "\n".join(out))

    npcs = await rows(RpgNpc)
    if npcs:
        out = []
        for n in npcs:
            sections = "\n".join(
                f"  {k}：{v}" for k, v in (n.profile_sections or {}).items() if str(v or "").strip()
            )
            out.append(_join(
                f"· {n.name}" + ("（主角）" if n.role == "protagonist" else ""),
                _line("  常驻", n.location), _line("  身份", n.description),
                _line("  性格", n.persona), _line("  外貌", n.appearance),
                sections,
            ))
        parts.append("【角色】\n" + "\n".join(out))

    for title, model, extra in (
        ("道具", RpgItem, lambda r: _join(_line("  分类", r.category), _line("  效果", _effects(r.effects)))),
        ("技能", RpgSkill, lambda r: _line("  效果", _effects(r.effects))),
        ("任务", RpgTask, lambda r: _join(_line("  目标", r.objective), _line("  奖励", _effects(r.effects)))),
    ):
        items = await rows(model)
        if items:
            out = []
            for r in items:
                out.append(_join(f"· {r.name}", _line("  说明", r.description), extra(r)))
            parts.append(f"【{title}】\n" + "\n".join(out))

    actions = await rows(RpgAction)
    if actions:
        out = [
            _join(f"· {a.name}" + (f"（{a.group}）" if a.group else ""),
                  _line("  提示", a.prompt_hint), _line("  数值", _effects(a.effects)))
            for a in actions
        ]
        parts.append("【动作按钮】\n" + "\n".join(out))

    book = [e for e in await rows(RpgWorldEntry) if e.enabled]
    if book:
        out = [_join(f"· {e.title or e.keywords}", _line("  内容", e.content)) for e in book]
        parts.append("【世界书】\n" + "\n".join(out))

    return "\n\n".join(parts)
