"""文风库的模型侧：按用户选的类别在全书粗筛、让模型摘原句，再提文风/角色/中性化映射，
最后按模式转成 few-shot。

模型在摘句这一步只负责「挑」：摘录必须逐字出自候选块，改过字的当编造丢掉，库里只存原文。

原文专名在 analyze 阶段就换成中性名，后面所有模式都不必再操心专名；
模型漏报、乱报的地方一律由代码补齐——落库形状是硬约束，不交给模型自觉。

每段的「玩家输入」也在导入时反推好随段落落库（scenes[].input）：游戏叙事示例
要的是「玩家说了什么 → 正文怎么接」，取用时直接拼，不再调模型。
"""
import asyncio

from app.prompts.loader import render
from app.services import llm_client, llm_json
from app.services.style_extract import (
    DIALOGUE,
    PRESET_CATEGORIES,
    PRESET_KEYWORDS,
    apply_replacements,
    dialogue_score,
    find_in,
    keyword_score,
    pick_candidates,
)

_INSTRUCTION_TOKENS = 2000
_DIALOGUE_TOKENS = 2000
_KEYWORD_TOKENS = 2000
_LOCATE_TOKENS = 4000
_EXCERPTS_PER_CATEGORY = 5
# 太短的看不出写法
_EXCERPT_MIN = 20
# 反推玩家输入：一批十段，一段一句话；批小点，一批崩了牵连的段落少
_PROMPT_BATCH = 10
_PROMPT_TOKENS = 3000


def _messages(rendered: str) -> list[dict]:
    return [
        {"role": "system", "content": "你只输出可解析的 JSON。"},
        {"role": "user", "content": rendered},
    ]


async def _call_json(rendered: str, model: str, api_format: str, max_tokens: int) -> dict | None:
    """单段调用；返回 None 表示这段没救，跳过还是报错由调用方决定。"""
    try:
        parsed, _, _ = await llm_json.call_json(
            _messages(rendered), model, api_format, max_tokens=max_tokens, expect="object"
        )
    except llm_json.JsonCallError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _gather_or_fail(tasks: list) -> list:
    """并发转换；单段失败跳过，全失败才报错——一段崩不该拖垮整次取用。"""
    results = await asyncio.gather(*tasks)
    ok = [r for r in results if r is not None]
    if not ok:
        raise ValueError("转换失败，请重试或换快速模型")
    return ok


async def _fill_inputs(
    scenes: list[dict], protagonist: str, mapping: dict[str, str], model: str, api_format: str
) -> None:
    """分批反推每段的玩家输入，原地写进 scenes[i]["input"]。

    刻意不走 _gather_or_fail：一批崩了只是那几段没有输入，书照样要能导进来。
    段号只认本批的，模型抄错编号不许写到别的段上。
    """
    async def one(start: int, part: list[dict]) -> None:
        rendered = render(
            "style_to_prompt.jinja2",
            protagonist=protagonist,
            items=[{"index": start + k, "text": s["text"]} for k, s in enumerate(part)],
        )
        parsed = await _call_json(rendered, model, api_format, _PROMPT_TOKENS)
        items = (parsed or {}).get("items")
        for raw in items if isinstance(items, list) else []:
            if not isinstance(raw, dict):
                continue
            index = raw.get("index")
            if isinstance(index, int) and start <= index < start + len(part):
                scenes[index]["input"] = apply_replacements(
                    str(raw.get("input") or "").strip(), mapping
                )

    # return_exceptions：_call_json 只吞解析失败，断网之类也不该把已经分析完的整本书作废
    await asyncio.gather(*(
        one(start, scenes[start:start + _PROMPT_BATCH])
        for start in range(0, len(scenes), _PROMPT_BATCH)
    ), return_exceptions=True)


async def _category_keywords(custom: list[str], model: str, api_format: str) -> dict[str, list[str]]:
    """自定义类别没有写死的词表，先让模型想一批特征词，所有自定义类别合一次调用。"""
    if not custom:
        return {}
    parsed = await _call_json(
        render("style_keywords.jinja2", categories=custom), model, api_format, _KEYWORD_TOKENS
    )
    raw = (parsed or {}).get("keywords")
    out: dict[str, list[str]] = {}
    for category in custom:
        # 类别名本身也算一个词：这次调用崩了也还能筛出点东西
        words = [category]
        values = raw.get(category) if isinstance(raw, dict) else None
        for word in values if isinstance(values, list) else []:
            word = str(word).strip()
            if word and word not in words:
                words.append(word)
        out[category] = words
    return out


