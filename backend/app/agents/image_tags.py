"""中文自然语言 → Danbooru tag。给光辉（Illustrious）这类 SDXL 系工作流用。

**为什么不能只调一次模型。** 让 LLM 直接吐 tag，它会编出看着很像样但词表里
根本不存在的词（实测：`internal_cutaway`、`masterpiece`、`illustration`），
那些词在 CLIP-L 眼里等于噪声——不报错，只是图里悄悄少画一样东西。
所以每个 tag 都要拿真词表核一遍，命不中的打回去重挑。

**第二趟为什么必须带上中文原文。** 词面匹配只在共享单词时有效：`crossection`
搜得到 `cross-section`，但 `internal_cutaway` 搜不到——词表里连 `cutaway`
这个词都没有，两者一个词都不重（这条已经写成 test_danbooru_tags 里的测试）。
纯语义的跳跃只能靠模型看着中文原意重挑，光给它一堆候选词是挑不出来的。

转换结果不落库、不直接出图：交回前端填进那个可编辑的 tag 框，用户过目。
「看得见能删」是这条链路的硬原则，见 routes/rpg.py 里出图那段注释。
"""

import logging

from app.services import danbooru_tags, llm_client, llm_json
from app.services.rpg_prompts import render

logger = logging.getLogger(__name__)

# 每个命不中的词给模型看几个候选。给多了会把提示词冲淡，也容易诱导它硬凑一个
# 沾边的；给少了真词可能不在里面
_CANDIDATES = 8

# 第二趟只跑一次。再多轮的收益很低——两趟之后还命不中的，基本都是「词表里
# 真没有这个概念」，第三趟只会让模型开始硬凑，而它凑出来的东西比缺一项更糟
_MAX_ROUNDS = 2


def _parse(data: dict) -> list[str]:
    """从模型返回的 JSON 里取 tags。

    容忍两种形状：`{"tags": [...]}`（模板要求的）和直接一个数组——
    模型偶尔会漏掉外层键，为这个整轮重试不值得。
    """
    tags = data.get("tags") if isinstance(data, dict) else data
    if not isinstance(tags, list):
        return []
    # 模型有时把一整串塞进一个元素里：["1girl, long_hair"]。逗号切开，
    # 下游 normalize 会处理剩下的空格和大小写
    out: list[str] = []
    for item in tags:
        if isinstance(item, str):
            out.extend(part for part in item.split(",") if part.strip())
    return out


async def convert(
    source: str,
    model_ref: str = "",
    *,
    nsfw: bool = False,
    char_name: str = "",
) -> tuple[list[str], list[str]]:
    """中文描述转成校验过的 tag 列表，返回 (命中的规范名, 最终仍命不中的原样词)。

    命不中的**不偷偷扔掉**：交回上层显示给用户。少画一样东西而不告诉他，
    比明说「这几个词没转成功」糟得多。

    char_name 非空时，让模型把这个角色名转成 Danbooru 角色 tag（做同人游戏时
    「日向雏田」要转成 `hyuuga_hinata` 当角色 tag）。默认空 = 不带角色名：
    原创角色、或不想让底模往已知角色脸上靠时就别传。

    用 fast_model 而不是叙事模型：这是查表式的翻译活，不是创作。
    """
    source = (source or "").strip()
    if not source:
        return [], []

    char_name = (char_name or "").strip()
    model, api_format = llm_client.get_agent_client("character", model_ref)
    unknown_ctx: list[dict] = []
    hits: list[str] = []
    unknown: list[str] = []

    for round_no in range(_MAX_ROUNDS):
        prompt = render("rpg_image_tags.jinja2", source=source, nsfw=nsfw,
                        char_name=char_name, unknown=unknown_ctx)
        data, _in_tok, _out_tok = await llm_json.call_json(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            api_format=api_format,
            max_tokens=1200,
        )
        hits, unknown = danbooru_tags.check(_parse(data))
        if not unknown:
            break
        logger.info("tag 转换第 %d 轮：%d 命中，%d 未命中 %s",
                    round_no + 1, len(hits), len(unknown), unknown[:5])
        unknown_ctx = [
            {"tag": tag, "candidates": danbooru_tags.search(tag, _CANDIDATES)}
            for tag in unknown
        ]

    return hits, unknown
