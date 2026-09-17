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

from app.agents import image_tags, rpg_assist, rpg_discover, rpg_turn, rpg_wizard
from app.api.deps import CurrentUser
from app.api.routes.rpg_prompts import router as prompts_router
from app.database import get_db
from app.models.rpg import (
    RpgAction, RpgActionPreset, RpgInstructionPreset, RpgItem, RpgLocation, RpgMessage,
    RpgModule, RpgNpc, RpgRule, RpgSave, RpgSession, RpgSkill, RpgStatPreset, RpgTask,
    RpgWorldEntry,
)
from app.schemas.rpg import (
    RpgActionCreate, RpgActionOut, RpgActionUpdate,
    RpgActionPresetCreate, RpgActionPresetOut, RpgActionPresetUpdate,
    RpgAdvanceOut,
    RpgAssistIn, RpgAssistOut,
    RpgDiscoveryApplyIn, RpgDiscoveryApplyOut,
    RpgGenerateIn,
    RpgInstructionPresetCreate, RpgInstructionPresetOut, RpgInstructionPresetUpdate,
    RpgItemClaimConfirmIn, RpgItemCreate, RpgItemOut, RpgItemUpdate,
    RpgLocationCreate, RpgLocationOut, RpgLocationUpdate,
    RpgMessageOut, RpgMessageUpdate,
    RpgModuleCreate, RpgModuleOut, RpgModuleUpdate,
    RpgMoveIn, RpgMoveOut,
    RpgNoteDeleteIn,
    RpgNpcAvatarGenerateIn, RpgNpcCreate, RpgNpcOut, RpgNpcUpdate,
    RpgPromptAsTagsIn, RpgPromptAsTagsOut,
    RpgRuleCreate, RpgRuleOut, RpgRuleUpdate,
    RpgSaveCreate, RpgSaveOut,
    RpgSessionCreate, RpgSessionOut, RpgSessionUpdate,
    RpgSkillCreate, RpgSkillOut, RpgSkillUpdate,
    RpgStatPresetCreate, RpgStatPresetOut, RpgStatPresetUpdate,
    RpgSuggestOut,
    RpgTaskCreate, RpgTaskOut, RpgTaskResolveIn, RpgTaskStateIn, RpgTaskUpdate,
    RpgTurnRequest,
    RpgWizardChatIn, RpgWizardExtractIn, RpgWizardExtractOut, RpgWizardFullIn,
    RpgWorldEntryCreate, RpgWorldEntryOut, RpgWorldEntryUpdate,
)
from app.services import comfyui, llm_json, rpg_image, rpg_settlement
from app.services.rpg_memory import invalidate_summaries
from app.services.rpg_context import (
    GROUP_MODE, PRIVATE_MODE, TURN_MODES, present_ids, turn_present,
)
from app.services.rpg_state import (
    OPENING_CHARS, OPENING_TAG,
    TASK_DONE, TASK_FAILED, TASK_OPEN,
    advance_slot, apply_npc_activity, apply_npc_notes, apply_place_note,
    apply_stats, close_task,
    init_relation, init_stats,
    apply_inventory,
    learn_skill, norm_name, open_task,
    protagonist_identity,
    push_chronicle, slot_table, spend_slot_action,
    starting_inventory, starting_skills, starting_tasks,
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


def _save_image_bytes(data: bytes, prefix: str, ext: str) -> str:
    """把图片字节写进头像目录，返回访问路径。"""
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    (AVATARS_DIR / filename).write_bytes(data)
    return f"/api/avatars/{filename}"


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
    return _save_image_bytes(data, prefix, ext)


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


async def _get_owned_instruction_preset(
    db: AsyncSession, preset_id: int, user
) -> RpgInstructionPreset:
    preset = await db.get(RpgInstructionPreset, preset_id)
    if not preset or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="常用指令不存在")
    return preset


async def _get_owned_stat_preset(db: AsyncSession, preset_id: int, user) -> RpgStatPreset:
    preset = await db.get(RpgStatPreset, preset_id)
    if not preset or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="数值套装不存在")
    return preset


async def _get_owned_action_preset(db: AsyncSession, preset_id: int, user) -> RpgActionPreset:
    preset = await db.get(RpgActionPreset, preset_id)
    if not preset or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="动作套装不存在")
    return preset


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


# ── 常用 GM 指令 ──────────────────────────────────────────────────────────
# 照酒馆 /tavern/instruction-presets/ 那一套，逐条对应。

@router.get("/instruction-presets/", response_model=list[RpgInstructionPresetOut])
async def list_instruction_presets(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(RpgInstructionPreset)
        .where(RpgInstructionPreset.user_id == user.id)
        .order_by(RpgInstructionPreset.updated_at.desc())
    )).scalars().all()


