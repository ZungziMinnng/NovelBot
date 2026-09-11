from jinja2 import StrictUndefined, TemplateError, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment

from app.prompts.loader import _TEMPLATE_DIR, render as render_default
from app.services.auth import current_user_var


PROMPTS = {
    "tavern_roleplay.jinja2": {
        "label": "角色扮演",
        "description": "每轮对话的基础扮演要求，后面还会拼入角色卡系统指令、人物设定、世界书和写作规则。",
        "variables": {"char_name": "当前角色名", "persona": "玩家名", "others": "同场其他角色名列表", "reply_length": "目标回复字数，0 表示不限"},
    },
    "tavern_summary.jinja2": {
        "label": "剧情摘要",
        "description": "把较早的对话压缩为长期记忆。建议保留禁止编造的要求；修改只影响下一次摘要。",
        "variables": {"previous_summary": "已有剧情摘要", "transcript": "需要压缩的对话"},
    },
    "tavern_suggest.jinja2": {
        "label": "帮我想想",
        "description": "生成玩家回复建议。请保持每行一条、共四行的输出格式。",
        "variables": {"persona": "玩家名", "char_name": "角色名", "summary": "已有剧情摘要", "transcript": "最近对话"},
    },
    "tavern_card_field.jinja2": {
        "label": "角色卡生成与优化",
        "description": "生成或优化性格、详细描述、开场环境等栏目。请只输出当前栏目的正文。",
        "variables": {"field_label": "栏目名称", "field_guidance": "栏目要求", "char_name": "角色名", "context_blocks": "其他栏目列表，每项含 label 和 content", "is_generate": "是否从零生成", "content": "当前栏目内容", "max_chars": "字数上限"},
    },
    "tavern_card_note.jinja2": {
        "label": "角色卡介绍",
        "description": "根据性格和详细描述生成给作者看的简介，简介不参与角色扮演。",
        "variables": {"char_name": "角色名", "personality": "角色性格", "description": "详细描述"},
    },
}

_env = ImmutableSandboxedEnvironment(undefined=StrictUndefined)
_env.globals.clear()


def default_content(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


def validate(name: str, content: str) -> None:
    parsed = _env.parse(content)
    unknown = meta.find_undeclared_variables(parsed) - PROMPTS[name]["variables"].keys()
    if unknown:
        raise TemplateError(f"未知变量：{'、'.join(sorted(unknown))}")
    values = {key: "示例" for key in PROMPTS[name]["variables"]}
    values.update(others=["同伴"], reply_length=200, context_blocks=[{"label": "性格", "content": "示例"}], is_generate=True, max_chars=1000)
    template = _env.from_string(content)
    template.render(**values)
    values.update(others=[], reply_length=0, context_blocks=[], is_generate=False)
    template.render(**values)


def render(template_name: str, **kwargs) -> str:
    user = current_user_var.get()
    overrides = getattr(user, "tavern_prompts", None) or {}
    content = overrides.get(template_name)
    if template_name in PROMPTS and content is not None:
        return _env.from_string(content).render(**kwargs)
    return render_default(template_name, **kwargs)
