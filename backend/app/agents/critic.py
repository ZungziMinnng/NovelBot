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

    prompt = render(
        "critic.jinja2",
        character_summary=char_summary or "（无角色信息）",
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
        max_tokens=400,
    )
    result = result.strip()

    if result.upper().startswith("PASS"):
        return True, "", in_tok, out_tok, model
    return False, result, in_tok, out_tok, model
