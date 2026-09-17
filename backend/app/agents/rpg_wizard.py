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
from app.agents.rpg_assist import FIELD_SPECS
from app.services import llm_client, llm_json
from app.services.rpg_prompts import render
from app.services.rpg_state import (
    DISPLAY_BAR, DISPLAY_CELLS, DISPLAY_NUMBER, DISPLAY_HIDDEN,
    ON_ZERO_NONE, ON_ZERO_DEAD, ON_ZERO_FLAG,
)

# 向导的步骤顺序。id 与 rpg_wizard.jinja2 / rpg_wizard_extract.jinja2 的 stage
# 分支、前端 wizardStages.ts 保持一致。顺序有依赖：数值是地基、地点要在角色之前
STAGES = ["world", "stats", "places", "slots", "cast", "things"]

# 每一步给模型多少输出额度。cast 单独给高：一个写全了的角色（性格+外貌+详细
# 设定+四栏档案）就要五六千 token，原先六步统一 3000，**一个人都放不下**。
# 给少了不会报错——llm_json.repair_json 会把被掐断的 JSON 补齐成合法的，于是
# 症状是「说好八个角色只出来三个」「最后一段写到一半没了」，全程静默
_STAGE_MAX_TOKENS = {"cast": 10000}
_STAGE_MAX_TOKENS_DEFAULT = 6000

_DISPLAYS = {DISPLAY_BAR, DISPLAY_NUMBER, DISPLAY_HIDDEN, DISPLAY_CELLS}
_ON_ZEROS = {ON_ZERO_NONE, ON_ZERO_DEAD, ON_ZERO_FLAG}

_RELATION_SUFFIXES = (
    ("好感度", "好感"), ("信任度", "信任"), ("亲密度", "亲密"),
    ("服从度", "服从"), ("敬畏度", "敬畏"), ("恐惧度", "恐惧"),
    ("依赖度", "依赖"), ("忠诚度", "忠诚"), ("敌意值", "敌意"),
    ("好感", "好感"), ("信任", "信任"), ("亲密", "亲密"),
    ("服从", "服从"), ("敬畏", "敬畏"), ("恐惧", "恐惧"),
    ("依赖", "依赖"), ("忠诚", "忠诚"), ("敌意", "敌意"),
)

# 叙事类字段的字数上限。**直接引用 FIELD_SPECS，不再抄数字**：以前这里抄了
# 一份，抄完两边就飘了——向导只有 assist 的三分之一（世界观 600 对 1800），
# 而注释还写着「已对齐」。于是同一段世界观，作者点单栏「AI 帮我写」能留 1800
# 字，走向导回填只剩 600，差三倍还没人发现。
# 这些是**防模型跑飞的天花板**，不是提示词预算：每轮实发多少由 rpg_context
# 那套 token 预算管，超了那边会优雅降级，不用在这儿再压一道
def _cap(field: str) -> int:
    return FIELD_SPECS[field][2]


_WORLD_CHARS = {
    "genre": 40,  # FIELD_SPECS 里没有这一栏：它是个标签，不是叙事段
    "worldview": _cap("worldview"),
    "opening_scene": _cap("opening_scene"),
    "system_instruction": _cap("system_instruction"),
    "narration_sample": _cap("narration_sample"),
}
# 地点描述和角色外貌在 FIELD_SPECS 里同为 900，共用一个常量
_DESC_CHARS = _cap("location_description")
# 道具/技能/任务的描述段，FIELD_SPECS 里同为 600
_THING_DESC_CHARS = _cap("item_description")
# 角色档案四栏。FIELD_SPECS 没有这一栏（界面上没给单栏辅助），按「四栏加起来
# 别比角色详细设定长太多」定。注意它要乘以在场人数去挤 NPC_TOKEN_BUDGET
_PROFILE_CHARS = 800


def _ladder(temperature: float | None) -> tuple[float, ...]:
    """抽取用的温度阶梯。作者只能调**起始**那一档，0.1 兜底始终保留——
    那一档是「JSON 又崩了，压到最低再试一次」的救命梯，不该被调掉。
    None = 老前端没传，按 call_json 的默认走。"""
    return (0.3, 0.1) if temperature is None else (temperature, 0.1)


