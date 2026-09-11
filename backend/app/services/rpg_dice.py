"""RPG 判定的成功率换算。纯函数，无 IO，不碰 LLM。

判定在这个模式里是**可选调味**，默认关着（module.check_mode 默认 never）。
推动游戏的是数值在动、跨过某条线解锁新内容，那部分在 services/rpg_state.py。
都市、养成这类题材根本不需要判定；冒险题材想要就自己打开。

用成功率而不是 d20 对抗 DC，因为玩家看得懂「说服 63%」，看不懂「D20+2 对抗 16」，
也不必先学会加值公式。

开了判定之后，成败仍必须由这里算。让写旁白的模型自己判等于没有判定——
它会按剧情需要给结果，玩家想成功它就让玩家成功。
"""
import random

# 模型唯一能选的东西。不在这五个里一律回落 DEFAULT_BAND
BANDS = ("trivial", "easy", "medium", "hard", "extreme")
DEFAULT_BAND = "medium"

# 档位→基础成功率（%）。模组作者可以整张改
DEFAULT_RATE_TABLE = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}

# 数值的基准。高于它加成功率，低于它减
STAT_BASELINE = 10
# 每高 1 点给多少个百分点。4 意味着 15 点比 10 点多 20% 成功率——
# 足够让玩家感到「练了有用」，又不至于一项点满就无脑通关
RATE_PER_POINT = 4

# 两头都留 5%：永远有意外，也永远有奇迹。这是文字游戏里最重要的
# 一条手感保障——100% 必成的判定不如不判
RATE_MIN, RATE_MAX = 5, 95

OUTCOME_LABELS = {
    "crit_success": "大成功",
    "success": "成功",
    "narrow": "险胜",
    "fail": "失败",
    "crit_fail": "大失败",
}

# 「险胜」能吃下多少个百分点的差距。没有这一档时纯失败率太高，
# 文字冒险里连续失败极其挫败，玩家玩几轮就关了。
# 而且「做成了但付出代价」比干净的失败更好看
NARROW_MARGIN = 20

# 掷出多低算大成功（成功率的几分之一）
CRIT_DIVISOR = 5
# 掷出多高算大失败
CRIT_FAIL_ROLL = 96

# 不掷随机数时的分档线。同一存档重玩结果一样
CERTAIN_CRIT = 85
CERTAIN_SUCCESS = 50
CERTAIN_NARROW = 35


def normalize_band(band) -> str:
    """模型给的档位。不认识就回落普通，不抛错——一次拼错不该让整轮判定失败。"""
    text = str(band or "").strip().lower()
    return text if text in BANDS else DEFAULT_BAND


def resolve_rate(rate_table, band, stat_value, bias: int = 0) -> int:
    """档位 + 数值 → 成功率（%）。模组表里缺这一档就用内置默认。"""
    key = normalize_band(band)
    table = rate_table if isinstance(rate_table, dict) else {}
    try:
        base = int(table.get(key, DEFAULT_RATE_TABLE[key]))
    except (TypeError, ValueError):
        base = DEFAULT_RATE_TABLE[key]
    try:
        base += (int(stat_value) - STAT_BASELINE) * RATE_PER_POINT
    except (TypeError, ValueError):
        pass
    try:
        base += int(bias)
    except (TypeError, ValueError):
        pass
    return max(RATE_MIN, min(RATE_MAX, base))


def classify(dice: int, rate: int) -> str:
    """掷出的 1~100 对成功率分档。掷得越低越好，和成功率同一把尺子。"""
    if dice >= CRIT_FAIL_ROLL:
        return "crit_fail"
    if dice <= max(1, rate // CRIT_DIVISOR):
        return "crit_success"
    if dice <= rate:
        return "success"
    if dice <= rate + NARROW_MARGIN:
        return "narrow"
    return "fail"


def classify_certain(rate: int) -> str:
    """不掷随机数时纯看成功率。确定性判定：同输入必然同结果。"""
    if rate >= CERTAIN_CRIT:
        return "crit_success"
    if rate >= CERTAIN_SUCCESS:
        return "success"
    if rate >= CERTAIN_NARROW:
        return "narrow"
    return "fail"


def roll(rate: int, random_check: bool = True, rng: random.Random | None = None) -> dict:
    """判一次。rng 只为测试可复现而留，正常调用不传。

    random_check 为假时 dice 为 0，前端据此只显示成功率不显示掷点。
    """
    rate = int(rate)
    if not random_check:
        return {"rate": rate, "dice": 0, "outcome": classify_certain(rate)}
    dice = (rng or random).randint(1, 100)
    return {"rate": rate, "dice": dice, "outcome": classify(dice, rate)}
