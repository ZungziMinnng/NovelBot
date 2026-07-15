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
from app.models.story_thread import StoryThread
from app.models.worldview_change import WorldviewChange
from app.prompts.loader import render
from app.services import llm_client, vector_store
from app.services.context_budget import estimate_tokens
from app.services.llm_json import JsonCallError, call_json, repair_json
from app.config import settings

logger = logging.getLogger(__name__)


def _build_analysis_messages(
    prompt_prefix: str,
    content: str,
    prompt_suffix: str,
    api_format: str,
) -> list[dict]:
    """组装「分析章节内容」类任务的消息列表。

    Gemini / OpenAI / DeepSeek: 统一使用单条 user 消息，避免把正文放入 assistant/model 轮次。
    """
    return [
        {"role": "user", "content": f"{prompt_prefix}\n\n--- 章节内容 ---\n{content}\n---\n\n{prompt_suffix}"},
    ]


# ── 正文清理：截断 LLM 可能自行附加的剧情发展选项 ─────────────────────────
_PLOT_SUGGESTION_PATTERNS = re.compile(
    r'\n\s*'
    r'(?:[-=*#＃_]{2,}\s*\n\s*)?'          # 可选分隔线（--- === *** 等独占一行）
    r'(?:[#＃]{1,6}\s*)?'                   # 可选 markdown 标题井号
    r'[*【「\s]{0,3}'                       # 可选加粗 / 方括号 / 引号
    r'(?:'
    r'后续剧情选项|后续剧情发展|后续剧情走向|后续剧情方向|后续剧情|'
    r'剧情发展选项|剧情发展方向|剧情发展建议|剧情发展|'
    r'剧情走向建议|剧情走向|剧情走势|剧情选项|'
    r'下一章剧情发展|下一章可能的发展|接下来的剧情|可能的发展方向|'
    r'后续选项|发展选项|选项'
    r')'
    r'[*】」\s]{0,3}'                       # 可选加粗 / 方括号 / 引号收尾
    r'[一二三四五六七八九十\d]*'             # 可选编号（如“选项一”“选项1”）
    r'[：:\s]',
)


# 无关键词的纯编号/字母选项行：序号(1-99 / A-Z / 一~十) + 分隔符 + 实际内容
_ENUM_LINE_PATTERN = re.compile(
    r'^[*_\s]*[(（【\[]?\s*'
    r'(?P<marker>\d{1,2}|[A-Za-z]|[一二三四五六七八九十]+)'
    r'\s*[)）】\].、:：.。]\s*'
    r'\S'
)


def _marker_ordinal(marker: str) -> tuple[str, int] | None:
    """返回 (类型, 序数)。类型用于要求同一块内序号同类，避免 1./B. 混搭误判。"""
    if marker.isdigit():
        return "num", int(marker)
    cjk = "一二三四五六七八九十"  # 须在字母判断之前：中文数字在 Python 里 isalpha() 也为真
    if marker and all(ch in cjk for ch in marker):
        return "cjk", cjk.index(marker[0]) + 1  # 仅需判定起始为「一」
    if len(marker) == 1 and marker.isalpha():
        return "alpha", ord(marker.upper()) - ord("A") + 1
    return None


def _strip_trailing_enum_options(text: str) -> str:
    """去除正文末尾「无关键词的纯编号/字母选项块」。
    强约束（尽量不误删正文）：位于文本末尾、连续 ≥2 行、序号同类型、从 1/A/一 起连续递增。"""
    lines = text.rstrip().split("\n")
    collected: list[tuple[int, str, int]] = []  # (行号, 类型, 序数)，自底向上
    cut = len(lines)
    i = len(lines) - 1
    while i >= 0:
        stripped = lines[i].strip()
        if not stripped:  # 跳过尾部/块内空行
            i -= 1
            continue
        m = _ENUM_LINE_PATTERN.match(stripped)
        if not m:
            break
        parsed = _marker_ordinal(m.group("marker"))
        if parsed is None:
            break
        collected.append((i, parsed[0], parsed[1]))
        cut = i
        i -= 1

    if len(collected) < 2:
        return text
    top_down = list(reversed(collected))
    kinds = {k for _, k, _ in top_down}
    ords = [o for _, _, o in top_down]
    if len(kinds) != 1 or ords[0] != 1:
        return text
    if any(b - a != 1 for a, b in zip(ords, ords[1:])):
        return text

    # 紧邻选项块上方、以冒号收尾的短引导行（如「接下来：」）一并去除；
    # 以问号收尾的悬念句属正文，保留。
    j = cut - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j >= 0:
        lead = lines[j].strip()
        if len(lead) <= 30 and lead.rstrip("*_").endswith(("：", ":")):
            cut = j
    return "\n".join(lines[:cut]).rstrip()


