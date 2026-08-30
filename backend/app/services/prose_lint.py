"""正文确定性检查：AI 味套式句 + 生成退化。

只做正则/统计能确定判定的项，不做文风主观判断。
对话内容不参与套式句判定（台词里说"不是A而是B"是正常的）。
"""
import re

_QUOTE_PAIRS = [("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’")]

# 引号外叙述层才判定的套式句
_NOT_IS_RE = re.compile(r"(?<![是就也不])不是[^。！？!?\n]{2,30}?[，,]?\s*而是[^。！？!?\n]{2,30}")
_REVERSE_NOT_IS_RE = re.compile(
    r"(?<![不就也还只可但倒像若要正便总老更最算怕凡或即自竟原本仍许净光单尽])"
    r"是([^。！？!?\n，,]{2,12})[，,]\s*(?:而)?不是([^。！？!?\n]{2,20})"
)
# 省略“而”的变体：“不是A，是B”“不是A，这才是B”。lookbehind 排除条件句
# （要不是/若不是/幸亏不是）与疑问式（是不是），这些带“不是”但不是对比翻转句。
_BARE_NOT_IS_RE = re.compile(
    r"(?<![是就也不要若如倘亏怕除])不是[^。！？!?\n]{2,30}?[，,]\s*"
    r"(?:这|那|它|他|她)?(?:才|正|恰)?是[^。！？!?\n]{2,20}"
)
_VOICE_CONTRAST_RE = re.compile(r"声音(?:并)?不[大高响亮][^。！？!?\n]{0,16}[却但偏]")
# 只收「没/没有」，不收「不X」——后者在正常汉语里太常见，收进来会大面积误报
_NEGATION_PARADE_RE = re.compile(r"(?:没(?:有)?[^。！？!?，,\n]{1,12}[，,]){2}")

# 章末升华句：只在正文末尾窗口内判定
_TAIL_WINDOW = 600
_TRAILER_RE = re.compile(
    r"没人知道|谁也不知道|谁也没想到|殊不知"
    r"|(?:这)?才刚刚开(?:始|头)"
    r"|(?<!正式)拉开(?:序幕|帷幕)"
    r"|即将(?:开始|来临|降临)"
    r"|(?:新的篇章|新的旅程|新的人生)[^。！？!?\n]{0,12}(?:开始|拉开|展开)"
    r"|命运[^。！？!?\n]{0,8}齿轮"
)

# 工程词泄漏：prompt 字段名被写进正文
_META_TIER1_RE = re.compile(r"细纲|情节点|卷纲|功能标签|目标情绪|字数目标|章首钩子|章尾钩子|写作方向|本章大纲")
_META_TIER2_RE = re.compile(r"伏笔|上一章|下一章|前文|后文")

_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]")
_VISIBLE_RE = re.compile(r"[一-鿿A-Za-z0-9]")

# ── 密度类检查（一律 advisory）─────────────────────────────────────────────
# 两道门槛都过才报：绝对次数防短章误报，每千字密度防长章漏报。
# 数字按"人类作品基本不会同时超两道门槛"取，宁可漏报不误报。

# 小动作口癖："抖了一下""顿了一阵""扫了一眼"
_MICRO_ACTION_RE = re.compile(r"了(?:[一两三几半])?[下阵圈道声眼口气会]")
MICRO_ACTION_MIN, MICRO_ACTION_PER_K = 5, 6.0

# 比喻密度。"像"要排除 不像/头像/图像 这类非比喻用法
_METAPHOR_RE = re.compile(r"(?<![不头图影录摄肖])像(?!素)|仿佛|好似|犹如|宛如|似的")
METAPHOR_MIN, METAPHOR_PER_K = 7, 3.0

# 网文里最常见的一批陈词，只收"高频且几乎只在套话里出现"的
_CLICHE_WORDS = [
    "不由自主", "不约而同", "不禁", "不寒而栗", "毫不犹豫", "毫无疑问",
    "无可奈何", "情不自禁", "眼神一凝", "眼中闪过", "嘴角微微", "嘴角勾起",
    "心中一凛", "心头一震", "心中暗道", "深吸一口气", "长长地", "缓缓地",
    "微微一笑", "淡淡一笑", "冷冷地", "轻描淡写", "如同潮水", "如释重负",
    "空气仿佛", "时间仿佛", "死一般的寂静", "鸦雀无声", "浑身一僵",
]
_CLICHE_RE = re.compile("|".join(_CLICHE_WORDS))
CLICHE_MIN, CLICHE_PER_K = 8, 12.0

