import json
import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, func
from sqlalchemy.orm.attributes import flag_modified
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.character import Character
from app.models.world_entity import WorldEntity
from app.models.location import Location
from app.models.novel import Novel
from app.prompts.loader import render
from app.services import llm_client, vector_store
from app.config import settings

logger = logging.getLogger(__name__)


def _build_analysis_messages(
    prompt_prefix: str,
    content: str,
    prompt_suffix: str,
    api_format: str,
) -> list[dict]:
    """组装「分析章节内容」类任务的消息列表。

    Gemini:  章节原文放 assistant(model) 角色，绕过 PROHIBITED_CONTENT 过滤。
    OpenAI / DeepSeek:  合并为单条 user 消息，确保模型将原文视为待分析素材。
    """
    if api_format == "gemini":
        return [
            {"role": "user", "content": prompt_prefix},
            {"role": "assistant", "content": f"--- 章节内容 ---\n{content}\n---"},
            {"role": "user", "content": prompt_suffix},
        ]
    return [
        {"role": "user", "content": f"{prompt_prefix}\n\n--- 章节内容 ---\n{content}\n---\n\n{prompt_suffix}"},
    ]


# ── 正文清理：截断 LLM 可能自行附加的剧情发展选项 ─────────────────────────
_PLOT_SUGGESTION_PATTERNS = re.compile(
    r'\n\s*(?:---+\s*\n\s*)?'
    r'(?:剧情发展选项|剧情走向建议|下一章剧情发展|后续剧情发展|'
    r'接下来的剧情|下一章可能的发展|剧情发展方向|可能的发展方向)'
    r'[：:\s]',
)


def strip_plot_suggestions(text: str) -> str:
    """去除章节正文末尾 LLM 自行附加的剧情发展选项段落。"""
    m = _PLOT_SUGGESTION_PATTERNS.search(text)
    if m:
        return text[:m.start()].rstrip()
    return text


# ── 摘要清理：去除 LLM 自行添加的前缀标题 ──────────────────────────────────
_SUMMARY_PREFIX_PATTERN = re.compile(
    r'^[\s\n]*(?:\*{0,2})?'
    r'(?:章节)?(?:剧情)?(?:梗概|摘要|概要|总结|概述)[：:]\s*(?:\*{0,2})?\s*\n?',
)


def _clean_summary(text: str) -> str:
    """去除 LLM 在摘要开头自行添加的标题前缀（如"章节剧情梗概："）和 Markdown 格式。"""
    cleaned = _SUMMARY_PREFIX_PATTERN.sub('', text).strip()
    # 去除整体的 Markdown 加粗包裹
    if cleaned.startswith('**') and '**' in cleaned[2:]:
        cleaned = cleaned.replace('**', '')
    return cleaned


_TIME_TAG_PATTERN = re.compile(r'^【([^】]+)】')
_ABSOLUTE_DAY_PATTERN = re.compile(r'第(\d+)日')
_RELATIVE_DAY_PATTERN = re.compile(r'^(当天|当日|本日|同日|当晚|当夜|次日|翌日|第二天)(?:[·・\s-]?(.+))?$')
_RELATIVE_DAYS_LATER_PATTERN = re.compile(r'^(\d+)日后(?:[·・\s-]?(.+))?$')


def _extract_day_number(time_tag: str) -> int | None:
    match = _ABSOLUTE_DAY_PATTERN.search(time_tag or "")
    if not match:
        return None
    return int(match.group(1))


