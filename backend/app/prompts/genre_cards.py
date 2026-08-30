"""题材腔调卡：按 novel.genre 召回一张卡，注入写作上下文。

genre 是自由文本（实际值多为"色情玄幻""都市色情"这类组合词），
所以用子串包含匹配；匹配不上就不注入。

novel.genre_card 可以覆盖自动匹配的结果：空串=按 genre 自动匹配，
OFF=本书不用题材卡，其他=指定卡名。
"""
from pathlib import Path

_CARD_DIR = Path(__file__).parent / "genre_cards"

# novel.genre_card 存这个值表示"这本书不用题材卡"。
# 与 context_config 的 genre_card 开关不同：那个是临时调上下文，这个是作品设定。
OFF = "none"

# 长名优先，避免"都市修真"先撞上"都市"
_MATCH_ORDER = [
    "古代权谋", "玄幻", "仙侠", "都市", "言情", "悬疑", "历史", "科幻",
    "武侠", "奇幻", "末世", "游戏", "军事",
]

# 市场上的常见叫法 → 卡名。genre 是自由文本，"灵气复苏""赘婿"这类说法
# 子串匹配抓不到，靠别名兜住。别名同样长名优先。
_ALIASES: dict[str, str] = {
    "灵气复苏": "都市", "都市高武": "都市", "现代修真": "都市", "赘婿": "都市",
    "战神": "都市", "神豪": "都市", "职场": "都市", "校园": "都市",
    "高武": "玄幻", "洪荒": "玄幻", "东方玄幻": "玄幻", "异世大陆": "玄幻",
    "修真": "仙侠", "修仙": "仙侠", "凡人流": "仙侠", "道门": "仙侠",
    "西方奇幻": "奇幻", "剑与魔法": "奇幻", "魔法": "奇幻", "克苏鲁": "奇幻",
    "星际": "科幻", "赛博朋克": "科幻", "机甲": "科幻", "未来": "科幻",
    "丧尸": "末世", "废土": "末世", "灾变": "末世", "无限流": "末世",
    "网游": "游戏", "电竞": "游戏", "系统流": "游戏", "副本": "游戏",
    "宫斗": "古代权谋", "朝堂": "古代权谋", "宅斗": "古代权谋", "种田": "古代权谋",
    "谍战": "军事", "抗战": "军事", "特种兵": "军事",
    "推理": "悬疑", "灵异": "悬疑", "盗墓": "悬疑", "诡秘": "悬疑",
    "江湖": "武侠", "武林": "武侠", "国术": "武侠",
    "言情甜宠": "言情", "甜宠": "言情", "总裁": "言情", "romance": "言情",
    "穿越": "历史", "架空历史": "历史", "三国": "历史",
}
# 长名优先，"都市高武"要先于"高武"命中
_ALIAS_ORDER = sorted(_ALIASES, key=len, reverse=True)

_INJECT_HEADER = (
    "=== 题材腔调参考 ===\n"
    "以下是本书题材的写法参考，用于校准场景选择、对话声线和爽点落法。"
    "只在你构思时使用，正文里不得出现“题材卡”“腔调”“禁止漂移”等字样，"
    "也不要写“已按题材要求”这类自评说明——只输出故事本身。\n"
    "与其他资料冲突时的优先级（从高到低）："
    "本章大纲与前后文连贯 > 用户本章指令 > 本书文风与规则 > 本卡的写法建议。\n"
)


def match_card_name(genre: str) -> str | None:
    """按子串包含匹配卡名，先试正式卡名再试别名，都不中返回 None。"""
    g = (genre or "").strip()
    if not g:
        return None
    for name in _MATCH_ORDER:
        if name in g:
            return name
    for alias in _ALIAS_ORDER:
        if alias in g:
            return _ALIASES[alias]
    return None


def list_aliases() -> dict[str, list[str]]:
    """卡名 → 别名列表，供前端展示"这张卡还能被哪些说法命中"。"""
    result: dict[str, list[str]] = {n: [] for n in _MATCH_ORDER}
    for alias in _ALIAS_ORDER:
        result.setdefault(_ALIASES[alias], []).append(alias)
    return result


def read_card(name: str) -> str:
    """读卡正文（不含注入头），文件缺失或为空时返回空串。"""
    if not name or name == OFF or name not in _MATCH_ORDER:
        return ""
    try:
        return (_CARD_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def list_cards() -> list[dict]:
    """列出实际存在正文的卡，供前端选择与预览。"""
    aliases = list_aliases()
    return [
        {"name": n, "body": body, "aliases": aliases.get(n, [])}
        for n in _MATCH_ORDER
        if (body := read_card(n))
    ]


def resolve_card_name(genre: str, override: str = "") -> str | None:
    """定出最终用哪张卡：OFF 返回 None，指定卡名优先，否则按 genre 自动匹配。

    指定的卡名如果已经不存在（卡被删或改名），回落到自动匹配而不是静默无卡。
    """
    ov = (override or "").strip()
    if ov == OFF:
        return None
    if ov and read_card(ov):
        return ov
    return match_card_name(genre)


def load_card(genre: str, override: str = "") -> str:
    """返回可直接注入的题材卡文本；不用卡、无匹配或文件缺失时返回空串。"""
    name = resolve_card_name(genre, override)
    body = read_card(name or "")
    if not body:
        return ""
    return f"{_INJECT_HEADER}\n{body}"
