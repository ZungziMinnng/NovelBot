"""文风库的模型侧：按用户选的类别在全书粗筛、让模型摘原句，再提文风/角色/中性化映射，
最后按模式转成 few-shot。

模型在摘句这一步只负责「挑」：摘录必须逐字出自候选块，改过字的当编造丢掉，库里只存原文。

原文专名在 analyze 阶段就换成中性名，后面所有模式都不必再操心专名；
模型漏报、乱报的地方一律由代码补齐——落库形状是硬约束，不交给模型自觉。

每段的「玩家输入」也在导入时反推好随段落落库（scenes[].input）：游戏叙事示例
要的是「玩家说了什么 → 正文怎么接」，取用时直接拼，不再调模型。

整场景直接切连续原文；粗筛后过本地重排；另有试写对比。
"""
import asyncio

from app.prompts.loader import render
from app.services import llm_client, llm_json, reranker
from app.services.style_extract import (
    DIALOGUE,
    GENERIC_TITLES,
    PRESET_CATEGORIES,
    PRESET_KEYWORDS,
    RERANK_QUERIES,
    WHOLE_SCENE,
    apply_replacements,
    compare_stats,
    compute_stats,
    dialogue_score,
    find_in,
    keyword_score,
    pick_candidates,
    whole_scenes,
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
# 词表粗筛先放宽到三倍，再让重排模型按类别描述精读挑 12 块——「一剑穿心」和「剑鞘挂在墙上」词表分不开
_PREFILTER = 36
_CANDIDATES = 12
# 试写：一次一段，字数够算统计就行
_TRIAL_LENGTH = 600
_TRIAL_TOKENS = 4000
_TRIAL_SAMPLES = 2

# 文风卡的栏目，顺序即展示顺序；模板里的 JSON 键要和这里一致
STYLE_CARD_FIELDS = (
    "叙述视角", "句子节奏", "分段习惯", "对话写法", "描写配比",
    "用词质感", "情绪表达", "场景转换与收尾", "这本书不做的事",
)


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


async def _shortlist(category: str, pool: list[tuple[int, str]], score) -> list[str]:
    cands = pick_candidates(pool, score, limit=_PREFILTER)
    if len(cands) <= 1:
        return cands
    # 重排模型没装/没 GPU 时原样返回，等于退回纯词表
    query = RERANK_QUERIES.get(category, category)
    ranked, _ = await asyncio.to_thread(
        reranker.rerank_hits, query, [{"text": t} for t in cands], len(cands)
    )
    return [h["text"] for h in ranked][:_CANDIDATES]


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
    chapters: list[str] | None = None,
) -> dict:
    """sample：随机抽样块，只用来写文风说明、认人名；pool：全书的块，按类别从里面摘录；
    chapters：整章原文，只有「整场景」用。"""
    # model_ref 为空 = 用户的默认快速模型；非空时归属校验在 resolve_model_ref 里做
    model, api_format = llm_client.get_agent_client("memory", model_ref)

    custom = [c for c in categories if c not in PRESET_CATEGORIES]
    custom_kw = await _category_keywords(custom, model, api_format)

    async def group(category: str) -> list[dict]:
        if category == WHOLE_SCENE:
            return [{"category": WHOLE_SCENE, "text": t, "summary": ""} for t in whole_scenes(chapters or [])]
        if category == DIALOGUE:
            score = dialogue_score
        else:
            words = PRESET_KEYWORDS.get(category) or custom_kw.get(category, [])
            score = lambda text, words=words: keyword_score(text, words)
        return await _locate(category, await _shortlist(category, pool, score), model, api_format)

    # 每类一次调用，并发；按类别顺序拼回来，摘录编号才稳定
    groups = await asyncio.gather(*(group(c) for c in categories))
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
    raws = [r for r in (raw_characters if isinstance(raw_characters, list) else []) if isinstance(r, dict)]

    def _aliases(raw: dict) -> list[str]:
        aliases = raw.get("aliases")
        return [str(a).strip() for a in (aliases if isinstance(aliases, list) else [])]

    claims: dict[str, int] = {}
    for raw in raws:
        for alias in set(_aliases(raw)):
            claims[alias] = claims.get(alias, 0) + 1

    for raw in raws:
        name = str(raw.get("name") or "").strip()
        # 称谓不是名字：「妻子」当人名换掉，正文就成了「林晓是个贤惠的林晓」
        if not name or name in GENERIC_TITLES:
            continue
        neutral = str(raw.get("neutral") or "").strip()
        if neutral:
            mapping[name] = neutral
            for alias in _aliases(raw):
                # 单字、称谓不换；两个人都报的别名（「师兄」「老大」）也不换，换给谁都错一半
                if len(alias) >= 2 and alias not in GENERIC_TITLES and alias != name and claims.get(alias, 0) == 1:
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

    # 高频词组是在原文上算的，前几名常是人名地名（「裴仙子」「镇岳宫」），既漏专名又不是文风。
    # 原地改：路由把同一个 stats 存进库
    phrases = stats.get("top_phrases")
    if isinstance(phrases, list):
        names = [k for k in mapping if len(k) >= 2]
        stats["top_phrases"] = [p for p in phrases if not any(k in p or p in k for k in names)]

    # 文风卡分栏输出，存成「【栏】内容」一行一栏，下游照旧当一段文字用；老模板/模型没给卡就退回 style_desc
    card = parsed.get("style_card")
    lines = []
    if isinstance(card, dict):
        lines = [f"【{k}】{str(card[k]).strip()}" for k in STYLE_CARD_FIELDS if str(card.get(k) or "").strip()]
    style_desc = "\n".join(lines) or str(parsed.get("style_desc") or "")

    return {
        "style_desc": apply_replacements(style_desc, mapping),
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
        # 导入时反推的是游戏的「玩家输入」（只写主角动作），和写手收到的「剧情节拍」不同构，
        # 拿来当写作方向模型学不到映射；小说一律现反推节拍
        model, api_format = llm_client.get_agent_client("memory", model_ref)
        examples = await _gather_or_fail([
            _novel_example(profile.style_desc or "", item["text"], model, api_format)
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


async def trial(profile, scene_indexes: list[int], model_ref: str = "") -> dict:
    """按文风说明+几段原文试写一段新内容，再用代码比统计——差在哪由数字说，不让模型自评。"""
    scenes = list(profile.scenes or [])
    texts = [
        str(scenes[i].get("text") or "") for i in dict.fromkeys(scene_indexes)
        if 0 <= i < len(scenes) and str(scenes[i].get("text") or "").strip()
    ]
    if not texts:
        # 没选就挑最长的：几十字的摘句看不出节奏，整场景最合适
        texts = sorted(
            (str(s.get("text") or "") for s in scenes if str(s.get("text") or "").strip()),
            key=len, reverse=True,
        )
    samples = texts[:_TRIAL_SAMPLES]
    style_desc = (profile.style_desc or "").strip()
    if not style_desc and not samples:
        raise ValueError("这个文风没有说明也没有段落，没法试写")

    model, api_format = llm_client.get_agent_client("memory", model_ref)
    rendered = render(
        "style_trial.jinja2", style_desc=style_desc, samples=samples, length=_TRIAL_LENGTH,
        person=str((profile.stats or {}).get("person") or ""),
    )
    text = (await llm_client.dispatch_chat_complete(
        [{"role": "user", "content": rendered}], model, api_format,
        temperature=0.8, max_tokens=_TRIAL_TOKENS,
    ) or "").strip()
    if not text:
        raise ValueError("试写没有返回内容，请重试或换模型")

    source_stats = dict(profile.stats or {})
    trial_stats = compute_stats([text])
    return {
        "text": text,
        "source_stats": source_stats,
        "trial_stats": trial_stats,
        "gaps": compare_stats(source_stats, trial_stats),
    }