@router.post("/instruction-presets/", response_model=RpgInstructionPresetOut)
async def create_instruction_preset(
    data: RpgInstructionPresetCreate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    name = data.name.strip()
    content = (data.content or "").strip()
    if not name or not content:
        raise HTTPException(status_code=400, detail="名称和内容都不能为空")
    preset = RpgInstructionPreset(name=name, content=content, user_id=user.id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.patch("/instruction-presets/{preset_id}", response_model=RpgInstructionPresetOut)
async def update_instruction_preset(
    preset_id: int, data: RpgInstructionPresetUpdate, user: CurrentUser,
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
    """删常用指令。模组侧无需清理：取用是拷贝文本，模组不存 preset_id。"""
    preset = await _get_owned_instruction_preset(db, preset_id, user)
    await db.delete(preset)
    await db.commit()
    return {"ok": True}


# ── 预设库 ────────────────────────────────────────────────────────────────
# 数值套装和动作套装各一套 CRUD。刻意平铺不抽工厂：只有两组、字段名还不一样，
# 抽出来读的人得先跳到工厂里才知道 /stat-presets/ 收什么。

@router.get("/stat-presets/", response_model=list[RpgStatPresetOut])
async def list_stat_presets(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(RpgStatPreset)
        .where(RpgStatPreset.user_id == user.id)
        .order_by(RpgStatPreset.sort_order, RpgStatPreset.id)
    )).scalars().all()


@router.post("/stat-presets/", response_model=RpgStatPresetOut)
async def create_stat_preset(
    data: RpgStatPresetCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="数值套装名称不能为空")
    preset = RpgStatPreset(**{**data.model_dump(), "name": name}, user_id=user.id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.patch("/stat-presets/{preset_id}", response_model=RpgStatPresetOut)
async def update_stat_preset(
    preset_id: int, data: RpgStatPresetUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    preset = await _get_owned_stat_preset(db, preset_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(preset, field, value)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/stat-presets/{preset_id}")
async def delete_stat_preset(
    preset_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """删数值套装。不需要任何模组侧清理：套用是拷贝一次就断开的，
    模组里从不存套装 id，本来就不存在引用。"""
    preset = await _get_owned_stat_preset(db, preset_id, user)
    await db.delete(preset)
    await db.commit()
    return {"ok": True}


@router.get("/action-presets/", response_model=list[RpgActionPresetOut])
async def list_action_presets(user: CurrentUser, db: AsyncSession = Depends(get_db)):
    return (await db.execute(
        select(RpgActionPreset)
        .where(RpgActionPreset.user_id == user.id)
        .order_by(RpgActionPreset.sort_order, RpgActionPreset.id)
    )).scalars().all()


@router.post("/action-presets/", response_model=RpgActionPresetOut)
async def create_action_preset(
    data: RpgActionPresetCreate, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="动作套装名称不能为空")
    preset = RpgActionPreset(**{**data.model_dump(), "name": name}, user_id=user.id)
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.patch("/action-presets/{preset_id}", response_model=RpgActionPresetOut)
async def update_action_preset(
    preset_id: int, data: RpgActionPresetUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    preset = await _get_owned_action_preset(db, preset_id, user)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(preset, field, value)
    await db.commit()
    await db.refresh(preset)
    return preset


@router.delete("/action-presets/{preset_id}")
async def delete_action_preset(
    preset_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """删动作套装。同数值套装：套完就断开，不存在需要清理的引用。"""
    preset = await _get_owned_action_preset(db, preset_id, user)
    await db.delete(preset)
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
    for model in (RpgWorldEntry, RpgItem, RpgSkill, RpgTask, RpgLocation, RpgAction):
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
            rpg_wizard.pick_model(data.model, module.model_ref),
            data.nsfw, data.stage, data.confirmed, data.play_style,
            data.world_scope,
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
            data.stage, transcript, data.known,
            rpg_wizard.pick_model(data.model, module.model_ref),
            data.temperature,
        )
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"抽取失败：{e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("RPG 模组 %s 向导步骤 %s 抽取失败", module_id, data.stage)
        raise HTTPException(status_code=500, detail="构思抽取发生内部错误，请重试；若持续失败，请查看后台日志") from e
    return RpgWizardExtractOut(**result)


@router.post("/modules/{module_id}/wizard/generate", response_model=RpgWizardExtractOut)
async def wizard_generate_full(
    module_id: int, data: RpgWizardFullIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """根据一句话生成整套模组草案，清洗后交给前端预览回填。"""
    module = await _get_owned_module(db, module_id, user)
    instruction = data.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="请先输入一句话想法")
    try:
        result = await rpg_wizard.generate_full(
            instruction, data.nsfw, module.play_style,
            rpg_wizard.pick_model(data.model, module.model_ref),
            data.world_scope,
            data.temperature,
        )
    except llm_json.JsonCallError as e:
        raise HTTPException(status_code=502, detail=f"生成失败：{e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RpgWizardExtractOut(**result)


# 一键生成的类别 → 拉「已有同名」用的模型。白名单靠查库，不用前端传
_GENERATE_MODELS = {
    "location": RpgLocation, "npc": RpgNpc, "item": RpgItem,
    "skill": RpgSkill, "task": RpgTask, "action": RpgAction,
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
            kind, data.instruction, count, known, data.nsfw,
            rpg_wizard.pick_model(data.model, module.model_ref),
            module.play_style,
            data.temperature,
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
    # 换成自己上传的图之后，原来那个种子已经不描述当前这张立绘了，留着是假信息
    npc.avatar_seed = 0
    await db.commit()
    await db.refresh(npc)
    return npc


@router.get("/comfy-workflows", response_model=list[str])
async def list_comfy_workflows(user: CurrentUser):
    """data/comfy_workflows/ 下有哪些工作流，给出图设置的下拉用。

    只要登录态：这是本机文件名列表，不是服务器配置，不该和 /settings 那组一样锁 admin。
    """
    return comfyui.list_workflows()


@router.get("/comfy-loras", response_model=list[dict])
async def list_comfy_loras(user: CurrentUser, workflow: str = ""):
    """某份工作流里有哪些 LoRA，给出图设置里的开关列表用。

    返回的是工作流文件里的原始状态。模组自己的覆写存在 image_config.loras，
    前端叠在这份上面——所以用户重新导出工作流、加减了 LoRA，这里会立刻反映
    出来，而已经调好的那几条设置不会丢。
    """
    try:
        return comfyui.inspect_loras(workflow.strip() or "npc_portrait")
    except comfyui.ComfyError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/comfy-checkpoints", response_model=dict)
async def list_comfy_checkpoints(user: CurrentUser, workflow: str = ""):
    """某份工作流认不认底模、现在写死的是哪个，外加本机有哪些可选。

    available 得问 ComfyUI（checkpoint 放在哪是它那边 extra_model_paths 的事），
    slots 读工作流文件。两份一起返回是为了让前端先看 slots：走 UNETLoader
    单文件的工作流（如默认的 npc_portrait）它就是空的，那种情况不画控件——
    画一个填了没反应的下拉比不画更糟。
    """
    try:
        return {
            "available": await comfyui.list_checkpoints(),
            "slots": comfyui.inspect_ckpts(workflow.strip() or "npc_portrait"),
        }
    except comfyui.ComfyError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/npcs/{npc_id}/avatar/generate", response_model=RpgNpcOut)
async def generate_npc_avatar(
    npc_id: int, data: RpgNpcAvatarGenerateIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """调本机 ComfyUI 出立绘。出图慢（十几秒到几分钟），前端要放宽超时。"""
    npc = await _get_owned_npc(db, npc_id, user)
    prompt = data.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="提示词不能为空")
    # 用哪份工作流是设置里的事，后端现读，不进请求体——前端传一遍反而会和库里漂移。
    # 风格词和题材则相反：它们已经由前端拼进 prompt 了，用户在弹窗里看得见能删。
    #
    # 两层：模组那份是总览和默认，这个人自己那份（`npc.image_config`，稀疏）盖在
    # 上面。合并规则见 services/rpg_image.py，前端预览用的是同一套规则
    module = await db.get(RpgModule, npc.module_id)
    workflow, loras, ckpt = rpg_image.resolve_workflow(
        module.image_config, npc.image_config
    )
    # 种子在这里先摇定再传下去，为的是出图成功后能把这一个确定的值记进库——
    # 让 comfyui.generate 自己摇的话，这边就不知道刚才用的是哪个了
    seed = data.seed if data.seed is not None else comfyui.random_seed()
    try:
        image = await comfyui.generate(
            prompt, data.width, data.height, seed=seed, loras=loras, ckpt=ckpt,
            **({"workflow": workflow} if workflow else {}),
        )
    except comfyui.ComfyError as e:
        raise HTTPException(status_code=502, detail=str(e))
    _unlink_image(npc.avatar_url)
    npc.avatar_url = _save_image_bytes(image, f"rpgnpc{npc_id}", ".png")
    npc.avatar_seed = seed
    await db.commit()
    await db.refresh(npc)
    return npc


@router.post("/npcs/{npc_id}/prompt-as-tags", response_model=RpgPromptAsTagsOut)
async def npc_prompt_as_tags(
    npc_id: int, data: RpgPromptAsTagsIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """把中文源文转成 Danbooru tag，交前端填进可编辑的 tag 框。

    不落库、不直接出图：转完的 tag 要给用户过目能删。为什么走这条链路而不是让
    模型一次吐 tag，见 agents/image_tags.py。用模组的 image_model_ref，空则顺次
    回落 fast_model_ref、model_ref——tag 过白名单校验又能给用户过目删改，便宜模型
    就够，没必要花叙事模型的钱。
    """
    npc = await _get_owned_npc(db, npc_id, user)
    module = await db.get(RpgModule, npc.module_id)
    try:
        tags, dropped = await image_tags.convert(
            data.source,
            module.image_model_ref or module.fast_model_ref or module.model_ref,
            nsfw=data.nsfw,
            char_name=npc.name if data.include_char_name else "",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RpgPromptAsTagsOut(tags=tags, dropped=dropped)


@router.delete("/npcs/{npc_id}/avatar", response_model=RpgNpcOut)
async def delete_npc_avatar(npc_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    npc = await _get_owned_npc(db, npc_id, user)
    _unlink_image(npc.avatar_url)
    npc.avatar_url = ""
    npc.avatar_seed = 0
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
_mount_module_child("skills", RpgSkill, RpgSkillOut, RpgSkillCreate, RpgSkillUpdate, "技能")
_mount_module_child("tasks", RpgTask, RpgTaskOut, RpgTaskCreate, RpgTaskUpdate, "任务")
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
    # 开局会的技能，同理：定义里勾了「开局就会」的那些
    learned = starting_skills((await db.execute(
        select(RpgSkill).where(RpgSkill.module_id == module_id).order_by(RpgSkill.sort_order, RpgSkill.id)
    )).scalars().all())
    # 开局就挂着的差事，同理：定义里勾了「开局就接下」的那些
    todo = starting_tasks((await db.execute(
        select(RpgTask).where(RpgTask.module_id == module_id).order_by(RpgTask.sort_order, RpgTask.id)
    )).scalars().all())
    # 锁了主角的模组，名字和出身一律照主角模板卡来——界面上那两栏是只读的，但
    # 界面拦不住直接打接口，而「玩家扮演谁」是这个模组的设定本身，不是建局偏好。
    # 没有那张卡（或卡上没名字）就当没锁：锁着一个空名字等于谁都开不了局
    char_name, char_desc = data.char_name, data.char_desc
    if module.lock_protagonist:
        fixed = protagonist_identity((await db.execute(
            select(RpgNpc).where(RpgNpc.module_id == module_id).order_by(RpgNpc.sort_order, RpgNpc.id)
        )).scalars().all())
        if fixed:
            char_name, char_desc = fixed
    sess = RpgSession(
        module_id=module_id,
        title=data.title or f"{char_name}的冒险",
        char_name=char_name,
        char_desc=char_desc,
        stats=stats,
        inventory=bag,
        skills=learned,
        tasks=todo,
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
            str(npc.id): init_relation(
                module.relation_stat_defs,
                npc.initial_state,
                npc.relation_stat_names,
            )
            for npc in npcs
            if getattr(npc, "relation_enabled", None) is not False
        }
        await db.commit()

    if module.opening_scene.strip():
        opening = module.opening_scene.strip()
        # 开场白是**场面线**的第一条旁白。历史是按线切的，所以私聊线里看不到它
        # ——玩家一开局去点开场白里写到的那个人，会撞上一条空线，而模型在那条
        # 线里也不知道刚刚发生了什么。
        db.add(RpgMessage(
            session_id=sess.id, role="assistant", content=opening,
            # 开场这一幕的在场名单也快照下来。开场白里写到的那些人从此算「她在
            # 场」——这正是第三十节那个「她像是不知道开场」的根
            location=sess.location or "",
            present=present_ids(npcs, sess.location, sess.slot, sess.npc_places),
        ))
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


@router.patch("/sessions/{session_id}/place-note", response_model=RpgSessionOut)
async def delete_place_note(
    session_id: int, data: RpgNoteDeleteIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """划掉 GM 给某个地方记错的那一句近况。data.key 是地名。

    理由同 delete_npc_note：这一句每次你走进这个地方都会进【场面】，模型
    照着它往下写。记错了（"整间屋子烧没了"，其实只是烧了张桌子）没有这个
    口子就只能读档，把这之后玩的全扔掉。
    """
    sess = await _get_owned_session(db, session_id, user)
    apply_place_note(sess, data.key, "")
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
    "status", "stats", "inventory", "skills", "location", "flags", "npc_states",
    "summary", "summarized_upto_id", "thread_summaries", "thread_upto",
    "dc_ledger", "turn_count",
    "time_slots", "slot", "day", "chronicle", "visited", "npc_notes",
    # AI 调度的产物。不回滚的话读档之后角色卡上还挂着「未来」的那句行动
    "npc_activities",
    # 剧情挪动的人物位置。不回滚的话读档回到三天前，赫敏还站在办公室里——
    # 而那个"办公室"是三天后你才叫她去的
    "npc_places",
    # 地点近况。同理：读档回到踹门之前，地窖那扇门不该还是坏的
    "place_notes",
    # 待确认的新发现。读档回到三回合前，那之后才冒出来的人不该还挂在角标上——
    # 它指向的那段剧情已经不存在了
    "discoveries",
    # 待办清单和待确认的收线提议。读档回到接下这桩事之前，任务栏不该还挂着它
    "tasks", "task_proposals",
    # 待认领的新道具。同理：读档回到捡到它之前，道具格上不该还挂着它
    "item_claims",
    # 这一格用掉的行动数和对话数。不回滚的话读档回到「还剩两格」那一刻，
    # 下一个动作就把时段推走了——时钟看着像自己乱跳
    "slot_actions", "slot_chats",
    # flag 的立起日期。必须跟着 flags 一起回滚，否则读档回到那件事之前，
    # flags 里没了它、日期却还留着，重新触发时「之后三天」当场就满足了
    "flag_days",
)
AUTO_SAVE_KEEP = 30

# 后加进 SNAPSHOT_FIELDS 的字段，老快照里根本没有这一项。读档时按这里的
# 默认值补上，否则读一个老档会把当前值留在原地。只列后加的——
# 「快照里没有」和「值是 None」是两回事，给老字段补默认反而会炸
SNAPSHOT_DEFAULTS = {
    "time_slots": [], "slot": "", "day": 1, "chronicle": [], "visited": [],
    "npc_notes": {}, "thread_summaries": {}, "thread_upto": {},
    "npc_activities": {}, "npc_places": {}, "place_notes": {},
    "discoveries": [],
    # 技能和冷却。读档回到学会它之前，技能栏不该还留着那一条
    "skills": [],
    "tasks": [], "task_proposals": [], "item_claims": [],
    # 时段计数器。老快照里没有这两项，补 0 = 「这一格还没用过」
    "slot_actions": 0, "slot_chats": 0,
    # 老快照里没有 flag 日期。补空字典 = 那些 flag 没记过日期，
    # after_days 条件判不过，和加这一列之前的行为一致
    "flag_days": {},
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


async def _rewind_to_save(db: AsyncSession, sess: RpgSession, save: RpgSave) -> None:
    """把这一局倒回这张快照：状态照抄，之后产生的消息与存档全部删掉。

    比这张更晚的存档一并删除——它们的 before_message_id 指向已经不存在的
    消息，留着只会在下次读档时把刚重玩的进度截断在一个错误的位置。
    不 commit，由调用方决定这一步和别的改动是不是一个事务。
    """
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


@router.post("/saves/{save_id}/restore", response_model=RpgSessionOut)
async def restore_save(save_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """读档：状态回到快照那一刻，之后产生的消息全部删掉。"""
    save = await _get_owned_save(db, save_id, user)
    sess = await db.get(RpgSession, save.session_id)
    await _rewind_to_save(db, sess, save)
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


@router.patch("/messages/{message_id}", response_model=RpgMessageOut)
async def update_message(
    message_id: int, data: RpgMessageUpdate, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """保存正文修订，标记结算过期并清除由旧正文派生的摘要。"""
    row = await db.get(RpgMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在")
    sess = await _get_owned_session(db, row.session_id, user)
    content = data.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    if content != row.content:
        row.content = content
        if row.role == "assistant":
            report = copy.deepcopy(row.settlement or {})
            report.update({"status": "stale", "retryable": bool(report.get("baseline")),
                           "facts": [], "warnings": ["正文已修改，状态需要重新结算"]})
            row.settlement = report
        later = (await db.execute(select(RpgMessage).where(
            RpgMessage.session_id == sess.id, RpgMessage.id > row.id, RpgMessage.role == "assistant",
        ))).scalars().all()
        for following in later:
            following.settlement = {
                **(following.settlement or {}), "status": "stale", "facts": [],
                "invalidated_by": row.id, "retryable": False,
                "warnings": [f"前面的消息 #{row.id} 已修改，请从对应玩家消息回滚重玩"],
            }
        invalidate_summaries(sess)
        sess.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/messages/{message_id}/settle", response_model=RpgMessageOut)
async def settle_message(
    message_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    row = await db.get(RpgMessage, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    await _get_owned_session(db, row.session_id, user)
    session_id, content = row.session_id, row.content
    report = row.settlement or {}
    label = report.get("outcome_label", "")
    engine_note, fixed_location = report.get("engine_note", ""), report.get("fixed_location")
    await db.rollback()
    try:
        await rpg_turn._settle(session_id, message_id, content, label, engine_note, fixed_location)
    except rpg_settlement.SettlementConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception("RPG 消息 %s 补结算失败", message_id)
        raise HTTPException(status_code=502, detail=f"补结算失败，剧情已保留：{error}") from error
    return await db.get(RpgMessage, message_id, populate_existing=True)


async def _fetch_discoveries(db: AsyncSession, sess: RpgSession, ids: list[str]) -> list[dict]:
    """按 id 从待确认列表里取出条目，顺序按前端传的 ids 走。找不到的直接忽略——
    两个标签页各点一次「加入」时，第二次该是静默的空操作，不是 404。"""
    by_id = {entry["id"]: entry for entry in (sess.discoveries or [])
             if isinstance(entry, dict) and entry.get("id")}
    return [by_id[key] for key in dict.fromkeys(ids) if key in by_id]


@router.post("/sessions/{session_id}/discoveries/apply", response_model=RpgDiscoveryApplyOut)
async def apply_discoveries(
    session_id: int, data: RpgDiscoveryApplyIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """把勾中的发现项补全成完整档案并建行。

    主要写模组表（rpg_npcs / rpg_locations / rpg_items / rpg_skills / rpg_tasks），
    不需要结算那套乐观锁——它锁的是 updated_at 加 `capture()` 出来的那些字段，
    而这里动的三列（discoveries / skills / tasks）都不在 STATE_FIELDS 里，
    结算不会覆写它们，也就不存在丢更新。所以**不要**在这里改 updated_at：
    改了只会让正在跑的那次结算白白报冲突。

    建出来的是**模组资产**：它跨局共用，所以「改完重发」回滚不会把它撤掉。
    作者不想要了在模组页删一行即可。
    """
    sess = await _get_owned_session(db, session_id, user)
    picked = await _fetch_discoveries(db, sess, data.ids)
    if not picked:
        return RpgDiscoveryApplyOut(remaining=sess.discoveries or [])
    module = await db.get(RpgModule, sess.module_id)

    # 依据只能是发现项所在的那几段正文。跨回合勾选时按消息顺序拼起来
    message_ids = sorted({entry.get("message_id") for entry in picked if entry.get("message_id")})
    rows = list((await db.execute(
        select(RpgMessage).where(RpgMessage.id.in_(message_ids), RpgMessage.session_id == session_id)
        .order_by(RpgMessage.id)
    )).scalars()) if message_ids else []
    narration = "\n\n".join(row.content for row in rows if row.content)

    npcs = list((await db.execute(select(RpgNpc).where(RpgNpc.module_id == module.id))).scalars())
    places = list((await db.execute(select(RpgLocation).where(RpgLocation.module_id == module.id))).scalars())
    items = list((await db.execute(select(RpgItem).where(RpgItem.module_id == module.id))).scalars())
    skills = list((await db.execute(select(RpgSkill).where(RpgSkill.module_id == module.id))).scalars())
    tasks = list((await db.execute(select(RpgTask).where(RpgTask.module_id == module.id))).scalars())

    try:
        drafted = await rpg_discover.flesh_out(
            module, picked, narration, [place.name for place in places],
            rpg_wizard.pick_model(data.model, module.model_ref), data.temperature,
        )
    except ValueError as error:  # 模型配错，同向导：别变成 500
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("RPG 局 %s 补全发现项失败", session_id)
        raise HTTPException(status_code=502, detail=f"补全失败：{error}") from error

    dropped = list(drafted["dropped"])
    taken = {
        "npc": {norm_name(row.name) for row in npcs},
        "place": {norm_name(row.name) for row in places},
        "item": {norm_name(row.name) for row in items},
        "skill": {norm_name(row.name) for row in skills},
        "task": {norm_name(row.name) for row in tasks},
    }

    def _fresh(kind: str, label: str, specs: list[dict]) -> list[dict]:
        """重名的一律拦下。通用 CRUD 入口不查重（见 _mount_module_child），但结算
        按名字找人找地方——撞名之后 _place_ref / _npc_ref 会认不出是哪一个，
        于是那个人的状态从此写不进去，还不报错。"""
        kept = []
        for spec in specs:
            slug = norm_name(spec["name"])
            if slug in taken[kind]:
                dropped.append(f"{label}「{spec['name']}」和模组里已有的重名，没有建")
                continue
            taken[kind].add(slug)
            kept.append(spec)
        return kept

    def _existing(kind: str, specs: list[dict]):
        """模组里已经有定义、这一次没建行的那几个。

        技能和任务要用它补上「这一局也拿到」那一步：定义早就建过了（作者手写的、
        或上一局建的），可这一局还没学会/接下的话，走到这儿会被 _fresh 当重名
        丢掉，于是玩家点了「加入」什么也没发生，而且它再也不会被报成新发现。
        """
        by_slug = {norm_name(row.name): row for row in (skills if kind == "skill" else tasks)}
        return [row for row in (by_slug.get(norm_name(spec["name"])) for spec in specs)
                if row is not None]

    # _fresh 会往 taken 里加名字，所以先把「已有的」摘出来，否则本批新建的
    # 也会被算成已有
    had_skills = _existing("skill", drafted["skills"])
    had_tasks = _existing("task", drafted["tasks"])

    made_npcs, made_places, made_items, made_skills, made_tasks = [], [], [], [], []
    for spec in _fresh("place", "地点", drafted["locations"]):
        row = RpgLocation(
            module_id=module.id, name=spec["name"], description=spec["description"],
            connections=spec["connections"],
        )
        db.add(row)
        made_places.append((row, spec["parent_name"]))
    for spec in _fresh("npc", "角色", drafted["npcs"]):
        row = RpgNpc(
            module_id=module.id, name=spec["name"], persona=spec["persona"],
            appearance=spec["appearance"], description=spec["description"],
            profile_sections=spec["profile_sections"], location=spec["location"],
            initial_state=spec["initial_state"],
            relation_enabled=bool(spec["initial_state"]),
        )
        db.add(row)
        made_npcs.append(row)
    for spec in _fresh("item", "道具", drafted["items"]):
        row = RpgItem(
            module_id=module.id, name=spec["name"], description=spec["description"],
            category=spec["category"], consumable=spec["consumable"],
            effects=spec["effects"],
            # 剧情里捡到的东西不该跟着下一局开场就带在身上
            start_with=False,
        )
        db.add(row)
        made_items.append(row)
    for spec in _fresh("skill", "技能", drafted["skills"]):
        row = RpgSkill(
            module_id=module.id, name=spec["name"], description=spec["description"],
            category=spec["category"], cooldown=spec["cooldown"], effects=spec["effects"],
            # 同道具：这一局学会的招不该跟着下一局开场就带着
            start_with=False,
        )
        db.add(row)
        made_skills.append(row)
    for spec in _fresh("task", "任务", drafted["tasks"]):
        row = RpgTask(
            module_id=module.id, name=spec["name"], description=spec["description"],
            objective=spec["objective"], category=spec["category"], effects=spec["effects"],
            auto_start=False,
        )
        db.add(row)
        made_tasks.append(row)

    await db.flush()
    # 父地点按名字引用，落库要转成 id。本批新建的地点也能当父级，所以在 flush
    # 拿到 id 之后才解析
    by_name = {norm_name(place.name): place.id for place in places}
    by_name.update({norm_name(row.name): row.id for row, _ in made_places})
    for row, parent_name in made_places:
        if parent_name:
            row.parent_id = by_name.get(norm_name(parent_name))

    # 技能和任务比人/地方/东西多这一步：光建行不够。剧情里写的是「你学会了一招」
    # 「你应下了这桩事」，建完档还躺在模组库里、这一局用不了的话，玩家会觉得
    # 「加入模组」什么也没发生。道具没有这一步是因为它本来就得先捡到手
    #
    # had_* 是模组里早就有定义、这一次只补「这一局也拿到」的那些：漏了它们的话，
    # 定义存在但这一局没学会就成了个死结（发现被筛掉、学也学不到）
    learned, opened = [], []
    for row in [*made_skills, *had_skills]:
        if learn_skill(sess, row.name):
            learned.append(row)
    for row in [*made_tasks, *had_tasks]:
        if open_task(sess, row.name, desc=row.description, goal=row.objective,
                     task_id=row.id, source="story"):
            opened.append(row)

    done = {entry["id"] for entry in picked}
    remaining = [entry for entry in (sess.discoveries or [])
                 if not (isinstance(entry, dict) and entry.get("id") in done)]
    sess.discoveries = remaining
    await db.commit()
    for row in [*made_npcs, *made_items, *made_skills, *made_tasks,
                *(row for row, _ in made_places)]:
        await db.refresh(row)
    return RpgDiscoveryApplyOut(
        npcs=made_npcs, locations=[row for row, _ in made_places], items=made_items,
        skills=made_skills, tasks=made_tasks, dropped=dropped, remaining=remaining,
        learned=[row.name for row in learned], opened=[row.name for row in opened],
    )


@router.delete("/sessions/{session_id}/discoveries/{discovery_id}", response_model=RpgSessionOut)
async def dismiss_discovery(
    session_id: int, discovery_id: str, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """「不要这个」。只是从待办里划掉，不影响剧情，也不阻止它下回合再被认出来——
    真不想再看见就把它建档，或者别在正文里提它。"""
    sess = await _get_owned_session(db, session_id, user)
    sess.discoveries = [entry for entry in (sess.discoveries or [])
                        if not (isinstance(entry, dict) and entry.get("id") == discovery_id)]
    await db.commit()
    await db.refresh(sess)
    return sess


@router.post("/sessions/{session_id}/item_claims/{claim_id}/confirm", response_model=RpgSessionOut)
async def confirm_item_claim(
    session_id: int, claim_id: str, data: RpgItemClaimConfirmIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """认下这一件：进背包，顺手在模组道具表里落一条定义。

    同名定义已经有了就复用那一条，不再建一行：作者可能早写过这件东西，只是没料到
    有人会在剧情里捡到它。建了同名的第二行，「用它的时候算哪一条的效果」从此没有
    答案（结算和引擎都按名字找，见 _fresh 那段的同一个理由）。复用时**不动
    start_with**——那是「开局就带」，和这一局捡到没有关系。

    不改 updated_at，理由同上面两个发现项端点：它是结算的乐观锁，为了记一笔待办
    去动它，只会让正在跑的那次结算白白报冲突。
    """
    sess = await _get_owned_session(db, session_id, user)
    claims = [entry for entry in (sess.item_claims or []) if isinstance(entry, dict)]
    claim = next((entry for entry in claims if entry.get("id") == claim_id), None)
    if claim is None:
        raise HTTPException(status_code=404, detail="这条待确认的道具已经不在了")

    name = str(claim.get("name") or "").strip()
    # 兜到至少 1：认下来的东西只可能是「有」，0 会被 apply_inventory 直接跳过，
    # 于是这一条从待确认里消失了、背包里也没有
    qty = max(1, int(claim.get("qty") or 1))
    rows = list((await db.execute(
        select(RpgItem).where(RpgItem.module_id == sess.module_id)
    )).scalars())
    if not any(norm_name(row.name) == norm_name(name) for row in rows):
        db.add(RpgItem(
            module_id=sess.module_id, name=name,
            description=str(claim.get("note") or ""),
            # 「一次性还是重复使用」问的就是这一格。分类跟着它填，作者翻定义时
            # 不用再猜；效果留空——正文没说它加多少，猜一个数比不给更糟
            category="消耗品" if data.consumable else "关键道具",
            consumable=data.consumable,
            # 剧情里捡到的东西不该跟着下一局开场就带在身上（同 apply_discoveries）
            start_with=False,
        ))

    apply_inventory(sess, [{"name": name, "qty": qty, "note": str(claim.get("note") or "")}])
    sess.item_claims = [entry for entry in claims if entry.get("id") != claim_id]
    await db.commit()
    await db.refresh(sess)
    return sess


@router.delete("/sessions/{session_id}/item_claims/{claim_id}", response_model=RpgSessionOut)
async def dismiss_item_claim(
    session_id: int, claim_id: str, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """「这不是我拿到的东西」。只把这条划掉，背包和模组道具表一个字都不动。

    刻意**不**顺手记一笔「丢掉了什么」：玩家说的是这件东西压根不该是他的，
    不是「我把它扔了」，两句话的后果完全不同。
    """
    sess = await _get_owned_session(db, session_id, user)
    sess.item_claims = [entry for entry in (sess.item_claims or [])
                        if not (isinstance(entry, dict) and entry.get("id") == claim_id)]
    await db.commit()
    await db.refresh(sess)
    return sess


async def _task_reward(db: AsyncSession, sess: RpgSession, row: dict) -> None:
    """一桩事办成之后发奖励。只认模组里那一条的 `effects`，剧情里冒出来的
    差事（task_id 为空）没有奖励——奖励是作者定的，不能让模型现编。"""
    if str(row.get("status") or "") != TASK_DONE:
        return
    task_id = row.get("task_id")
    if not task_id:
        return
    task = await db.get(RpgTask, int(task_id))
    if task is None or not task.effects:
        return
    module = await db.get(RpgModule, sess.module_id)
    if module is not None:
        apply_stats(module, sess, task.effects)


@router.post("/sessions/{session_id}/tasks/resolve", response_model=RpgSessionOut)
async def resolve_tasks(
    session_id: int, data: RpgTaskResolveIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """玩家在确认窗里勾完了。勾中的按提议改状态并发奖励，没勾的只是从
    待确认里消失——「我看过了，这条不算完」和「还没看」必须是两回事，
    否则同一条提议每回合都会再弹一次。

    只认 id：提议的名字和动作以库里存的为准，前端改了也不算数。"""
    sess = await _get_owned_session(db, session_id, user)
    proposals = {
        str(p.get("id")): p for p in (sess.task_proposals or []) if isinstance(p, dict)
    }
    seen: list[str] = []
    for entry in data.accepts or []:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("id") or "")
        proposal = proposals.get(pid)
        if proposal is None:
            continue
        seen.append(pid)
        if not entry.get("accept"):
            continue
        action = str(proposal.get("action") or TASK_DONE)
        row = close_task(sess, str(proposal.get("name") or ""), action)
        # close_task 对已经了结的那条返回 None，奖励因此只可能发一次
        if row is not None:
            await _task_reward(db, sess, row)
    sess.task_proposals = [
        p for p in (sess.task_proposals or [])
        if isinstance(p, dict) and str(p.get("id")) not in seen
    ]
    await db.commit()
    await db.refresh(sess)
    return sess


@router.patch("/sessions/{session_id}/tasks", response_model=RpgSessionOut)
async def set_task_state(
    session_id: int, data: RpgTaskStateIn, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """玩家自己在任务格里改一条：手动标完成/失败、改回进行中，或者划掉。

    手动标完成同样发奖励（走 close_task 的「只改 open 的那条」，重复点不会
    发两次）；标回 open 不退奖励——已经拿到手的东西不该因为改主意消失。"""
    sess = await _get_owned_session(db, session_id, user)
    name = (data.name or "").strip()
    status = (data.status or "").strip()
    if not name:
        raise HTTPException(400, "要改哪一条")
    if status and status not in (TASK_OPEN, TASK_DONE, TASK_FAILED):
        raise HTTPException(400, f"不认识的状态「{status}」")
    rows = [dict(t) for t in (sess.tasks or []) if isinstance(t, dict)]
    if not any(norm_name(str(t.get("name") or "")) == norm_name(name) for t in rows):
        raise HTTPException(404, "没有这一条待办")
    if not status:
        sess.tasks = [
            t for t in rows if norm_name(str(t.get("name") or "")) != norm_name(name)
        ]
    elif status == TASK_OPEN:
        for row in rows:
            if norm_name(str(row.get("name") or "")) == norm_name(name):
                row["status"] = TASK_OPEN
                row["closed_turn"] = 0
        sess.tasks = rows
    else:
        row = close_task(sess, name, status)
        if row is not None:
            await _task_reward(db, sess, row)
    # 这条事既然玩家自己定了，模型对它的提议就作废，别再弹
    sess.task_proposals = [
        p for p in (sess.task_proposals or [])
        if isinstance(p, dict) and norm_name(str(p.get("name") or "")) != norm_name(name)
    ]
    await db.commit()
    await db.refresh(sess)
    return sess


@router.post("/messages/{message_id}/rewind", response_model=RpgSessionOut)
async def rewind_before_message(
    message_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db),
):
    """回到这条消息发生**之前**：这条以及之后的消息全删，状态一起回滚。

    改自己说过的话等于从那一句重来，所以不能只删消息——数值、背包、时段、
    好感都是那一轮结算出来的，留着就会出现「话没说过，代价却还在」。
    回滚点用的是每回合开打前拍的那张自动档（见 `_take_save`）：取
    before_message_id 小于这条消息里最靠后的那张，正好是这一轮之前的状态。

    自动档只留最近 AUTO_SAVE_KEEP 张，太久之前的消息因此改不了——那时候
    没有可回滚的状态，硬删消息只会留下一局对不上账的存档。
    """
    row = await db.get(RpgMessage, message_id)
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在")
    sess = await _get_owned_session(db, row.session_id, user)
    save = (await db.execute(
        select(RpgSave)
        .where(
            RpgSave.session_id == sess.id,
            RpgSave.before_message_id < message_id,
        )
        # 同一个位置可能有好几张（手动档 + 自动档），取最早那张：它才是
        # 「这一串操作之前」，同 _take_save 的去重口径
        .order_by(RpgSave.before_message_id.desc(), RpgSave.id.asc())
        .limit(1)
    )).scalars().first()
    if save is None:
        raise HTTPException(
            status_code=400,
            detail=f"这条太早了，自动存档只留最近 {AUTO_SAVE_KEEP} 次回合，回滚不到那一刻",
        )
    await _rewind_to_save(db, sess, save)
    await db.commit()
    await db.refresh(sess)
    return sess


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
    """结束当前时段。碰最后一格就翻篇：新的一天、跨天恢复。

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

    # 走成了才记一格行动。这一路和 _resolve_engine 里的移动是同一件事——
    # 只是入口不同（点地图 vs 打字说「我去后山」），预算上不该有两个口径。
    # 上面那个「没走成就原样返回」已经把被门槛拦下的情形挡在外面了
    module = await db.get(RpgModule, sess.module_id)
    moved_on = spend_slot_action(module, sess)
    if moved_on:
        message += "。" + "，".join(moved_on)
    await _prune_auto_saves(db, session_id)
    sess.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(sess)
    return RpgMoveOut(session=sess, message=message)


# ── 帮我想想 ──────────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/suggest", response_model=RpgSuggestOut)
async def suggest_actions(
    session_id: int, user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """根据最近几轮给出 3 条候选行动，点一条直接发出去。

    「最近几轮」和叙事模型看到的那几轮是同一份：都交给 history_window，都按
    此刻的在场名单筛。这里自己算一遍名单，是因为 suggest_actions 拿不到 db。

    原先这里还收一个 focus_npc_id，但它声明成 query 参数而前端发在 body 里，
    从来没接到过值。现在筛选依据是「谁在跟前」而不是「玩家点了谁」，它也就
    没有用处了，一并摘掉
    """
    sess = await _get_owned_session(db, session_id, user)
    module = await db.get(RpgModule, sess.module_id)
    rows = list((await db.execute(
        select(RpgMessage)
        .where(RpgMessage.session_id == session_id)
        .order_by(RpgMessage.id)
    )).scalars().all())
    npcs = list((await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == sess.module_id)
    )).scalars().all())
    here_ids = set(present_ids(npcs, sess.location, sess.slot, sess.npc_places))
    try:
        suggestions = await rpg_turn.suggest_actions(module, sess, rows, here_ids)
        return RpgSuggestOut(suggestions=suggestions)
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
    stale = (await db.execute(select(RpgMessage.id).where(
        RpgMessage.session_id == session_id,
        RpgMessage.settlement["status"].as_string() == "stale",
    ).limit(1))).scalar()
    if stale is not None:
        raise HTTPException(status_code=409, detail="有修改过的剧情尚未重新结算，请先补结算；若已有后续回合，请从对应玩家消息回滚重玩")
    running = (await db.execute(select(RpgMessage.id).where(
        RpgMessage.session_id == session_id,
        RpgMessage.settlement["status"].as_string() == "running",
    ).limit(1))).scalar()
    if running is not None:
        raise HTTPException(status_code=409, detail="上一轮仍在结算，请等待完成；若服务曾中断，请在该回合重试结算")

    # 这里原先有三件事：解析这一轮归哪条线、线主不在跟前就拒、显式给了 null
    # 就不拿 target_npc 兜底。全是线的概念，线拆了，三件一起没了。
    # **req.thread_id 不再读**：它是老前端的字段，忽略即可，不再代表归属——
    # 一段叙事归谁看由消息上的 present 决定，那是快照，不是请求参数
    npcs = list((await db.execute(
        select(RpgNpc).where(RpgNpc.module_id == sess.module_id)
    )).scalars().all())
    mode = req.mode if req.mode in TURN_MODES else GROUP_MODE
    move_target = req.move_to
    if not (move_target or req.action_id or req.item_name or req.skill_name) and mode != PRIVATE_MODE:
        locations = list((await db.execute(
            select(RpgLocation).where(RpgLocation.module_id == sess.module_id)
        )).scalars().all())
        move_target = rpg_turn.movement_target(content, locations)
    if mode == PRIVATE_MODE:
        target = next((n for n in npcs if n.id == req.private_with), None)
        if target is None:
            raise HTTPException(status_code=404, detail="角色不存在")
        # 不在跟前的人叫不到一边去。放过去的话会凭空造出一段两人根本不在同一个
        # 地方的对话，而且只记进她一个人的记忆，事后连查都难查
        if target.id not in present_ids(npcs, sess.location, sess.slot, sess.npc_places):
            raise HTTPException(
                status_code=400, detail=f"{target.name}不在跟前，没法单独说话"
            )

    # 自动存档必须在这一轮动任何东西之前拍：有了权威状态就必须能反悔，
    # 一次坏判定不该毁掉整局
    await _take_save(db, sess, "auto", "")
    await _prune_auto_saves(db, session_id)

    # 这一轮的在场名单，**在写 user 行之前快照一次**，同一轮的两行共用。
    # 不能等 assistant 行落库时再算：结算会把人物挪走（apply_npc_activity /
    # move_npcs），那时候算出来的是「这一轮结束后谁在」，一问一答会分到两拨
    # 在场名单里，于是同一次对话在两个人的视图里各缺一半。
    #
    # 走 turn_present 而不是裸的 present_ids：私聊要把名单收窄到那一个人，
    # 而**拼上下文那边用的是同一个函数**，两边差一个人就会出「他说过的话他
    # 自己不记得」
    present = [n.id for n in turn_present(npcs, sess, mode, req.private_with)]
    place = sess.location or ""

    row = RpgMessage(
        session_id=session_id, role="user", content=content,
        location=place, present=present,
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
                action_id=req.action_id, item_name=req.item_name,
                skill_name=req.skill_name, move_to=move_target,
                target_npc=req.target_npc,
                present=present, place=place, mode=mode,
                private_with=req.private_with,
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
