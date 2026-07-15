"""Critic Agent: 审查生成内容的一致性"""
import json
import re
from app.services import llm_client
from app.services.summarizer import strip_plot_suggestions
from app.prompts.loader import render

_TIME_TAG_LEAK_RE = re.compile(r'【第\d+日[^】]*】|第\d+日')
_VARIANT_SPLIT_RE = re.compile(r'[,，、;；\n]')
_ENDING_CHARS = '。！？…」】”’』"—~'


def _local_precheck(generated_text: str, ctx: dict, target_words: int) -> list[str]:
    """确定性检查：字数、禁用词、时间标注泄漏、结尾截断。返回问题列表。"""
    issues: list[str] = []
    clean = strip_plot_suggestions(generated_text or "").strip()

    if not clean:
        return ["正文为空"]

    if target_words > 0:
        min_words = int(target_words * 0.9)
        if len(clean) < min_words:
            issues.append(
                f"字数不足：正文 {len(clean)} 字，低于目标 {target_words} 字的 90%（{min_words} 字），"
                "请补足内容"
            )

    for g in ctx.get("glossary", []):
        term = (g.get("term") or "").strip()
        for variant in _VARIANT_SPLIT_RE.split(g.get("forbidden_variants") or ""):
            variant = variant.strip()
            if not variant or (term and variant in term):
                continue
            count = clean.count(variant)
            if count:
                issues.append(
                    f"使用了禁用写法「{variant}」（应写作「{term}」），出现 {count} 处，请全部替换"
                )

    leaks = _TIME_TAG_LEAK_RE.findall(clean)
    if leaks:
        issues.append(
            f"正文泄漏内部时间标注（如「{leaks[0]}」，共 {len(leaks)} 处），"
            "请删除并改用自然的时间过渡描写"
        )

    if clean[-1] not in _ENDING_CHARS:
        issues.append(f"结尾疑似被截断（末尾为「…{clean[-10:]}」），请以完整句子收尾")

    return issues


async def review_chapter(
    generated_text: str,
    ctx: dict,
    fast_model: str = "",
    target_words: int = 0,
) -> tuple[bool, str, int, int, str]:
    """
    审查章节内容。
    返回 (passed, issues_text, input_tokens, output_tokens, model)
    passed=True 表示通过，issues_text 为空
    """
    # 本地确定性检查先行：硬伤直接打回，不消耗 LLM 调用
    local_issues = _local_precheck(generated_text, ctx, target_words)
    if local_issues:
        issues_text = "【本地检查未通过】\n" + "\n".join(f"- {i}" for i in local_issues)
        return False, issues_text, 0, 0, "local-precheck"

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