def normalize_timeline_tag(time_tag: str, previous_time_tag: str = "") -> str:
    """Convert relative timeline tags into absolute 第X日 tags when possible."""
    tag = (time_tag or "").strip().strip("【】")
    if not tag:
        return tag
    if "→" in tag:
        parts = [part.strip() for part in tag.split("→") if part.strip()]
        normalized_parts: list[str] = []
        prev = previous_time_tag
        for part in parts:
            normalized = normalize_timeline_tag(part, prev)
            normalized_parts.append(normalized)
            prev = normalized
        return "→".join(normalized_parts)
    if _ABSOLUTE_DAY_PATTERN.search(tag):
        return tag

    prev_day = _extract_day_number(previous_time_tag)
    if prev_day is None:
        return tag

    match = _RELATIVE_DAY_PATTERN.match(tag)
    if match:
        rel, period = match.groups()
        if rel in ("次日", "翌日", "第二天"):
            day = prev_day + 1
        else:
            day = prev_day
        if not period and rel in ("当晚", "当夜"):
            period = "夜晚"
        return f"第{day}日{f'·{period}' if period else ''}"

    later_match = _RELATIVE_DAYS_LATER_PATTERN.match(tag)
    if later_match:
        days, period = later_match.groups()
        day = prev_day + int(days)
        return f"第{day}日{f'·{period}' if period else ''}"

    return tag


def normalize_summary_timeline_tag(summary: str, previous_time_tag: str = "") -> str:
    match = _TIME_TAG_PATTERN.match((summary or "").strip())
    if not match:
        return summary
    old_tag = match.group(1)
    new_tag = normalize_timeline_tag(old_tag, previous_time_tag)
    if new_tag == old_tag:
        return summary
    return summary.replace(f"【{old_tag}】", f"【{new_tag}】", 1)


CHAPTER_SUMMARY_PROMPT_PREFIX = """你是一位小说编辑，需要将以下章节内容压缩为250字以内的剧情梗概。

输出规范：
- 梗概开头用【第X日】标注本章覆盖的故事时间段（如：【第12日·白天】、【第13日·夜晚】）
- 时间必须使用绝对日期计数，禁止使用“当天、当日、次日、翌日、第二天、三日后”等相对表达
- 如果章节内发生了时间跳跃，必须明确标注
- 如实记录章节中发生的所有重要事件，包括人物行为、决定、冲突、关系变化
- 保留对后续剧情有影响的关键细节
- 使用简洁的叙述语言"""

CHAPTER_SUMMARY_PROMPT_SUFFIX = (
    "请直接输出剧情梗概文本。\n"
    "⚠️ 格式要求（必须遵守）：\n"
    "1. 第一行必须以【第X日】开头（如【第12日·夜晚】、【第13日·清晨】）\n"
    "2. 禁止使用当天、当日、次日、翌日、第二天、三日后等相对时间词\n"
    "3. 不要输出任何标题、前缀（如『章节剧情梗概：』）或 Markdown 格式符号（如 ** 或 ##）\n"
    "4. 直接以【时间标注】开始正文"
)


CHARACTER_UPDATE_PROMPT_PREFIX = """根据以下章节内容，更新角色状态卡。

输出规范：
- 如实记录本章中角色的状态变化
- 提取对后续剧情有影响的变化：位置、目标、已知秘密、关系变化、能力变化
- 使用简洁的事实语言

小说当前角色状态：
{character_states}"""

CHARACTER_UPDATE_PROMPT_SUFFIX = """以 JSON 格式输出，格式为：
{
  "角色名": {
    "location": "当前位置",
    "current_goal": "当前目标",
    "titles": ["称谓/头衔列表，如：师姐、掌门、院长；本章无新称谓则为空数组"],
    "affiliation": "所属门派/组织/学院，如：太渊宫；本章无变化则保持原值或留空字符串",
    "known_secrets": ["仅限：阴谋、隐藏身份、未公开的关键情报；不要记录普通对话或公开信息"],
    "relationship_changes": {"其他角色名": "当前最显著的关系变化（仅1-2条最重要的）"}
  }
}

只输出 JSON，不要任何解释。"""


