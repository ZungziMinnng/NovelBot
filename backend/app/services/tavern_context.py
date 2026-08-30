"""酒馆模式的上下文组装与两层记忆。

安全底线：card.creator_note 是"AI 不会看到的介绍"，本模块的任何返回值里都不能出现它。
test_tavern.py 用哨兵串守这一条。
"""
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tavern import (
    TavernCard, TavernMessage, TavernRule, TavernSession, TavernWorldEntry,
)
from app.prompts.loader import render
from app.services import llm_client
from app.services.context_budget import estimate_tokens, truncate_to_token_budget

logger = logging.getLogger(__name__)

# system prompt 与摘要各自的上限，避免一条超长世界书词条把窗口挤爆
SYSTEM_TOKEN_BUDGET = 8000
SUMMARY_TOKEN_BUDGET = 2000

# 群聊里这两块会随人数膨胀，先各自限额再拼。
# 不这么做的话总量超标时会从尾部截断，先切掉的正好是排在最后的规则和此前剧情
ONSTAGE_TOKEN_BUDGET = 1500
WORLD_TOKEN_BUDGET = 3000

_PLACEHOLDER_CHAR = re.compile(r"\{\{\s*char\s*\}\}", re.IGNORECASE)
_PLACEHOLDER_USER = re.compile(r"\{\{\s*user\s*\}\}", re.IGNORECASE)

DEFAULT_PERSONA_NAME = "user"


def substitute(text: str, char_name: str, persona_name: str) -> str:
    """{{char}} / {{user}} 替换。卡文本与消息都存原文，只在出库时替换。

    这样改了 persona 名字后历史消息跟着变，不会出现半场换名。
    """
    if not text:
        return ""
    return _PLACEHOLDER_USER.sub(
        persona_name.strip() or DEFAULT_PERSONA_NAME,
        _PLACEHOLDER_CHAR.sub(char_name or "", text),
    )


async def resolve_rules(
    session: AsyncSession, user_id: int | None, ids: list[int]
) -> str:
    """按卡上勾选的 id 拼酒馆规则，无兜底——空就是空。

    与小说侧 prompt_rules.resolve_rules_block 的区别：那边 NULL 要回退到内置护栏，
    因为老书原本就有护栏、静默丢了用户不会立刻发现。酒馆默认就是不注入。
    """
    if not ids:
        return ""
    wanted = {int(i) for i in ids}
    rules = (await session.execute(
        select(TavernRule)
        .where(TavernRule.user_id == user_id, TavernRule.enabled.is_(True))
        .order_by(TavernRule.sort_order, TavernRule.id)
    )).scalars().all()
    return "\n\n".join(
        r.content.strip() for r in rules if r.id in wanted and r.content.strip()
    )


_KEYWORD_SEP = re.compile(r"[,，、;；\n]+")


def _keywords_of(entry: TavernWorldEntry) -> list[str]:
    """关键词切分。顿号和分号也算分隔符——中文里列举词条本来就爱用顿号，
    只认逗号会让"十六岁、男婴"变成一个永远匹配不上的长串。
    """
    return [k.strip() for k in _KEYWORD_SEP.split(entry.keywords or "") if k.strip()]


def triggered_entries(
    entries: list[TavernWorldEntry], scan_text: str
) -> list[TavernWorldEntry]:
    """本轮生效的词条：常驻的全要，其余看关键词是否命中。

    用子串匹配而不是分词：世界书关键词是用户逐条写死的，"出现这个词就触发"才是他的
    预期，也才可预测。分词会带来"为什么这条没触发"这种没法解释的行为。
    """
    haystack = (scan_text or "").lower()
    hits = []
    for entry in entries:
        if not entry.enabled or not (entry.content or "").strip():
            continue
        if getattr(entry, "constant", False):
            hits.append(entry)
        elif haystack and any(kw.lower() in haystack for kw in _keywords_of(entry)):
            hits.append(entry)
    return hits


def _build_example_turns(examples, sub) -> list[dict]:
    """对话示例转成真实的 few-shot 消息轮，两端都有内容才算一组。

    形状与小说侧 writer._build_example_turns 一致。
    """
    turns = []
    for ex in examples or []:
        u = sub((ex.get("user") or "").strip())
        a = sub((ex.get("assistant") or "").strip())
        if u and a:
            turns.append({"role": "user", "content": u})
            turns.append({"role": "assistant", "content": a})
    return turns