async def generate_full(
    instruction: str, nsfw: bool, play_style: str, model_ref: str,
    world_scope: str = "region", temperature: float | None = None,
) -> dict:
    """Generate one complete, form-shaped module draft from a short idea."""
    prompt = render(
        "rpg_wizard_full.jinja2",
        instruction=instruction.strip(), nsfw=nsfw, play_style=play_style or "rpg",
        world_scope=world_scope if world_scope in {"world", "region"} else "region",
    )
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": instruction.strip()},
        ],
        model,
        api_format,
        # 这一发要出整个模组（设定+数值+地点+时段+角色+道具+动作），原先的
        # 6500/9000 连几个写全了的角色都装不下，多出来的部分被静默吞掉
        max_tokens=16000 if world_scope == "world" else 12000,
        temperatures=_ladder(temperature),
    )
    dropped: list[str] = []
    world = _clean_world(parsed, dropped)
    stats = _clean_stats(parsed, dropped)
    places = _clean_places(parsed, dropped)
    slots = _clean_slots(parsed, dropped)
    relation_names = [s["name"] for s in stats["relation_stat_defs"]]
    stat_names = [s["name"] for s in stats["stat_defs"]]
    location_names = [p["name"] for p in places["locations"]]
    cast = _clean_cast(parsed, dropped, relation_names, location_names)
    things = _clean_things(parsed, dropped, stat_names, relation_names)
    result = {**world, **stats, **places, **slots, **cast, **things}
    result["dropped"] = dropped
    return result


def pick_model(chosen: str, module_ref: str) -> str:
    """向导这一步用哪个模型：作者在向导里选的优先，没选才跟模组走。

    下拉的第一项是「模组默认模型」（value 为空串），所以空 = 按模组配置走，
    **不是**「没配」。三个入口（对话 / 抽取 / 一键生成）都要过这里——从前后端
    各自判一次的话，出现过的正是「选了模型却还是连默认模型」：前端把选择发了
    出来，路由没接。

    不在这里校验模型是否存在：那是 resolve_model_ref 的活，它认不出来会抛
    ValueError，路由翻成人话的 400。
    """
    return (chosen or "").strip() or module_ref


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


def _list_field(parsed: dict, field: str) -> list:
    value = parsed.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise llm_json.JsonCallError(f"模型返回的 {field} 格式错误，应为列表，请重新抽取")
    return value


def _object_field(value, label: str, dropped: list) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dropped.append(f"{label}格式错误，应为对象，已留空；其余内容保留")
    return {}


def _clean_relation_name(value) -> str:
    name = _text(value)
    for suffix, generic in _RELATION_SUFFIXES:
        if name == suffix:
            return generic
        if name.endswith(suffix) and len(name) > len(suffix):
            return generic
    return name


async def chat_stream_args(
    messages: list[dict], model_ref: str, nsfw: bool, stage: str,
    confirmed: str, play_style: str, world_scope: str = "region",
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
        world_scope=world_scope if world_scope in {"world", "region"} else "region",
    )
    full = [{"role": "system", "content": system_prompt}]
    full += [{"role": m["role"], "content": m["content"]} for m in messages]
    model, api_format = llm_client.get_agent_client("writer", model_ref)
    return full, model, api_format


async def extract_stage(
    stage: str, transcript: str, known: dict, model_ref: str,
    temperature: float | None = None,
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
        max_tokens=_STAGE_MAX_TOKENS.get(stage, _STAGE_MAX_TOKENS_DEFAULT),
        temperatures=_ladder(temperature),
    )

    cleaners = {
        "world": _clean_world,
        "stats": _clean_stats,
        "places": _clean_places,
        "slots": _clean_slots,
        "cast": lambda p, d: _clean_cast(p, d, relation_names, location_names),
        "things": lambda p, d: _clean_things(p, d, stat_names, relation_names),
    }
    dropped: list[str] = []
    result = cleaners[stage](parsed, dropped)
    result["dropped"] = dropped
    return result


# 单摊一键生成支持的类别。和 rpg_generate.jinja2 的 kind 分支、前端 BatchGenerate 一致
KINDS = ["location", "npc", "item", "skill", "task", "action"]


def _batch_max_tokens(kind: str, count: int) -> int:
    """按要生成几个算额度，不能是定值：原先固定 3000，而「生成 10 个角色」光
    角色卡就要几万 token，结果是后面七个静默消失、作者以为模型偷懒。
    角色单价高（性格+外貌+详细设定+四栏档案），其余一摊只是名字加一句话。
    封顶 16000 是迁就供应商——不少模型的单次输出上限就在 16K 上下，要更高得先
    确认模型支持，否则请求直接被拒。"""
    per = 5000 if kind == "npc" else 1200
    return min(16000, max(_STAGE_MAX_TOKENS_DEFAULT, per * max(1, count)))