async def summarize_chapter(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
) -> tuple[str, int, int]:
    """生成章节摘要并存储。返回 (summary, input_tokens, output_tokens)。"""
    if not chapter.content.strip():
        return "", 0, 0

    clean_content = strip_plot_suggestions(chapter.content)
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)

    # 查询上一章摘要的时间标记，为当前章提供日期连续性上下文
    prev_time_hint = ""
    prev_time_tag = ""
    if chapter.number > 1:
        prev_mem_result = await session.execute(
            select(Memory.content)
            .where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
                Memory.chapter_number == chapter.number - 1,
            )
            .order_by(Memory.id.desc())
            .limit(1)
        )
        prev_summary = prev_mem_result.scalar_one_or_none()
        if prev_summary:
            import re as _re
            m = _re.match(r'【(.+?)】', prev_summary)
            if m:
                prev_time_tag = m.group(1)
                prev_time_hint = (
                    f"\n- 上一章（第{chapter.number - 1}章）的时间标记为【{prev_time_tag}】，"
                    "请根据本章内容推算本章的绝对日期，保持日期连续性；"
                    "如果本章写“当天/当日”，换算为上一章同一日；如果写“次日/翌日”，换算为上一章后一日"
                )

    prompt_prefix = render("chapter_summary_prefix.jinja2") + prev_time_hint
    messages = _build_analysis_messages(
        prompt_prefix, clean_content[:6000],
        render("chapter_summary_suffix.jinja2"), api_format,
    )
    summary, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=2000,
    )
    summary = _clean_summary(summary)

    # 检测输出截断：摘要未以正常标点结尾，说明被中途截断（token 耗尽或安全过滤）
    _s = summary.strip()
    _truncated = bool(_s) and _s[-1] not in '。！？…」】'
    if _truncated:
        logger.warning(
            "章节 %s 摘要疑似被截断 (len=%d, tail=%r)，将使用脱敏提示重试",
            chapter.number, len(_s), _s[-20:],
        )
    if not _s:
        logger.warning("章节 %s 摘要为空，将使用脱敏提示重试", chapter.number)
    if not _s or _truncated:
        # 截断重试：换用更简洁的提示，减少输出长度
        retry_messages = _build_analysis_messages(
            (
                "请为一部小说章节写一段200字的剧情梗概。\n"
                "第一行必须以【第X日】或【第X日·时段】开头，禁止使用当天、次日等相对时间词。\n"
                f"上一章时间标记：{f'【{prev_time_tag}】' if prev_time_tag else '未知'}。"
            ),
            clean_content[:4000],
            "请基于以上内容输出剧情梗概，直接以【第X日】时间标记开始：",
            api_format,
        )
        retry_summary, retry_in, retry_out = await llm_client.dispatch_chat_complete_with_usage(
            messages=retry_messages,
            model=model,
            api_format=api_format,
            temperature=0.1,
            max_tokens=2000,
        )
        in_tok += retry_in
        out_tok += retry_out
        retry_summary = _clean_summary(retry_summary)
        if retry_summary.strip() and len(retry_summary.strip()) > len(summary.strip()):
            logger.info(
                "章节 %s 脱敏重试成功 (len=%d → %d)",
                chapter.number, len(summary.strip()), len(retry_summary.strip()),
            )
            summary = retry_summary
        else:
            logger.warning(
                "章节 %s 脱敏重试未改善 (original=%d, retry=%d)",
                chapter.number, len(summary.strip()), len(retry_summary.strip()),
            )

    # LLM 返回空字符串时（内容过滤等），跳过保存，避免创建空 Memory 行
    if not summary.strip():
        return "", in_tok, out_tok

    summary = normalize_summary_timeline_tag(summary, prev_time_tag)

    # 保存摘要到章节
    chapter.summary = summary
    chapter.word_count = len(clean_content)

    # 先删除同章节的旧摘要，避免多次生成/确认产生重复行占用滚动窗口
    await session.execute(
        sql_delete(Memory).where(
            Memory.chapter_id == chapter.id,
            Memory.memory_type == "chapter_summary",
        )
    )
    # 存入 Memory 表
    memory = Memory(
        novel_id=novel.id,
        chapter_id=chapter.id,
        memory_type="chapter_summary",
        content=summary,
        volume=chapter.volume,
        chapter_number=chapter.number,
    )
    session.add(memory)

    # 存入向量库（异步，不阻塞事件循环）
    doc_id = f"chapter_{chapter.id}_summary"
    await vector_store.astore_text(
        novel_id=novel.id,
        doc_id=doc_id,
        text=summary,
        metadata={
            "type": "chapter_summary",
            "volume": chapter.volume,
            "chapter_number": chapter.number,
        },
    )
    memory.embedding_id = doc_id
    return summary, in_tok, out_tok


