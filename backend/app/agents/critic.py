"""Critic Agent: 审查生成内容的一致性"""
import json
from app.services import llm_client
from app.prompts.loader import render


async def review_chapter(
    generated_text: str,
    ctx: dict,
    fast_model: str = "",
) -> tuple[bool, str, int, int, str]:
    """
    审查章节内容。
    返回 (passed, issues_text, input_tokens, output_tokens, model)
    passed=True 表示通过，issues_text 为空
    """
    chars = ctx.get("characters", [])
    char_summary = ""
    for c in chars:
        state = c.get("state", {})
        char_summary += f"- {c['name']}（{c['role']}）：{c['description']}"
        if state:
            char_summary += f"，当前状态：{json.dumps(state, ensure_ascii=False)}"
        char_summary += "\n"

    setting_summary = _build_setting_summary(ctx)

    prompt = render(
        "critic.jinja2",
        character_summary=char_summary or "（无角色信息）",
        setting_summary=setting_summary or "（无设定库信息）",
        chapter_outline=ctx.get("chapter_outline", "（无大纲）"),
        rolling_summary=ctx.get("rolling_summary", "（无历史摘要）"),
        chapter_content=generated_text[:3000],
    )

    model, api_format = llm_client.get_agent_client("critic", fast_model)
    result, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.2,
        max_tokens=1000,
    )
    result = result.strip()

    if result.upper().startswith("PASS"):
        return True, "", in_tok, out_tok, model
    return False, result, in_tok, out_tok, model


def _build_setting_summary(ctx: dict) -> str:
    parts: list[str] = []

    entities = ctx.get("world_entities", [])
    items = [e for e in entities if e.get("type") == "item"]
    systems = [e for e in entities if e.get("type") == "system"]
    other_entities = [e for e in entities if e.get("type") not in ("item", "system")]

    if items:
        parts.append("【道具/物品】")
        for e in items:
            parts.append(_entity_line(e))

    if systems:
        parts.append("【系统】")
        for e in systems:
            parts.append(_entity_line(e))

    if other_entities:
        parts.append("【其他实体】")
        for e in other_entities:
            parts.append(_entity_line(e))

    factions = ctx.get("factions", [])
    if factions:
        parts.append("【势力】")
        for f in factions:
            parts.append(
                f"- {f.get('name', '')}（{f.get('type', '')}）："
                f"{f.get('description', '')}"
                f"{'；首领：' + str(f.get('leader')) if f.get('leader') else ''}"
                f"{'；目标：' + str(f.get('goals')) if f.get('goals') else ''}"
            )

    techniques = ctx.get("techniques", [])
    if techniques:
        parts.append("【功法/技能】")
        for t in techniques:
            parts.append(
                f"- {t.get('name', '')}（{t.get('type', '')}）：{t.get('description', '')}"
                f"{'；使用者：' + str(t.get('practitioners')) if t.get('practitioners') else ''}"
            )

    return "\n".join(parts)


def _entity_line(entity: dict) -> str:
    state = entity.get("state") or {}
    props = entity.get("properties") or {}
    extra = ""
    if props:
        extra += f"；属性：{json.dumps(props, ensure_ascii=False)}"
    if state:
        extra += f"；当前状态：{json.dumps(state, ensure_ascii=False)}"
    return f"- {entity.get('name', '')}：{entity.get('description', '')}{extra}"
