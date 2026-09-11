import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.routes.tavern_prompts import router as prompts_router
from app.database import AsyncSessionLocal, get_db
from app.models.tavern import (
    TavernCard, TavernInstructionPreset, TavernMessage, TavernRule, TavernSession,
    TavernSessionCard, TavernWorldEntry,
)
from app.schemas.tavern import (
    TavernCardAssistOut, TavernCardAssistRequest,
    TavernCardCreate, TavernCardOut, TavernCardUpdate,
    TavernGroupSessionCreate,
    TavernInstructionPresetCreate, TavernInstructionPresetOut, TavernInstructionPresetUpdate,
    TavernMessageOut, TavernMessageUpdate,
    TavernRuleCreate, TavernRuleOut, TavernRuleUpdate,
    TavernSessionCardOut, TavernSessionCreate, TavernSessionOut, TavernSessionUpdate,
    TavernSuggestOut, TavernTurnRequest,
    TavernWorldEntryCreate, TavernWorldEntryOut, TavernWorldEntryUpdate,
)
from app.agents import tavern_card_agent
from app.services import llm_client, tavern_context
from app.services.sse import sse_event as _sse

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(prompts_router)

# 强引用池：asyncio 只弱引用 task，不留着可能在跑完前被 GC 掉
_detached_tasks: set[asyncio.Task] = set()


def _spawn_detached(coro) -> None:
    """把收尾工作丢到独立 task 上跑，不受当前请求取消的影响。"""
    task = asyncio.create_task(coro)
    _detached_tasks.add(task)
    task.add_done_callback(_detached_tasks.discard)
    task.add_done_callback(
        lambda t: t.cancelled() or (
            t.exception() and logger.exception("酒馆收尾任务失败", exc_info=t.exception())
        )
    )


AVATARS_DIR = Path("data/avatars")
_ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_AVATAR_BYTES = 5 * 1024 * 1024


def _unlink_avatar(avatar_url: str) -> None:
    """删旧头像文件。只取 basename，避免 avatar_url 里的路径成分逃出目录。"""
    if not avatar_url:
        return
    (AVATARS_DIR / Path(avatar_url).name).unlink(missing_ok=True)


# ── 归属检查：id 不属于当前用户一律 404（防 id 枚举，同 deps.get_owned_novel）──

async def _get_owned_card(db: AsyncSession, card_id: int, user) -> TavernCard:
    card = await db.get(TavernCard, card_id)
    if not card or card.user_id != user.id:
        raise HTTPException(status_code=404, detail="角色卡不存在")
    return card


async def _get_owned_entry(db: AsyncSession, entry_id: int, user) -> TavernWorldEntry:
    entry = await db.get(TavernWorldEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="词条不存在")
    await _get_owned_card(db, entry.card_id, user)
    return entry


async def _get_owned_session(db: AsyncSession, session_id: int, user) -> TavernSession:
    sess = await db.get(TavernSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="会话不存在")
    await _get_owned_card(db, sess.card_id, user)
    return sess


async def _get_owned_message(db: AsyncSession, message_id: int, user) -> TavernMessage:
    msg = await db.get(TavernMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    await _get_owned_session(db, msg.session_id, user)
    return msg


async def _get_owned_instruction_preset(
    db: AsyncSession, preset_id: int, user
) -> TavernInstructionPreset:
    preset = await db.get(TavernInstructionPreset, preset_id)
    if not preset or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="常用指令不存在")
    return preset