def _example_text(card: TavernCard, sub) -> str:
    """多卡时的说话样例：写成一段文字而不是真实的 few-shot 轮。

    真实轮在群聊里会串味——模型看到"user/assistant"交替的样例，会把别人的台词
    也当成自己该写的部分。文字引用定腔调的效果弱一些，但不会让角色互相染上语气。
    """
    pairs = []
    for ex in card.dialogue_examples or []:
        u = sub((ex.get("user") or "").strip())
        a = sub((ex.get("assistant") or "").strip())
        if u and a:
            pairs.append(f"对方：{u}\n{card.name}：{a}")
    if not pairs:
        return ""
    return f"【{card.name}的说话样例】\n" + "\n\n".join(pairs)


async def _world_book_cards(
    session: AsyncSession, cards: list[TavernCard]
) -> dict[int, TavernCard]:
    """要一起匹配世界书的卡：参与卡自己的，加上它们引用的。

    引用的卡必须同属主——否则填一个别人的 card_id 就能把别人的世界书读出来。
    返回 {card_id: card}，词条正文要按所属卡替换 {{char}}。
    """
    out = {c.id: c for c in cards}
    linked = {
        int(i) for c in cards for i in (getattr(c, "linked_book_card_ids", None) or [])
    } - set(out)
    if not linked:
        return out
    owners = {c.user_id for c in cards}
    rows = (await session.execute(
        select(TavernCard).where(TavernCard.id.in_(linked))
    )).scalars().all()
    for row in rows:
        if row.user_id in owners:
            out[row.id] = row
    return out


def _history_window(
    card: TavernCard, sess: TavernSession, history: list[TavernMessage]
) -> list[TavernMessage]:
    """发原文的窗口：已压缩进 summary 的消息不再重复发。"""
    upto = sess.summarized_upto_id or 0
    limit = max(1, card.context_turns or 20) * 2
    return [m for m in history if m.id > upto][-limit:]