def strip_plot_suggestions(text: str) -> str:
    """去除章节正文末尾 LLM 自行附加的剧情发展选项段落。
    先按关键词标题截断；再兜底去除无关键词的纯编号/字母选项块。"""
    m = _PLOT_SUGGESTION_PATTERNS.search(text)
    if m:
        text = text[:m.start()].rstrip()
    return _strip_trailing_enum_options(text)


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


# ── 本地时间推进词扫描：从章节开头判断相对上一章的天数偏移 ─────────────────
_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _parse_small_number(s: str) -> int | None:
    """解析数字或简单中文数字（一~九十九）。"""
    if s.isdigit():
        return int(s)
    if not s or any(ch not in _CN_NUM for ch in s):
        return None
    if len(s) == 1:
        return _CN_NUM[s]
    if "十" in s:
        tens_part, _, ones_part = s.partition("十")
        tens = _CN_NUM.get(tens_part, 1) if tens_part else 1
        ones = _CN_NUM.get(ones_part, 0) if ones_part else 0
        if tens > 9:
            return None
        return tens * 10 + ones
    return None


_LOCAL_NEXT_DAY_RE = re.compile(r'次日|翌日|第二天|隔日|隔天')
_LOCAL_SAME_DAY_RE = re.compile(r'当天|当日|当晚|当夜|同日|同一天')
_LOCAL_LATER_RE = re.compile(
    r'(?:半个?月|(?P<num>\d{1,3}|[一两二三四五六七八九十]{1,3})\s*(?P<unit>个月|[天日]|年))(?:之|过)?后'
)
_LATER_UNIT_DAYS = {"天": 1, "日": 1, "个月": 30, "年": 365}


def _inside_quotes(text: str, pos: int) -> bool:
    """粗判 pos 是否处于未闭合的引号内（对话中的时间词不算叙事推进）。"""
    before = text[:pos]
    for open_ch, close_ch in (("「", "」"), ("“", "”"), ("『", "』")):
        if before.count(open_ch) > before.count(close_ch):
            return True
    return False


def _detect_local_day_offset(content: str) -> int | None:
    """扫描章节开头第一段的时间推进词，返回相对上一章的天数偏移。

    只信任高置信度的显式线索（次日/三天后/当天等）；扫不到或无法量化
    （如"数日后"）时返回 None，交由 LLM 判断。"""
    head = (content or "").lstrip()
    head = head.split("\n", 1)[0][:200]
    if not head:
        return None

    candidates: list[tuple[int, int]] = []  # (位置, 偏移天数)
    for m in _LOCAL_NEXT_DAY_RE.finditer(head):
        candidates.append((m.start(), 1))
    for m in _LOCAL_SAME_DAY_RE.finditer(head):
        candidates.append((m.start(), 0))
    for m in _LOCAL_LATER_RE.finditer(head):
        if m.group("num") is None:  # 半月后 / 半个月后
            candidates.append((m.start(), 15))
            continue
        num = _parse_small_number(m.group("num"))
        if num is None:
            continue
        candidates.append((m.start(), num * _LATER_UNIT_DAYS[m.group("unit")]))

    for pos, offset in sorted(candidates):
        if not _inside_quotes(head, pos):
            return offset
    return None


def _strip_leading_time_tag(body: str) -> str:
    """去除模型仍自带的开头【…】时间标记（日期由系统统一生成）。"""
    return _TIME_TAG_PATTERN.sub("", (body or "").strip(), count=1).strip()


def _compose_summary_with_day(body: str, absolute_day: int, period: str) -> str:
    """在梗概正文前拼接系统计算的绝对日期标记。"""
    period_part = f"·{period}" if period else ""
    return f"【第{absolute_day}日{period_part}】{body}"


async def _prev_absolute_day(
    session: AsyncSession,
    novel_id: int,
    chapter_number: int,
) -> int:
    """回溯查找当前章之前最近一条带【第X日】标记的摘要，返回其绝对日数。
    首章或历史摘要均无可解析标记时返回 0。"""
    if chapter_number <= 1:
        return 0
    result = await session.execute(
        select(Memory.content, Memory.chapter_number)
        .where(
            Memory.novel_id == novel_id,
            Memory.memory_type == "chapter_summary",
            Memory.chapter_number < chapter_number,
        )
        .order_by(Memory.chapter_number.desc(), Memory.id.desc())
    )
    seen: set[int] = set()
    for content, ch_num in result:
        if ch_num in seen:  # 每章只看最新一条（id 最大）
            continue
        seen.add(ch_num)
        match = _TIME_TAG_PATTERN.match((content or "").strip())
        if match:
            day = _extract_day_number(match.group(1))
            if day is not None:
                return day
    return 0


