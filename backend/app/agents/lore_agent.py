"""设定库：把若干来源设定融合成一条新设定。只产出草稿，不写库。"""
from app.prompts.loader import render
from app.services import llm_client, llm_json

_MAX_TOKENS = 3000

_FIELDS = ("name", "category", "level", "description", "detail")


def _clean(kind: str, parsed: dict) -> dict:
    """白名单 + 缺栏补空，模型多吐的键一律丢掉。规则类只用 description。"""
    out = {key: str(parsed.get(key) or "").strip() for key in _FIELDS}
    if kind == "rule":
        out["level"] = ""
        out["detail"] = ""
    return out


async def fuse(kind: str, sources: list[dict], goal: str, model_ref: str) -> dict:
    """sources: 中立档案 + weight + instruction + name。返回中立档案草稿。"""
    prompt = render("lore_fuse.jinja2", kind=kind, sources=sources, goal=goal.strip())
    model, api_format = llm_client.get_fast_client(model_ref)
    parsed, _, _ = await llm_json.call_json(
        [{"role": "user", "content": prompt}],
        model,
        api_format,
        temperatures=(0.9, 0.5),
        max_tokens=_MAX_TOKENS,
    )
    draft = _clean(kind, parsed)
    if not draft["name"]:
        raise ValueError("模型没有给新设定起名字，再炼一次")
    return draft
