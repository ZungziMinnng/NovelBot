from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from jinja2 import Environment, TemplateSyntaxError
from pydantic import BaseModel

from app.prompts.loader import _TEMPLATE_DIR, reload as reload_templates
from app.api.deps import require_admin

# 提示词模板是全局共享文件，只允许管理员查看/修改
router = APIRouter(dependencies=[Depends(require_admin)])

PROMPT_META: dict[str, dict[str, str]] = {
    "writer.jinja2": {"category": "创作", "label": "Writer 写作", "description": "章节生成系统提示词"},
    "writer_opening.jinja2": {"category": "创作", "label": "Writer 开篇（黄金三章）", "description": "仅第 1-3 章追加的开篇要求，按章号分三段；与护栏同样不被自定义写手提示词覆盖"},
    "rewriter.jinja2": {"category": "创作", "label": "Rewriter 重写", "description": "章节重写系统提示词"},
    "outline.jinja2": {"category": "世界与大纲", "label": "Outline 大纲", "description": "章节大纲生成提示词"},
    "initializer.jinja2": {"category": "世界与大纲", "label": "World 初始化", "description": "世界观初始化提示词"},
    "world_optimizer.jinja2": {"category": "世界与大纲", "label": "World 优化", "description": "世界观优化提示词"},
    "world_section.jinja2": {"category": "世界与大纲", "label": "World 分区块生成/优化", "description": "单个世界观区块（时代背景/核心规则/特殊元素）的生成或优化提示词"},
    "character.jinja2": {"category": "角色与图像", "label": "Character 角色", "description": "角色档案生成提示词"},
    "build_characters.jinja2": {"category": "世界与大纲", "label": "Build 角色阵容", "description": "一键建书：根据世界观批量设计主要角色的提示词"},
    "build_locations.jinja2": {"category": "世界与大纲", "label": "Build 地点", "description": "一键建书：批量生成初始地点的提示词"},
    "build_factions.jinja2": {"category": "世界与大纲", "label": "Build 势力", "description": "一键建书：批量生成初始势力的提示词"},
    "build_techniques.jinja2": {"category": "世界与大纲", "label": "Build 功法", "description": "一键建书：批量生成初始功法体系的提示词"},
    "image_prompt_sd_tags.jinja2": {"category": "角色与图像", "label": "Image SD 标签", "description": "文生图 Illustrious/SD 标签提示词"},
    "image_prompt_natural_zh.jinja2": {"category": "角色与图像", "label": "Image 中文描述", "description": "文生图中文自然语言提示词"},
    "brainstorm.jinja2": {"category": "世界与大纲", "label": "新建小说 构思对话", "description": "新建小说页右侧探讨窗口的提示词，自由聊天和七步向导共用。前半段是人设与回话规则，末尾按 stage 分支给出每一步问什么（随便说说/核心点子/人物/开篇/剧情/世界观/收尾）。不读表单草稿（对话单向影响表单），要求不写正文、结论能落回表单"},
    "brainstorm_extract.jinja2": {"category": "世界与大纲", "label": "新建小说 结论抽取", "description": "把构思对话里聊定的结论抽成表单字段的提示词，抽完给作者确认才写进表单"},
    "critic.jinja2": {"category": "审查", "label": "Critic 审查", "description": "质量审查提示词"},
    "detail_review.jinja2": {"category": "审查", "label": "Review 剧情细节", "description": "生成章节保存前的剧情细节审查提示词"},
    "fulltext_review.jinja2": {"category": "审查", "label": "Review 全文审查", "description": "全书范围连续性与矛盾审查提示词"},
    "chapter_summary_prefix.jinja2": {"category": "记忆", "label": "章节摘要前置", "description": "章节内容压缩为剧情梗概的前置提示词"},
    "chapter_summary_suffix.jinja2": {"category": "记忆", "label": "章节摘要后置", "description": "章节摘要输出格式约束提示词"},
    "chapter_summary_discover_prefix.jinja2": {"category": "记忆", "label": "摘要+发现+伏笔前置", "description": "生成流水线：单次调用同时完成章节摘要、五类新设定发现、伏笔/秘密（长期事实）提取的前置提示词，含各自的提取规则"},
    "chapter_summary_discover_suffix.jinja2": {"category": "记忆", "label": "摘要+发现+伏笔后置", "description": "摘要+新设定发现+伏笔/秘密提取合并调用的 JSON 输出格式提示词（threads 字段即伏笔/秘密）"},
    "character_update_prefix.jinja2": {"category": "记忆", "label": "角色更新前置", "description": "根据章节内容更新角色状态的前置提示词"},
    "character_update_suffix.jinja2": {"category": "记忆", "label": "角色更新后置", "description": "角色状态更新 JSON 输出格式提示词"},
    "entity_location_update_prefix.jinja2": {"category": "记忆", "label": "实体+地点更新前置", "description": "根据章节内容一次性更新道具/系统与地点状态的前置提示词"},
    "entity_location_update_suffix.jinja2": {"category": "记忆", "label": "实体+地点更新后置", "description": "实体与地点状态更新 JSON 输出格式提示词"},
    "arc_summary.jinja2": {"category": "记忆", "label": "故事弧概要", "description": "多章摘要合并为故事弧概要的提示词"},
    "book_summary.jinja2": {"category": "记忆", "label": "全书概要", "description": "章节摘要合并为全书概要的提示词"},
    "book_summary_merge.jinja2": {"category": "记忆", "label": "全书概要合并", "description": "分批概要合并为完整全书概要的提示词"},
    "book_summary_update.jinja2": {"category": "记忆", "label": "全书概要增量更新", "description": "把最近几章摘要融入现有全书概要的增量更新提示词"},
    "worldview_drift.jinja2": {"category": "审查", "label": "世界观漂移检测", "description": "检测近期章节与世界观规则冲突的提示词"},
    "tavern_roleplay.jinja2": {"category": "酒馆", "label": "酒馆 扮演底层指令", "description": "每轮拼在系统提示最前面的扮演规则（怎么演、旁白尺度、不许替玩家发言），角色卡的系统指令排在它后面可覆盖"},
    "tavern_summary.jinja2": {"category": "酒馆", "label": "酒馆 剧情梗概", "description": "酒馆早期对话压缩成长期记忆的提示词（含禁止编造的约束，改动请保留）"},
    "tavern_suggest.jinja2": {"category": "酒馆", "label": "酒馆 帮我想想", "description": "根据角色最后一句话生成四条候选玩家回复的提示词"},
    "tavern_card_field.jinja2": {"category": "酒馆", "label": "酒馆 角色卡分栏生成/优化", "description": "角色卡单栏（角色性格/详细描述/开场环境）的生成或优化提示词，栏位为空时生成、有内容时优化"},
    "tavern_card_note.jinja2": {"category": "酒馆", "label": "酒馆 角色卡介绍", "description": "根据角色性格与详细描述生成角色卡介绍的提示词（这栏只给作者看、不进扮演 prompt）"},
}


