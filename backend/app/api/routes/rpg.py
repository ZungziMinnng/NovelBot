import asyncio
import copy
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import rpg_assist, rpg_turn, rpg_wizard
from app.api.deps import CurrentUser
from app.api.routes.rpg_prompts import router as prompts_router
from app.database import get_db
from app.models.rpg import (
    RpgAction, RpgItem, RpgLocation, RpgMessage, RpgModule, RpgNpc,
    RpgRule, RpgSave, RpgSession, RpgWorldEntry,
)
from app.schemas.rpg import (
    RpgActionCreate, RpgActionOut, RpgActionUpdate,
    RpgAdvanceOut,
    RpgAssistIn, RpgAssistOut,
    RpgGenerateIn,
    RpgItemCreate, RpgItemOut, RpgItemUpdate,
    RpgLocationCreate, RpgLocationOut, RpgLocationUpdate,
    RpgMessageOut,
    RpgModuleCreate, RpgModuleOut, RpgModuleUpdate,
    RpgMoveIn, RpgMoveOut,
    RpgNoteDeleteIn,
    RpgNpcCreate, RpgNpcOut, RpgNpcUpdate,
    RpgRuleCreate, RpgRuleOut, RpgRuleUpdate,
    RpgSaveCreate, RpgSaveOut,
    RpgSessionCreate, RpgSessionOut, RpgSessionUpdate,
    RpgSuggestOut,
    RpgTurnRequest,
    RpgWizardChatIn, RpgWizardExtractIn, RpgWizardExtractOut,
    RpgWorldEntryCreate, RpgWorldEntryOut, RpgWorldEntryUpdate,
)
from app.services import llm_json
from app.services.rpg_state import (
    OPENING_CHARS, OPENING_TAG,
    advance_slot, apply_npc_activity, apply_npc_notes, init_relation, init_stats,
    push_chronicle, slot_table,
    starting_inventory,
)
from app.services.sse import sse_event, stream_chat

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(prompts_router)

AVATARS_DIR = Path("data/avatars")
_ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _unlink_image(url: str) -> None:
    """删旧图片文件。只取 basename，避免 url 里的路径成分逃出目录。"""
    if not url:
        return
    (AVATARS_DIR / Path(url).name).unlink(missing_ok=True)


