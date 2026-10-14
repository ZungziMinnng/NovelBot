"""熔炉的字段映射：三种来源 <-> 中立档案。纯函数，不碰数据库、不调模型。

中立档案的键：name / age / description / personality / speech_style / appearance /
background / abilities / relationships / dialogue_examples。

酒馆卡的 creator_note / opening_scene / system_instruction 一律不读：
creator_note 是「AI 永远看不到」的栏，其余两栏是那张卡自己的运行指令，混进新角色会串味。
"""
import re

from app.models.rpg import normalize_profile_sections

TEXT_FIELDS = (
    "age", "description", "personality", "speech_style",
    "appearance", "background", "abilities", "relationships",
)

_TAVERN_KEYS = {
    "appearance": "appearance",
    "background": "background",
    "abilities": "abilities",
    "relationships": "relationships",
}
_NPC_KEYS = {
    "background": "背景故事",
    "abilities": "能力特长",
    "relationships": "关系网络",
}


def _s(value) -> str:
    return str(value or "").strip()


def _examples(raw) -> list[dict]:
    out = []
    for turn in raw or []:
        if not isinstance(turn, dict):
            continue
        user, assistant = _s(turn.get("user")), _s(turn.get("assistant"))
        if user or assistant:
            out.append({"user": user, "assistant": assistant})
    return out


def _neutral(name: str, **fields) -> dict:
    out = {"name": _s(name), "dialogue_examples": _examples(fields.pop("dialogue_examples", []))}
    for key in TEXT_FIELDS:
        out[key] = _s(fields.get(key))
    return out


def to_neutral(kind: str, obj) -> dict:
    if kind == "tavern":
        sections = obj.profile_sections or {}
        return _neutral(
            obj.name,
            description=obj.description,
            personality=obj.personality,
            appearance=sections.get("appearance"),
            background=sections.get("background"),
            abilities=sections.get("abilities"),
            relationships=sections.get("relationships"),
            dialogue_examples=obj.dialogue_examples,
        )
    if kind == "npc":
        sections, appearance = normalize_profile_sections(obj.profile_sections, obj.appearance or "")
        return _neutral(
            obj.name,
            age=obj.age,
            description=obj.description,
            personality=obj.persona,
            appearance=appearance,
            background=sections.get("背景故事"),
            abilities=sections.get("能力特长"),
            relationships=sections.get("关系网络"),
            dialogue_examples=obj.dialogue_examples,
        )
    if kind == "novel":
        sheet = obj.full_sheet or {}
        skills = sheet.get("skills") or []
        return _neutral(
            obj.name,
            age=obj.age,
            description=obj.description,
            personality=sheet.get("personality"),
            speech_style=sheet.get("speech_style"),
            appearance=sheet.get("appearance"),
            abilities="、".join(str(s).strip() for s in skills if str(s).strip())
            if isinstance(skills, list) else skills,
        )
    raise ValueError(f"未知来源类型：{kind}")


def _join(*parts: str, sep: str = "\n") -> str:
    return sep.join(p for p in parts if p)


def to_tavern(n: dict) -> dict:
    sections = {
        key: n[key] for key in _TAVERN_KEYS.values() if n.get(key)
    }
    age = f"年龄：{n['age']}。" if n.get("age") else ""
    return {
        "name": n["name"],
        "description": _join(age, n.get("description", ""), sep=""),
        "personality": _join(
            n.get("personality", ""),
            f"说话风格：{n['speech_style']}" if n.get("speech_style") else "",
        ),
        "profile_sections": sections,
        "dialogue_examples": n.get("dialogue_examples", []),
    }


def to_npc(n: dict) -> dict:
    sections = {
        cn: n[key] for key, cn in _NPC_KEYS.items() if n.get(key)
    }
    return {
        "name": n["name"],
        "role": "npc",
        "age": n.get("age", "")[:20],
        "description": n.get("description", ""),
        "persona": _join(
            n.get("personality", ""),
            f"说话风格：{n['speech_style']}" if n.get("speech_style") else "",
        ),
        "appearance": n.get("appearance", ""),
        "profile_sections": sections,
        "dialogue_examples": n.get("dialogue_examples", []),
    }


def to_novel(n: dict) -> dict:
    """小说角色没有背景 / 关系栏，折进简述（有损）。对话示例没有位置，丢弃。"""
    skills = [s for s in re.split(r"[、，,;；\n]+", n.get("abilities", "")) if s.strip()]
    extra = _join(
        f"背景：{n['background']}" if n.get("background") else "",
        f"关系：{n['relationships']}" if n.get("relationships") else "",
    )
    return {
        "name": n["name"],
        "role": "配角",
        "age": n.get("age", "")[:20],
        "description": _join(n.get("description", ""), extra),
        "full_sheet": {
            "personality": n.get("personality", ""),
            "skills": [s.strip() for s in skills],
            "appearance": n.get("appearance", ""),
            "speech_style": n.get("speech_style", ""),
        },
    }