async def _locate(category: str, candidates: list[str], model: str, api_format: str) -> list[dict]:
    if not candidates:
        return []
    rendered = render(
        "style_locate.jinja2",
        category=category,
        limit=_EXCERPTS_PER_CATEGORY,
        chunks=[{"index": i, "text": text} for i, text in enumerate(candidates)],
    )
    parsed = await _call_json(rendered, model, api_format, _LOCATE_TOKENS)
    items = (parsed or {}).get("items")

    out: list[dict] = []
    seen: set[str] = set()
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            continue
        excerpt = str(raw.get("excerpt") or "").strip()
        key = "".join(excerpt.split())
        # 模型编的、改过字的一律丢，库里只存原文
        if len(excerpt) < _EXCERPT_MIN or key in seen or not find_in(excerpt, candidates):
            continue
        seen.add(key)
        out.append({
            "category": category,
            "text": excerpt,
            "summary": str(raw.get("summary") or "").strip(),
        })
        if len(out) >= _EXCERPTS_PER_CATEGORY:
            break
    return out


async def analyze(
    sample: list[str],
    pool: list[tuple[int, str]],
    categories: list[str],
    stats: dict,
    model_ref: str = "",
) -> dict:
    """sample：随机抽样块，只用来写文风说明、认人名；pool：全书的块，按类别从里面摘录。"""
    # model_ref 为空 = 用户的默认快速模型；非空时归属校验在 resolve_model_ref 里做
    model, api_format = llm_client.get_agent_client("memory", model_ref)

    custom = [c for c in categories if c not in PRESET_CATEGORIES]
    custom_kw = await _category_keywords(custom, model, api_format)

    candidates: list[list[str]] = []
    for category in categories:
        if category == DIALOGUE:
            score = dialogue_score
        else:
            words = PRESET_KEYWORDS.get(category) or custom_kw.get(category, [])
            score = lambda text, words=words: keyword_score(text, words)
        candidates.append(pick_candidates(pool, score))

    # 每类一次调用，并发；按类别顺序拼回来，摘录编号才稳定
    groups = await asyncio.gather(*(
        _locate(category, cands, model, api_format)
        for category, cands in zip(categories, candidates)
    ))
    excerpts = [e for group in groups for e in group]
    if not excerpts:
        raise ValueError("书里没找到所选的内容，换几个类别试试")

    rendered = render(
        "style_analyze.jinja2",
        chunks=[{"index": i, "text": text} for i, text in enumerate(sample)],
        excerpts=[{"index": i, "text": e["text"]} for i, e in enumerate(excerpts)],
        stats=stats,
    )
    parsed, _, _ = await llm_json.call_json(
        # 输出是文风说明+角色表+每条摘录的说话人，比以前每段一句概括少；上限先不动
        _messages(rendered), model, api_format, max_tokens=8000, expect="object"
    )

    # 映射 = replacements + 角色名/别名 → neutral。角色名以角色表为准覆盖一遍，
    # 不指望模型在 replacements 里也记得收
    mapping: dict[str, str] = {}
    replacements = parsed.get("replacements")
    if isinstance(replacements, dict):
        for src, dst in replacements.items():
            src, dst = str(src).strip(), str(dst).strip()
            if src and dst:
                mapping[src] = dst

    characters: list[dict] = []
    raw_characters = parsed.get("characters")
    for raw in raw_characters if isinstance(raw_characters, list) else []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        neutral = str(raw.get("neutral") or "").strip()
        if neutral:
            mapping[name] = neutral
            aliases = raw.get("aliases")
            for alias in aliases if isinstance(aliases, list) else []:
                alias = str(alias).strip()
                if alias:
                    mapping[alias] = neutral
        characters.append({"name": neutral or name, "role": str(raw.get("role") or "").strip()})

    # 段落以摘录为准，一条不少；模型只贡献说话人，编号越界、重复的忽略
    speakers_of: dict[int, list[str]] = {}
    raw_scenes = parsed.get("scenes")
    for raw in raw_scenes if isinstance(raw_scenes, list) else []:
        if not isinstance(raw, dict):
            continue
        index = raw.get("index")
        if not isinstance(index, int) or not (0 <= index < len(excerpts)) or index in speakers_of:
            continue
        speakers: list[str] = []
        raw_speakers = raw.get("speakers")
        for speaker in raw_speakers if isinstance(raw_speakers, list) else []:
            mapped = mapping.get(str(speaker).strip(), str(speaker).strip())
            if mapped and mapped not in speakers:
                speakers.append(mapped)
        speakers_of[index] = speakers

    # 场景类型就是提取时的类别，不再让模型判
    scenes = [
        {
            "summary": apply_replacements(e["summary"], mapping),
            "scene_type": e["category"],
            "text": apply_replacements(e["text"], mapping),
            "speakers": speakers_of.get(i, []),
            "input": "",
        }
        for i, e in enumerate(excerpts)
    ]

    # 喂进去的是中性化之后的正文，主角也用中性名，反推出来的输入直接能用
    protagonist = next((c["name"] for c in characters if c["role"] == "主角"), "")
    await _fill_inputs(scenes, protagonist, mapping, model, api_format)

    return {
        "style_desc": apply_replacements(str(parsed.get("style_desc") or ""), mapping),
        "characters": characters,
        "scenes": scenes,
    }