async def generate_batch(
    kind: str, instruction: str, count: int, known: dict, nsfw: bool, model_ref: str,
    play_style: str = "rpg", temperature: float | None = None,
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
        play_style=play_style or "rpg",
        stat_names="、".join(stat_names),
        relation_names="、".join(relation_names),
        location_names="、".join(location_names),
        existing_names="、".join(existing_names),
    )
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": instruction.strip()},
        ],
        model,
        api_format,
        max_tokens=_batch_max_tokens(kind, count),
        temperatures=_ladder(temperature),
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
    elif kind == "skill":
        things = _clean_things(parsed, dropped, stat_names, relation_names)
        result = {"skills": things["skills"]}
    elif kind == "task":
        things = _clean_things(parsed, dropped, stat_names, relation_names)
        result = {"tasks": things["tasks"]}
    else:  # action
        things = _clean_things(parsed, dropped, stat_names, relation_names)
        result = {"actions": things["actions"]}

    # 和库里已有的重名的直接剔掉——作者要的是补新的，不是覆盖
    existing = {n.strip().lower() for n in existing_names}
    key = {
        "location": "locations", "npc": "npcs", "item": "items",
        "skill": "skills", "task": "tasks", "action": "actions",
    }[kind]
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


def _clean_slots(parsed: dict, dropped: list) -> dict:
    slots = []
    for value in _list_field(parsed, "time_slots"):
        name = _text(value, 40)
        if name and name not in slots:
            slots.append(name)
    return {"time_slots": slots}


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
        # effect 不在这里截：抽取写进库的是原文，砍那一刀留给 rpg_context 拼提示词时。
        # 原先在这儿按 EFFECT_CHARS 砍完再存，作者的后半句就永久没了，以后调宽上限
        # 也救不回来，只能重抽。手填那条路径本来就是存全文，这样两边也一致了。
        "effect": _text(spec.get("effect"))
        or f"影响与{name}相关的判定和剧情结果",
    }
    if full:
        on_zero = _text(spec.get("on_zero"))
        out["on_zero"] = on_zero if on_zero in _ON_ZEROS else ON_ZERO_NONE
        out["for_check"] = bool(spec.get("for_check"))
    return out


def _clean_stats(parsed: dict, dropped: list) -> dict:
    stat_defs = []
    for spec in _list_field(parsed, "stat_defs"):
        if isinstance(spec, dict):
            cleaned = _clean_stat_def(spec, full=True)
            if cleaned:
                stat_defs.append(cleaned)
    relation_defs = []
    relation_names = set()
    for spec in _list_field(parsed, "relation_stat_defs"):
        if isinstance(spec, dict):
            cleaned = _clean_stat_def(spec, full=False)
            if cleaned:
                original_name = cleaned["name"]
                cleaned["name"] = _clean_relation_name(original_name)
                if not cleaned["name"] or cleaned["name"] in relation_names:
                    if original_name:
                        dropped.append(f"关系数值「{original_name}」与已有通用关系维度重复，已去掉")
                    continue
                relation_names.add(cleaned["name"])
                relation_defs.append(cleaned)
    return {"stat_defs": stat_defs, "relation_stat_defs": relation_defs}


