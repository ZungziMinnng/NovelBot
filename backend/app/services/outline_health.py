"""大纲体检：只报告不拦截。

纯函数，输入 dict 列表，输出 findings。不查库、不调模型，所有阈值都是明数字。
findings 每条：level(warn/info) / label / detail。
"""
import math
from collections import Counter

from app.services.outline_plan import CHAPTER_ROLES

# 章节定位配比（占章数比例）。参考 oh-story 的统计口径，只当提醒不当硬规则。
# 各档区间加起来不等于 100%（下限合计 65%，上限合计 115%），所以不能两头都查，
# 否则任何一份大纲都必然踩中某一条。只查"少了真的有问题"和"多了真的有问题"的方向：
#   check="min" → 只报偏少（撑不起爽感/推进力）
#   check="max" → 只报偏多（水）
#   修炼试错、关系回收多两章无所谓，不查
ROLE_QUOTA = {
    "高压": (0.15, 0.20, "min"),
    "推进": (0.40, 0.50, "min"),
    "修炼试错": (0.05, 0.10, None),
    "关系回收": (0.05, 0.10, None),
    "低压生活": (0.0, 0.10, "max"),
    "信息整理": (0.0, 0.05, "max"),
}
# 低压生活 + 信息整理 合计上限
IDLE_ROLES = ("低压生活", "信息整理")
IDLE_MAX_RATIO = 0.15

BIG_PAYOFF_INTERVAL = 7        # 每多少章要有一个高强度爽点章
HOOK_REPEAT_MAX = 2            # 同一钩子类型最多连用几章
MIN_HOOK_STRENGTH = 2          # 普通章的钩子强度下限
OUTLINE_PROSE_RATIO = (2.0, 4.0)  # 正文字数 / 细纲字数 的合理区间
RATIO_MIN_SAMPLES = 3          # 少于这么多章有正文，字数比不下结论

ENDGAME_MIN = 2                # 留到结尾的牌至少还剩几张


def _count_lines(text: str) -> int:
    return len([ln for ln in (text or "").splitlines() if ln.strip()])


def check_volume_reserves(volume: dict, total_target_words: int) -> list[dict]:
    """卷级库存三问：结尾还有牌吗、实力档位够撑满字数吗、好料是不是提前烧完了。

    total_target_words 传 0 表示未设定字数目标，跳过档位算数那一问。
    """
    findings: list[dict] = []

    endgame = _count_lines(volume.get("endgame_cards", ""))
    if endgame == 0:
        findings.append({
            "level": "warn",
            "label": "没有登记留到结尾才揭的牌",
            "detail": "主角身世、大反派真身、世界真相这类要留到最后的东西，"
                      "现在一条都没记。写到后半段容易发现无牌可打",
        })
    elif endgame < ENDGAME_MIN:
        findings.append({
            "level": "warn",
            "label": f"留到结尾的牌只剩 {endgame} 张",
            "detail": f"建议至少留 {ENDGAME_MIN} 张，否则结局只能靠一个悬念撑",
        })

    tiers = int(volume.get("tier_count") or 0)
    per_tier = int(volume.get("words_per_tier") or 0)
    if total_target_words > 0 and tiers > 0 and per_tier > 0:
        capacity = tiers * per_tier
        if capacity < total_target_words:
            findings.append({
                "level": "warn",
                "label": f"实力档位撑不满全书（{tiers} 档 × {per_tier} 字 = {capacity} 字）",
                "detail": f"全书目标 {total_target_words} 字，还差 "
                          f"{total_target_words - capacity} 字。"
                          f"要么加档位，要么每档多写，否则写到一半就顶天了",
            })
    elif total_target_words > 0 and (tiers == 0 or per_tier == 0):
        findings.append({
            "level": "info",
            "label": "没填实力档位数或每档字数",
            "detail": "填上就能直接算出实力体系够不够撑满全书字数",
        })

    spent = _count_lines(volume.get("spent_payoffs", ""))
    if spent and endgame and spent > endgame:
        findings.append({
            "level": "warn",
            "label": f"本卷已用掉 {spent} 个大爆点，剩下的牌只有 {endgame} 张",
            "detail": "用掉的比留着的多，后面几卷的料可能已经提前烧掉了",
        })

    return findings


def _is_big_payoff(o: dict) -> bool:
    return o.get("chapter_role") == "高压" and int(o.get("emotion_intensity") or 0) >= 4


def check_chapter_outlines(outlines: list[dict]) -> list[dict]:
    """章纲体检。outlines 需按章号升序，每项可含 word_count（该章正文字数）。"""
    findings: list[dict] = []
    if not outlines:
        return findings

    total = len(outlines)

    unplanned = [o for o in outlines if not o.get("chapter_role")]
    if unplanned:
        findings.append({
            "level": "warn" if len(unplanned) == total else "info",
            "label": f"{len(unplanned)}/{total} 章没有执行计划",
            "detail": "这些章缺定位/情绪/钩子，写正文时只能靠模型临场决定："
                      + _chapter_list(unplanned),
        })

    planned = [o for o in outlines if o.get("chapter_role")]
    if planned:
        findings.extend(_check_role_mix(planned))
        findings.extend(_check_payoff_density(planned))

    findings.extend(_check_hooks(outlines))
    findings.extend(_check_outline_prose_ratio(outlines))
    return findings