def _repair_json(raw: str) -> str:
    """尝试修复 LLM 常见的 JSON 格式问题"""
    text = raw.strip()
    # 去除 markdown 代码块包裹
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text.strip())
    # 提取最外层 { ... }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end <= 0:
        return text
    text = text[start:end]
    # 去除行尾 // 注释
    text = re.sub(r'//[^\n]*', '', text)
    # 去除尾部逗号: ,} 或 ,]
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # 修复字符串值内的裸换行符（JSON 标准不允许字符串里有未转义换行）
    # 逐字符扫描：在引号内部时将 \n \r \t 替换为转义形式
    result = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '\\' and in_string and i + 1 < len(text):
            result.append(ch)
            result.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
        i += 1
    text = ''.join(result)
    # 修复未闭合的字符串（LLM 截断导致引号不配对）
    unescaped_quotes = re.findall(r'(?<!\\)"', text)
    if len(unescaped_quotes) % 2 != 0:
        text += '"'
    # 截断修复：如果 JSON 未闭合，补齐缺失的闭合符号
    open_brackets = text.count('[') - text.count(']')
    open_braces = text.count('{') - text.count('}')
    if open_brackets > 0:
        text += ']' * open_brackets
    if open_braces > 0:
        text += '}' * open_braces
    return text


def _fuzzy_match_character(name: str, char_map: dict[str, "Character"]) -> str | None:
    """模糊匹配角色名。优先精确匹配，其次尝试子串包含匹配。
    返回匹配到的 char_map key，或 None。
    """
    if name in char_map:
        return name
    # LLM 输出名包含数据库角色名（如 LLM 输出 "张三丰"，数据库有 "三丰"）
    for db_name in char_map:
        if db_name in name:
            return db_name
    # 数据库角色名包含 LLM 输出名（如 LLM 输出 "三丰"，数据库有 "张三丰"）
    for db_name in char_map:
        if name in db_name:
            return db_name
    return None


async def update_character_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    instruction: str = "",
) -> tuple[bool, str, int, int]:
    """根据章节内容更新角色状态卡。
    返回 (success, warning_message, input_tokens, output_tokens)。
    """
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    characters = result.scalars().all()
    if not characters:
        return True, "", 0, 0

    states_text = json.dumps(
        {c.name: c.current_state for c in characters},
        ensure_ascii=False,
        indent=2,
    )
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt_prefix = render("character_update_prefix.jinja2", character_states=states_text)
    chapter_content = strip_plot_suggestions(chapter.content)[:6000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    messages = _build_analysis_messages(
        prompt_prefix, chapter_content, render("character_update_suffix.jinja2"), api_format,
    )

    total_in, total_out = 0, 0
    try:
        raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=1500,
        )
        total_in += in_tok
        total_out += out_tok
    except Exception as e:
        return False, f"角色状态更新：LLM 调用失败 ({type(e).__name__}: {e})", 0, 0

    # 提取并修复 JSON（处理尾部逗号、截断、markdown 包裹等常见 LLM 问题）
    json_text = _repair_json(raw)
    try:
        updates = json.loads(json_text)
    except json.JSONDecodeError:
        # 修复失败 → 降低 temperature 重试一次 LLM 调用
        try:
            raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=0.1,
                max_tokens=1500,
            )
            total_in += in_tok
            total_out += out_tok
            json_text = _repair_json(raw)
            updates = json.loads(json_text)
        except Exception as e:
            return False, f"角色状态更新：JSON 解析失败（含重试）({e})", total_in, total_out, []

    if not isinstance(updates, dict):
        return False, "角色状态更新：LLM 返回的 JSON 不是对象类型", total_in, total_out, []

    char_map = {c.name: c for c in characters}
    unmatched = []
    matched_count = 0
    for name, state in updates.items():
        if not isinstance(state, dict):
            continue
        target_name = _fuzzy_match_character(name, char_map)
        if target_name is None:
            unmatched.append(name)
            continue
        existing = char_map[target_name].current_state or {}
        merged = dict(existing)
        # titles 直接覆盖（当前称谓列表，不累积）；其余 list 字段合并去重
        _OVERWRITE_LIST_KEYS = {"titles"}
        for key, val in state.items():
            if isinstance(val, list):
                if key in _OVERWRITE_LIST_KEYS:
                    # 非空才覆盖，空数组不清除已有数据
                    if val:
                        merged[key] = val
                else:
                    old_val = existing.get(key, [])
                    old_list = old_val if isinstance(old_val, list) else [old_val] if old_val else []
                    combined = list(dict.fromkeys(old_list + val))
                    if key == "known_secrets" and len(combined) > 10:
                        combined = combined[-10:]
                    merged[key] = combined
            elif key == "relationship_changes" and isinstance(val, dict):
                initial = dict(merged.get("initial_relationships", {}))
                if not isinstance(initial, dict):
                    initial = {}
                for tgt, lbl in val.items():
                    if tgt not in initial:
                        initial[tgt] = lbl
                merged["initial_relationships"] = initial
                merged[key] = val
            elif val:  # 非空值才覆盖，避免清除上一章已存的信息
                merged[key] = val
        char_map[target_name].current_state = merged
        flag_modified(char_map[target_name], "current_state")
        matched_count += 1

    warning = ""
    if unmatched:
        warning = f"角色状态更新：以下名称未匹配到角色库 [{', '.join(unmatched)}]"
    if matched_count == 0 and not unmatched:
        warning = "角色状态更新：LLM 未返回任何角色状态数据"
    return True, warning, total_in, total_out, unmatched