def _day_offset_hint(chapter_number: int) -> str:
    if chapter_number > 1:
        return (
            f"\n- 这是第{chapter_number}章，前面已有章节；请判断本章相对上一章经过了多少天，"
            "填入 day_offset（同一天=0，第二天=1，跳过N天=N），不要输出绝对日期。"
        )
    return "\n- 这是第1章，day_offset 请填 0。"


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

    # 回溯上一章的绝对日期，供代码确定性累加（模型只判断相对偏移 day_offset）
    prev_day = await _prev_absolute_day(session, novel.id, chapter.number)
    prompt_prefix = render("chapter_summary_prefix.jinja2") + _day_offset_hint(chapter.number)
    messages = _build_analysis_messages(
        prompt_prefix, clean_content[:12000],
        render("chapter_summary_suffix.jinja2"), api_format,
    )
    raw_summary, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=2000,
    )
    body, importance, day_offset, period = _parse_summary_payload(raw_summary)
    body = _strip_leading_time_tag(_clean_summary(body))

    # 检测输出截断：正文未以正常标点结尾，说明被中途截断（token 耗尽或安全过滤）
    _s = body.strip()
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
                "请为一部小说章节写一段200字以内的剧情梗概，并判断本章相对上一章经过的天数。\n"
                "只输出 JSON：{\"day_offset\": 0, \"period\": \"\", \"summary\": \"梗概正文\", \"importance\": 3}\n"
                "day_offset：同一天=0，第二天=1，跳过N天=N；正文中不要出现【第X日】等时间标记。"
            ),
            clean_content[:4000],
            "请基于以上内容输出 JSON：",
            api_format,
        )
        retry_raw, retry_in, retry_out = await llm_client.dispatch_chat_complete_with_usage(
            messages=retry_messages,
            model=model,
            api_format=api_format,
            temperature=0.1,
            max_tokens=2000,
        )
        in_tok += retry_in
        out_tok += retry_out
        r_body, r_imp, r_offset, r_period = _parse_summary_payload(retry_raw)
        r_body = _strip_leading_time_tag(_clean_summary(r_body))
        if r_body.strip() and len(r_body.strip()) > len(body.strip()):
            logger.info(
                "章节 %s 脱敏重试成功 (len=%d → %d)",
                chapter.number, len(body.strip()), len(r_body.strip()),
            )
            body, importance, day_offset, period = r_body, r_imp, r_offset, r_period
        else:
            logger.warning(
                "章节 %s 脱敏重试未改善 (original=%d, retry=%d)",
                chapter.number, len(body.strip()), len(r_body.strip()),
            )

    # LLM 返回空字符串时（内容过滤等），跳过保存，避免创建空 Memory 行
    if not body.strip():
        return "", in_tok, out_tok

    summary = await _persist_summary(
        session, chapter, novel, body, importance, day_offset, period, prev_day, clean_content,
    )
    return summary, in_tok, out_tok


async def _persist_summary(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    body: str,
    importance: int,
    day_offset: int,
    period: str,
    prev_day: int,
    clean_content: str,
) -> str:
    """时间线判定 + 摘要落库（章节字段 / Memory 表 / 向量库）。返回最终摘要文本。"""
    # 本地时间线索优先：章节开头有显式时间推进词（次日/三天后/当天等）时，
    # 用代码判定覆盖 LLM 的 day_offset；扫不到线索才信 LLM
    local_offset = _detect_local_day_offset(clean_content)
    if local_offset is not None:
        if local_offset != day_offset:
            logger.info(
                "章节 %s day_offset 本地判定 %d 覆盖 LLM 判定 %d",
                chapter.number, local_offset, day_offset,
            )
        day_offset = local_offset

    # 代码确定性累加绝对日期：单调不减，首章/无历史标记时锚定第1日
    absolute_day = prev_day + max(0, day_offset) if prev_day > 0 else 1
    summary = _compose_summary_with_day(body, absolute_day, period)

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
        importance=importance,
    )
    session.add(memory)

    # 存入向量库（异步，不阻塞事件循环）
    # 先确保加载小说配置的嵌入模型：冷缓存时回退默认模型会导致维度不匹配。
    try:
        await vector_store.ensure_embedding_configured(novel.id, session)
    except Exception:
        logger.warning("章节 %s 摘要嵌入模型配置加载失败，回退默认模型", chapter.number, exc_info=True)

    # 向量写入失败不应回滚摘要落库（与实体向量同步策略一致），否则会连带
    # 触发 confirm 流程后续步骤在已过期 ORM 对象上的 greenlet 错误。
    doc_id = f"chapter_{chapter.id}_summary"
    try:
        await vector_store.astore_text(
            novel_id=novel.id,
            doc_id=doc_id,
            text=summary,
            metadata={
                "type": "chapter_summary",
                "volume": chapter.volume,
                "chapter_number": chapter.number,
                "importance": importance,
            },
        )
        memory.embedding_id = doc_id
    except Exception:
        logger.warning(
            "章节 %s 摘要向量写入失败（摘要已保存，可稍后 reindex 重建）",
            chapter.number, exc_info=True,
        )
    return summary


