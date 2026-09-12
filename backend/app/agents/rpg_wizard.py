"""模组构思向导：对话 + 分步抽取。对应小说侧的 brainstorm。

和小说侧那套的根本区别，是 RPG 的数据靠**名字**互相引用：角色的关系数值起点
（initial_state）引用关系数值名，道具/动作的 effects 引用玩家数值名，角色的
location 引用地点名。小说侧每步重抽全量、靠 knownNames 去重的做法在这里会出事——
第 4 步抽角色时模型会连数值表一起重抽，「精力」抽成「体力」，于是道具点下去
什么都不发生，还不报错。

所以：**每步只抽这一步的字段**，前面已定的名字当白名单传下来，抽完在这里按
白名单过滤，对不上的键直接丢掉、并记进 dropped 让前端标出来。静默丢弃 = 用户
以为生成了，实际没有。
"""
from app.services import llm_client, llm_json
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    DISPLAY_BAR, DISPLAY_NUMBER, DISPLAY_HIDDEN,
    ON_ZERO_NONE, ON_ZERO_DEAD, ON_ZERO_FLAG,
    EFFECT_CHARS,
)

# 向导的步骤顺序。id 与 rpg_wizard.jinja2 / rpg_wizard_extract.jinja2 的 stage
# 分支、前端 wizardStages.ts 保持一致。顺序有依赖：数值是地基、地点要在角色之前
STAGES = ["world", "stats", "places", "cast", "things"]

_DISPLAYS = {DISPLAY_BAR, DISPLAY_NUMBER, DISPLAY_HIDDEN}
_ON_ZEROS = {ON_ZERO_NONE, ON_ZERO_DEAD, ON_ZERO_FLAG}

# 叙事类字段的字数上限，和 rpg_assist.FIELD_SPECS 对齐，别另立一套
_WORLD_CHARS = {
    "genre": 40,
    "worldview": 600,
    "opening_scene": 400,
    "system_instruction": 400,
    "narration_sample": 300,
}
_DESC_CHARS = 300  # 地点/角色/道具的描述段


def _num(value, fallback=0):
    """抽取里的数字。float 也留着（temperature 那种），只挡文字。"""
    try:
        n = float(value)
        return int(n) if n == int(n) else n
    except (TypeError, ValueError):
        return fallback


def _text(value, limit=0) -> str:
    s = str(value or "").strip()
    return s[:limit] if limit else s


async def chat_stream_args(
    messages: list[dict], model_ref: str, nsfw: bool, stage: str,
    confirmed: str, play_style: str,
):
    """组装构思对话的 (messages, model, api_format)。SSE 由路由层包。

    用叙事模型而不是便宜模型：这是陪作者攒世界观的创作活，同 rpg_assist 的理由。
    """
    stage = stage if stage in STAGES else ""
    system_prompt = render(
        "rpg_wizard.jinja2",
        nsfw=nsfw,
        stage=stage,
        confirmed=confirmed if stage else "",
        play_style=play_style or "rpg",
    )
    full = [{"role": "system", "content": system_prompt}]
    full += [{"role": m["role"], "content": m["content"]} for m in messages]
    model, api_format = llm_client.get_agent_client("writer", model_ref)
    return full, model, api_format


async def extract_stage(
    stage: str, transcript: str, known: dict, model_ref: str,
) -> dict:
    """抽当前这一步的字段并清洗。known 带前面已定的名字白名单。

    返回 {字段..., "dropped": [被丢掉的东西的说明]}。抽取用便宜模型 + JSON 重试，
    同小说侧；清洗全在本地做，不再调模型。
    """
    if stage not in STAGES:
        return {"dropped": []}

    stat_names = [str(n) for n in (known.get("stat_names") or [])]
    relation_names = [str(n) for n in (known.get("relation_names") or [])]
    location_names = [str(n) for n in (known.get("location_names") or [])]

    system_prompt = render(
        "rpg_wizard_extract.jinja2",
        stage=stage,
        stat_names="、".join(stat_names),
        relation_names="、".join(relation_names),
        location_names="、".join(location_names),
    )
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"=== 对话记录 ===\n{transcript}"},
        ],
        model,
        api_format,
        max_tokens=3000,
    )

    cleaners = {
        "world": _clean_world,
        "stats": _clean_stats,
        "places": _clean_places,
        "cast": lambda p, d: _clean_cast(p, d, relation_names, location_names),
        "things": lambda p, d: _clean_things(p, d, stat_names, relation_names),
    }
    dropped: list[str] = []
    result = cleaners[stage](parsed, dropped)
    result["dropped"] = dropped
    return result