ENTITY_UPDATE_PROMPT_PREFIX = """根据以下章节内容，更新世界实体（道具/系统）的状态。

输出规范：
- 如实记录本章中实体的状态变化
- 道具：关注持有者变化、已知能力
- 系统：关注等级/层次变化、已解锁能力
- 只输出本章有变化的实体，无变化的不要输出
- 每个实体所有字段内容合计不超过300字，请精炼概括

当前世界实体状态：
{entity_states}"""

ENTITY_UPDATE_PROMPT_SUFFIX = """以 JSON 格式输出，格式为：
{
  "实体名": {
    "owner": "当前持有者/归属者，无变化则留空字符串",
    "description": "综合已有信息和本章新信息，简要描述该实体；无新信息则留空字符串",
    "new_abilities": "简要概括该实体目前已知的所有能力，无则留空字符串",
    "level_changes": "当前等级/层次，无变化则留空字符串"
  }
}

只输出 JSON，不要任何解释。"""


def _trim_entity_state(state: dict, limit: int = 300) -> None:
    """确保实体状态的文本内容总长不超过 limit 字。"""
    total = sum(len(str(v)) for v in state.values())
    if total <= limit:
        return
    overflow = total - limit
    for key in ("description", "new_abilities", "level_changes"):
        if key not in state or not isinstance(state[key], str):
            continue
        val = state[key]
        if len(val) <= 10:
            continue
        trim = min(overflow, len(val) - 10)
        state[key] = val[:len(val) - trim] + "…"
        overflow -= trim
        if overflow <= 0:
            return