async def build_tavern_messages(
    session: AsyncSession,
    cards: list[TavernCard] | TavernCard,
    sess: TavernSession,
    history: list[TavernMessage],
    new_input: str,
    speaker: TavernCard | None = None,
) -> tuple[list[dict], dict]:
    """组装发给模型的 messages，返回 (messages, diag)。

    cards 是这条故事线的全部参与卡，speaker 是这一轮开口的人（默认第一张）。
    单卡时两者相同，走的路径与加群聊之前一致。

    creator_note 永不出现在返回值里——那是"AI 不会看到的介绍"。
    """
    if isinstance(cards, TavernCard):
        cards = [cards]
    card = speaker or cards[0]
    others = [c for c in cards if c.id != card.id]
    persona = (sess.persona_name or "").strip()

    def sub_for(owner: TavernCard):
        """{{char}} 按文本的归属替换：林越性格里的 {{char}} 永远是林越，
        即便这一轮在演别人。共用一个 char_name 会让引用来的世界书串名字。
        """
        return lambda text: substitute(text or "", owner.name, persona)

    sub = sub_for(card)

    window = _history_window(cards[0], sess, history)
    # scan_depth=1 就只扫玩家刚发的这句。往回扫得越多，角色自己的回复越容易
    # 让词条反复命中——它提到了那个词，下一轮扫描又扫到，自己喂自己。
    # 群聊取参与卡里的最大值：取小会让另一张卡的词条静默失效，最难查
    back = max(
        0,
        max(int(getattr(c, "scan_depth", 3) or 3) for c in cards) - 1,
    )
    scan_parts = ([m.content for m in window[-back:]] if back else []) + [new_input]
    scan_text = sub("\n".join(p for p in scan_parts if p))

    book_cards = await _world_book_cards(session, cards)
    entries = (await session.execute(
        select(TavernWorldEntry)
        .where(TavernWorldEntry.card_id.in_(list(book_cards)))
        .order_by(TavernWorldEntry.sort_order, TavernWorldEntry.id)
    )).scalars().all()
    hits = triggered_entries(list(entries), scan_text)

    def entry_sub(entry: TavernWorldEntry) -> str:
        """词条正文按所属卡替换：引用来的词条里写 {{char}} 指的是它自己那张卡"""
        owner = book_cards.get(entry.card_id)
        return (sub_for(owner) if owner else sub)(entry.content.strip())

    # 多张卡勾了同一条规则时只注入一遍
    rule_ids = list(dict.fromkeys(
        int(i) for c in cards for i in (c.enabled_rule_ids or [])
    ))
    rules_block = await resolve_rules(session, cards[0].user_id, rule_ids)

    sections: list[str] = []
    # 底层扮演指令永远在最前面：不填 system_instruction 的卡也得知道该怎么演。
    # 放第一段、卡上的系统指令紧随其后，用户想改行为可以直接在后面覆盖。
    sections.append(render(
        "tavern_roleplay.jinja2",
        char_name=card.name,
        persona=persona or DEFAULT_PERSONA_NAME,
        reply_length=max(0, int(getattr(card, "reply_length", 0) or 0)),
        others=[c.name for c in others],
    ).strip())

    if (card.system_instruction or "").strip():
        sections.append(sub(card.system_instruction.strip()))

    role_lines = [f"【角色】{card.name}"]
    if (card.personality or "").strip():
        role_lines.append(sub(card.personality.strip()))
    sections.append("\n".join(role_lines))

    if (card.description or "").strip():
        sections.append("【角色详细设定】\n" + sub(card.description.strip()))

    # 同场角色只给名字和性格，不给详细设定：省 token，也免得模型拿着别人的
    # 完整设定替他发言
    if others:
        blocks = []
        for other in others:
            osub = sub_for(other)
            lines = [other.name]
            if (other.personality or "").strip():
                lines.append(osub(other.personality.strip()))
            blocks.append("\n".join(lines))
        sections.append(truncate_to_token_budget(
            "【同场角色】\n" + "\n\n".join(blocks), ONSTAGE_TOKEN_BUDGET
        ))

    if persona or (sess.persona_desc or "").strip():
        player_lines = [f"【玩家】{persona or DEFAULT_PERSONA_NAME}"]
        if (sess.persona_desc or "").strip():
            player_lines.append(sub(sess.persona_desc.strip()))
        sections.append("\n".join(player_lines))

    # depth=0 拼进 system；depth>0 留到下面按深度插进对话流
    system_hits = [e for e in hits if (getattr(e, "depth", 0) or 0) <= 0]
    depth_hits = [e for e in hits if (getattr(e, "depth", 0) or 0) > 0]
    if system_hits:
        sections.append(truncate_to_token_budget(
            "【世界设定】\n" + "\n\n".join(entry_sub(e) for e in system_hits),
            WORLD_TOKEN_BUDGET,
        ))

    # 多卡时对话示例降级成文字：真实 few-shot 轮会让角色互相染上语气
    if others:
        example_text = _example_text(card, sub)
        if example_text:
            sections.append(example_text)

    if (sess.summary or "").strip():
        sections.append(
            "【此前剧情】\n"
            + truncate_to_token_budget(sub(sess.summary.strip()), SUMMARY_TOKEN_BUDGET)
        )

    if rules_block:
        sections.append(rules_block)

    system_content = truncate_to_token_budget(
        "\n\n".join(sections), SYSTEM_TOKEN_BUDGET
    )

    # 单卡才拼真实 few-shot 轮，多卡已在上面降级成 system 里的文字
    example_turns = [] if others else _build_example_turns(card.dialogue_examples, sub)

    messages = [{"role": "system", "content": system_content}]
    messages.extend(example_turns)
    by_id = {c.id: c for c in cards}
    for m in window:
        # 每条历史按它自己的说话人替换：谁的 {{char}} 都指向谁
        owner = by_id.get(m.card_id) if m.card_id else None
        text = (sub_for(owner) if owner else sub)(m.content)
        # 群聊里得让模型知道刚才那句是谁说的，否则几个角色的话糊成一团
        if others and owner and m.role == "assistant":
            text = f"{owner.name}：{text}"
        messages.append({"role": m.role, "content": text})
    messages.append({"role": "user", "content": sub(new_input)})

    _inject_by_depth(messages, depth_hits, entry_sub)

    diag = {
        "system_tokens": estimate_tokens(system_content),
        "history_count": len(window),
        "triggered": [
            {
                "id": e.id,
                "keywords": e.keywords,
                "constant": bool(getattr(e, "constant", False)),
                "depth": int(getattr(e, "depth", 0) or 0),
            }
            for e in hits
        ],
        "rules_used": len(rules_block.split("\n\n")) if rules_block else 0,
        "examples_used": sum(
            1 for ex in (card.dialogue_examples or [])
            if (ex.get("user") or "").strip() and (ex.get("assistant") or "").strip()
        ),
        "speaker": {"card_id": card.id, "name": card.name},
    }
    return messages, diag