# 单摊一键生成支持的类别。和 rpg_generate.jinja2 的 kind 分支、前端 BatchGenerate 一致
KINDS = ["location", "npc", "item", "action"]


async def generate_batch(
    kind: str, instruction: str, count: int, known: dict, nsfw: bool, model_ref: str,
) -> dict:
    """按作者的一句要求，批量生成某一摊（地点/角色/道具/动作），清洗后返回。

    和向导的区别：白名单（已有的数值名/地点名/同类已有名字）由路由层从库里查好传进来，
    不靠对话累积。清洗复用向导那几个函数——引用对不上照样丢进 dropped。返回结构同
    extract_stage，前端预览面板两处通用。
    """
    if kind not in KINDS:
        return {"dropped": []}

    stat_names = [str(n) for n in (known.get("stat_names") or [])]
    relation_names = [str(n) for n in (known.get("relation_names") or [])]
    location_names = [str(n) for n in (known.get("location_names") or [])]
    existing_names = [str(n) for n in (known.get("existing_names") or [])]

    system_prompt = render(
        "rpg_generate.jinja2",
        kind=kind,
        instruction=instruction,
        count=count,
        nsfw=nsfw,
        stat_names="、".join(stat_names),
        relation_names="、".join(relation_names),
        location_names="、".join(location_names),
        existing_names="、".join(existing_names),
    )
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [{"role": "system", "content": system_prompt}],
        model,
        api_format,
        max_tokens=3000,
    )

    dropped: list[str] = []
    if kind == "location":
        # 已有地点当作连接的合法目标，新地点才能连回旧地图
        result = _clean_places(parsed, dropped, known_names=existing_names)
        # 单摊补充不改起始地点，那是模组层面的决定
        result.pop("default_location", None)
    elif kind == "npc":
        result = _clean_cast(parsed, dropped, relation_names, location_names)
    elif kind == "item":
        things = _clean_things(parsed, dropped, stat_names, relation_names)
        result = {"items": things["items"]}
    else:  # action
        things = _clean_things(parsed, dropped, stat_names, relation_names)
        result = {"actions": things["actions"]}

    # 和库里已有的重名的直接剔掉——作者要的是补新的，不是覆盖
    existing = {n.strip().lower() for n in existing_names}
    key = {"location": "locations", "npc": "npcs", "item": "items", "action": "actions"}[kind]
    rows, dup = [], []
    for row in result.get(key) or []:
        if row["name"].strip().lower() in existing:
            dup.append(row["name"])
        else:
            rows.append(row)
    result[key] = rows
    for name in dup:
        dropped.append(f"「{name}」模组里已经有了，跳过")

    result["dropped"] = dropped
    return result


def _clean_world(parsed: dict, dropped: list) -> dict:
    return {key: _text(parsed.get(key), limit) for key, limit in _WORLD_CHARS.items()}


def _clean_stat_def(spec: dict, *, full: bool) -> dict | None:
    """一条数值定义。full=True 是玩家数值（有 for_check/on_zero），False 是关系数值。

    initial 夹在 min..max 之间，display/on_zero 非法值落默认，都不报错——作者手填
    时也是这么兜的（见 rpg_state），抽取更该兜住。
    """
    name = _text(spec.get("name"))
    if not name:
        return None
    lo = _num(spec.get("min"), 0)
    raw_max = spec.get("max")
    hi = None if raw_max is None else _num(raw_max, None)
    initial = _num(spec.get("initial"), lo)
    if hi is not None and hi < lo:
        lo, hi = hi, lo
    initial = max(initial, lo)
    if hi is not None:
        initial = min(initial, hi)
    display = _text(spec.get("display"))
    if display not in _DISPLAYS:
        # 没上限的当数字，其余当进度条——同模板里给模型的规矩
        display = DISPLAY_NUMBER if hi is None else DISPLAY_BAR
    out = {
        "name": name, "initial": initial, "min": lo, "max": hi,
        "display": display,
        "effect": _text(spec.get("effect"), EFFECT_CHARS),
    }
    if full:
        on_zero = _text(spec.get("on_zero"))
        out["on_zero"] = on_zero if on_zero in _ON_ZEROS else ON_ZERO_NONE
        out["for_check"] = bool(spec.get("for_check"))
    return out