_DISCOVER_KEYS = ("characters", "entities", "locations", "techniques", "factions")

# 长期事实（伏笔/秘密）自动提取：kind 归一化 + 每章条数上限
_THREAD_KIND_MAP = {
    "secret": "secret", "秘密": "secret", "谎言": "secret",
    "foreshadowing": "foreshadowing", "伏笔": "foreshadowing",
    "承诺": "foreshadowing", "处置": "foreshadowing",
}
_MAX_THREADS_PER_CHAPTER = 2


async def _save_extracted_threads(
    session: AsyncSession,
    novel_id: int,
    chapter_number: int,
    raw_threads,
    stale_auto: list[StoryThread],
    dedup_pool: list[StoryThread],
) -> None:
    """把合并调用里提取的长期事实写入伏笔/秘密库（source='auto'）。

    raw_threads 不是列表（模型未按新格式输出）时不做任何事；
    是列表时视为提取已生效——先删本章旧的 auto 活跃条目（重新生成后已过期），
    再与库内其余条目按标题/内容互含去重后插入。
    """
    if not isinstance(raw_threads, list):
        return
    saved: list[StoryThread] = []
    for t in raw_threads:
        if len(saved) >= _MAX_THREADS_PER_CHAPTER:
            break
        if not isinstance(t, dict):
            continue
        kind = _THREAD_KIND_MAP.get(str(t.get("kind") or "").strip().lower())
        content = str(t.get("content") or "").strip()
        if not kind or not content:
            continue
        title = str(t.get("title") or "").strip()[:50]
        try:
            imp = max(1, min(5, int(round(float(t.get("importance", 3))))))
        except (TypeError, ValueError):
            imp = 3
        known_by = (
            [str(n).strip() for n in (t.get("known_by") or []) if str(n).strip()]
            if kind == "secret" and isinstance(t.get("known_by"), list) else []
        )
        dup = False
        for e in dedup_pool + saved:
            e_title = ((e.title or "")).strip()
            e_content = (e.content or "").strip()
            if (title and title == e_title) or (e_content and (content in e_content or e_content in content)):
                dup = True
                break
        if dup:
            continue
        saved.append(StoryThread(
            novel_id=novel_id,
            kind=kind,
            title=title,
            content=content,
            importance=imp,
            known_by=known_by,
            source_chapter=chapter_number,
            source="auto",
        ))
    for stale in stale_auto:
        await session.delete(stale)
    for thread in saved:
        session.add(thread)
    if saved:
        logger.info(
            "章节 %s 自动提取 %d 条长期事实: %s",
            chapter_number, len(saved), "；".join(t.title or t.content[:20] for t in saved),
        )


def _fmt_known(names: list[str]) -> str:
    return "、".join(names) if names else "（暂无）"


