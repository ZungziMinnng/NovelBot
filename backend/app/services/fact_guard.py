"""事实守门员：不依赖 LLM 的、代码级的关键事实一致性校验。

记忆系统的状态写入完全由 LLM 产出 JSON、代码直接落库，缺少一个机械的
矛盾拦截层。本模块提供纯函数校验（无 DB、无 LLM、无副作用），在状态落库
前检测违反物理常识的非法跃迁。

第一批只覆盖「生死」——current_state["存续"] 含"死亡"即判定死亡，与
context_builder 的读取口径一致，是唯一能做到零容忍硬拦的干净布尔事实。
"""

# 合法复活出口：新的存续值显式带这些关键词时放行（对应 prompt 允许的描述性写法）
_RESURRECTION_KEYWORDS = ("复活", "复生", "重生", "借尸还魂", "还魂", "起死回生")


def _is_dead(status: str) -> bool:
    # "假死" 不含子串"死亡"，不会被误判为真死
    return "死亡" in (status or "")


def check_life_death(existing: dict, merged: dict) -> dict | None:
    """检测死亡→存活的非法逆转。

    参数为合并前的旧状态 existing 与合并后的新状态 merged（均为 current_state dict）。
    返回 None（无冲突）或冲突描述 dict：
      {"field", "severity", "reason", "corrected_value"}
    仅当「旧值判定死亡 且 新值不再判定死亡 且 新值无复活关键词」时返回 block。
    corrected_value 交由调用方回写，本函数不碰 ORM、不改传入 dict。
    """
    old = str((existing or {}).get("存续", "") or "")
    new = str((merged or {}).get("存续", "") or "")
    if not _is_dead(old):
        return None  # 旧值非死亡，不管
    if _is_dead(new):
        return None  # 仍是死亡，无逆转
    if any(k in new for k in _RESURRECTION_KEYWORDS):
        return None  # 显式复活，放行
    return {
        "field": "存续",
        "severity": "block",
        "reason": f"存续状态从『{old}』被改为『{new or '（清空）'}』，无复活证据，已还原为死亡",
        "corrected_value": old,
    }
