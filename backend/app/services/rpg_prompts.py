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
        "variables": {"action": "玩家这一轮的输入", "stats": "玩家数值表", "location": "当前位置", "recent": "最近一段剧情", "ledger": "本局此前的判定记录，每项含 key、attr、band", "roster": "模组登记过的角色名单，一行一个，用来把「宗主」「我娘」这类称呼还原成名字"},
    },
    "rpg_judgement.jinja2": {
        "label": "判定结果注入",
        "description": "把判定结果告诉叙事模型。这一段会插在你那句话的最前面，是全局最要紧的一块——建议保留「不可更改」和禁用含糊词的要求，否则模型会把失败写成成功。",
        "variables": {"intent": "归一化后的行动描述", "attr": "检定的数值名", "rate": "成功率（%）", "dice": "掷出的点数，关掉随机时为 0", "outcome_label": "结果档位（大成功/成功/险胜/失败/大失败）", "guidance": "该档位对应的写法提示，由后端生成"},
    },
    "rpg_settle.jinja2": {
        "label": "回合结算",
        "description": "从刚写出的剧情里读出状态变化，并顺带给出三条建议行动。请保持 JSON 输出格式和字段名，后端按字段名解析。数值名不在模组定义里的会被丢弃。",
        "variables": {"narration": "刚写出来的剧情", "outcome_label": "本回合判定结果，没开判定时为空", "outcome_failed": "这一轮是不是判定失败（失败/大失败）。为真时多一句「失败必须留下代价」——后端也会按这一条校验，空结算会被打回重做", "stats": "玩家当前数值表", "location": "当前位置", "place_note": "这个地方已经记下的那一句近况，提示模型别重复写", "inventory": "背包，每项含 name、qty", "flags": "当前处境开关", "npcs": "在场角色，每项含 id、name、notes（这一局已经记下的近况）、relations（这个人当前的关系数字）、appearance（这一局已经被改写掉的外貌）", "note_keys": "这一局所有角色用过的近况键名，提示模型别造同义词", "relation_names": "模组定义的关系数值名", "step_caps": "作者定了每轮变化上限的数值，{名字: 上限}，没定过的不在里面", "engine_note": "本轮已由引擎精确结算的部分，提示模型不要重复计算", "chronicle": "已经传开的事，最近几条，提示模型不要重复记录", "tasks": "手上还没办完的事，每项含 name、goal（怎样才算办完）；模型只能在这份清单里提议收线", "has_clock": "这个模组有没有时段。只有有时段时才问模型「这一幕收尾了吗」（scene_wrapped）"},
    },
    "rpg_suggest.jinja2": {
        "label": "帮我想想",
        "description": "生成玩家的候选行动。请保持每行一条、共三行的输出格式。",
        "variables": {"char_name": "玩家角色名", "location": "当前位置", "summary": "已有剧情梗概", "transcript": "最近发生的事"},
    },
    "rpg_summary.jinja2": {
        "label": "剧情梗概",
        "description": "把较早的剧情压缩为长期记忆。建议保留禁止编造的要求；修改只影响下一次压缩。",
        "variables": {"previous_summary": "已有剧情梗概", "transcript": "需要压缩的剧情", "scope": "这一份梗概属于谁（你自己的经历，还是与某个角色之间的事）"},
    },
    "rpg_offscreen.jinja2": {
        "label": "外场简报",
        "description": "玩家推时段时，写一两句「别处此刻在发生什么」进大事记。只在模组里勾上「时段跳转时写外场简报」才会走这个模板，默认不调用；整个模板最要紧的是不许造新人新地名，否则传闻会污染所有对话线。",
        "variables": {"day": "第几天", "from_slot": "刚过去的时段名", "slot": "现在的时段名", "location": "玩家所在地点", "others": "玩家见过、此刻不在他身边的角色，每项含 name、place、persona、notes", "chronicle": "已经传开的事，最近几条"},
    },
    "rpg_activity.jinja2": {
        "label": "角色自由行动",
        "description": "给这一轮没被提到的角色各写一句「最近在做什么」。只在角色卡上勾了「AI 调度」才会走这个模板，默认不调用；写法上最要紧的是不许造新人新地名，也不许写会影响玩家的重大事件——这些句子会常驻在那个人的设定里。",
        "variables": {"day": "第几天", "slot": "当前时段名", "location": "玩家所在地点", "recent": "最近一段剧情，只用来看时间对不齐", "npcs": "这一轮没被提到、且开了 AI 调度的角色，每项含 name、place、persona、activity（上次记下的那句）"},
    },
    "rpg_assist.jinja2": {
        "label": "帮我写（模组编辑）",
        "description": "编辑模组时点「AI 生成 / AI 优化」用的。同一个模板兼管两件事：这一栏是空的就从零写，有内容就在原文上改。只影响编辑器里的按钮，不进游玩时的任何环节。",
        "variables": {"field_label": "正在写哪一栏", "field_guidance": "这一栏该写什么，由后端按栏位给出", "max_chars": "字数上限", "content": "这一栏当前的内容，空表示从零写", "is_generate": "true = 从零写，false = 在原文上改", "context_blocks": "模组里已经写好的其他部分，每项含 label、content"},
    },
    "rpg_wizard.jinja2": {
        "label": "构思向导（对话）",
        "description": "新建模组时那个「构思助手」的对话提示词。根据作者选择的世界规模，带作者一步步搭建完整世界或一块区域，再聊核心循环、数值、地点、角色、道具，最后聊任务和主线。只帮着攒设定，不进游玩时的任何环节。",
        "variables": {"nsfw": "是否开成人模式", "stage": "当前哪一步（world/loop/stats/places/slots/cast/things/quests），空表示还没进向导", "confirmed": "前面几步已经定下来的内容，空表示还没定", "play_style": "玩法类别（sim/rpg/slg），决定该往哪个方向聊", "world_scope": "世界规模（world=完整世界，region=单一区域故事）"},
    },
    "rpg_wizard_extract.jinja2": {
        "label": "构思向导（抽取）",
        "description": "把构思对话里聊定的结论抽成表单字段。按当前这一步只抽对应的那一摊。角色/道具/动作引用的数值名、地点名要和前面定过的对得上，对不上的会被后端丢掉。请保持 JSON 输出格式和字段名。",
        "variables": {"stage": "当前哪一步（world/loop/stats/places/slots/cast/things/quests）。loop 只产 GM 规则那一栏，quests 只产任务", "stat_names": "前面定过的玩家数值名，供道具/动作的 effects 校验", "relation_names": "前面定过的关系数值名，供角色 initial_state 和动作 relation_effects 校验", "location_names": "前面定过的地点名，供角色 location 和动作 at_location 校验", "slot_names": "前面定过的时段名，供角色作息表 slot_locations 校验；和地点名缺一个，作息表就整摊丢掉"},
    },
    "rpg_wizard_full.jinja2": {
        "label": "一句话生成整套模组",
        "description": "根据一句话想法和选择的世界规模一次生成模组编辑页已有的全部字段，技能、任务、角色作息和说话样例也一并出；完整世界会铺开大陆、区域、组织和多人物，区域故事则聚焦一个局部。返回草案供用户勾选回填。可在 RPG 提示词页面直接编辑。",
        "variables": {"instruction": "作者的一句话想法", "nsfw": "是否开启成人模式", "play_style": "玩法类别（sim/rpg/slg）", "world_scope": "世界规模（world=完整世界，region=单一区域故事）"},
    },
    "rpg_image_tags.jinja2": {
        "label": "中文转 Danbooru tag",
        "description": "出图设置里把提示词形态选成「英文 tag」时用的。把中文描述翻成 Danbooru tag，只在光辉（Illustrious）这类 SDXL 工作流上需要——它们只认英文 tag。每个 tag 都会拿本地词表核一遍，核不上的会带着候选词回来让模型重挑，所以第二段里的「不要再造新词」建议保留。",
        "variables": {"source": "要转换的中文描述", "nsfw": "是否开成人模式", "char_name": "同人角色名，非空时让模型转成 Danbooru 角色 tag；原创角色留空", "unknown": "上一轮没能在词表里查到的词，每项含 tag、candidates（词表里相近的词，可能为空）；第一轮是空的"},
    },
    "rpg_generate.jinja2": {
        "label": "一键生成（模组编辑）",
        "description": "在地点/角色/道具/动作那一摊点「AI 生成」时用的。按作者一句话的要求批量生成，引用的数值名、地点名要和模组里已有的对得上，对不上的会被后端丢掉。请保持 JSON 输出格式和字段名。",
        "variables": {"kind": "生成哪一摊（location/npc/item/action）", "instruction": "作者的要求，如「生成霍格沃兹的五个地点」", "count": "目标数量", "nsfw": "是否开成人模式", "play_style": "玩法类别（sim/rpg/slg）", "stat_names": "模组已有的玩家数值名，供道具/动作 effects 校验", "relation_names": "模组已有的关系数值名，供角色 initial_state 和动作 relation_effects 校验", "location_names": "模组已有的地点名，供角色 location 校验", "existing_names": "这一摊里模组已有的名字，提示模型别重复生成"},
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
        npcs=[{
            "id": 1, "name": "老兵", "notes": {"伤势": "左肩中刀"},
            # relations 只有「回合结算」用得上，place/persona/activity 只有
            # 「角色自由行动」用得上。多给的键对别的模板无害，
            # 而少给一个键 StrictUndefined 会当场炸
            "relations": {"好感": 42},
            "place": "铁匠铺", "persona": "话少", "activity": "在磨刀",
            # 已经改写过的外貌，同样只有「回合结算」用得上
            "appearance": {"左手": "齐腕断了，已结痂"},
        }], note_keys=["伤势"], step_caps={"好感": 3},
        chronicle=["后山挖出了尸首"],
        tasks=[{"name": "送信给老周", "goal": "把信交到老周手上"}],
        max_chars=400, is_generate=True,
        context_blocks=[{"label": "世界观", "content": "示例"}],
        day=3, from_slot="中", slot="晚", has_clock=True,
        others=[{"name": "赫敏", "place": "图书馆", "persona": "好胜", "notes": "左肩中刀"}],
        stat_names=["精力", "资金"], location_names=["酒馆", "后巷"],
        count=3, existing_names=["酒馆", "后巷"],
        char_name="日向雏田",
        # candidates 给一条空的：词表里查不到相近词是常态（见 danbooru_tags.search
        # 的说明），用户模板里那条分支得走到
        unknown=[{"tag": "internal_cutaway", "candidates": ["cross-section", "x-ray"]},
                 {"tag": "masterpiece", "candidates": []}],
    )
    template = _env.from_string(content)
    template.render(**values)
    values.update(
        reply_length=0, stats={}, ledger=[], inventory=[], flags={}, npcs=[],
        note_keys=[], relation_names=[], step_caps={},
        location="", recent="", summary="", previous_summary="", scope="", dice=0,
        # 一个模组都可能没登记过角色，roster 空的那条分支要走得到
        roster="",
        outcome_label="", outcome_failed=False, engine_note="", chronicle=[], tasks=[],
        is_generate=False, context_blocks=[],
        from_slot="", slot="", has_clock=False, others=[],
        stat_names=[], location_names=[],
        existing_names=[],
        char_name="", unknown=[],
    )
    template.render(**values)


def render(template_name: str, **kwargs) -> str:
    user = current_user_var.get()
    overrides = getattr(user, "rpg_prompts", None) or {}
    content = overrides.get(template_name)
    if template_name in PROMPTS and content is not None:
        return _env.from_string(content).render(**kwargs)
    return render_default(template_name, **kwargs)
