from pathlib import Path
from fastapi import APIRouter, HTTPException
from jinja2 import Environment, TemplateSyntaxError
from pydantic import BaseModel

from app.prompts.loader import _TEMPLATE_DIR, reload as reload_templates

router = APIRouter()

PROMPT_META: dict[str, dict[str, str]] = {
    "writer.jinja2": {"category": "创作", "label": "Writer 写作", "description": "章节生成系统提示词"},
    "rewriter.jinja2": {"category": "创作", "label": "Rewriter 重写", "description": "章节重写系统提示词"},
    "outline.jinja2": {"category": "世界与大纲", "label": "Outline 大纲", "description": "章节大纲生成提示词"},
    "initializer.jinja2": {"category": "世界与大纲", "label": "World 初始化", "description": "世界观初始化提示词"},
    "world_optimizer.jinja2": {"category": "世界与大纲", "label": "World 优化", "description": "世界观优化提示词"},
    "character.jinja2": {"category": "角色与图像", "label": "Character 角色", "description": "角色档案生成提示词"},
    "image_prompt_sd_tags.jinja2": {"category": "角色与图像", "label": "Image SD 标签", "description": "文生图 Illustrious/SD 标签提示词"},
    "image_prompt_natural_zh.jinja2": {"category": "角色与图像", "label": "Image 中文描述", "description": "文生图中文自然语言提示词"},
    "critic.jinja2": {"category": "审查", "label": "Critic 审查", "description": "质量审查提示词"},
    "detail_review.jinja2": {"category": "审查", "label": "Review 剧情细节", "description": "生成章节保存前的剧情细节审查提示词"},
    "fulltext_review.jinja2": {"category": "审查", "label": "Review 全文审查", "description": "全书范围连续性与矛盾审查提示词"},
    "chapter_summary_prefix.jinja2": {"category": "记忆", "label": "章节摘要前置", "description": "章节内容压缩为剧情梗概的前置提示词"},
    "chapter_summary_suffix.jinja2": {"category": "记忆", "label": "章节摘要后置", "description": "章节摘要输出格式约束提示词"},
    "character_update_prefix.jinja2": {"category": "记忆", "label": "角色更新前置", "description": "根据章节内容更新角色状态的前置提示词"},
    "character_update_suffix.jinja2": {"category": "记忆", "label": "角色更新后置", "description": "角色状态更新 JSON 输出格式提示词"},
    "entity_update_prefix.jinja2": {"category": "记忆", "label": "实体更新前置", "description": "根据章节内容更新道具/系统状态的前置提示词"},
    "entity_update_suffix.jinja2": {"category": "记忆", "label": "实体更新后置", "description": "实体状态更新 JSON 输出格式提示词"},
    "location_update_prefix.jinja2": {"category": "记忆", "label": "地点更新前置", "description": "根据章节内容更新地点状态的前置提示词"},
    "location_update_suffix.jinja2": {"category": "记忆", "label": "地点更新后置", "description": "地点状态更新 JSON 输出格式提示词"},
    "arc_summary.jinja2": {"category": "记忆", "label": "故事弧概要", "description": "多章摘要合并为故事弧概要的提示词"},
    "book_summary.jinja2": {"category": "记忆", "label": "全书概要", "description": "章节摘要合并为全书概要的提示词"},
    "book_summary_merge.jinja2": {"category": "记忆", "label": "全书概要合并", "description": "分批概要合并为完整全书概要的提示词"},
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
