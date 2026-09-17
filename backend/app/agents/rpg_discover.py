"""把结算认出来的新实体补全成可以落库的档案。

结算那一步只报了名字和一句正文依据（见 rpg_settlement.filter_discoveries）——
够作者判断"要不要收"，但不够建行：NPC 得有属性和常驻地点，地点得挂父级和连接，
道具得有描述。补全就是这第二次调用，**只在作者点了「加入」之后才发生**，
所以没人勾就一分钱不花。

清洗完全复用向导那套（rpg_wizard._clean_*）。理由和向导本身一样：RPG 的数据
靠名字互相引用，模型写出一个不存在的地点名，落库之后地图就是一条断头线，而且
不报错。白名单过滤只有一份实现，两个入口共用。
"""
from app.agents import rpg_wizard
from app.services import llm_client, llm_json
from app.services.rpg_prompts import render
from app.services.rpg_state import def_map

# 一次补全最多处理多少条。勾太多一是 prompt 撑爆，二是模型开始糊弄；
# 前端按这个数分批，作者无感
MAX_PER_CALL = 12


async def flesh_out(module, picked, narration, location_names, model_ref, temperature=None):
    """给勾中的发现项补出完整档案。

    picked  —— [{"kind": "npc|place|item|skill|task", "name": ..., "hint": ...}]
    返回 {"npcs": [...], "locations": [...], "items": [...], "skills": [...],
          "tasks": [...], "dropped": [...]}，
    形状和向导的抽取结果一致，dropped 是被白名单拦下的东西，要回给前端标出来。
    """
    picked = list(picked)[:MAX_PER_CALL]
    if not picked:
        return {"npcs": [], "locations": [], "items": [], "skills": [], "tasks": [], "dropped": []}

    stat_names = [str(name) for name in def_map(module.stat_defs)]
    relation_names = [str(name) for name in def_map(module.relation_stat_defs)]
    location_names = [str(name) for name in location_names]

    prompt = render(
        "rpg_discover.jinja2",
        worldview=module.worldview or "",
        narration=narration,
        picked=picked,
        stat_names=stat_names,
        relation_names=relation_names,
        location_names=location_names,
    )
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [{"role": "user", "content": prompt}], model, api_format,
        max_tokens=3000, temperatures=rpg_wizard._ladder(temperature),
    )
    if not isinstance(parsed, dict):
        raise ValueError("补全结果必须是 JSON 对象")

    dropped: list[str] = []
    # 地点先洗：洗完拿到的名字要喂给角色那一步当白名单，这一批新建的地点
    # 才能当作角色的常驻地。顺序同向导的 STAGES（places 在 cast 之前）
    places = rpg_wizard._clean_places(parsed, dropped, known_names=location_names)
    cast = rpg_wizard._clean_cast(
        parsed, dropped, relation_names,
        location_names + [loc["name"] for loc in places["locations"]],
    )
    things = rpg_wizard._clean_things(parsed, dropped, stat_names, relation_names)

    # 只留作者真的勾了的那些：模型顺手多编一个角色是常事，而这一步是
    # 「照着勾选建档」，不是「再生成一批」
    kinds = ("npc", "place", "item", "skill", "task")
    wanted = {kind: {name for k, name in _keys(picked) if k == kind} for kind in kinds}
    return {
        "npcs": _only(cast["npcs"], wanted["npc"], "角色", dropped),
        "locations": _only(places["locations"], wanted["place"], "地点", dropped),
        "items": _only(things["items"], wanted["item"], "道具", dropped),
        "skills": _only(things["skills"], wanted["skill"], "技能", dropped),
        "tasks": _only(things["tasks"], wanted["task"], "任务", dropped),
        "dropped": dropped,
    }


def _keys(picked):
    for entry in picked:
        yield entry.get("kind"), str(entry.get("name") or "").strip()


def _only(rows, wanted, label, dropped):
    kept = []
    for row in rows:
        if row["name"] in wanted:
            kept.append(row)
        else:
            dropped.append(f"{label}「{row['name']}」不在你勾选的列表里，已丢掉")
    return kept