DENSITY_MIN_SAMPLE = 200  # 叙述层可见字数低于此不算密度

# 句号结巴：连续这么多句都是超短叙述句。
# 这是连跑长度而非密度，不受 DENSITY_MIN_SAMPLE 限制——短章里连着六个三字句也是结巴
STUTTER_RUN = 6
STUTTER_SENT_MAX = 5  # 一句的可见字数上限


def _visible_len(text: str) -> int:
    """可见字数，不含标点空白。"""
    return len(_VISIBLE_RE.findall(text or ""))


def _mask_quoted(text: str) -> str:
    """把引号内容替换为等长句号：保留偏移，且句号天然截断 [^。] 字符类。"""
    chars = list(text)
    for open_q, close_q in _QUOTE_PAIRS:
        depth = 0
        for i, ch in enumerate(chars):
            if ch == open_q:
                depth += 1
            elif ch == close_q and depth > 0:
                depth -= 1
            elif depth > 0:
                chars[i] = "。"
    return "".join(chars)


def _excerpt(text: str, start: int, end: int, pad: int = 6) -> str:
    """取命中处上下文摘录，供审稿意见定位。"""
    left = max(0, start - pad)
    right = min(len(text), end + pad)
    return text[left:right].replace("\n", " ").strip()


def _tail_offset(text: str) -> int:
    """章末窗口起点：从末尾往前累计 _TAIL_WINDOW 个可见字。"""
    count = 0
    for i in range(len(text) - 1, -1, -1):
        if _VISIBLE_RE.match(text[i]):
            count += 1
            if count >= _TAIL_WINDOW:
                return i
    return 0


def _check_ai_patterns(text: str, masked: str) -> list[dict]:
    """AI 味套式句，仅判定叙述层（引号内已 mask）。"""
    findings: list[dict] = []

    for label, pattern in (
        ("不是A而是B 套式句", _NOT_IS_RE),
        ("不是A是B 套式句", _BARE_NOT_IS_RE),
        ("是A不是B 套式句", _REVERSE_NOT_IS_RE),
        ("声音对比套式句", _VOICE_CONTRAST_RE),
        ("否定排比套式句", _NEGATION_PARADE_RE),
    ):
        for m in pattern.finditer(masked):
            findings.append({
                "severity": "blocking",
                "category": "ai_pattern",
                "label": label,
                "evidence": _excerpt(text, m.start(), m.end()),
            })

    tail_start = _tail_offset(masked)
    for m in _TRAILER_RE.finditer(masked, tail_start):
        findings.append({
            "severity": "blocking",
            "category": "ai_pattern",
            "label": "章末升华/剧透句",
            "evidence": _excerpt(text, m.start(), m.end()),
        })

    return findings


def _is_pure_dialogue(line: str) -> bool:
    """整行基本就是一句台词：去掉引号内容后几乎不剩字。"""
    stripped = line.strip()
    if not stripped:
        return False
    visible = _visible_len(stripped)
    if not visible:
        return False
    outside = _visible_len(_mask_quoted(stripped))
    return outside * 3 <= visible


def _check_density(text: str, masked: str) -> list[dict]:
    """口癖/比喻/陈词的密度。全部 advisory，只提醒不打回。"""
    findings: list[dict] = []
    narration_len = _visible_len(masked)
    if narration_len < DENSITY_MIN_SAMPLE:  # 样本太短，密度不可靠
        return findings
    per_k = narration_len / 1000

    for label, pattern, floor, density in (
        ("小动作口癖", _MICRO_ACTION_RE, MICRO_ACTION_MIN, MICRO_ACTION_PER_K),
        ("比喻过密", _METAPHOR_RE, METAPHOR_MIN, METAPHOR_PER_K),
        ("陈词滥调过密", _CLICHE_RE, CLICHE_MIN, CLICHE_PER_K),
    ):
        hits = pattern.findall(masked)
        n = len(hits)
        if n < floor or n / per_k < density:
            continue
        samples = "、".join(dict.fromkeys(str(h) for h in hits[:5]))
        findings.append({
            "severity": "advisory",
            "category": "density",
            "label": f"{label}（叙述层 {n} 处，每千字 {n / per_k:.1f} 处）",
            "evidence": samples,
        })

    return findings


