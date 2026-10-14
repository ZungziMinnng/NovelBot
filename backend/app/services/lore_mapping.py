"""设定库的字段映射：四种来源 <-> 中立档案。纯函数，不碰数据库、不调模型。

中立档案的键：name / category / level / description / detail。

RPG 道具 / 技能的 effects 一律不读：那是那套战斗系统里调好的数值，
搬到别处只会变成一串没有上下文的数字。
"""

_RPG_ITEM_CATEGORIES = {"消耗品", "武器", "装备", "关键道具", "资料"}
_RPG_SKILL_CATEGORIES = {"主动", "被动"}


def _s(value) -> str:
    return str(value or "").strip()


def _neutral(name: str, **fields) -> dict:
    out = {"name": _s(name)}
    for key in ("category", "level", "description", "detail"):
        out[key] = _s(fields.get(key))
    return out


def to_neutral(origin: str, kind: str, obj) -> dict:
    if origin == "lore":
        return _neutral(
            obj.name, category=obj.category, level=obj.level,
            description=obj.description, detail=obj.detail,
        )
    if origin == "novel":
        if kind == "item":
            props = obj.properties or {}
            return _neutral(
                obj.name, description=obj.description, detail=obj.function,
                category=props.get("类别"), level=props.get("稀有度"),
            )
        if kind == "skill":
            practitioners = _s(obj.practitioners)
            return _neutral(
                obj.name, category=obj.type, level=obj.power_level,
                description=obj.description,
                detail=f"修习者：{practitioners}" if practitioners else "",
            )
        if kind == "rule":
            return _neutral(obj.title, description=obj.content)
    if origin == "rpg":
        if kind == "item":
            parts = ["可用"] if obj.usable else []
            if obj.consumable:
                parts.append("用后消耗")
            return _neutral(
                obj.name, category=obj.category, description=obj.description,
                detail="；".join(parts),
            )
        if kind == "skill":
            return _neutral(
                obj.name, category=obj.category, description=obj.description,
                detail=f"冷却 {obj.cooldown} 回合" if obj.cooldown else "",
            )
        if kind == "rule":
            return _neutral(obj.name, description=obj.content)
    if origin == "tavern" and kind == "rule":
        return _neutral(obj.name, description=obj.content)
    raise ValueError(f"未知来源类型：{origin}/{kind}")


def _join(*parts: str, sep: str = "\n") -> str:
    return sep.join(p for p in parts if p)


def to_novel_item(n: dict) -> dict:
    props = {"类别": n["category"], "稀有度": n["level"]}
    return {
        "type": "item",
        "name": n["name"],
        "description": n["description"],
        "function": n["detail"],
        "properties": {k: v for k, v in props.items() if v},
    }


def to_novel_skill(n: dict) -> dict:
    return {
        "name": n["name"],
        "type": n["category"],
        "description": n["description"],
        "power_level": n["level"],
        "practitioners": "",
    }


def to_novel_rule(n: dict) -> dict:
    return {"kind": "rule", "title": n["name"], "content": n["description"]}


def to_rpg_item(n: dict) -> dict:
    return {
        "name": n["name"],
        "description": _join(n["description"], n["detail"]),
        "category": n["category"] if n["category"] in _RPG_ITEM_CATEGORIES else "消耗品",
        "effects": {},
    }


def to_rpg_skill(n: dict) -> dict:
    category = n["category"] if n["category"] in _RPG_SKILL_CATEGORIES else "主动"
    return {
        "name": n["name"],
        "description": _join(n["description"], n["detail"]),
        "category": category,
        "usable": category != "被动",
        "effects": {},
        "requires": {},
    }


def to_rpg_rule(n: dict) -> dict:
    return {"name": n["name"], "content": n["description"]}


def to_tavern_rule(n: dict) -> dict:
    return {"name": n["name"], "content": n["description"]}


def to_tavern_entry(n: dict) -> dict:
    head = f"【{n['category']}】{n['name']}" if n["category"] else n["name"]
    body = f"{head}：{n['description']}" if n["description"] else head
    return {
        "keywords": n["name"],
        "content": _join(body, n["detail"]),
        "constant": False,
        "depth": 0,
        "enabled": True,
    }


_EXPORTERS = {
    ("novel", "item"): to_novel_item,
    ("novel", "skill"): to_novel_skill,
    ("novel", "rule"): to_novel_rule,
    ("rpg", "item"): to_rpg_item,
    ("rpg", "skill"): to_rpg_skill,
    ("rpg", "rule"): to_rpg_rule,
    ("tavern", "rule"): to_tavern_rule,
    ("tavern", "item"): to_tavern_entry,
    ("tavern", "skill"): to_tavern_entry,
}


def export_fields(target: str, kind: str, n: dict) -> dict:
    """按 (目标, 种类) 返回可直接展开给模型构造器的字段（不含 id / 外键）。"""
    fn = _EXPORTERS.get((target, kind))
    if fn is None:
        raise ValueError(f"未知导出目标：{target}/{kind}")
    return fn(n)