async def update_entity_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    instruction: str = "",
) -> tuple[bool, str, int, int]:
    """根据章节内容更新世界实体状态。
    返回 (success, warning_message, input_tokens, output_tokens)。
    """
    result = await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel.id)
    )
    entities = result.scalars().all()
    if not entities:
        return True, "", 0, 0

    states_text = json.dumps(
        {e.name: {"type": e.type, **(e.current_state or {})} for e in entities},
        ensure_ascii=False,
        indent=2,
    )
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt_prefix = render("entity_update_prefix.jinja2", entity_states=states_text)
    chapter_content = strip_plot_suggestions(chapter.content)[:6000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    messages = _build_analysis_messages(
        prompt_prefix, chapter_content, render("entity_update_suffix.jinja2"), api_format,
    )

    total_in, total_out = 0, 0
    try:
        raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=1500,
        )
        total_in += in_tok
        total_out += out_tok
    except Exception as e:
        return False, f"实体状态更新：LLM 调用失败 ({type(e).__name__}: {e})", 0, 0

    json_text = _repair_json(raw)
    try:
        updates = json.loads(json_text)
    except json.JSONDecodeError:
        try:
            raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=0.1,
                max_tokens=1500,
            )
            total_in += in_tok
            total_out += out_tok
            json_text = _repair_json(raw)
            updates = json.loads(json_text)
        except Exception as e:
            return False, f"实体状态更新：JSON 解析失败（含重试）({e})", total_in, total_out, []

    if not isinstance(updates, dict):
        return False, "实体状态更新：LLM 返回的 JSON 不是对象类型", total_in, total_out, []

    entity_map = {e.name: e for e in entities}
    unmatched = []
    matched_count = 0
    for name, state in updates.items():
        if not isinstance(state, dict):
            continue
        target_name = _fuzzy_match_character(name, entity_map)
        if target_name is None:
            unmatched.append(name)
            continue
        existing = entity_map[target_name].current_state or {}
        merged = dict(existing)
        for key, val in state.items():
            if val:
                merged[key] = val
        _trim_entity_state(merged)
        entity_map[target_name].current_state = merged
        flag_modified(entity_map[target_name], "current_state")
        matched_count += 1

    warning = ""
    if unmatched:
        warning = f"实体状态更新：以下名称未匹配到实体库 [{', '.join(unmatched)}]"
    if matched_count == 0 and not unmatched:
        warning = "实体状态更新：LLM 未返回任何实体状态数据"
    return True, warning, total_in, total_out, unmatched


LOCATION_UPDATE_PROMPT_PREFIX = """根据以下章节内容，更新地点的动态状态。

输出规范：
- 如实记录本章中地点的状态变化
- 关注控制方、当前局势、破坏/修复、封锁/开放、重要事件遗留影响
- 只输出本章有变化的地点，无变化的不要输出

当前地点状态：
{location_states}"""

LOCATION_UPDATE_PROMPT_SUFFIX = """以 JSON 格式输出，格式为：
{
  "地点名": {
    "current_situation": "当前局势或状态，无法判断则留空字符串",
    "control": "当前控制方/所属势力，无变化则留空字符串",
    "notable_changes": ["本章造成的地点变化，无则为空数组"]
  }
}

只输出 JSON，不要任何解释。"""


async def update_location_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    instruction: str = "",
) -> tuple[bool, str, int, int]:
    result = await session.execute(
        select(Location).where(Location.novel_id == novel.id)
    )
    locations = result.scalars().all()
    if not locations:
        return True, "", 0, 0

    states_text = json.dumps(
        {l.name: {"type": l.type, **(l.current_state or {})} for l in locations},
        ensure_ascii=False,
        indent=2,
    )
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt_prefix = render("location_update_prefix.jinja2", location_states=states_text)
    chapter_content = strip_plot_suggestions(chapter.content)[:6000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    messages = _build_analysis_messages(
        prompt_prefix, chapter_content, render("location_update_suffix.jinja2"), api_format,
    )

    total_in, total_out = 0, 0
    try:
        raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=1500,
        )
        total_in += in_tok
        total_out += out_tok
    except Exception as e:
        return False, f"地点状态更新：LLM 调用失败 ({type(e).__name__}: {e})", 0, 0

    json_text = _repair_json(raw)
    try:
        updates = json.loads(json_text)
    except json.JSONDecodeError:
        try:
            raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
                messages=messages,
                model=model,
                api_format=api_format,
                temperature=0.1,
                max_tokens=1500,
            )
            total_in += in_tok
            total_out += out_tok
            json_text = _repair_json(raw)
            updates = json.loads(json_text)
        except Exception as e:
            return False, f"地点状态更新：JSON 解析失败（含重试）({e})", total_in, total_out, []

    if not isinstance(updates, dict):
        return False, "地点状态更新：LLM 返回的 JSON 不是对象类型", total_in, total_out, []

    location_map = {l.name: l for l in locations}
    unmatched = []
    matched_count = 0
    for name, state in updates.items():
        if not isinstance(state, dict):
            continue
        target_name = _fuzzy_match_character(name, location_map)
        if target_name is None:
            unmatched.append(name)
            continue
        existing = location_map[target_name].current_state or {}
        merged = dict(existing)
        for key, val in state.items():
            if isinstance(val, list):
                old_val = existing.get(key, [])
                old_list = old_val if isinstance(old_val, list) else [old_val] if old_val else []
                merged[key] = list(dict.fromkeys(old_list + val))[-20:]
            elif val:
                merged[key] = val
        location_map[target_name].current_state = merged
        flag_modified(location_map[target_name], "current_state")
        matched_count += 1

    warning = ""
    if unmatched:
        warning = f"地点状态更新：以下名称未匹配到地点库 [{', '.join(unmatched)}]"
    if matched_count == 0 and not unmatched:
        warning = "地点状态更新：LLM 未返回任何地点状态数据"
    return True, warning, total_in, total_out, unmatched