def _check_stutter(text: str) -> list[dict]:
    """连续超短叙述句。整行台词把计数清零，不是跳过——台词本来就短。"""
    findings: list[dict] = []
    run = 0
    worst = 0
    evidence = ""
    for line in text.split("\n"):
        if not line.strip():
            continue
        if _is_pure_dialogue(line):
            run = 0
            continue
        for sent in _SENTENCE_SPLIT_RE.split(_mask_quoted(line)):
            n = _visible_len(sent)
            if n == 0:  # 掩码留下的空片段，不计入也不清零
                continue
            if n <= STUTTER_SENT_MAX:
                run += 1
                if run > worst:
                    worst = run
                    evidence = line.strip()[:40]
            else:
                run = 0
    if worst >= STUTTER_RUN:
        findings.append({
            "severity": "advisory",
            "category": "density",
            "label": f"连续 {worst} 句都是 {STUTTER_SENT_MAX} 字以内的短叙述句",
            "evidence": evidence,
        })
    return findings


def _check_degeneration(text: str) -> list[dict]:
    """生成退化：复读、工程词泄漏。截断检查由 critic 现有逻辑负责。"""
    findings: list[dict] = []

    lines = [ln.strip() for ln in text.split("\n")]
    prev = ""
    for line in lines:
        if line and line == prev and _visible_len(line) >= 8:
            findings.append({
                "severity": "blocking",
                "category": "degeneration",
                "label": "相邻段落完全重复",
                "evidence": line[:40],
            })
        if line:
            prev = line

    counts: dict[str, int] = {}
    for sent in _SENTENCE_SPLIT_RE.split(_mask_quoted(text)):
        s = sent.strip()
        if _visible_len(s) >= 12:
            counts[s] = counts.get(s, 0) + 1
    for sent, n in counts.items():
        if n >= 3:
            findings.append({
                "severity": "blocking",
                "category": "degeneration",
                "label": f"同一句在全文重复 {n} 次",
                "evidence": sent[:40],
            })

    for m in _META_TIER1_RE.finditer(_mask_quoted(text)):
        findings.append({
            "severity": "blocking",
            "category": "meta_leak",
            "label": f"正文泄漏内部字段名「{m.group()}」",
            "evidence": _excerpt(text, m.start(), m.end(), pad=10),
        })

    for m in _META_TIER2_RE.finditer(_mask_quoted(text)):
        findings.append({
            "severity": "advisory",
            "category": "meta_leak",
            "label": f"正文出现创作术语「{m.group()}」",
            "evidence": _excerpt(text, m.start(), m.end(), pad=10),
        })

    return findings


def lint(text: str) -> list[dict]:
    """检查正文，返回 findings 列表。

    每条 finding：severity(blocking/advisory) / category / label / evidence。
    category=meta_leak 且 blocking 表示提示词字段名漏进正文，
    这类问题改写改不掉，调用方应重新生成而非修订。
    """
    if not text or not text.strip():
        return []
    masked = _mask_quoted(text)
    return (
        _check_ai_patterns(text, masked)
        + _check_degeneration(text)
        + _check_density(text, masked)
        + _check_stutter(text)
    )


def format_issues(findings: list[dict]) -> list[str]:
    """把 findings 转成审稿意见行，同类合并只报首例避免刷屏。"""
    seen: dict[str, int] = {}
    order: list[str] = []
    samples: dict[str, str] = {}
    for f in findings:
        label = f["label"]
        if label not in seen:
            order.append(label)
            samples[label] = f.get("evidence", "")
        seen[label] = seen.get(label, 0) + 1

    lines: list[str] = []
    for label in order:
        n = seen[label]
        count_part = f"，共 {n} 处" if n > 1 else ""
        lines.append(f"{label}（原文：…{samples[label]}…{count_part}），请改写")
    return lines