async def _get_owned_rule(db: AsyncSession, rule_id: int, user) -> TavernRule:
    rule = await db.get(TavernRule, rule_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


async def _session_counts(db: AsyncSession, card_ids: list[int]) -> dict[int, int]:
    """一张卡参与了几条故事线。按参与表算，群聊里的配角也要计数。"""
    if not card_ids:
        return {}
    rows = (await db.execute(
        select(TavernSessionCard.card_id, func.count(TavernSessionCard.session_id))
        .where(TavernSessionCard.card_id.in_(card_ids))
        .group_by(TavernSessionCard.card_id)
    )).all()
    return {cid: n for cid, n in rows}


async def _session_cards(db: AsyncSession, sess: TavernSession) -> list[TavernCard]:
    """故事线的参与卡，按 sort_order 排（= 不点名时的发言顺序）。

    主卡永远排在最前：会话级操作（摘要、帮我想想）认它，权限也认它。
    参与表为空 = 群聊之前的老数据，回落成单卡。
    """
    rows = (await db.execute(
        select(TavernCard)
        .join(TavernSessionCard, TavernSessionCard.card_id == TavernCard.id)
        .where(TavernSessionCard.session_id == sess.id)
        .order_by(TavernSessionCard.sort_order, TavernSessionCard.id)
    )).scalars().all()
    cards = [c for c in rows if c.id == sess.card_id]
    cards += [c for c in rows if c.id != sess.card_id]
    if cards:
        return cards
    main = await db.get(TavernCard, sess.card_id)
    return [main] if main else []


def _card_out(card: TavernCard, session_count: int = 0) -> TavernCardOut:
    out = TavernCardOut.model_validate(card)
    out.session_count = session_count
    return out


# ── 角色卡 ────────────────────────────────────────────────────────────────

@router.get("/cards/", response_model=list[TavernCardOut])
async def list_cards(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    cards = (await db.execute(
        select(TavernCard)
        .where(TavernCard.user_id == user.id)
        .order_by(TavernCard.updated_at.desc())
    )).scalars().all()
    counts = await _session_counts(db, [c.id for c in cards])
    return [_card_out(c, counts.get(c.id, 0)) for c in cards]


@router.post("/cards/", response_model=TavernCardOut)
async def create_card(
    data: TavernCardCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    card = TavernCard(**data.model_dump(), user_id=user.id)
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return _card_out(card)


@router.get("/cards/{card_id}", response_model=TavernCardOut)
async def get_card(card_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    card = await _get_owned_card(db, card_id, user)
    counts = await _session_counts(db, [card.id])
    return _card_out(card, counts.get(card.id, 0))


@router.patch("/cards/{card_id}", response_model=TavernCardOut)
async def update_card(
    card_id: int, data: TavernCardUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    card = await _get_owned_card(db, card_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(card, field, value)
    await db.commit()
    await db.refresh(card)
    counts = await _session_counts(db, [card.id])
    return _card_out(card, counts.get(card.id, 0))


@router.delete("/cards/{card_id}")
async def delete_card(card_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    card = await _get_owned_card(db, card_id, user)
    # 级联手写：PRAGMA foreign_keys=ON 且 _repair_data() 在清悬垂外键，不能留孤儿行
    # 它当主卡的故事线整条删；只是参与者的群聊留着，仅摘掉它的参与行
    session_ids = list((await db.execute(
        select(TavernSession.id).where(TavernSession.card_id == card.id)
    )).scalars().all())
    if session_ids:
        await db.execute(
            delete(TavernMessage).where(TavernMessage.session_id.in_(session_ids))
        )
        await db.execute(
            delete(TavernSessionCard).where(TavernSessionCard.session_id.in_(session_ids))
        )
        await db.execute(delete(TavernSession).where(TavernSession.id.in_(session_ids)))
    await db.execute(
        delete(TavernSessionCard).where(TavernSessionCard.card_id == card.id)
    )
    # 别人群聊里它说过的话：留着正文，只把说话人置空（回落显示成主卡）
    await db.execute(
        TavernMessage.__table__.update()
        .where(TavernMessage.card_id == card.id)
        .values(card_id=None)
    )
    # 别的卡引用了它的世界书，引用要摘掉，否则悬空
    for other in (await db.execute(
        select(TavernCard).where(TavernCard.user_id == user.id, TavernCard.id != card.id)
    )).scalars().all():
        linked = list(other.linked_book_card_ids or [])
        if card.id in linked:
            other.linked_book_card_ids = [i for i in linked if i != card.id]
    await db.execute(delete(TavernWorldEntry).where(TavernWorldEntry.card_id == card.id))
    _unlink_avatar(card.avatar_url)
    await db.delete(card)
    await db.commit()
    return {"ok": True}


# ── 头像 ──────────────────────────────────────────────────────────────────

@router.post("/cards/{card_id}/avatar", response_model=TavernCardOut)
async def upload_avatar(
    card_id: int,
    user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    card = await _get_owned_card(db, card_id, user)
    _unlink_avatar(card.avatar_url)

    # 后缀只认白名单：文件名来自用户，直接拼进路径会被穿越（../）和任意扩展名利用
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_AVATAR_EXT:
        raise HTTPException(status_code=400, detail="仅支持 png / jpg / webp / gif 图片")
    data = await file.read()
    if len(data) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")

    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"tavern{card_id}_{uuid.uuid4().hex[:8]}{ext}"
    (AVATARS_DIR / filename).write_bytes(data)

    card.avatar_url = f"/api/avatars/{filename}"
    await db.commit()
    await db.refresh(card)
    counts = await _session_counts(db, [card.id])
    return _card_out(card, counts.get(card.id, 0))


@router.delete("/cards/{card_id}/avatar", response_model=TavernCardOut)
async def delete_avatar(card_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    card = await _get_owned_card(db, card_id, user)
    _unlink_avatar(card.avatar_url)
    card.avatar_url = ""
    await db.commit()
    await db.refresh(card)
    counts = await _session_counts(db, [card.id])
    return _card_out(card, counts.get(card.id, 0))


# ── 角色卡 AI 辅助 ────────────────────────────────────────────────────────

@router.post("/cards/assist", response_model=TavernCardAssistOut)
async def assist_card_field(data: TavernCardAssistRequest, user: CurrentUser):
    """按前端传来的当前表单文本，生成或优化某一栏。不落库，由前端保存时统一提交。

    没有 card_id：新卡还没创建时也要能用。
    """
    try:
        if data.field == "creator_note":
            if not (data.personality.strip() or data.description.strip()):
                raise HTTPException(
                    status_code=400,
                    detail="请先写点角色性格或详细描述，卡介绍是根据它们生成的",
                )
            text = await tavern_card_agent.assist_creator_note(
                data.name, data.personality, data.description, data.model_ref
            )
        elif data.field in tavern_card_agent.FIELD_SPECS:
            text = await tavern_card_agent.assist_field(
                data.field,
                getattr(data, data.field),
                data.name,
                data.personality,
                data.description,
                data.model_ref,
                data.profile_sections,
            )
        else:
            raise HTTPException(status_code=400, detail=f"不支持的栏位：{data.field}")
    except ValueError as e:
        # 模型没配好时 resolve_model_ref 抛 ValueError，别变成 500
        raise HTTPException(status_code=400, detail=str(e)) from e
    return TavernCardAssistOut(text=text)


# ── 常用系统指令 ──────────────────────────────────────────────────────────

@router.get("/instruction-presets/", response_model=list[TavernInstructionPresetOut])
async def list_instruction_presets(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(TavernInstructionPreset)
        .where(TavernInstructionPreset.user_id == user.id)
        .order_by(TavernInstructionPreset.updated_at.desc())
    )).scalars().all()


@router.post("/instruction-presets/", response_model=TavernInstructionPresetOut)
async def create_instruction_preset(
    data: TavernInstructionPresetCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    name = data.name.strip()
    content = (data.content or "").strip()
    if not name or not content:
        raise HTTPException(status_code=400, detail="名称和内容都不能为空")
    preset = TavernInstructionPreset(name=name, content=content, user_id=user.id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.patch("/instruction-presets/{preset_id}", response_model=TavernInstructionPresetOut)
async def update_instruction_preset(
    preset_id: int, data: TavernInstructionPresetUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    preset = await _get_owned_instruction_preset(db, preset_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(preset, field, value)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/instruction-presets/{preset_id}")
async def delete_instruction_preset(
    preset_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    preset = await _get_owned_instruction_preset(db, preset_id, user)
    await db.delete(preset)
    await db.commit()
    return {"ok": True}


# ── 写作规则 ──────────────────────────────────────────────────────────────

@router.get("/rules/", response_model=list[TavernRuleOut])
async def list_rules(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(TavernRule)
        .where(TavernRule.user_id == user.id)
        .order_by(TavernRule.sort_order, TavernRule.id)
    )).scalars().all()


@router.post("/rules/", response_model=TavernRuleOut)
async def create_rule(
    data: TavernRuleCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="规则名称不能为空")
    rule = TavernRule(
        **{**data.model_dump(), "name": name}, user_id=user.id,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=TavernRuleOut)
async def update_rule(
    rule_id: int, data: TavernRuleUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    rule = await _get_owned_rule(db, rule_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """删规则。勾选过它的角色卡里会留一个失效 id，解析时自然跳过，不用回头清。"""
    rule = await _get_owned_rule(db, rule_id, user)
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


# ── 世界书 ────────────────────────────────────────────────────────────────

@router.get("/cards/{card_id}/world-entries", response_model=list[TavernWorldEntryOut])
async def list_world_entries(
    card_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    await _get_owned_card(db, card_id, user)
    return (await db.execute(
        select(TavernWorldEntry)
        .where(TavernWorldEntry.card_id == card_id)
        .order_by(TavernWorldEntry.sort_order, TavernWorldEntry.id)
    )).scalars().all()


@router.post("/cards/{card_id}/world-entries", response_model=TavernWorldEntryOut)
async def create_world_entry(
    card_id: int, data: TavernWorldEntryCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_card(db, card_id, user)
    entry = TavernWorldEntry(**data.model_dump(), card_id=card_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/world-entries/{entry_id}", response_model=TavernWorldEntryOut)
async def update_world_entry(
    entry_id: int, data: TavernWorldEntryUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    entry = await _get_owned_entry(db, entry_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/world-entries/{entry_id}")
async def delete_world_entry(
    entry_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    entry = await _get_owned_entry(db, entry_id, user)
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


# ── 会话 ──────────────────────────────────────────────────────────────────

async def _message_counts(db: AsyncSession, session_ids: list[int]) -> dict[int, int]:
    if not session_ids:
        return {}
    rows = (await db.execute(
        select(TavernMessage.session_id, func.count(TavernMessage.id))
        .where(TavernMessage.session_id.in_(session_ids))
        .group_by(TavernMessage.session_id)
    )).all()
    return {sid: n for sid, n in rows}


def _session_out(
    sess: TavernSession,
    message_count: int = 0,
    cards: list[TavernCard] | None = None,
) -> TavernSessionOut:
    out = TavernSessionOut.model_validate(sess)
    out.message_count = message_count
    out.cards = [
        TavernSessionCardOut(id=c.id, name=c.name, avatar_url=c.avatar_url)
        for c in (cards or [])
    ]
    return out


async def _sessions_cards(
    db: AsyncSession, session_ids: list[int]
) -> dict[int, list[TavernCard]]:
    """批量取参与卡，避免列表页每条故事线单独查一次。"""
    if not session_ids:
        return {}
    rows = (await db.execute(
        select(TavernSessionCard.session_id, TavernCard)
        .join(TavernCard, TavernSessionCard.card_id == TavernCard.id)
        .where(TavernSessionCard.session_id.in_(session_ids))
        .order_by(TavernSessionCard.sort_order, TavernSessionCard.id)
    )).all()
    out: dict[int, list[TavernCard]] = {}
    for sid, card in rows:
        out.setdefault(sid, []).append(card)
    return out


@router.get("/cards/{card_id}/sessions", response_model=list[TavernSessionOut])
async def list_sessions(card_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """这张卡参与的故事线。走参与表——群聊里当配角的那些也要列出来。"""
    await _get_owned_card(db, card_id, user)
    sessions = (await db.execute(
        select(TavernSession)
        .join(TavernSessionCard, TavernSessionCard.session_id == TavernSession.id)
        .where(TavernSessionCard.card_id == card_id)
        .order_by(TavernSession.updated_at.desc())
    )).scalars().all()
    ids = [s.id for s in sessions]
    counts = await _message_counts(db, ids)
    cards = await _sessions_cards(db, ids)
    return [_session_out(s, counts.get(s.id, 0), cards.get(s.id)) for s in sessions]


async def _create_session(
    db: AsyncSession, card_ids: list[int], data: TavernSessionCreate, user
) -> TavernSessionOut:
    """建故事线。首个 card_id 是主卡，开场环境取主卡的。"""
    ids = list(dict.fromkeys(int(i) for i in card_ids))
    if not ids:
        raise HTTPException(status_code=400, detail="至少要选一个角色")
    cards = [await _get_owned_card(db, cid, user) for cid in ids]

    sess = TavernSession(**data.model_dump(), card_id=cards[0].id)
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    for order, card in enumerate(cards):
        db.add(TavernSessionCard(session_id=sess.id, card_id=card.id, sort_order=order))
    # 开场环境落成首条 assistant 消息：原文入库，占位符出库时才替换
    if (cards[0].opening_scene or "").strip():
        db.add(TavernMessage(
            session_id=sess.id, role="assistant", card_id=cards[0].id,
            content=cards[0].opening_scene.strip(),
        ))
    await db.commit()
    counts = await _message_counts(db, [sess.id])
    return _session_out(sess, counts.get(sess.id, 0), cards)


@router.post("/sessions", response_model=TavernSessionOut)
async def create_group_session(
    data: TavernGroupSessionCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    return await _create_session(
        db, data.card_ids, TavernSessionCreate(**data.model_dump(exclude={"card_ids"})), user
    )


@router.post("/cards/{card_id}/sessions", response_model=TavernSessionOut)
async def create_session(
    card_id: int, data: TavernSessionCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """单卡建故事线。保留这条路径，前端老调用点还在用。"""
    return await _create_session(db, [card_id], data, user)


@router.get("/sessions/{session_id}", response_model=TavernSessionOut)
async def get_session(session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    sess = await _get_owned_session(db, session_id, user)
    counts = await _message_counts(db, [sess.id])
    return _session_out(sess, counts.get(sess.id, 0), await _session_cards(db, sess))


@router.patch("/sessions/{session_id}", response_model=TavernSessionOut)
async def update_session(
    session_id: int, data: TavernSessionUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    sess = await _get_owned_session(db, session_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(sess, field, value)
    await db.commit()
    await db.refresh(sess)
    counts = await _message_counts(db, [sess.id])
    return _session_out(sess, counts.get(sess.id, 0), await _session_cards(db, sess))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    sess = await _get_owned_session(db, session_id, user)
    await db.execute(delete(TavernMessage).where(TavernMessage.session_id == sess.id))
    await db.execute(
        delete(TavernSessionCard).where(TavernSessionCard.session_id == sess.id)
    )
    await db.delete(sess)
    await db.commit()
    return {"ok": True}


# ── 消息 ──────────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages", response_model=list[TavernMessageOut])
async def list_messages(
    session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    sess = await _get_owned_session(db, session_id, user)
    cards = await _session_cards(db, sess)
    messages = (await db.execute(
        select(TavernMessage)
        .where(TavernMessage.session_id == session_id)
        .order_by(TavernMessage.id)
    )).scalars().all()

    # 出库时替换占位符，库里始终是原文。{{char}} 按每条自己的说话人替换
    by_id = {c.id: c for c in cards}
    out = []
    for m in messages:
        speaker = by_id.get(m.card_id) or cards[0]
        item = TavernMessageOut.model_validate(m)
        item.content = tavern_context.substitute(
            m.content, speaker.name, sess.persona_name
        )
        out.append(item)
    return out


@router.patch("/messages/{message_id}", response_model=TavernMessageOut)
async def update_message(
    message_id: int, data: TavernMessageUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """改写某条消息。改完的原文入库，回给前端的是替换过占位符的版本。

    用户手改角色的话是酒馆的常规操作——一句跑偏的回复会被后续几轮当成既定事实。
    """
    msg = await _get_owned_message(db, message_id, user)
    content = (data.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    msg.content = content
    await db.commit()
    await db.refresh(msg)

    sess = await db.get(TavernSession, msg.session_id)
    cards = await _session_cards(db, sess)
    speaker = next((c for c in cards if c.id == msg.card_id), None) or cards[0]
    out = TavernMessageOut.model_validate(msg)
    out.content = tavern_context.substitute(msg.content, speaker.name, sess.persona_name)
    return out


@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    msg = await _get_owned_message(db, message_id, user)
    await db.delete(msg)
    await db.commit()
    return {"ok": True}


# ── 帮我想想 ──────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/suggest", response_model=TavernSuggestOut)
async def suggest_replies(
    session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """根据最近几轮给出 4 条候选玩家回复，点一条直接发送。"""
    sess = await _get_owned_session(db, session_id, user)
    # 会话级操作统一用主卡的模型
    cards = await _session_cards(db, sess)
    history = list((await db.execute(
        select(TavernMessage)
        .where(TavernMessage.session_id == session_id)
        .order_by(TavernMessage.id)
    )).scalars().all())
    try:
        return TavernSuggestOut(
            suggestions=await tavern_context.suggest_replies(
                cards[0], sess, history, cards
            )
        )
    except ValueError as e:
        # 模型配错时 resolve_model_ref 抛 ValueError，别变成 500
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 游玩：流式一轮 ─────────────────────────────────────────────────────────

def _resolve_speakers(cards: list[TavernCard], content: str) -> list[TavernCard]:
    """这一轮谁开口：@点名则只有被点的，没点名则全体按参与顺序依次。

    长名字先匹配，命中的那段从文本里挖掉再继续——否则「@林越」里的「@林」会把
    同场的「林」也算上。@ 的文本保留在入库的消息里，玩家写的是台词不是命令。
    """
    if len(cards) <= 1:
        return list(cards)
    rest = content
    picked = set()
    for card in sorted(cards, key=lambda c: -len(c.name or "")):
        tag = f"@{card.name}"
        if card.name and tag in rest:
            picked.add(card.id)
            rest = rest.replace(tag, " ")
    if not picked:
        return list(cards)
    # 点了多个就按参与顺序依次发言
    return [c for c in cards if c.id in picked]


def _strip_name_prefix(reply: str, name: str) -> str:
    """去掉模型自己加的"名字："开头。

    群聊提示词里有"刚才那句是谁说的"的标注，模型会照着格式给自己也加一个前缀，
    前端已经单独显示名字了，留着就成了重复。
    """
    for sep in ("：", ":"):
        head = f"{name}{sep}"
        if reply.startswith(head):
            return reply[len(head):].lstrip()
    return reply

@router.post("/sessions/{session_id}/stream")
async def stream_turn(
    session_id: int,
    req: TavernTurnRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式接口：酒馆一轮对话。群聊时一轮里多个角色依次发言。

    事件类型：
      speaker    → 本次开口的是谁 {card_id, name, avatar_url}，每人一次，在 token 之前
      meta       → 本轮注入诊断 {system_tokens, history_count, triggered, rules_used}
      token      → 逐 token 输出，归属最近一个 speaker
      warning    → 供应商侧告警
      summarized → 触发了早期剧情压缩
      done       → {input_tokens, output_tokens, message_id}，每人一次
      error      → 错误信息
    """
    sess = await _get_owned_session(db, session_id, user)
    cards = await _session_cards(db, sess)

    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")

    speakers = _resolve_speakers(cards, content)

    # 用户消息先落库：网络断了这条也得留下
    user_row = TavernMessage(session_id=session_id, role="user", content=content)
    db.add(user_row)
    await db.commit()
    # 前端要靠这个 id 才能编辑刚发出的这句，否则得刷新页面重新拉一遍
    user_message_id = user_row.id

    main_card_id = cards[0].id
    card_ids = [c.id for c in cards]
    speaker_plan = [
        {
            "card_id": c.id,
            "name": c.name,
            "avatar_url": c.avatar_url,
            "model_ref": c.model_ref,
            "temperature": c.temperature,
            "max_tokens": c.max_tokens,
        }
        for c in speakers
    ]

    async def _build(speaker_id: int) -> tuple[list[dict], dict]:
        """按当前说话人组装。每人开口前重查一次历史——后发言的要看得见前面刚说的话。"""
        async with AsyncSessionLocal() as store:
            fresh_sess = await store.get(TavernSession, session_id)
            rows = (await store.execute(
                select(TavernCard).where(TavernCard.id.in_(card_ids))
            )).scalars().all()
            by_id = {c.id: c for c in rows}
            ordered = [by_id[i] for i in card_ids if i in by_id]
            history = list((await store.execute(
                select(TavernMessage)
                .where(
                    TavernMessage.session_id == session_id,
                    # 只排掉刚落库的这句玩家输入（它由 new_input 单独传）。
                    # 本轮前面的人已说完的话 id 更大，必须留下——否则第二个人看不见
                    TavernMessage.id != user_row.id,
                )
                .order_by(TavernMessage.id)
            )).scalars().all())
            return await tavern_context.build_tavern_messages(
                store, ordered, fresh_sess, history, content,
                speaker=by_id.get(speaker_id) or ordered[0],
            )

    async def _store_reply(
        reply: str, in_tok: int, out_tok: int, summarize: bool, speaker_id: int,
    ) -> tuple[int, int]:
        """落 assistant 消息行，顺带按需压缩早期剧情。返回 (message_id, 压缩到的 id)。

        必须另开 session：Depends(get_db) 那个在 handler 返回时就关了，而 handler
        早于生成器结束返回。压缩也放这个 session 里，出了 with 块 ORM 对象就失效了。
        """
        async with AsyncSessionLocal() as store:
            row = TavernMessage(
                session_id=session_id, role="assistant", content=reply,
                card_id=speaker_id,
                input_tokens=in_tok, output_tokens=out_tok,
            )
            store.add(row)
            fresh_sess = await store.get(TavernSession, session_id)
            # 摘要按主卡的窗口算：summarized_upto_id 是故事线级别的单值
            fresh_card = await store.get(TavernCard, main_card_id)
            # 显式改一个字段才会触发 onupdate，会话列表靠 updated_at 排序
            fresh_sess.updated_at = datetime.utcnow()
            await store.commit()
            await store.refresh(row)

            upto = 0
            if summarize and await tavern_context.maybe_summarize(
                store, fresh_card, fresh_sess
            ):
                upto = fresh_sess.summarized_upto_id
            return row.id, upto

    async def event_stream():
        # 只保当前说话人的缓冲：前面说完的人在各自的 done 时已落库
        buf: list[str] = []
        in_tok = 0
        out_tok = 0
        current = speaker_plan[0]
        first = True
        try:
            for plan in speaker_plan:
                current, buf, in_tok, out_tok = plan, [], 0, 0
                messages, diag = await _build(plan["card_id"])

                if len(speaker_plan) > 1:
                    yield _sse("speaker", {
                        "card_id": plan["card_id"],
                        "name": plan["name"],
                        "avatar_url": plan["avatar_url"],
                    })
                # 先发 meta：模型没配好时也要让前端拿到 user_message_id，否则那条消息
                # 已经落库却编辑不了。id 只在第一个人的 meta 里带
                yield _sse("meta", {
                    **diag,
                    **({"user_message_id": user_message_id} if first else {}),
                })
                first = False

                # 模型解析放生成器内：非管理员模型配错时 resolve_model_ref 抛 ValueError，
                # 放外面会变成 500 白屏，放这里能变成一条 error 事件
                model, api_format = llm_client.get_agent_client(
                    "writer", plan["model_ref"]
                )

                async for chunk in llm_client.dispatch_chat_stream_with_usage(
                    messages=messages,
                    model=model,
                    api_format=api_format,
                    temperature=plan["temperature"],
                    max_tokens=plan["max_tokens"],
                ):
                    if isinstance(chunk, tuple):
                        _, in_tok, out_tok = chunk
                    elif isinstance(chunk, dict):
                        if "warning" in chunk:
                            yield _sse("warning", chunk["warning"])
                    else:
                        buf.append(chunk)
                        yield _sse("token", chunk)

                # 摘要只在最后一个人说完后跑一次，不是每人一次
                message_id, upto = await _store_reply(
                    _strip_name_prefix("".join(buf).strip(), plan["name"]),
                    in_tok, out_tok,
                    summarize=plan is speaker_plan[-1],
                    speaker_id=plan["card_id"],
                )
                if upto:
                    yield _sse("summarized", {"upto_id": upto})

                yield _sse("done", {
                    "input_tokens": in_tok,
                    "output_tokens": out_tok,
                    "message_id": message_id,
                })
        except (asyncio.CancelledError, GeneratorExit):
            # 用户按了停止：已经吐出来的半段也要留下，否则刷新页面就没了。
            # 两种都要接：取消落在生成器内部的 await 上是 CancelledError，落在 yield
            # 上则是 aclose() 抛的 GeneratorExit。
            # 这里不能 await 落库——本 task 已被取消，下一个 await 会再次抛出，半段就
            # 丢了；GeneratorExit 分支里 await 更是直接 RuntimeError。丢给独立 task 才跑得完。
            # 不压缩：中断的这半段还没定稿，等下一轮正常结束再一起算
            reply = _strip_name_prefix("".join(buf).strip(), current["name"])
            if reply:
                _spawn_detached(_store_reply(
                    reply, in_tok, out_tok,
                    summarize=False, speaker_id=current["card_id"],
                ))
            raise
        except Exception as e:
            yield _sse("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
