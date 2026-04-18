import json
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, func
from sqlalchemy.orm.attributes import flag_modified
from app.models.chapter import Chapter
from app.models.memory import Memory, Outline
from app.models.character import Character
from app.models.novel import Novel
from app.services import llm_client, vector_store
from app.config import settings


CHAPTER_SUMMARY_PROMPT_PREFIX = """请将以下章节内容压缩为250字以内的情节摘要。

输出规范（严格遵守）：
- 只描述：人物去了哪里、做了什么决定、获得了什么信息、情节如何推进
- 涉及亲密或暴力场景时，只写结果，不写任何过程细节
- 若出现任何露骨词汇或动作描写，可改写或者减弱程度
- 使用编辑/编剧视角的中性叙述语言"""

CHAPTER_SUMMARY_PROMPT_SUFFIX = "只输出摘要文本，不要任何前缀或说明。"


CHARACTER_UPDATE_PROMPT_PREFIX = """根据以下章节内容，更新角色状态卡。

输出规范（严格遵守）：
- 所有字段使用编辑/编剧视角的中性事实语言
- 涉及亲密关系：只写"与X发生了亲密关系"或"与X关系发生变化"，不写任何细节
- 涉及暴力/对抗：只写"击败/控制了X"，不写过程
- 禁止出现任何露骨词汇、动作描写或场景描述
- 只提取对后续剧情有影响的状态变化（位置、目标、已知秘密、关系结果）

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
    "relationship_changes": {"其他角色名": "关系描述"}
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

    model, api_format = llm_client.get_agent_client("memory", novel.fast_model)
    # 章节原文放入 assistant 消息（Gemini model 角色），避免触发 PROHIBITED_CONTENT 过滤。
    messages = [
        {"role": "user", "content": CHAPTER_SUMMARY_PROMPT_PREFIX},
        {"role": "assistant", "content": f"--- 章节内容 ---\n{chapter.content[:6000]}\n---"},
        {"role": "user", "content": CHAPTER_SUMMARY_PROMPT_SUFFIX},
    ]
    summary, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=0.3,
        max_tokens=500,
    )

    # 保存摘要到章节
    chapter.summary = summary
    chapter.word_count = len(chapter.content)

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
    await vector_store.astore_text(
        novel_id=novel.id,
        doc_id=f"chapter_{chapter.id}_summary",
        text=summary,
        metadata={
            "type": "chapter_summary",
            "volume": chapter.volume,
            "chapter_number": chapter.number,
        },
    )
    # 原文分段批量存入向量库（每500字一段，单次 upsert）
    chunks = [chapter.content[i:i+500] for i in range(0, len(chapter.content), 500)]
    batch_items = [
        (
            f"chapter_{chapter.id}_chunk_{idx}",
            chunk,
            {"type": "chapter_content", "volume": chapter.volume, "chapter_number": chapter.number},
        )
        for idx, chunk in enumerate(chunks)
    ]
    await vector_store.astore_texts_batch(novel.id, batch_items)
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
    prompt_prefix = CHARACTER_UPDATE_PROMPT_PREFIX.format(character_states=states_text)
    # 章节原文放入 assistant 消息（Gemini model 角色），避免触发 PROHIBITED_CONTENT 过滤。
    chapter_content = chapter.content[:6000]
    if instruction:
        chapter_content = f"[写作指令参考：{instruction}]\n\n{chapter_content}"

    messages = [
        {"role": "user", "content": prompt_prefix},
        {"role": "assistant", "content": f"--- 章节内容 ---\n{chapter_content}\n---"},
        {"role": "user", "content": CHARACTER_UPDATE_PROMPT_SUFFIX},
    ]

    total_in, total_out = 0, 0
    try:
        raw, in_tok, out_tok = await llm_client.dispatch_chat_complete_with_usage(
            messages=messages,
            model=model,
            api_format=api_format,
            temperature=0.2,
            max_tokens=800,
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
                max_tokens=800,
            )
            total_in += in_tok
            total_out += out_tok
            json_text = _repair_json(raw)
            updates = json.loads(json_text)
        except Exception as e:
            return False, f"角色状态更新：JSON 解析失败（含重试）({e})", total_in, total_out

    if not isinstance(updates, dict):
        return False, "角色状态更新：LLM 返回的 JSON 不是对象类型", total_in, total_out

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
        for key, val in state.items():
            if isinstance(val, list):
                # list 字段保序去重合并（known_secrets, titles 等）
                old_val = existing.get(key, [])
                old_list = old_val if isinstance(old_val, list) else [old_val] if old_val else []
                combined = list(dict.fromkeys(old_list + val))
                # known_secrets 只保留最近 10 条，避免无限膨胀
                if key == "known_secrets" and len(combined) > 10:
                    combined = combined[-10:]
                merged[key] = combined
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
    return True, warning, total_in, total_out


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
    prompt_template: str = BOOK_SUMMARY_PROMPT,
) -> str:
    """用指定 prompt 模板对一段摘要文本做概要"""
    prompt = prompt_template.format(summaries=summaries_text)
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
    当章节数超过 BATCH_SIZE 时，自动分批概括再整合，支持百章级别。"""
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
            prompt_template=BOOK_SUMMARY_MERGE_PROMPT,
        )

    novel.book_summary = book_summary
    return book_summary


async def get_rolling_summary(
    session: AsyncSession,
    novel_id: int,
    current_chapter_number: int,
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