ARC_SUMMARY_PROMPT = """你是一位专业的文学编辑。以下是一部小说连续若干章的章节摘要，请将它们整合为一段故事弧概要。

要求：
- 聚焦这段章节内的主线进展、重要事件、核心角色变化
- 保留新引入的伏笔和待解决的冲突
- 控制在500字以内
- 使用客观叙述语气，按时间线组织

各章节摘要：
{summaries}

直接输出故事弧概要，不要任何前缀。"""


async def generate_arc_summary(
    session: AsyncSession,
    novel: "Novel",  # noqa: F821
    start_chapter: int,
    end_chapter: int,
    volume: int = 1,
) -> str:
    """将 start_chapter 到 end_chapter 的章节摘要合并为一段故事弧概要，
    存入 Memory 表（memory_type='arc_summary'）。"""
    result = await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "chapter_summary",
            Memory.volume == volume,
            Memory.chapter_number >= start_chapter,
            Memory.chapter_number <= end_chapter,
        )
        .order_by(Memory.chapter_number.asc())
    )
    memories = result.scalars().all()
    if not memories:
        return ""

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)

    summaries_text = "\n".join(
        f"第{m.chapter_number}章：{m.content}" for m in memories
    )
    prompt = render("arc_summary.jinja2", summaries=summaries_text)
    arc_summary = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=2000,
    )

    if not arc_summary.strip():
        return ""

    # 删除同范围的旧弧摘要（避免重复占用空间）
    await session.execute(
        sql_delete(Memory).where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "arc_summary",
            Memory.volume == volume,
            Memory.chapter_number == end_chapter,
        )
    )

    # 存入 Memory 表
    memory = Memory(
        novel_id=novel.id,
        memory_type="arc_summary",
        content=arc_summary.strip(),
        volume=volume,
        chapter_number=end_chapter,
    )
    session.add(memory)
    return arc_summary.strip()


BOOK_SUMMARY_PROMPT = """你是一位专业的文学编辑。以下是一部小说各章节的摘要，请将它们整合为一份全书概要。

要求：
- 聚焦主线剧情、核心人物关系、重要转折点
- 保留关键伏笔和待解决的矛盾
- 控制在500字以内
- 使用客观叙述语气，不添加评价

各章节摘要：
{summaries}

直接输出全书概要，不要任何前缀。"""

BOOK_SUMMARY_MERGE_PROMPT = """你是一位专业的文学编辑。以下是一部小说的多段分批概要，请将它们整合为一份完整的全书概要。

要求：
- 聚焦主线剧情、核心人物关系、重要转折点
- 保留关键伏笔和待解决的矛盾
- 控制在500字以内
- 使用客观叙述语气，不添加评价
- 按时间线顺序组织，保持因果关系清晰

各段概要：
{summaries}

直接输出全书概要，不要任何前缀。"""

BATCH_SIZE = 50  # 每批最多处理 50 章摘要