def _clean_stats(parsed: dict, dropped: list) -> dict:
    stat_defs = []
    for spec in parsed.get("stat_defs") or []:
        if isinstance(spec, dict):
            cleaned = _clean_stat_def(spec, full=True)
            if cleaned:
                stat_defs.append(cleaned)
    relation_defs = []
    for spec in parsed.get("relation_stat_defs") or []:
        if isinstance(spec, dict):
            cleaned = _clean_stat_def(spec, full=False)
            if cleaned:
                relation_defs.append(cleaned)
    return {"stat_defs": stat_defs, "relation_stat_defs": relation_defs}


def _clean_places(parsed: dict, dropped: list, known_names=()) -> dict:
    """known_names 是模组里已有的地点名。向导第一次生成时为空（连接只能连本批）；
    单摊补充生成时带上已有地点，新地点就能连回旧地图。"""
    locations = []
    names: list[str] = []
    for spec in parsed.get("locations") or []:
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        locations.append({
            "name": name,
            "description": _text(spec.get("description"), _DESC_CHARS),
            "connections": spec.get("connections") or [],
        })
        names.append(name)
    # connections 必须指向真实存在的地点（本批新建的 + 模组里已有的），否则地图连线断头
    valid = set(names) | {_text(n) for n in known_names if _text(n)}
    for loc in locations:
        kept, cut = [], []
        for target in loc["connections"]:
            t = _text(target)
            (kept if t and t in valid and t != loc["name"] else cut).append(t)
        loc["connections"] = kept
        for t in cut:
            if t:
                dropped.append(f"地点「{loc['name']}」连去了不存在的「{t}」，已去掉")
    default_location = _text(parsed.get("default_location"))
    if default_location and default_location not in valid:
        dropped.append(f"起始地点「{default_location}」不在生成的地点里，已留空")
        default_location = ""
    return {"locations": locations, "default_location": default_location}


def _clean_cast(parsed: dict, dropped: list, relation_names, location_names) -> dict:
    relations = set(relation_names)
    places = set(location_names)
    npcs = []
    for spec in parsed.get("npcs") or []:
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        # 关系数值起点：键必须是前面定过的关系数值名
        initial_state = {}
        for key, value in (spec.get("initial_state") or {}).items():
            k = _text(key)
            if k and k in relations:
                initial_state[k] = _num(value, 0)
            elif k:
                dropped.append(f"角色「{name}」的关系「{k}」不在数值表里，已去掉")
        location = _text(spec.get("location"))
        if location and location not in places:
            dropped.append(f"角色「{name}」在的地点「{location}」不存在，已留空")
            location = ""
        npcs.append({
            "name": name,
            "persona": _text(spec.get("persona"), 400),
            "appearance": _text(spec.get("appearance"), _DESC_CHARS),
            "description": _text(spec.get("description"), 500),
            "location": location,
            "initial_state": initial_state,
        })
    return {"npcs": npcs}


def _clean_effects(raw, allowed: set, name: str, kind: str, dropped: list) -> dict:
    out = {}
    for key, value in (raw or {}).items():
        k = _text(key)
        if k and k in allowed:
            out[k] = _num(value, 0)
        elif k:
            dropped.append(f"{kind}「{name}」影响的「{k}」不在数值表里，已去掉")
    return out


def _clean_things(parsed: dict, dropped: list, stat_names, relation_names) -> dict:
    stats = set(stat_names)
    relations = set(relation_names)
    items = []
    for spec in parsed.get("items") or []:
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        items.append({
            "name": name,
            "description": _text(spec.get("description"), 200),
            "category": _text(spec.get("category")) or "消耗品",
            "consumable": bool(spec.get("consumable", True)),
            "start_with": bool(spec.get("start_with")),
            "effects": _clean_effects(spec.get("effects"), stats, name, "道具", dropped),
        })
    actions = []
    for spec in parsed.get("actions") or []:
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        actions.append({
            "name": name,
            "prompt_hint": _text(spec.get("prompt_hint"), 200),
            "needs_target": bool(spec.get("needs_target")),
            "effects": _clean_effects(spec.get("effects"), stats, name, "动作", dropped),
            "relation_effects": _clean_effects(
                spec.get("relation_effects"), relations, name, "动作", dropped
            ),
        })
    return {"items": items, "actions": actions}