async def summarize_and_discover(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    *,
    known_char_names: list[str],
    known_entity_names: list[str],
    known_locations: list[dict],
    known_tech_names: list[str],
    known_faction_names: list[str],
) -> tuple[str, dict | None, int, int]:
    """单次 LLM 调用同时生成章节摘要 + 发现五类新设定候选。

    返回 (summary, discovered_raw | None, input_tokens, output_tokens)。
    discovered_raw 为 LLM 原始输出的五类候选 dict（未过滤已知名称）；
    合并调用失败或摘要为空/截断时降级为纯摘要路径，discovered_raw 返回 None。
    """
    if not chapter.content.strip():
        return "", None, 0, 0

    clean_content = strip_plot_suggestions(chapter.content)
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prev_day = await _prev_absolute_day(session, novel.id, chapter.number)

    loc_str = (
        "、".join(f"{l['name']}({l['type']})" for l in known_locations)
        if known_locations else "（暂无）"
    )

    # 已有伏笔/秘密条目：本章旧的 auto 活跃条目（重新生成后过期，稍后删除重提）
    # 不进提示词和去重池，否则 regen 时同一事实会被去重拦下、随删除一起丢失
    existing_threads = (await session.execute(
        select(StoryThread).where(
            StoryThread.novel_id == novel.id,
            StoryThread.status != "abandoned",
        )
    )).scalars().all()
    stale_auto = [
        t for t in existing_threads
        if t.source == "auto" and t.source_chapter == chapter.number and t.status == "active"
    ]
    dedup_pool = [t for t in existing_threads if t not in stale_auto]

    prompt_prefix = render(
        "chapter_summary_discover_prefix.jinja2",
        known_characters=_fmt_known(known_char_names),
        known_entities=_fmt_known(known_entity_names),
        known_locations=loc_str,
        known_techniques=_fmt_known(known_tech_names),
        known_factions=_fmt_known(known_faction_names),
        known_threads="；".join(
            (t.title or (t.content or "")[:20]) for t in dedup_pool
        ) or "（暂无）",
    ) + _day_offset_hint(chapter.number)
    messages = _build_analysis_messages(
        prompt_prefix, clean_content[:12000],
        render("chapter_summary_discover_suffix.jinja2"), api_format,
    )

    try:
        data, in_tok, out_tok = await call_json(
            messages, model, api_format,
            temperatures=(0.3, 0.1), max_tokens=3000,
        )
    except JsonCallError as e:
        logger.warning("章节 %s 合并摘要+发现调用失败，降级为纯摘要: %s", chapter.number, e)
        summary, s_in, s_out = await summarize_chapter(session, chapter, novel)
        return summary, None, e.input_tokens + s_in, e.output_tokens + s_out

    body = _strip_leading_time_tag(_clean_summary(str(data.get("summary") or "").strip()))
    _s = body.strip()
    if not _s or _s[-1] not in '。！？…」】':
        # 摘要为空或疑似截断：整体降级为纯摘要路径（其内部含截断重试），发现结果丢弃
        logger.warning(
            "章节 %s 合并调用摘要为空或疑似截断 (len=%d)，降级为纯摘要", chapter.number, len(_s),
        )
        summary, s_in, s_out = await summarize_chapter(session, chapter, novel)
        return summary, None, in_tok + s_in, out_tok + s_out

    importance, day_offset, period = _coerce_summary_fields(data)
    summary = await _persist_summary(
        session, chapter, novel, body, importance, day_offset, period, prev_day, clean_content,
    )
    await _save_extracted_threads(
        session, novel.id, chapter.number, data.get("threads"), stale_auto, dedup_pool,
    )
    discovered = {k: data.get(k) if isinstance(data.get(k), list) else [] for k in _DISCOVER_KEYS}
    return summary, discovered, in_tok, out_tok


def _coerce_summary_fields(data: dict) -> tuple[int, int, str]:
    """从摘要 JSON 中提取并规整 (importance, day_offset, period)。"""
    try:
        imp = int(round(float(data.get("importance", 3))))
    except (TypeError, ValueError):
        imp = 3
    imp = max(1, min(5, imp))
    try:
        offset = int(round(float(data.get("day_offset", 0))))
    except (TypeError, ValueError):
        offset = 0
    period = str(data.get("period") or "").strip()
    return imp, max(0, offset), period


def _parse_summary_payload(raw: str) -> tuple[str, int, int, str]:
    """解析章节摘要 LLM 的 JSON 输出 {summary, importance, day_offset, period}。
    返回 (summary, importance, day_offset, period)。失败时回退为
    「整段文本 + 中性分3 + 偏移0 + 空时段」，保证核心摘要路径不因 JSON 解析失败而中断。"""
    try:
        data = json.loads(repair_json(raw))
        if isinstance(data, dict) and "summary" in data:
            summary = str(data.get("summary") or "").strip()
            imp, offset, period = _coerce_summary_fields(data)
            if summary:
                return summary, imp, offset, period
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return raw.strip(), 3, 0, ""


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


def _char_titles(c: Character) -> list:
    titles = (c.current_state or {}).get("titles")
    return titles if isinstance(titles, list) else []


def _filter_mentioned(items: list, text: str, aliases_of=None) -> list:
    """只保留名字（或称谓别名）出现在正文里的条目，控制状态更新的输入成本。
    未点名的条目本章状态基本不会变，不再全量发给 LLM。"""
    out = []
    for it in items:
        names = [it.name]
        if aliases_of is not None:
            names.extend(aliases_of(it))
        if any(isinstance(n, str) and n.strip() and n in text for n in names):
            out.append(it)
    return out