async def _summarize_batch(
    summaries_text: str,
    model: str,
    api_format: str,
    prompt_template: str = "book_summary.jinja2",
) -> str:
    """用指定 prompt 模板对一段摘要文本做概要"""
    prompt = render(prompt_template, summaries=summaries_text)
    return await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=2000,
    )


async def generate_book_summary(
    session: AsyncSession,
    novel: "Novel",  # noqa: F821
) -> str:
    """将所有章节摘要整合成全书概要，存入 novel.book_summary。
    优先使用弧摘要（arc_summary）减少压缩层级；若无弧摘要则回退到章节摘要。
    当摘要数超过 BATCH_SIZE 时，自动分批概括再整合，支持百章级别。"""
    # 优先使用弧摘要（中间粒度，信息保留率更高）
    arc_result = await session.execute(
        select(Memory)
        .where(
            Memory.novel_id == novel.id,
            Memory.memory_type == "arc_summary",
        )
        .order_by(Memory.chapter_number.asc())
    )
    arc_memories = arc_result.scalars().all()
    if arc_memories:
        memories = list(arc_memories)
        last_arc_chapter = max(m.chapter_number or 0 for m in arc_memories)
        # Include chapter summaries after the latest arc summary, otherwise chapters
        # 16-20, 31-35, etc. are invisible until the next 15-chapter arc exists.
        trailing_result = await session.execute(
            select(Memory)
            .where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
                Memory.chapter_number > last_arc_chapter,
            )
            .order_by(Memory.chapter_number.asc())
        )
        memories.extend(trailing_result.scalars().all())
    else:
        # 回退到章节摘要
        result = await session.execute(
            select(Memory)
            .where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
            )
            .order_by(Memory.chapter_number.asc())
        )
        memories = result.scalars().all()

    if not memories:
        return ""

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)

    if len(memories) <= BATCH_SIZE:
        # 少量章节：单次生成
        summaries_text = "\n".join(
            f"第{m.chapter_number}章：{m.content}" for m in memories
        )
        book_summary = await _summarize_batch(summaries_text, model, api_format)
    else:
        # 大量章节：分批概括 → 再整合
        batch_summaries = []
        for i in range(0, len(memories), BATCH_SIZE):
            batch = memories[i:i + BATCH_SIZE]
            start_ch = batch[0].chapter_number
            end_ch = batch[-1].chapter_number
            summaries_text = "\n".join(
                f"第{m.chapter_number}章：{m.content}" for m in batch
            )
            summary = await _summarize_batch(summaries_text, model, api_format)
            batch_summaries.append(f"第{start_ch}-{end_ch}章概要：{summary}")

        # 合并各批次概要
        merged_text = "\n\n".join(batch_summaries)
        book_summary = await _summarize_batch(
            merged_text, model, api_format,
            prompt_template="book_summary_merge.jinja2",
        )

    novel.book_summary = book_summary
    return book_summary


async def get_rolling_summary(
    session: AsyncSession,
    novel_id: int,
    current_chapter_number: int,
    volume: int = 1,
    max_summaries: int = 5,
) -> tuple[str, list[int]]:
    """获取最近 N 章摘要拼接（每章只取最新一条，避免重复生成导致窗口被挤压）。
    返回 (摘要文本, 包含的章节号列表)。"""
    # 子查询：每个 chapter_number 只保留 id 最大（最新）的那条
    subq = (
        select(func.max(Memory.id).label("max_id"))
        .where(
            Memory.novel_id == novel_id,
            Memory.memory_type == "chapter_summary",
            Memory.volume == volume,
            Memory.chapter_number < current_chapter_number,
        )
        .group_by(Memory.chapter_number)
        .subquery()
    )
    result = await session.execute(
        select(Memory)
        .where(Memory.id.in_(select(subq.c.max_id)))
        .order_by(Memory.chapter_number.desc())
        .limit(max_summaries)
    )
    memories = result.scalars().all()
    if not memories:
        return "", []
    chapter_nums = sorted(m.chapter_number for m in memories)
    parts = [f"第{m.chapter_number}章摘要：{m.content}" for m in reversed(memories)]
    return "\n".join(parts), chapter_nums
