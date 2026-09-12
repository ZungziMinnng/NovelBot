"""RPG 模式的提示词注册表与用户覆盖。结构与 tavern_prompts 一致。

分开一份而不是并进酒馆那份：两边的变量集完全不同，合表会让设置页列出
一堆对当前模式无意义的模板，而且改 RPG 的变量要顾虑酒馆。
"""
from jinja2 import StrictUndefined, TemplateError, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment

from app.prompts.loader import _TEMPLATE_DIR, render as render_default
from app.services.auth import current_user_var


PROMPTS = {
    "rpg_gm.jinja2": {
        "label": "主持人（GM）",
        "description": "每轮叙事的基础要求，后面还会拼入模组的 GM 风格、世界观、你的状态、在场角色和世界设定。",
        "variables": {"char_name": "玩家角色名", "genre": "游戏类型（都市、魔法世界、互动养成……）", "reply_length": "目标叙事字数，0 表示不限"},
    },
    "rpg_adjudicate.jinja2": {
        "label": "行动裁决",
        "description": "判断玩家的行动要不要判定、看哪一项数值、有多难。难度只能从五个档位里选，成功率由模组的档位表定死——改动时请保留这一点，否则同一件事的难度会每轮乱跳。判定默认是关着的，只有在模组里手动打开才会走这个模板。",
        "variables": {"action": "玩家这一轮的输入", "stats": "玩家数值表", "location": "当前位置", "recent": "最近一段剧情", "ledger": "本局此前的判定记录，每项含 key、attr、band"},
    },
    "rpg_judgement.jinja2": {
        "label": "判定结果注入",
        "description": "把判定结果告诉叙事模型。这一段会插在你那句话的最前面，是全局最要紧的一块——建议保留「不可更改」和禁用含糊词的要求，否则模型会把失败写成成功。",
        "variables": {"intent": "归一化后的行动描述", "attr": "检定的数值名", "rate": "成功率（%）", "dice": "掷出的点数，关掉随机时为 0", "outcome_label": "结果档位（大成功/成功/险胜/失败/大失败）", "guidance": "该档位对应的写法提示，由后端生成"},
    },
    "rpg_settle.jinja2": {
        "label": "回合结算",
        "description": "从刚写出的剧情里读出状态变化，并顺带给出三条建议行动。请保持 JSON 输出格式和字段名，后端按字段名解析。数值名不在模组定义里的会被丢弃。",
        "variables": {"narration": "刚写出来的剧情", "outcome_label": "本回合判定结果，没开判定时为空", "stats": "玩家当前数值表", "location": "当前位置", "inventory": "背包，每项含 name、qty", "flags": "当前处境开关", "npcs": "在场角色，每项含 id、name、notes（这一局已经记下的近况）", "note_keys": "这一局所有角色用过的近况键名，提示模型别造同义词", "relation_names": "模组定义的关系数值名", "engine_note": "本轮已由引擎精确结算的部分，提示模型不要重复计算", "chronicle": "已经传开的事，最近几条，提示模型不要重复记录"},
    },
    "rpg_suggest.jinja2": {
        "label": "帮我想想",
        "description": "生成玩家的候选行动。请保持每行一条、共三行的输出格式。",
        "variables": {"char_name": "玩家角色名", "location": "当前位置", "summary": "已有剧情梗概", "transcript": "最近发生的事"},
    },
    "rpg_summary.jinja2": {
        "label": "剧情梗概",
        "description": "把较早的剧情压缩为长期记忆。建议保留禁止编造的要求；修改只影响下一次压缩。",
        "variables": {"previous_summary": "已有剧情梗概", "transcript": "需要压缩的剧情"},
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
    # 渲染两遍：一遍全都有值，一遍全是空的。只测有值那遍的话，
    # 用户写的 {% for %} 里一旦引用了列表元素的字段，空列表那条路径永远没被走过
    values = {key: "示例" for key in PROMPTS[name]["variables"]}
    values.update(
        reply_length=200, stats={"敏捷": 12}, ledger=[{"key": "撬锁", "attr": "敏捷", "band": "hard"}],
        rate=63, dice=41, relation_names=["好感", "信任"],
        inventory=[{"name": "火把", "qty": 1}], flags={"地窖门已开": True},
        npcs=[{"id": 1, "name": "老兵", "notes": {"伤势": "左肩中刀"}}], note_keys=["伤势"],
        chronicle=["后山挖出了尸首"],
    )
    template = _env.from_string(content)
    template.render(**values)
    values.update(
        reply_length=0, stats={}, ledger=[], inventory=[], flags={}, npcs=[],
        note_keys=[], relation_names=[],
        location="", recent="", summary="", previous_summary="", dice=0,
        outcome_label="", engine_note="", chronicle=[],
    )
    template.render(**values)


def render(template_name: str, **kwargs) -> str:
    user = current_user_var.get()
    overrides = getattr(user, "rpg_prompts", None) or {}
    content = overrides.get(template_name)
    if template_name in PROMPTS and content is not None:
        return _env.from_string(content).render(**kwargs)
    return render_default(template_name, **kwargs)