async def update_character_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    instruction: str = "",
) -> tuple[bool, str, int, int, list[str], list[int]]:
    """根据章节内容更新角色状态卡。
    返回 (success, warning_message, input_tokens, output_tokens, unmatched_names, updated_ids)。
    """
    result = await session.execute(
        select(Character).where(Character.novel_id == novel.id)
    )
    all_characters = result.scalars().all()
    if not all_characters:
        return True, "", 0, 0, [], []

    chapter_content = strip_plot_suggestions(chapter.content)[:12000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    # 只发本章点名（含称谓）的角色状态；一个都没命中就跳过调用
    characters = _filter_mentioned(all_characters, chapter_content, _char_titles)
    if not characters:
        return True, "", 0, 0, [], []

    states_text = json.dumps(
        {c.name: c.current_state for c in characters},
        ensure_ascii=False,
        indent=2,
    )
    # 字段词表取全库，保持字段命名跨章一致
    existing_fields = sorted({
        str(key)
        for c in all_characters
        if isinstance(c.current_state, dict)
        for key in c.current_state.keys()
        if str(key).strip()
    })
    state_fields = "、".join(existing_fields) if existing_fields else "暂无，按本章明确变化创建必要字段"
    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt_prefix = render(
        "character_update_prefix.jinja2",
        character_states=states_text,
        state_fields=state_fields,
    )

    messages = _build_analysis_messages(
        prompt_prefix, chapter_content, render("character_update_suffix.jinja2"), api_format,
    )

    try:
        updates, total_in, total_out = await call_json(
            messages, model, api_format,
            temperatures=(0.2, 0.1), max_tokens=1500,
        )
    except JsonCallError as e:
        return False, f"角色状态更新：LLM 调用/解析失败（含重试）({e})", e.input_tokens, e.output_tokens, [], []

    char_map = {c.name: c for c in characters}
    unmatched = []
    matched_count = 0
    updated_ids: list[int] = []
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
        updated_ids.append(char_map[target_name].id)

    warning = ""
    if unmatched:
        warning = f"角色状态更新：以下名称未匹配到角色库 [{', '.join(unmatched)}]"
    if matched_count == 0 and not unmatched:
        warning = "角色状态更新：LLM 未返回任何角色状态数据"
    return True, warning, total_in, total_out, unmatched, updated_ids


def _trim_entity_state(state: dict, limit: int = 300) -> None:
    """确保实体状态的文本内容总长不超过 limit 字。"""
    total = sum(len(str(v)) for v in state.values())
    if total <= limit:
        return
    overflow = total - limit
    for key in ("recent_changes", "level", "owner"):
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


# 旧版每章全量重写字段已废弃（与静态描述/属性重复），落库时顺带清理
_OBSOLETE_ENTITY_STATE_KEYS = ("description", "new_abilities", "level_changes")


def _apply_entity_updates(entities, updates: dict) -> tuple[int, list[str], list[int]]:
    """将 LLM 输出的实体状态合并入库，返回 (matched_count, unmatched_names, updated_ids)。"""
    entity_map = {e.name: e for e in entities}
    for e in entities:
        st = e.current_state or {}
        if any(k in st for k in _OBSOLETE_ENTITY_STATE_KEYS):
            for k in _OBSOLETE_ENTITY_STATE_KEYS:
                st.pop(k, None)
            e.current_state = st
            flag_modified(e, "current_state")

    unmatched = []
    matched_count = 0
    updated_ids: list[int] = []
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
        for k in _OBSOLETE_ENTITY_STATE_KEYS:
            merged.pop(k, None)
        _trim_entity_state(merged)
        entity_map[target_name].current_state = merged
        flag_modified(entity_map[target_name], "current_state")
        matched_count += 1
        updated_ids.append(entity_map[target_name].id)
    return matched_count, unmatched, updated_ids


def _apply_location_updates(locations, updates: dict) -> tuple[int, list[str], list[int]]:
    """将 LLM 输出的地点状态合并入库，返回 (matched_count, unmatched_names, updated_ids)。"""
    location_map = {l.name: l for l in locations}
    unmatched = []
    matched_count = 0
    updated_ids: list[int] = []
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
        updated_ids.append(location_map[target_name].id)
    return matched_count, unmatched, updated_ids


async def update_entity_location_states(
    session: AsyncSession,
    chapter: Chapter,
    novel: Novel,
    instruction: str = "",
) -> dict:
    """单次 LLM 调用同时更新世界实体（道具/系统）与地点状态。

    返回 {
        "entity": {"ok": bool, "warning": str, "unmatched": list[str], "updated_ids": list[int]},
        "location": {"ok": bool, "warning": str, "unmatched": list[str], "updated_ids": list[int]},
        "input_tokens": int, "output_tokens": int,
    }
    """
    def _section(ok: bool = True, warning: str = "", unmatched: list[str] | None = None,
                 updated_ids: list[int] | None = None) -> dict:
        return {"ok": ok, "warning": warning, "unmatched": unmatched or [], "updated_ids": updated_ids or []}

    def _result(entity: dict, location: dict, in_tok: int = 0, out_tok: int = 0) -> dict:
        return {"entity": entity, "location": location, "input_tokens": in_tok, "output_tokens": out_tok}

    ent_result = await session.execute(
        select(WorldEntity).where(WorldEntity.novel_id == novel.id)
    )
    entities = ent_result.scalars().all()
    loc_result = await session.execute(
        select(Location).where(Location.novel_id == novel.id)
    )
    locations = loc_result.scalars().all()
    if not entities and not locations:
        return _result(_section(), _section())

    chapter_content = strip_plot_suggestions(chapter.content)[:12000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    # 只发本章点名的实体/地点状态；全都没命中就跳过调用
    entities = _filter_mentioned(entities, chapter_content)
    locations = _filter_mentioned(locations, chapter_content)
    if not entities and not locations:
        return _result(_section(), _section())

    entity_states = json.dumps(
        {e.name: {"type": e.type, **(e.current_state or {})} for e in entities},
        ensure_ascii=False,
        indent=2,
    ) if entities else ""
    location_states = json.dumps(
        {l.name: {"type": l.type, **(l.current_state or {})} for l in locations},
        ensure_ascii=False,
        indent=2,
    ) if locations else ""

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt_prefix = render(
        "entity_location_update_prefix.jinja2",
        entity_states=entity_states,
        location_states=location_states,
    )

    messages = _build_analysis_messages(
        prompt_prefix, chapter_content, render("entity_location_update_suffix.jinja2"), api_format,
    )

    try:
        updates, total_in, total_out = await call_json(
            messages, model, api_format,
            temperatures=(0.2, 0.1), max_tokens=2000,
        )
    except JsonCallError as e:
        msg = f"实体/地点状态更新：LLM 调用/解析失败（含重试）({e})"
        return _result(_section(False, msg), _section(False, msg), e.input_tokens, e.output_tokens)

    ent_updates = updates.get("entities")
    loc_updates = updates.get("locations")
    ent_updates = ent_updates if isinstance(ent_updates, dict) else {}
    loc_updates = loc_updates if isinstance(loc_updates, dict) else {}

    entity_section = _section()
    if entities:
        matched, unmatched, updated_ids = _apply_entity_updates(entities, ent_updates)
        warning = ""
        if unmatched:
            warning = f"实体状态更新：以下名称未匹配到实体库 [{', '.join(unmatched)}]"
        entity_section = _section(True, warning, unmatched, updated_ids)

    location_section = _section()
    if locations:
        matched, unmatched, updated_ids = _apply_location_updates(locations, loc_updates)
        warning = ""
        if unmatched:
            warning = f"地点状态更新：以下名称未匹配到地点库 [{', '.join(unmatched)}]"
        location_section = _section(True, warning, unmatched, updated_ids)

    return _result(entity_section, location_section, total_in, total_out)


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


BATCH_SIZE = 50  # 每批最多处理 50 章摘要


def _book_summary_max_tokens(chapter_count: int) -> int:
    """全书概要的输出预算随篇幅增长：基础 2000，每满 50 章加 500。"""
    return 2000 + (max(0, chapter_count) // 50) * 500


async def _summarize_batch(
    summaries_text: str,
    model: str,
    api_format: str,
    prompt_template: str = "book_summary.jinja2",
    max_tokens: int = 2000,
) -> str:
    """用指定 prompt 模板对一段摘要文本做概要"""
    prompt = render(prompt_template, summaries=summaries_text)
    return await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=max_tokens,
    )


async def generate_book_summary(
    session: AsyncSession,
    novel: "Novel",  # noqa: F821
    window: tuple[int, int] | None = None,
) -> str:
    """将所有章节摘要整合成全书概要，存入 novel.book_summary。

    window=(start_ch, end_ch) 且已有概要时走增量路径：旧概要 + 窗口内新章摘要 →
    更新版概要，成本与总章数无关。增量前提不满足（无旧概要/窗口无摘要/输出为空）
    自动退回全量重建。

    全量路径：优先使用弧摘要（arc_summary）减少压缩层级；若无弧摘要则回退到章节摘要。
    当摘要数超过 BATCH_SIZE 时，自动分批概括再整合，支持百章级别。"""
    if window and (novel.book_summary or "").strip():
        start_ch, end_ch = window
        window_result = await session.execute(
            select(Memory)
            .where(
                Memory.novel_id == novel.id,
                Memory.memory_type == "chapter_summary",
                Memory.chapter_number >= start_ch,
                Memory.chapter_number <= end_ch,
            )
            .order_by(Memory.chapter_number.asc(), Memory.id.asc())
        )
        latest_by_chapter: dict[int, Memory] = {
            m.chapter_number: m for m in window_result.scalars().all()
        }
        if latest_by_chapter:
            new_summaries = "\n".join(
                f"第{n}章：{latest_by_chapter[n].content}"
                for n in sorted(latest_by_chapter)
            )
            model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
            prompt = render(
                "book_summary_update.jinja2",
                old_summary=novel.book_summary,
                new_summaries=new_summaries,
            )
            updated = (await llm_client.dispatch_chat_complete(
                messages=[{"role": "user", "content": prompt}],
                model=model,
                api_format=api_format,
                temperature=0.3,
                max_tokens=_book_summary_max_tokens(end_ch),
            )).strip()
            if updated:
                novel.book_summary = updated
                return updated

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
    budget = _book_summary_max_tokens(max((m.chapter_number or 0) for m in memories))

    if len(memories) <= BATCH_SIZE:
        # 少量章节：单次生成
        summaries_text = "\n".join(
            f"第{m.chapter_number}章：{m.content}" for m in memories
        )
        book_summary = await _summarize_batch(summaries_text, model, api_format, max_tokens=budget)
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
            max_tokens=budget,
        )

    novel.book_summary = book_summary
    return book_summary


async def detect_worldview_drift(
    session: AsyncSession,
    novel: "Novel",  # noqa: F821
    recent: int = 10,
) -> list[dict]:
    """AI 检测：找出原世界观设定中被近期剧情推翻/取代的条目。

    对比原 core_setting + 已有变更 + 最近 N 章摘要，返回 list[dict]
    （fact / supersedes / effective_chapter）。只返回，不落库；
    去重与写入由调用方通过 persist_pending_drifts 处理。
    """
    if not (novel.core_setting or "").strip():
        return []

    # 最近 N 章摘要（每章取最新一条）
    rolling_text, rolling_nums = await get_rolling_summary(
        session, novel.id, novel.current_chapter + 1,
        volume=novel.current_volume, max_summaries=recent,
    )
    if not rolling_text.strip():
        return []

    existing = (await session.execute(
        select(WorldviewChange).where(WorldviewChange.novel_id == novel.id)
    )).scalars().all()
    existing_text = "\n".join(f"- {c.fact}" for c in existing) or "（暂无）"

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    prompt = render(
        "worldview_drift.jinja2",
        core_setting=novel.core_setting,
        existing_changes=existing_text,
        recent_summaries=rolling_text,
    )
    messages = [{"role": "user", "content": prompt}]

    # 模板要求输出 JSON 数组，expect="array" 才能正确提取（旧版按对象提取导致数组输出被剥坏）
    try:
        parsed, _, _ = await call_json(
            messages, model, api_format,
            temperatures=(0.2, 0.1), max_tokens=1500, expect="array",
        )
    except JsonCallError as e:
        logger.warning("世界观漂移检测失败: %s", e)
        return []

    drifts: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        if not fact:
            continue
        try:
            eff = int(item.get("effective_chapter") or 0)
        except (TypeError, ValueError):
            eff = 0
        drifts.append({
            "fact": fact,
            "supersedes": str(item.get("supersedes") or "").strip(),
            "effective_chapter": eff,
        })
    return drifts


async def persist_pending_drifts(
    session: AsyncSession,
    novel_id: int,
    drifts: list[dict],
) -> list[WorldviewChange]:
    """把检测到的漂移以 status=pending/source=ai 写入，跳过 fact 文本重复的项。

    不 commit，由调用方提交。"""
    if not drifts:
        return []
    existing_facts = {
        f.strip() for (f,) in (await session.execute(
            select(WorldviewChange.fact).where(WorldviewChange.novel_id == novel_id)
        )).all()
    }
    new_rows: list[WorldviewChange] = []
    for d in drifts:
        fact = d["fact"].strip()
        if fact in existing_facts:
            continue
        existing_facts.add(fact)
        row = WorldviewChange(
            novel_id=novel_id,
            fact=fact,
            supersedes=d.get("supersedes", ""),
            effective_chapter=d.get("effective_chapter", 0),
            status="pending",
            source="ai",
        )
        session.add(row)
        new_rows.append(row)
    return new_rows


async def get_rolling_summary(
    session: AsyncSession,
    novel_id: int,
    current_chapter_number: int,
    volume: int = 1,
    max_summaries: int = 5,
    token_budget: int | None = None,
    min_summaries: int = 3,
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

    selected: list[Memory] = []
    used_tokens = 0
    minimum = min(max_summaries, max(0, min_summaries))
    for memory in memories:  # newest -> oldest
        part = f"第{memory.chapter_number}章摘要：{memory.content}"
        part_tokens = estimate_tokens(part)
        if token_budget and selected and used_tokens + part_tokens > token_budget and len(selected) >= minimum:
            break
        selected.append(memory)
        used_tokens += part_tokens

    chapter_nums = sorted(m.chapter_number for m in selected)
    parts = [f"第{m.chapter_number}章摘要：{m.content}" for m in reversed(selected)]
    return "\n".join(parts), chapter_nums
