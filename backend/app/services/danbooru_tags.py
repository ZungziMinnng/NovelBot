"""Danbooru tag 词表：把 LLM 吐出来的 tag 校准成模型真认识的那个写法。

**为什么需要这一层。** 光辉（Illustrious）走 SDXL 那套 CLIP-L，只认 Danbooru
体系的英文 tag。让 LLM 直接吐 tag 它很乐意编——编出来的词看着像模样，实际
词表里根本没有，在模型眼里就是噪声。实测过的例子：

  - `internal_cutaway`（想表达剖面图）→ 不存在，真词是 `cross-section`
  - `onomatopoeia`（想表达拟声词）→ 不存在，真词是 `sound_effects` / `emphasis_lines`
  - `masterpiece` / `best_quality` → 都不存在，是 NAI leak 时代的 SD1.5 遗留

所以每个 tag 都要拿真实词表核一遍。命不中的**不偷偷扔掉也不硬猜**，收进
unknown 交回上层：报给用户看比悄悄少画一样东西好。

词表文件由 `scripts/fetch_danbooru_tags.py` 生成，26k 条，已提交进仓库。
"""

import csv
import logging
from functools import lru_cache
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_CSV_NAME = "danbooru_tags.csv"


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, str], dict[str, int]]:
    """(查找表, 热度表)。查找表把规范名和别名都指向规范名。

    懒加载 + 缓存：26k 行的 CSV 解析不算贵，但出图是逐个 NPC 点的，
    每次重读没必要。进程内只读一次。

    文件缺失不抛错，返回空表——转换会退化成「全都命不中」，上层照常把
    unknown 报给用户。比起启动直接崩，这样至少别的功能还能用。
    """
    path = Path(settings.data_dir) / _CSV_NAME
    if not path.exists():
        logger.warning("词表 %s 不存在，tag 校验会全部命不中。跑 scripts/fetch_danbooru_tags.py 生成", path)
        return {}, {}

    lookup: dict[str, str] = {}
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) < 3 or not row[2].isdigit():
                continue
            name, count = row[0], int(row[2])
            counts[name] = count
            lookup[name] = name
            for alias in (row[3] if len(row) > 3 else "").split(","):
                alias = alias.strip()
                # 别名冲突时**热度高的赢**：同一个别名偶尔挂在两个 tag 上，
                # 挑用得多的那个，猜错的代价小
                if alias and counts.get(lookup.get(alias, ""), -1) < count:
                    lookup[alias] = name
    logger.info("词表已载入：%d 条规范名，%d 条可查写法", len(counts), len(lookup))
    return lookup, counts


def normalize(tag: str) -> str:
    """把一个 tag 归一成词表里的写法：小写、空格换下划线、去掉权重括号。

    LLM 什么形态都可能吐：`Long Hair`、`long hair`、`(long_hair:1.2)`。
    词表里统一是 `long_hair`。**不动连字符**——`cross-section`、`x-ray` 的
    横杠是规范名的一部分，换成下划线就查不到了。
    """
    tag = tag.strip()
    # 只脱**整体被一对括号包住**的那层（权重语法 `(long_hair:1.2)` 的外壳）。
    # 不能无脑 strip 两端括号字符：角色 tag 大量是 `tsunade_(naruto)` 这种
    # 名字带 `_(作品名)` 后缀的，`strip("()")` 会把结尾那个 `)` 剥掉、
    # 剩下 `tsunade_(naruto` 括号不配对，永远查不到
    while len(tag) >= 2 and tag[0] == "(" and tag[-1] == ")":
        tag = tag[1:-1].strip()
    # 权重语法 `tag:1.2`，只切最后一个冒号后面是数字的情况：tag 本身也可能带
    # 冒号（`re:zero` 这类作品名）
    if ":" in tag:
        head, _, tail = tag.rpartition(":")
        if head and tail.replace(".", "", 1).isdigit():
            tag = head
    return tag.strip().lower().replace(" ", "_")


def resolve(tag: str) -> str | None:
    """一个 tag 的规范名，命不中返回 None。别名会被换成规范名（`womb` → `uterus`）。"""
    return _table()[0].get(normalize(tag))


def post_count(tag: str) -> int:
    """这个 tag 在 Danbooru 上多少张图用过，命不中是 0。用来给候选排序。"""
    lookup, counts = _table()
    return counts.get(lookup.get(normalize(tag), ""), 0)


def check(tags: list[str]) -> tuple[list[str], list[str]]:
    """批量校验，返回 (命中的规范名, 命不中的原样词)。

    命中的**按输入顺序**保留，不按热度重排：tag 顺序在 SDXL 里影响权重，
    前面的更重。LLM 把主体放前面、背景放后面是有意的，重排会打乱这个意图。

    去重也按顺序留第一个。别名和规范名同时出现（`womb` 和 `uterus`）时合成
    一条，不然同一个概念在提示词里出现两次，等于悄悄加权。
    """
    hits: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        if not raw.strip():
            continue
        canon = resolve(raw)
        if canon is None:
            unknown.append(raw.strip())
        elif canon not in seen:
            seen.add(canon)
            hits.append(canon)
    return hits, unknown


def search(word: str, limit: int = 12) -> list[str]:
    """按词重叠找候选，热度高的在前。给「这个词命不中，那你从这些里挑」用。

    纯字符串匹配，不做向量检索：这个项目的嵌入端点在用户网络下不稳
    （见 docs 里那条约束），为一个辅助功能加一条网络依赖不值。
    覆盖不到的情况本来就是「词表里真没这个概念」，如实说没有比瞎猜好。

    匹配的是**下划线切出来的词**而不是子串：子串匹配会让 `ear` 命中
    `earring` / `beard` / `search` 一大片，噪声压过信号。

    **别名一起进匹配池**，命中后折回规范名：`crossection` 是 `cross-section`
    的别名，只扫规范名的话这个写法一个候选都搜不出来。

    能力边界（实测）：只有**共享单词**时才搜得到。`internal_cutaway` 找不到
    `cross-section`——词表里根本没有 `cutaway` 这个词，两者一个词都不重。
    这种纯语义的跳跃靠词面匹配到不了，得让上层拿中文原文再问一次模型。
    """
    lookup, counts = _table()
    if not lookup:
        return []
    needle = normalize(word)
    if not needle:
        return []
    parts = {p for p in needle.split("_") if p}

    # 同一个规范名可能从多条别名命中，取最高的那次重叠数
    best: dict[str, int] = {}
    for form, canon in lookup.items():
        overlap = len(parts & {p for p in form.replace("-", "_").split("_") if p})
        if overlap > best.get(canon, 0):
            best[canon] = overlap
    # 先按重叠词数，再按热度。重叠数相同时，用得多的更可能是用户想要的那个
    scored = sorted(
        ((n, counts.get(c, 0), c) for c, n in best.items() if n),
        reverse=True,
    )
    return [c for _, _, c in scored[:limit]]
