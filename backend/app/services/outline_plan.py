"""章纲的执行计划字段：本章定位、情绪、章尾钩子。

大纲阶段就把这几项定下来，写正文时按计划执行，不靠模型临场发挥。
枚举值故意用中文：既是存库值，也是直接喂给模型的提示词文本，不做二次映射。
"""
import re

# 章尾钩子 13 式（与 writer.jinja2 的清单同源，改这里要同步改模板）
HOOK_TYPES = [
    "突然揭示", "紧急危机", "动作未完", "身份反转", "两难抉择", "神秘物品",
    "倒计时", "承诺威胁", "忽然消失", "话里有话", "画面意象", "呼应前文", "留白",
]

# 本章定位。配比检查见 outline_health，比例参考 oh-story 的统计口径
CHAPTER_ROLES = ["高压", "推进", "修炼试错", "关系回收", "低压生活", "信息整理"]

# 情绪基调。不做正负分类，落点是给模型定腔调
EMOTION_TONES = ["爽快", "压抑", "紧张", "温情", "悲怆", "荒诞", "悬疑", "平稳"]

_FIELD_PATTERNS = {
    "chapter_role": re.compile(r"本章定位[：:\s]*([^\n（(，,]{1,10})"),
    "emotion_tone": re.compile(r"情绪基调[：:\s]*([^\n（(，,]{1,10})"),
    "emotion_intensity": re.compile(r"情绪强度[：:\s]*([1-5])"),
    "hook_type": re.compile(r"章尾钩子[：:\s]*([^\n（(，,]{1,10})"),
    "hook_strength": re.compile(r"钩子强度[：:\s]*([1-5])"),
}
# 从正文里剥掉这些计划行，content 只留剧情描述
_PLAN_LINE_RE = re.compile(
    r"^\s*(?:本章定位|情绪基调|情绪强度|章尾钩子|钩子强度)[：:].*$", re.MULTILINE
)


def _match_enum(value: str, allowed: list[str]) -> str:
    """把模型的自由文本对齐到枚举值，对不上返回空串（宁可留空也不存脏值）。"""
    v = (value or "").strip().strip("【】[]「」")
    if not v:
        return ""
    if v in allowed:
        return v
    # 模型常写"高压章""关系回收类"这类带后缀的说法
    for name in allowed:
        if name in v or v in name:
            return name
    return ""


def clean_plan(data: dict) -> dict:
    """校验模型返回的计划字段（JSON 形态），对不上枚举/范围的键直接丢弃。"""
    plan: dict = {}
    for key, allowed in (
        ("chapter_role", CHAPTER_ROLES),
        ("emotion_tone", EMOTION_TONES),
        ("hook_type", HOOK_TYPES),
    ):
        if v := _match_enum(str(data.get(key) or ""), allowed):
            plan[key] = v
    for key in ("emotion_intensity", "hook_strength"):
        try:
            n = int(data.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 5:
            plan[key] = n
    return plan


def parse_plan(text: str) -> dict:
    """从章纲文本抽出计划字段，抽不到的键不出现在返回值里。"""
    plan: dict = {}
    for key, pattern in _FIELD_PATTERNS.items():
        m = pattern.search(text or "")
        if not m:
            continue
        raw = m.group(1)
        if key in ("emotion_intensity", "hook_strength"):
            plan[key] = int(raw)
        elif key == "chapter_role":
            if v := _match_enum(raw, CHAPTER_ROLES):
                plan[key] = v
        elif key == "emotion_tone":
            if v := _match_enum(raw, EMOTION_TONES):
                plan[key] = v
        elif key == "hook_type":
            if v := _match_enum(raw, HOOK_TYPES):
                plan[key] = v
    return plan


def strip_plan_lines(text: str) -> str:
    """剥掉计划行后的剧情正文；剥完为空则原样返回，避免大纲内容整体丢失。"""
    stripped = _PLAN_LINE_RE.sub("", text or "")
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    return stripped or (text or "").strip()


def format_plan(
    *,
    chapter_role: str = "",
    emotion_tone: str = "",
    emotion_intensity: int = 0,
    hook_type: str = "",
    hook_strength: int = 0,
) -> str:
    """渲染成注入写作上下文的一行；全为空返回空串。"""
    parts: list[str] = []
    if chapter_role:
        parts.append(f"本章定位：{chapter_role}")
    if emotion_tone:
        tone = f"情绪基调：{emotion_tone}"
        if emotion_intensity:
            tone += f"（强度 {emotion_intensity}/5）"
        parts.append(tone)
    if hook_type:
        hook = f"章尾用「{hook_type}」收束"
        if hook_strength:
            hook += f"（强度 {hook_strength}/5）"
        parts.append(hook)
    return "；".join(parts)