def _inject_by_depth(messages: list[dict], entries: list, entry_sub) -> None:
    """把词条正文并进倒数第 depth 条消息的开头，原地改 messages。

    不新增消息行：Gemini / Anthropic 侧只认一个 system，且各供应商对 user/assistant
    交替有要求，插新行会破坏交替。并进已有那条的正文既保住深度又不动结构。
    """
    if not entries:
        return
    convo_start = 1  # 0 是 system
    tail = len(messages) - convo_start
    if tail <= 0:
        return
    by_index: dict[int, list[str]] = {}
    for e in entries:
        depth = max(1, min(int(getattr(e, "depth", 1) or 1), tail))
        by_index.setdefault(len(messages) - depth, []).append(entry_sub(e))
    for idx, blocks in by_index.items():
        note = "【世界设定】\n" + "\n\n".join(blocks)
        messages[idx]["content"] = f"{note}\n\n{messages[idx]['content']}"


def _transcript(
    rows: list[TavernMessage],
    persona: str,
    main: TavernCard,
    cards: list[TavernCard] | None = None,
) -> str:
    """把消息渲染成"名字：内容"。群聊按每行的说话人取名，否则全挂主卡名下。"""
    by_id = {c.id: c for c in (cards or [main])}
    lines = []
    for m in rows:
        owner = by_id.get(m.card_id) if m.card_id else None
        if m.role == "user":
            name = persona
        else:
            name = (owner or main).name
        lines.append(
            f"{name}：{substitute(m.content, (owner or main).name, persona)}"
        )
    return "\n".join(lines)


async def suggest_replies(
    card: TavernCard,
    sess: TavernSession,
    history: list[TavernMessage],
    cards: list[TavernCard] | None = None,
) -> list[str]:
    """「帮我想想」：给出 4 条候选玩家回复。

    card 是主卡（会话级操作统一用它的模型），cards 是群聊的全部参与卡。
    只读最近几轮，不读 creator_note。返回空列表表示没能生成，前端提示一下就好。
    """
    recent = history[-6:]
    if not recent:
        return []

    persona = (sess.persona_name or "").strip() or DEFAULT_PERSONA_NAME
    transcript = _transcript(recent, persona, card, cards)
    prompt = render(
        "tavern_suggest.jinja2",
        char_name=card.name,
        persona=persona,
        summary=truncate_to_token_budget(
            substitute(sess.summary or "", card.name, persona), SUMMARY_TOKEN_BUDGET
        ),
        transcript=transcript,
    )
    model, api_format = llm_client.get_agent_client("memory", card.model_ref)
    text = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.95,
        max_tokens=600,
    )

    lines = []
    for raw in (text or "").splitlines():
        # 模型时常自作主张加编号或引号，去掉再用
        # 编号必须带分隔符才剥，否则 "3天后再来" 会被吃掉开头的数字
        line = re.sub(
            r"^\s*(?:[-*•]\s*)?(?:\d+\s*[.、)）]\s*)?", "", raw
        ).strip().strip('"“”「」')
        if line:
            lines.append(line)
    return lines[:4]


async def maybe_summarize(
    session: AsyncSession,
    card: TavernCard,
    sess: TavernSession,
    cards: list[TavernCard] | None = None,
) -> bool:
    """未压缩消息超出保留窗口时，把溢出部分折进 sess.summary。

    card 必须是主卡：summarized_upto_id 是故事线级别的单值，按卡各算会互相打乱指针。
    一次 LLM 调用。失败只记日志不抛——摘要停在旧位置，上下文退化成纯截断，
    不影响下一轮能继续聊。
    """
    keep = max(1, card.context_turns or 20) * 2
    pending = (await session.execute(
        select(TavernMessage)
        .where(
            TavernMessage.session_id == sess.id,
            TavernMessage.id > (sess.summarized_upto_id or 0),
        )
        .order_by(TavernMessage.id)
    )).scalars().all()
    if len(pending) <= keep:
        return False

    overflow = pending[: len(pending) - keep]
    persona = (sess.persona_name or "").strip() or DEFAULT_PERSONA_NAME
    transcript = _transcript(overflow, persona, card, cards)

    try:
        model, api_format = llm_client.get_agent_client("memory", card.model_ref)
        prompt = render(
            "tavern_summary.jinja2",
            previous_summary=(sess.summary or "").strip(),
            transcript=transcript,
        )
        text = await llm_client.dispatch_chat_complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            temperature=0.3,
            max_tokens=1200,
        )
    except Exception:
        logger.exception("酒馆会话 %s 摘要生成失败，上下文退化为纯截断", sess.id)
        return False

    if not (text or "").strip():
        return False

    sess.summary = text.strip()
    sess.summarized_upto_id = overflow[-1].id
    await session.commit()
    return True