def _chapter_list(items: list[dict], limit: int = 12) -> str:
    nums = [str(o.get("chapter_number") or 0) for o in items[:limit]]
    tail = " 等" if len(items) > limit else ""
    return "第 " + "、".join(nums) + f" 章{tail}"


def _check_role_mix(planned: list[dict]) -> list[dict]:
    findings: list[dict] = []
    total = len(planned)
    counts = Counter(o["chapter_role"] for o in planned)

    for role in CHAPTER_ROLES:
        lo, hi, check = ROLE_QUOTA.get(role, (0.0, 1.0, None))
        if check is None:
            continue
        n = counts.get(role, 0)
        ratio = n / total
        # 比章数不比比例：2/19=10.5% 这种四舍五入的零头不该报警
        if check == "min" and n < math.floor(total * lo):
            findings.append({
                "level": "warn",
                "label": f"{role}章偏少（{n}/{total}，{ratio:.0%}）",
                "detail": f"建议占 {lo:.0%}-{hi:.0%}，至少 {math.floor(total * lo)} 章",
            })
        elif check == "max" and n > math.ceil(total * hi):
            findings.append({
                "level": "warn",
                "label": f"{role}章偏多（{n}/{total}，{ratio:.0%}）",
                "detail": f"建议不超过 {hi:.0%}，即 {math.ceil(total * hi)} 章",
            })

    idle = sum(counts.get(r, 0) for r in IDLE_ROLES)
    if idle > math.ceil(total * IDLE_MAX_RATIO):
        findings.append({
            "level": "warn",
            "label": f"低压生活加信息整理合计 {idle}/{total}（{idle / total:.0%}）",
            "detail": f"合计建议不超过 {IDLE_MAX_RATIO:.0%}，过多会让读者觉得水",
        })
    return findings


def _check_payoff_density(planned: list[dict]) -> list[dict]:
    """高强度爽点章的间隔：只看已规划的章，避免把未规划段落算成断档。"""
    payoff_positions = [
        i for i, o in enumerate(planned) if _is_big_payoff(o)
    ]
    if not payoff_positions:
        if len(planned) >= BIG_PAYOFF_INTERVAL:
            return [{
                "level": "warn",
                "label": "全程没有高强度爽点章",
                "detail": f"已规划 {len(planned)} 章里没有一章是「高压 + 情绪强度≥4」，"
                          f"建议每 {BIG_PAYOFF_INTERVAL} 章左右安排一个",
            }]
        return []

    findings: list[dict] = []
    gaps: list[str] = []
    prev = -1
    for pos in payoff_positions + [len(planned)]:
        gap = pos - prev - 1
        if gap > BIG_PAYOFF_INTERVAL:
            start = planned[prev + 1].get("chapter_number")
            end = planned[pos - 1].get("chapter_number")
            gaps.append(f"第{start}-{end}章（{gap}章）")
        prev = pos
    if gaps:
        findings.append({
            "level": "warn",
            "label": f"有 {len(gaps)} 段连续 {BIG_PAYOFF_INTERVAL} 章以上没有高强度爽点",
            "detail": "、".join(gaps[:6]),
        })
    return findings


def _check_hooks(outlines: list[dict]) -> list[dict]:
    findings: list[dict] = []

    run_type = ""
    run_len = 0
    repeats: list[str] = []
    for o in outlines:
        hook = o.get("hook_type") or ""
        if hook and hook == run_type:
            run_len += 1
            if run_len > HOOK_REPEAT_MAX:
                repeats.append(f"第{o.get('chapter_number')}章「{hook}」")
        else:
            run_type, run_len = hook, 1
    if repeats:
        findings.append({
            "level": "warn",
            "label": f"同一种章尾钩子连用超过 {HOOK_REPEAT_MAX} 章",
            "detail": "、".join(repeats[:8]),
        })

    weak = [
        o for o in outlines
        if o.get("hook_type") and 0 < int(o.get("hook_strength") or 0) < MIN_HOOK_STRENGTH
    ]
    if weak:
        findings.append({
            "level": "info",
            "label": f"{len(weak)} 章的钩子强度低于 {MIN_HOOK_STRENGTH}",
            "detail": _chapter_list(weak),
        })
    return findings


def _check_outline_prose_ratio(outlines: list[dict]) -> list[dict]:
    """细纲与正文的字数比。样本太少不下结论，避免开篇几章就误报。"""
    pairs = [
        (o, len(o.get("content") or ""), int(o.get("word_count") or 0))
        for o in outlines
    ]
    usable = [(o, oc, wc) for o, oc, wc in pairs if oc >= 20 and wc > 0]
    if len(usable) < RATIO_MIN_SAMPLES:
        return []

    lo, hi = OUTLINE_PROSE_RATIO
    thin = [o for o, oc, wc in usable if wc / oc > hi]
    fat = [o for o, oc, wc in usable if wc / oc < lo]
    findings: list[dict] = []
    if thin:
        findings.append({
            "level": "info",
            "label": f"{len(thin)}/{len(usable)} 章的细纲相对正文偏薄",
            "detail": f"正文字数超过细纲的 {hi:g} 倍，这些章基本是模型自己发挥的："
                      + _chapter_list(thin),
        })
    if fat:
        findings.append({
            "level": "info",
            "label": f"{len(fat)}/{len(usable)} 章的正文没写开",
            "detail": f"正文不到细纲的 {lo:g} 倍，细纲里的内容可能没写完："
                      + _chapter_list(fat),
        })
    return findings
