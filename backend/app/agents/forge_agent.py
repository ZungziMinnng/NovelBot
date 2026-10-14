"""熔炉：把若干来源角色融合成一个新角色。只产出草稿，不写库。"""
from app.prompts.loader import render
from app.services import llm_client, llm_json
from app.services.forge_mapping import TEXT_FIELDS

_MAX_TOKENS = 3000


def _clean(parsed: dict) -> dict:
    """白名单 + 缺栏补空，模型多吐的键一律丢掉。"""
    out = {"name": str(parsed.get("name") or "").strip()}
    for key in TEXT_FIELDS:
        out[key] = str(parsed.get(key) or "").strip()
    examples = []
    for turn in parsed.get("dialogue_examples") or []:
        if not isinstance(turn, dict):
            continue
        user, assistant = str(turn.get("user") or "").strip(), str(turn.get("assistant") or "").strip()
        if user or assistant:
            examples.append({"user": user, "assistant": assistant})
    out["dialogue_examples"] = examples
    return out


async def fuse(sources: list[dict], goal: str, model_ref: str) -> dict:
    """sources: 中立档案 + weight + instruction + name。返回中立档案草稿。"""
    prompt = render("forge_fuse.jinja2", sources=sources, goal=goal.strip())
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [{"role": "user", "content": prompt}],
        model,
        api_format,
        temperatures=(0.9, 0.5),
        max_tokens=_MAX_TOKENS,
    )
    draft = _clean(parsed)
    if not draft["name"]:
        raise ValueError("模型没有给新角色起名字，再炼一次")
    return draft