class PromptInfo(BaseModel):
    name: str
    category: str
    label: str
    description: str


class PromptContent(BaseModel):
    name: str
    content: str


class PromptUpdate(BaseModel):
    content: str


@router.get("/", response_model=list[PromptInfo])
async def list_prompts():
    result = []
    for name, meta in PROMPT_META.items():
        path = _TEMPLATE_DIR / name
        if path.exists():
            result.append(PromptInfo(name=name, **meta))
    return result


@router.get("/{name}", response_model=PromptContent)
async def get_prompt(name: str):
    if name not in PROMPT_META:
        raise HTTPException(404, "未知的提示词模板")
    path = _TEMPLATE_DIR / name
    if not path.exists():
        raise HTTPException(404, "模板文件不存在")
    return PromptContent(name=name, content=path.read_text(encoding="utf-8"))


@router.put("/{name}", response_model=PromptContent)
async def update_prompt(name: str, data: PromptUpdate):
    if name not in PROMPT_META:
        raise HTTPException(404, "未知的提示词模板")
    path = _TEMPLATE_DIR / name
    if not path.exists():
        raise HTTPException(404, "模板文件不存在")
    try:
        Environment().parse(data.content)
    except TemplateSyntaxError as exc:
        raise HTTPException(400, f"模板语法错误：{exc.message}") from exc
    path.write_text(data.content, encoding="utf-8")
    reload_templates()
    return PromptContent(name=name, content=data.content)