def _clean_places(parsed: dict, dropped: list, known_names=()) -> dict:
    """known_names 是模组里已有的地点名。向导第一次生成时为空（连接只能连本批）；
    单摊补充生成时带上已有地点，新地点就能连回旧地图。"""
    locations = []
    names: list[str] = []
    for spec in _list_field(parsed, "locations"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        locations.append({
            "name": name,
            "description": _text(spec.get("description"), _DESC_CHARS),
            "parent_name": _text(spec.get("parent_name")),
            "connections": _list_field(spec, "connections"),
        })
        names.append(name)
    # connections 必须指向真实存在的地点（本批新建的 + 模组里已有的），否则地图连线断头
    valid = set(names) | {_text(n) for n in known_names if _text(n)}
    for loc in locations:
        parent = loc["parent_name"]
        if parent and (parent not in valid or parent == loc["name"]):
            dropped.append(f"地点「{loc['name']}」的父地点「{parent}」不存在，已设为顶层")
            loc["parent_name"] = ""
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
    for spec in _list_field(parsed, "npcs"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        # 关系数值起点：键必须是前面定过的关系数值名
        initial_state = {}
        for key, value in _object_field(spec.get("initial_state"), f"角色「{name}」的关系起点", dropped).items():
            raw_key = _text(key)
            # 关系数值名在 _clean_stats 里被归一化过（「信任度」→「信任」），
            # 这里引用时也得过同一道，否则模型写「信任度」就对不上白名单、被全员丢掉
            k = _clean_relation_name(raw_key)
            if k and k in relations:
                initial_state[k] = _num(value, 0)
            elif raw_key:
                dropped.append(f"角色「{name}」的关系「{raw_key}」不在数值表里，已去掉")
        location = _text(spec.get("location"))
        if location and location not in places:
            dropped.append(f"角色「{name}」在的地点「{location}」不存在，已留空")
            location = ""
        profile_sections = _object_field(spec.get("profile_sections"), f"角色「{name}」的详细档案", dropped)
        npcs.append({
            "name": name,
            "persona": _text(spec.get("persona"), _cap("npc_persona")),
            "appearance": _text(spec.get("appearance"), _DESC_CHARS),
            "description": _text(spec.get("description"), _cap("npc_description")),
            "profile_sections": {
                key: _text(profile_sections.get(key), _PROFILE_CHARS)
                for key in ("appearance", "background", "abilities", "relationships")
                if _text(profile_sections.get(key), _PROFILE_CHARS)
            },
            "location": location,
            "initial_state": initial_state,
        })
    return {"npcs": npcs}


def _clean_effects(raw, allowed: set, name: str, kind: str, dropped: list, normalize=None) -> dict:
    """normalize 用于关系数值：白名单里的名字是归一化过的，键也要归一化才能对上。"""
    out = {}
    for key, value in _object_field(raw, f"{kind}「{name}」的数值效果", dropped).items():
        raw_key = _text(key)
        k = normalize(raw_key) if normalize else raw_key
        if k and k in allowed:
            out[k] = _num(value, 0)
        elif raw_key:
            dropped.append(f"{kind}「{name}」影响的「{raw_key}」不在数值表里，已去掉")
    return out


def _clean_things(parsed: dict, dropped: list, stat_names, relation_names) -> dict:
    stats = set(stat_names)
    relations = set(relation_names)
    items = []
    for spec in _list_field(parsed, "items"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        items.append({
            "name": name,
            "description": _text(spec.get("description"), _THING_DESC_CHARS),
            "category": _text(spec.get("category")) or "消耗品",
            "consumable": bool(spec.get("consumable", True)),
            "start_with": bool(spec.get("start_with")),
            "effects": _clean_effects(spec.get("effects"), stats, name, "道具", dropped),
        })
    skills = []
    for spec in _list_field(parsed, "skills"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        # requires 不让模型生成：条件是一套嵌套结构，模型胡编出来的条件既看不懂
        # 也没法在界面上改对。作者要门槛就自己在技能那一摊点两下
        skills.append({
            "name": name,
            "description": _text(spec.get("description"), _THING_DESC_CHARS),
            "category": _text(spec.get("category")) or "主动",
            "cooldown": max(0, int(_num(spec.get("cooldown"), 0))),
            "start_with": bool(spec.get("start_with")),
            "effects": _clean_effects(spec.get("effects"), stats, name, "技能", dropped),
        })
    tasks = []
    for spec in _list_field(parsed, "tasks"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        tasks.append({
            "name": name,
            "description": _text(spec.get("description"), _THING_DESC_CHARS),
            # 判定完成与否只看这一句，所以它必须写成「做到什么才算办完」，
            # 不能是又一句剧情简介
            "objective": _text(spec.get("objective"), 200),
            "category": _text(spec.get("category")) or "支线",
            "auto_start": bool(spec.get("auto_start")),
            "effects": _clean_effects(spec.get("effects"), stats, name, "任务", dropped),
        })
    actions = []
    for spec in _list_field(parsed, "actions"):
        if not isinstance(spec, dict):
            continue
        name = _text(spec.get("name"))
        if not name:
            continue
        actions.append({
            "name": name,
            "prompt_hint": _text(spec.get("prompt_hint"), 200),
            "needs_target": bool(spec.get("needs_target")),
            # 分组是纯文本，编错了也只是分栏难看，所以放给模型生成。
            # cost_slot 和 at_location 不给：一个要模型懂这个模组的时段节奏，
            # 一个要它写对地点名，猜错就是个永远灰着的按钮，作者还不知道为什么
            "group": _text(spec.get("group"), 50),
            "effects": _clean_effects(spec.get("effects"), stats, name, "动作", dropped),
            "relation_effects": _clean_effects(
                spec.get("relation_effects"), relations, name, "动作", dropped,
                normalize=_clean_relation_name,
            ),
        })
    return {"items": items, "skills": skills, "tasks": tasks, "actions": actions}