def _novel_user(length: int, instruction: str) -> str:
    # 写手收到的最后一条 user 就是「写作任务 + 写作方向」两块，示例长得不一样
    # 模型就学不到映射；标字数是为了不让短示例把整章写短
    return (
        f"=== 写作任务 ===\n写一个约{length}字的片段，直接输出正文，不要标题或任何前缀。\n\n"
        f"=== 写作方向（严格遵守，与其他要求冲突时以本节为准）===\n{instruction}"
    )


async def _novel_example(style_desc: str, text: str, model: str, api_format: str) -> dict | None:
    rendered = render(
        "style_to_instruction.jinja2", style_desc=style_desc, text=text, length=len(text)
    )
    parsed = await _call_json(rendered, model, api_format, _INSTRUCTION_TOKENS)
    if parsed is None:
        return None
    instruction = str(parsed.get("instruction") or "").strip()
    if not instruction:
        return None
    return {"user": _novel_user(len(text), instruction), "assistant": text}


async def _ready(value):
    return value


async def _dialogue_pairs(
    text: str, character: str, model: str, api_format: str
) -> list[dict] | None:
    rendered = render("style_to_dialogue.jinja2", text=text, character=character)
    parsed = await _call_json(rendered, model, api_format, _DIALOGUE_TOKENS)
    if parsed is None:
        return None
    out: list[dict] = []
    pairs = parsed.get("pairs")
    for pair in pairs if isinstance(pairs, list) else []:
        if not isinstance(pair, dict):
            continue
        user = str(pair.get("user") or "").strip()
        assistant = str(pair.get("assistant") or "").strip()
        if not user or not assistant:
            continue
        out.append({"user": user, "assistant": assistant})
    return out


def _rename(examples: list[dict], name_map: dict[str, str] | None) -> list[dict]:
    """套用户手填的名字对照。只换一个人的话，示例里其他人还是导入时起的中性名，
    和用户那边的角色对不上；所以一张表、所有模式、两侧一起换。"""
    mapping = {
        str(k).strip(): str(v).strip()
        for k, v in (name_map or {}).items()
        if str(k).strip() and str(v).strip()
    }
    if not mapping:
        return examples
    return [
        {"user": apply_replacements(ex["user"], mapping),
         "assistant": apply_replacements(ex["assistant"], mapping)}
        for ex in examples
    ]


async def adapt(
    profile,
    mode: str,
    scene_indexes: list[int],
    character: str = "",
    name_map: dict[str, str] | None = None,
    model_ref: str = "",
) -> dict:
    scenes = list(profile.scenes or [])
    picked: list[dict] = []
    seen: set[int] = set()
    for index in scene_indexes:
        if not (0 <= index < len(scenes)) or index in seen:
            continue
        seen.add(index)
        text = str(scenes[index].get("text") or "")
        if text.strip():
            picked.append({
                "text": text,
                "input": str(scenes[index].get("input") or "").strip(),
                "speakers": scenes[index].get("speakers") or [],
            })
    if not picked:
        raise ValueError("没有可用的段落")

    if mode == "novel":
        # 导入时已反推出输入的段直接拼；只有旧数据才现问模型——都有输入时不碰模型配置
        model = api_format = ""
        if any(not item["input"] for item in picked):
            model, api_format = llm_client.get_agent_client("memory", model_ref)
        examples = await _gather_or_fail([
            _ready({"user": _novel_user(len(item["text"]), item["input"]), "assistant": item["text"]})
            if item["input"]
            else _novel_example(profile.style_desc or "", item["text"], model, api_format)
            for item in picked
        ])
        return {"examples": _rename(examples, name_map)}

    if mode in ("tavern", "rpg_npc"):
        character = character.strip()
        if not character:
            raise ValueError("请先选一个角色")
        matched = [item for item in picked if character in item["speakers"]]
        if not matched:
            raise ValueError(f"选中的段落里没有「{character}」说话")
        model, api_format = llm_client.get_agent_client("memory", model_ref)
        groups = await _gather_or_fail([
            _dialogue_pairs(item["text"], character, model, api_format)
            for item in matched
        ])
        return {"examples": _rename([pair for group in groups for pair in group], name_map)}

    if mode == "rpg_narration":
        # 玩家输入 → 原文正文，不调模型；名字跟着这一局走，否则模型会照抄示例里的名字
        examples = [
            {"user": item["input"], "assistant": item["text"]}
            for item in picked
            if item["input"]
        ]
        if not examples:
            raise ValueError("这些段落没有生成示例，请重新导入这本书")
        return {"examples": _rename(examples, name_map)}

    raise ValueError(f"未知模式：{mode}")