async def _save_image(file: UploadFile, prefix: str) -> str:
    """存一张上传的图片，返回访问路径。后缀只认白名单：文件名来自用户，
    直接拼进路径会被穿越（../）和任意扩展名利用。
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXT:
        raise HTTPException(status_code=400, detail="仅支持 png / jpg / webp / gif 图片")
    data = await file.read()
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    (AVATARS_DIR / filename).write_bytes(data)
    return f"/api/avatars/{filename}"


# ── 归属检查：id 不属于当前用户一律 404（防 id 枚举，同酒馆）──

async def _get_owned_module(db: AsyncSession, module_id: int, user) -> RpgModule:
    module = await db.get(RpgModule, module_id)
    if not module or module.user_id != user.id:
        raise HTTPException(status_code=404, detail="模组不存在")
    return module


async def _get_owned_entry(db: AsyncSession, entry_id: int, user) -> RpgWorldEntry:
    entry = await db.get(RpgWorldEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="词条不存在")
    await _get_owned_module(db, entry.module_id, user)
    return entry


async def _get_owned_npc(db: AsyncSession, npc_id: int, user) -> RpgNpc:
    npc = await db.get(RpgNpc, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC 不存在")
    await _get_owned_module(db, npc.module_id, user)
    return npc


async def _get_owned_session(db: AsyncSession, session_id: int, user) -> RpgSession:
    sess = await db.get(RpgSession, session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="存档不存在")
    await _get_owned_module(db, sess.module_id, user)
    return sess


async def _get_owned_rule(db: AsyncSession, rule_id: int, user) -> RpgRule:
    rule = await db.get(RpgRule, rule_id)
    if not rule or rule.user_id != user.id:
        raise HTTPException(status_code=404, detail="规则不存在")
    return rule


async def _module_counts(db: AsyncSession, module_ids: list[int]) -> dict[int, dict]:
    """批量取每个模组的局数 / NPC 数 / 词条数，避免列表页 N+1。"""
    if not module_ids:
        return {}
    out = {mid: {"session_count": 0, "npc_count": 0, "entry_count": 0} for mid in module_ids}
    for model, key in (
        (RpgSession, "session_count"), (RpgNpc, "npc_count"), (RpgWorldEntry, "entry_count")
    ):
        rows = (await db.execute(
            select(model.module_id, func.count(model.id))
            .where(model.module_id.in_(module_ids))
            .group_by(model.module_id)
        )).all()
        for mid, n in rows:
            out[mid][key] = n
    return out


def _module_out(module: RpgModule, counts: dict | None = None) -> RpgModuleOut:
    out = RpgModuleOut.model_validate(module)
    for key, value in (counts or {}).items():
        setattr(out, key, value)
    return out


# ── 写作规则 ──────────────────────────────────────────────────────────────

@router.get("/rules/", response_model=list[RpgRuleOut])
async def list_rules(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(RpgRule)
        .where(RpgRule.user_id == user.id)
        .order_by(RpgRule.sort_order, RpgRule.id)
    )).scalars().all()


@router.post("/rules/", response_model=RpgRuleOut)
async def create_rule(
    data: RpgRuleCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="规则名称不能为空")
    rule = RpgRule(**{**data.model_dump(), "name": name}, user_id=user.id)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=RpgRuleOut)
async def update_rule(
    rule_id: int, data: RpgRuleUpdate, user: CurrentUser,
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
    """删规则。勾选过它的模组里会留一个失效 id，解析时自然跳过，不用回头清。"""
    rule = await _get_owned_rule(db, rule_id, user)
    await db.delete(rule)
    await db.commit()
    return {"ok": True}


# ── 模组 ──────────────────────────────────────────────────────────────────

@router.get("/modules/", response_model=list[RpgModuleOut])
async def list_modules(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    modules = (await db.execute(
        select(RpgModule)
        .where(RpgModule.user_id == user.id)
        .order_by(RpgModule.updated_at.desc())
    )).scalars().all()
    counts = await _module_counts(db, [m.id for m in modules])
    return [_module_out(m, counts.get(m.id)) for m in modules]


@router.post("/modules/", response_model=RpgModuleOut)
async def create_module(
    data: RpgModuleCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    module = RpgModule(**data.model_dump(), user_id=user.id)
    db.add(module)
    await db.commit()
    await db.refresh(module)
    return _module_out(module)


@router.get("/modules/{module_id}", response_model=RpgModuleOut)
async def get_module(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    module = await _get_owned_module(db, module_id, user)
    counts = await _module_counts(db, [module.id])
    return _module_out(module, counts.get(module.id))


@router.patch("/modules/{module_id}", response_model=RpgModuleOut)
async def update_module(
    module_id: int, data: RpgModuleUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    module = await _get_owned_module(db, module_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(module, field, value)
    await db.commit()
    await db.refresh(module)
    counts = await _module_counts(db, [module.id])
    return _module_out(module, counts.get(module.id))


@router.delete("/modules/{module_id}")
async def delete_module(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    module = await _get_owned_module(db, module_id, user)
    # 级联手写：PRAGMA foreign_keys=ON 且 _repair_data() 在清悬垂外键，不能留孤儿行
    session_ids = list((await db.execute(
        select(RpgSession.id).where(RpgSession.module_id == module.id)
    )).scalars().all())
    if session_ids:
        await db.execute(delete(RpgMessage).where(RpgMessage.session_id.in_(session_ids)))
        await db.execute(delete(RpgSave).where(RpgSave.session_id.in_(session_ids)))
        await db.execute(delete(RpgSession).where(RpgSession.id.in_(session_ids)))
    for npc in (await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == module.id)
    )).scalars().all():
        _unlink_image(npc.avatar_url)
    await db.execute(delete(RpgNpc).where(RpgNpc.module_id == module.id))
    for model in (RpgWorldEntry, RpgItem, RpgLocation, RpgAction):
        await db.execute(delete(model).where(model.module_id == module.id))
    _unlink_image(module.cover_url)
    await db.delete(module)
    await db.commit()
    return {"ok": True}


@router.post("/modules/{module_id}/assist", response_model=RpgAssistOut)
async def assist_module_field(
    module_id: int, data: RpgAssistIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """帮作者写某一栏。不落库——生成完给作者过目，他点「用这个」才进表单。"""
    module = await _get_owned_module(db, module_id, user)
    if data.field not in rpg_assist.FIELD_SPECS:
        raise HTTPException(status_code=400, detail="这一栏不支持 AI 生成")
    try:
        text = await rpg_assist.assist_field(
            data.field, data.content, data.context, module.model_ref
        )
    except ValueError as e:
        # 模型配错时 resolve_model_ref 抛 ValueError，别变成 500
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RpgAssistOut(text=text)


@router.post("/modules/{module_id}/wizard")
async def wizard_chat(
    module_id: int, data: RpgWizardChatIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """构思向导的对话轮，SSE 流式。不落库——聊定的结论前端逐项确认后才写回。"""
    module = await _get_owned_module(db, module_id, user)
    try:
        messages, model, api_format = await rpg_wizard.chat_stream_args(
            [m.model_dump() for m in data.messages],
            module.model_ref, data.nsfw, data.stage, data.confirmed, data.play_style,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return stream_chat(messages, model, api_format, module.temperature, module.max_tokens)


@router.post("/modules/{module_id}/wizard/extract", response_model=RpgWizardExtractOut)
async def wizard_extract(
    module_id: int, data: RpgWizardExtractIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """抽当前这一步聊定的结论并按白名单清洗。不落库。"""
    module = await _get_owned_module(db, module_id, user)
    if data.stage not in rpg_wizard.STAGES:
        raise HTTPException(status_code=400, detail="未知的向导步骤")
    if not data.messages:
        return RpgWizardExtractOut()
    transcript = "\n\n".join(
        f"{'作者' if m.role == 'user' else '助手'}：{m.content}"
        for m in data.messages if m.content
    )
    try:
        result = await rpg_wizard.extract_stage(
            data.stage, transcript, data.known, module.model_ref
        )
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"抽取失败：{e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RpgWizardExtractOut(**result)


# 一键生成的类别 → 拉「已有同名」用的模型。白名单靠查库，不用前端传
_GENERATE_MODELS = {
    "location": RpgLocation, "npc": RpgNpc, "item": RpgItem, "action": RpgAction,
}


@router.post("/modules/{module_id}/generate/{kind}", response_model=RpgWizardExtractOut)
async def generate_batch(
    module_id: int, kind: str, data: RpgGenerateIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """在某一摊点「AI 生成」，按一句话要求批量生成并按白名单清洗。不落库——
    前端预览勾选后各自建行。白名单（数值名/地点名/同类已有名字）在这里查库，
    避免前端传一份可能过期的。"""
    module = await _get_owned_module(db, module_id, user)
    if kind not in _GENERATE_MODELS:
        raise HTTPException(status_code=400, detail="这一摊不支持一键生成")

    location_names = list((await db.execute(
        select(RpgLocation.name).where(RpgLocation.module_id == module.id)
    )).scalars().all())
    existing_names = list((await db.execute(
        select(_GENERATE_MODELS[kind].name).where(
            _GENERATE_MODELS[kind].module_id == module.id
        )
    )).scalars().all())
    known = {
        "stat_names": [s.get("name") for s in (module.stat_defs or []) if s.get("name")],
        "relation_names": [
            s.get("name") for s in (module.relation_stat_defs or []) if s.get("name")
        ],
        "location_names": location_names,
        "existing_names": existing_names,
    }
    count = max(1, min(data.count, 10))
    try:
        result = await rpg_wizard.generate_batch(
            kind, data.instruction, count, known, data.nsfw, module.model_ref,
        )
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"生成失败：{e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RpgWizardExtractOut(**result)


@router.post("/modules/{module_id}/cover", response_model=RpgModuleOut)
async def upload_cover(
    module_id: int, user: CurrentUser,
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
):
    module = await _get_owned_module(db, module_id, user)
    _unlink_image(module.cover_url)
    module.cover_url = await _save_image(file, f"rpgmod{module_id}")
    await db.commit()
    await db.refresh(module)
    counts = await _module_counts(db, [module.id])
    return _module_out(module, counts.get(module.id))


@router.delete("/modules/{module_id}/cover", response_model=RpgModuleOut)
async def delete_cover(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    module = await _get_owned_module(db, module_id, user)
    _unlink_image(module.cover_url)
    module.cover_url = ""
    await db.commit()
    await db.refresh(module)
    counts = await _module_counts(db, [module.id])
    return _module_out(module, counts.get(module.id))


# ── 世界书 ────────────────────────────────────────────────────────────────

@router.get("/modules/{module_id}/entries/", response_model=list[RpgWorldEntryOut])
async def list_entries(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_module(db, module_id, user)
    return (await db.execute(
        select(RpgWorldEntry)
        .where(RpgWorldEntry.module_id == module_id)
        .order_by(RpgWorldEntry.sort_order, RpgWorldEntry.id)
    )).scalars().all()


@router.post("/modules/{module_id}/entries/", response_model=RpgWorldEntryOut)
async def create_entry(
    module_id: int, data: RpgWorldEntryCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_module(db, module_id, user)
    entry = RpgWorldEntry(**data.model_dump(), module_id=module_id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/entries/{entry_id}", response_model=RpgWorldEntryOut)
async def update_entry(
    entry_id: int, data: RpgWorldEntryUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    entry = await _get_owned_entry(db, entry_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    entry = await _get_owned_entry(db, entry_id, user)
    await db.delete(entry)
    await db.commit()
    return {"ok": True}


# ── NPC ───────────────────────────────────────────────────────────────────

@router.get("/modules/{module_id}/npcs/", response_model=list[RpgNpcOut])
async def list_npcs(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_module(db, module_id, user)
    return (await db.execute(
        select(RpgNpc)
        .where(RpgNpc.module_id == module_id)
        .order_by(RpgNpc.sort_order, RpgNpc.id)
    )).scalars().all()


@router.post("/modules/{module_id}/npcs/", response_model=RpgNpcOut)
async def create_npc(
    module_id: int, data: RpgNpcCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_module(db, module_id, user)
    npc = RpgNpc(**data.model_dump(), module_id=module_id)
    db.add(npc)
    await db.commit()
    await db.refresh(npc)
    return npc


@router.patch("/npcs/{npc_id}", response_model=RpgNpcOut)
async def update_npc(
    npc_id: int, data: RpgNpcUpdate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    npc = await _get_owned_npc(db, npc_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(npc, field, value)
    await db.commit()
    await db.refresh(npc)
    return npc


@router.delete("/npcs/{npc_id}")
async def delete_npc(npc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    npc = await _get_owned_npc(db, npc_id, user)
    _unlink_image(npc.avatar_url)
    await db.delete(npc)
    await db.commit()
    return {"ok": True}


@router.post("/npcs/{npc_id}/avatar", response_model=RpgNpcOut)
async def upload_npc_avatar(
    npc_id: int, user: CurrentUser,
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
):
    npc = await _get_owned_npc(db, npc_id, user)
    _unlink_image(npc.avatar_url)
    npc.avatar_url = await _save_image(file, f"rpgnpc{npc_id}")
    await db.commit()
    await db.refresh(npc)
    return npc


@router.delete("/npcs/{npc_id}/avatar", response_model=RpgNpcOut)
async def delete_npc_avatar(npc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    npc = await _get_owned_npc(db, npc_id, user)
    _unlink_image(npc.avatar_url)
    npc.avatar_url = ""
    await db.commit()
    await db.refresh(npc)
    return npc


# ── 道具 / 地点 / 动作按钮 ────────────────────────────────────────────────
# 三张表的 CRUD 形状完全一样，用工厂生成而不是抄三遍：字段各不相同的地方
# 全在 schema 里，路由这一层只剩「查归属 → 增删改」这一句话

def _mount_module_child(prefix: str, model, out_schema, create_schema, update_schema, label: str):
    async def _owned(db: AsyncSession, row_id: int, user):
        row = await db.get(model, row_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"{label}不存在")
        await _get_owned_module(db, row.module_id, user)
        return row

    @router.get(f"/modules/{{module_id}}/{prefix}/", response_model=list[out_schema])
    async def _list(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
        await _get_owned_module(db, module_id, user)
        return (await db.execute(
            select(model)
            .where(model.module_id == module_id)
            .order_by(model.sort_order, model.id)
        )).scalars().all()

    @router.post(f"/modules/{{module_id}}/{prefix}/", response_model=out_schema)
    async def _create(
        module_id: int, data: create_schema, user: CurrentUser,
        db: AsyncSession = Depends(get_db),
    ):
        await _get_owned_module(db, module_id, user)
        row = model(**data.model_dump(), module_id=module_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    @router.patch(f"/{prefix}/{{row_id}}", response_model=out_schema)
    async def _update(
        row_id: int, data: update_schema, user: CurrentUser,
        db: AsyncSession = Depends(get_db),
    ):
        row = await _owned(db, row_id, user)
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        return row

    @router.delete(f"/{prefix}/{{row_id}}")
    async def _delete(row_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
        row = await _owned(db, row_id, user)
        await db.delete(row)
        await db.commit()
        return {"ok": True}


_mount_module_child("items", RpgItem, RpgItemOut, RpgItemCreate, RpgItemUpdate, "道具")
_mount_module_child(
    "locations", RpgLocation, RpgLocationOut, RpgLocationCreate, RpgLocationUpdate, "地点"
)
_mount_module_child("actions", RpgAction, RpgActionOut, RpgActionCreate, RpgActionUpdate, "动作")


# ── 存档局 ────────────────────────────────────────────────────────────────

@router.get("/modules/{module_id}/sessions/", response_model=list[RpgSessionOut])
async def list_sessions(module_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_module(db, module_id, user)
    return (await db.execute(
        select(RpgSession)
        .where(RpgSession.module_id == module_id)
        .order_by(RpgSession.updated_at.desc())
    )).scalars().all()


@router.post("/modules/{module_id}/sessions/", response_model=RpgSessionOut)
async def create_session(
    module_id: int, data: RpgSessionCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """开一局：按模组的数值定义初始化，并把开场白落成首条 assistant 消息。

    角色属于这一局而不是模组——同一个模组可以开多局，每局角色不同。
    """
    module = await _get_owned_module(db, module_id, user)
    stats = init_stats(module.stat_defs)
    # 玩家在建局界面调过的那几项才覆盖，定义里没有的键丢掉
    for name, value in (data.stats or {}).items():
        if name in stats:
            stats[name] = value
    start = data.location if data.location is not None else module.default_location
    # 开局背包 = 模组写的那些 + 道具定义里勾了「开局就有」的。
    # 以前只拷 default_inventory，所以「在道具页定义了一件东西」和「玩家身上
    # 有这件东西」之间没有任何桥，定义完开局背包还是空的——这就是作者看到
    # 「道具定义了却用不上」的地方
    bag = starting_inventory(module, (await db.execute(
        select(RpgItem).where(RpgItem.module_id == module_id).order_by(RpgItem.sort_order, RpgItem.id)
    )).scalars().all())
    sess = RpgSession(
        module_id=module_id,
        title=data.title or f"{data.char_name}的冒险",
        char_name=data.char_name,
        char_desc=data.char_desc,
        stats=stats,
        inventory=bag,
        location=start,
        # 站在哪就算去过哪：地图一开局就该有一块是亮的
        visited=[start] if str(start or "").strip() else [],
        # 时段表只有玩家真的改过才存进这一局。**存空 = 跟模组走**，不是
        # 「这一局不要时钟」——空和「没配过」必须是同一个意思，模组后来调整
        # 时段表时还没定制的局才会跟着走（见 rpg_state.slot_table）
        time_slots=(
            [str(s).strip() for s in data.time_slots if str(s).strip()]
            if data.time_slots else []
        ),
    )
    # 开局就站在第一个时段上，否则首轮的状态块里时间是空的
    slots = slot_table(module, sess)
    if slots:
        sess.slot = slots[0]
    db.add(sess)
    await db.commit()
    await db.refresh(sess)

    # 每个角色各持一份关系数值。定义共用一套，起点可以被角色卡的
    # initial_state 单独覆盖（青梅竹马开局好感就该比陌生人高）
    npcs = (await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == module_id)
    )).scalars().all()
    if npcs:
        sess.npc_states = {
            str(npc.id): init_relation(module.relation_stat_defs, npc.initial_state)
            for npc in npcs
        }
        await db.commit()

    if module.opening_scene.strip():
        opening = module.opening_scene.strip()
        # 开场白是**场面线**的第一条旁白。历史是按线切的，所以私聊线里看不到它
        # ——玩家一开局去点开场白里写到的那个人，会撞上一条空线，而模型在那条
        # 线里也不知道刚刚发生了什么。
        db.add(RpgMessage(session_id=sess.id, role="assistant", content=opening))
        # 所以顺手压一条进外场。开场那一幕是这一局最公共的事实（「你在校长
        # 办公室、赫敏就在跟前」），而大事记本来就是跨线共享的那条通道，抬头
        # 还写着「传闻不等于亲眼见过」，正好合用。**不复制全文到每条线**：
        # 那样每条线都会各自演化、各自被总结，同一段话在不同线里会变成不同的事
        push_chronicle(sess, f"{OPENING_TAG}{opening[:OPENING_CHARS]}")
        await db.commit()
    return sess


@router.get("/sessions/{session_id}", response_model=RpgSessionOut)
async def get_session(session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return await _get_owned_session(db, session_id, user)


@router.patch("/sessions/{session_id}", response_model=RpgSessionOut)
async def update_session(
    session_id: int, data: RpgSessionUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    sess = await _get_owned_session(db, session_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(sess, field, value)
    await db.commit()
    await db.refresh(sess)
    return sess


@router.patch("/sessions/{session_id}/npc-notes/{npc_id}", response_model=RpgSessionOut)
async def delete_npc_note(
    session_id: int, npc_id: int, data: RpgNoteDeleteIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """划掉 GM 记错的一条近况。

    这是玩家唯一的补救：近况会一直画在角色卡上、每轮注入那个人的设定块，
    模型在第 12 回合写下一句「其实是幕后凶手」，没有这个口子就只能读档，
    把这之后玩的全扔掉。
    """
    sess = await _get_owned_session(db, session_id, user)
    apply_npc_notes(sess, npc_id, {data.key: None})
    await db.commit()
    await db.refresh(sess)
    return sess


@router.delete("/sessions/{session_id}/npc-activity/{npc_id}", response_model=RpgSessionOut)
async def delete_npc_activity(
    session_id: int, npc_id: int, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """划掉 AI 调度给这个人记的那句「最近在做什么」。

    这是玩家唯一的补救，理由同 delete_npc_note：那句话每轮注入这个人的设定块，
    模型会照着它往下编。她不在这儿的时候写了什么，玩家没看着、也不该被逼着
    接受——比如调度给一个刚死了哥的人编了「在集市上跟人闲聊天」。

    只清这一句，不清掉他的「AI 调度」开关：开关是模组作者的决定，改它要回模组页。
    """
    sess = await _get_owned_session(db, session_id, user)
    apply_npc_activity(sess, npc_id, "")
    await db.commit()
    await db.refresh(sess)
    return sess


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    sess = await _get_owned_session(db, session_id, user)
    await db.execute(delete(RpgMessage).where(RpgMessage.session_id == sess.id))
    await db.execute(delete(RpgSave).where(RpgSave.session_id == sess.id))
    await db.delete(sess)
    await db.commit()
    return {"ok": True}


# ── 存档 ──────────────────────────────────────────────────────────────────

# 一局上所有会随回合改变的字段。summary 和 summarized_upto_id 必须跟着一起
# 存：漏了它们，回溯之后摘要里还留着「未来」的剧情，模型会写出玩家没经历过
# 的事，这是最难查的一类 bug
#
# 通则：任何「会随回合自己变的」会话列都必须加进这张表。漏一个不会报错，
# 只会在读档之后留下一个不还原的字段——时段和天数就是这么进来的
SNAPSHOT_FIELDS = (
    "status", "stats", "inventory", "location", "flags", "npc_states",
    "summary", "summarized_upto_id", "dc_ledger", "turn_count",
    "time_slots", "slot", "day", "chronicle", "visited", "npc_notes",
    # AI 调度的产物。不回滚的话读档之后角色卡上还挂着「未来」的那句行动
    "npc_activities",
    # 分线概要同理，而且更隐蔽：场面线的概要回滚了、角色线的没回滚，
    # 读档之后两条线对同一段往事的记忆会直接打架
    "thread_summaries", "thread_upto",
    # 剧情挪动的人物位置。不回滚的话读档回到三天前，赫敏还站在办公室里——
    # 而那个"办公室"是三天后你才叫她去的
    "npc_places",
)
AUTO_SAVE_KEEP = 30

# 后加进 SNAPSHOT_FIELDS 的字段，老快照里根本没有这一项。读档时按这里的
# 默认值补上，否则读一个老档会把当前值留在原地。只列后加的——
# 「快照里没有」和「值是 None」是两回事，给老字段补默认反而会炸
SNAPSHOT_DEFAULTS = {
    "time_slots": [], "slot": "", "day": 1, "chronicle": [], "visited": [],
    "npc_notes": {}, "thread_summaries": {}, "thread_upto": {},
    "npc_activities": {}, "npc_places": {},
}


async def _take_save(db: AsyncSession, sess: RpgSession, kind: str, label: str) -> RpgSave:
    """存下「这一回合发生之前」的干净状态。

    JSON 列存的是引用，本轮还会就地改这些字典，所以必须深拷贝一份。
    """
    last_id = (await db.execute(
        select(func.max(RpgMessage.id)).where(RpgMessage.session_id == sess.id)
    )).scalar() or 0
    if kind == "auto":
        # 同一个消息位置只留最早那一张。时钟和瞬移不产生消息，连点十次就是
        # 十张 before_message_id 相同的快照，把 30 张的窗口挤满、真正的回合档
        # 被挤掉。最早那张才是「这一串点击之前」，后面的没有信息量
        dupe = (await db.execute(
            select(RpgSave)
            .where(
                RpgSave.session_id == sess.id,
                RpgSave.kind == "auto",
                RpgSave.before_message_id == last_id,
            )
            .order_by(RpgSave.id)
            .limit(1)
        )).scalars().first()
        if dupe is not None:
            return dupe
    row = RpgSave(
        session_id=sess.id,
        kind=kind,
        label=label or f"第 {sess.turn_count} 回合",
        turn_index=sess.turn_count,
        before_message_id=last_id,
        state={f: copy.deepcopy(getattr(sess, f)) for f in SNAPSHOT_FIELDS},
    )
    db.add(row)
    return row


async def _prune_auto_saves(db: AsyncSession, session_id: int) -> None:
    """自动档只留最近 30 张。手动档永不自动清。"""
    keep = (await db.execute(
        select(RpgSave.id)
        .where(RpgSave.session_id == session_id, RpgSave.kind == "auto")
        .order_by(RpgSave.id.desc())
        .limit(AUTO_SAVE_KEEP)
    )).scalars().all()
    if len(keep) >= AUTO_SAVE_KEEP:
        await db.execute(delete(RpgSave).where(
            RpgSave.session_id == session_id,
            RpgSave.kind == "auto",
            RpgSave.id.notin_(keep),
        ))


async def _get_owned_save(db: AsyncSession, save_id: int, user) -> RpgSave:
    save = await db.get(RpgSave, save_id)
    if not save:
        raise HTTPException(status_code=404, detail="存档不存在")
    await _get_owned_session(db, save.session_id, user)
    return save


@router.get("/sessions/{session_id}/saves/", response_model=list[RpgSaveOut])
async def list_saves(session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_session(db, session_id, user)
    return (await db.execute(
        select(RpgSave).where(RpgSave.session_id == session_id).order_by(RpgSave.id.desc())
    )).scalars().all()


@router.post("/sessions/{session_id}/saves/", response_model=RpgSaveOut)
async def create_save(
    session_id: int, data: RpgSaveCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """手动存档：存的是当下这一刻，读回来就回到现在。"""
    sess = await _get_owned_session(db, session_id, user)
    save = await _take_save(db, sess, "manual", data.label.strip())
    await db.commit()
    await db.refresh(save)
    return save


@router.post("/saves/{save_id}/restore", response_model=RpgSessionOut)
async def restore_save(save_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """读档：状态回到快照那一刻，之后产生的消息全部删掉。

    比这张更晚的存档一并删除——它们的 before_message_id 指向已经不存在的
    消息，留着只会在下次读档时把刚重玩的进度截断在一个错误的位置。
    """
    save = await _get_owned_save(db, save_id, user)
    sess = await db.get(RpgSession, save.session_id)

    await db.execute(delete(RpgMessage).where(
        RpgMessage.session_id == sess.id,
        RpgMessage.id > save.before_message_id,
    ))
    state = save.state or {}
    for field in SNAPSHOT_FIELDS:
        if field in state:
            setattr(sess, field, copy.deepcopy(state[field]))
        elif field in SNAPSHOT_DEFAULTS:
            setattr(sess, field, copy.deepcopy(SNAPSHOT_DEFAULTS[field]))
    await db.execute(delete(RpgSave).where(
        RpgSave.session_id == sess.id, RpgSave.id > save.id
    ))
    sess.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sess)
    return sess


@router.delete("/saves/{save_id}")
async def delete_save(save_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    save = await _get_owned_save(db, save_id, user)
    await db.delete(save)
    await db.commit()
    return {"ok": True}


# ── 消息与回合 ────────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/messages/", response_model=list[RpgMessageOut])
async def list_messages(session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _get_owned_session(db, session_id, user)
    return (await db.execute(
        select(RpgMessage)
        .where(RpgMessage.session_id == session_id)
        .order_by(RpgMessage.id)
    )).scalars().all()


@router.delete("/messages/{message_id}")
async def delete_message(message_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    row = await db.get(RpgMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在")
    await _get_owned_session(db, row.session_id, user)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ── 时间 ──────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/advance", response_model=RpgAdvanceOut)
async def advance_time(
    session_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """结束当前时段。碰最后一格就翻篇：新的一天、跨天回满。

    默认**纯引擎，不调模型**——按一下时钟不该产生任何叙事，也不该花玩家的钱。
    模组上勾了「外场简报」才会额外调一次便宜的模型写一两句别处的事，
    那时的花费和等待都写在按钮的提示里。
    """
    sess = await _get_owned_session(db, session_id, user)
    if sess.status != "alive":
        raise HTTPException(status_code=400, detail="这一局已经结束了，先读档再继续")

    # 和回合一样，动任何状态之前先拍档：时钟按错了也要能反悔
    await _take_save(db, sess, "auto", "")
    await _prune_auto_saves(db, session_id)

    module = await db.get(RpgModule, sess.module_id)
    was = str(sess.slot or "").strip()
    facts = advance_slot(module, sess)
    sess.updated_at = datetime.utcnow()
    await db.commit()

    # 简报在写事务提交之后才调模型：这个项目的铁律是写锁绝不跨 LLM 调用。
    # 简报自己另开一条连接写大事记，写完再把这个 sess 刷回来看新值
    if module is not None and module.offscreen_brief:
        facts = facts + await rpg_turn.offscreen_brief(session_id, was)

    await db.refresh(sess)
    return RpgAdvanceOut(session=sess, facts=facts)


# ── 瞬移 ──────────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/move", response_model=RpgMoveOut)
async def move_to(
    session_id: int, req: RpgMoveIn, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """从地点总览点一个地方就直接过去。纯引擎，零 LLM。

    进不去就把拒绝的理由原样返回（进入条件没满足），不是错误——
    被门槛拦下是地图的正常反馈，不该弹一个红色的失败提示。
    """
    sess = await _get_owned_session(db, session_id, user)
    if sess.status != "alive":
        raise HTTPException(status_code=400, detail="这一局已经结束了，先读档再继续")

    # 地点表和角色表在这里读、改动在这里提交：移动必须跑在路由自己这条连接上。
    # 另开一条连接写 rpg_sessions 会和下面拍存档的写事务互锁（SQLite 单写者）
    locs = list((await db.execute(
        select(RpgLocation).where(RpgLocation.module_id == sess.module_id)
    )).scalars().all())
    npcs = list((await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == sess.module_id)
    )).scalars().all())

    # 自己拍档，和 /advance 同一个理由：它绕过了 stream_turn 的存档，
    # 不拍的话瞬移五格再读档会回到上一个回合，中间的地点跳转无法反悔。
    # before_message_id 与上一次回合相同，读档会删 0 条消息、只回滚状态
    before = sess.location
    save = await _take_save(db, sess, "auto", "")
    message = rpg_turn.move_by_name(sess, locs, npcs, req.target)
    if sess.location == before:
        # 没走成（没路、门槛没过、已经在这儿了）：什么都没改，刚拍的那张档
        # 也撤回去，否则点几个走不通的地点就攒出一串一模一样的空快照
        if save in db.new:
            db.expunge(save)
        return RpgMoveOut(session=sess, message=message)

    await _prune_auto_saves(db, session_id)
    sess.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sess)
    return RpgMoveOut(session=sess, message=message)


# ── 帮我想想 ──────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/suggest", response_model=RpgSuggestOut)
async def suggest_actions(
    session_id: int, user: CurrentUser, thread_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """根据最近几轮给出 3 条候选行动，点一条直接发出去。

    「最近几轮」指**当前这条线**的最近几轮：在老兵屋里给的建议，不该来自
    隔壁酒馆刚聊的那些话。
    """
    sess = await _get_owned_session(db, session_id, user)
    module = await db.get(RpgModule, sess.module_id)
    history = [
        m for m in (await db.execute(
            select(RpgMessage)
            .where(RpgMessage.session_id == session_id)
            .order_by(RpgMessage.id)
        )).scalars().all()
        if (m.thread_id or None) == (thread_id or None)
    ]
    try:
        return RpgSuggestOut(
            suggestions=await rpg_turn.suggest_actions(module, sess, history, thread_id)
        )
    except ValueError as e:
        # 模型配错时 resolve_model_ref 抛 ValueError，别变成 500
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sessions/{session_id}/stream")
async def stream_turn(
    session_id: int, req: RpgTurnRequest, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """跑一回合：引擎结算 →（可选）判定 → 叙事 → 结算，全程 SSE。

    玩家那句话在开流之前就落库并提交——网络断了也得留下，否则前端重连后
    对不上。编排在 agents/rpg_turn.py，这里只负责落库和把事件编码成 SSE。
    """
    sess = await _get_owned_session(db, session_id, user)
    if sess.status != "alive":
        raise HTTPException(status_code=400, detail="这一局已经结束了，先读档再继续")
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="说点什么再发")

    # 这一轮归哪条线：只在这里解析一次，之后一路传下去。
    # 线主不在当前地点就整轮拒掉——历史照常可读，只是不给输入框
    npcs = list((await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == sess.module_id)
    )).scalars().all())
    thread_id = rpg_turn.resolve_thread_id(sess, npcs, req.thread_id, req.target_npc)
    if req.thread_id and thread_id is None:
        raise HTTPException(status_code=404, detail="这条对话线不存在")
    blocker = rpg_turn.thread_blocker(sess, npcs, thread_id)
    if blocker:
        raise HTTPException(status_code=400, detail=blocker)

    # 自动存档必须在这一轮动任何东西之前拍：有了权威状态就必须能反悔，
    # 一次坏判定不该毁掉整局
    await _take_save(db, sess, "auto", "")
    await _prune_auto_saves(db, session_id)

    row = RpgMessage(
        session_id=session_id, role="user", content=content, thread_id=thread_id
    )
    db.add(row)
    sess.turn_count += 1
    sess.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    user_message_id = row.id

    async def event_stream():
        try:
            async for event, data in rpg_turn.run_turn(
                session_id, user_message_id, content, req.attr,
                req.action_id, req.item_name, req.move_to, req.target_npc,
                thread_id,
            ):
                yield sse_event(event, data)
        except (asyncio.CancelledError, GeneratorExit):
            # 半段的落库由 run_turn 自己丢给独立 task，这里只让取消继续往上传
            raise
        except Exception as e:
            logger.exception("RPG 局 %s 这一轮崩了", session_id)
            yield sse_event("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
