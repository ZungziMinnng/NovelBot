"""伏笔/秘密与词库的上下文预算控制。

百万字规模下这两类数据只增不减，必须有上限，否则后期撑爆 prompt。
select_story_threads: 旧已回收剔除、近期已回收压缩、活跃按重要度装入预算（高重要度保底）。
cap_glossary: 词库按字符预算截断。
"""

THREAD_BUDGET_CHARS = 4000
RESOLVED_KEEP_WINDOW = 30
GUARANTEED_IMPORTANCE = 4
GLOSSARY_BUDGET_CHARS = 3000


def _importance(thread: dict) -> int:
    try:
        return int(thread.get("importance") or 3)
    except (TypeError, ValueError):
        return 3


def _thread_cost(thread: dict) -> int:
    return (
        len(thread.get("title") or "")
        + len(thread.get("content") or "")
        + len(thread.get("resolution") or "")
        + 40  # 渲染时的标签/括号等固定开销
    )


def select_story_threads(
    threads: list[dict],
    current_chapter: int,
    *,
    budget_chars: int = THREAD_BUDGET_CHARS,
    resolved_keep_window: int = RESOLVED_KEEP_WINDOW,
) -> list[dict]:
    """筛选进入写作上下文的伏笔/秘密条目。

    - 已回收且回收超过 resolved_keep_window 章：剔除（正文早已消化，不再占上下文）。
    - 近期已回收：保留但标记 compact=True，渲染时压成一行提醒"已回收，别再当悬念写"。
    - 活跃条目：按重要度从高到低装入 budget_chars 预算；
      重要度 >= GUARANTEED_IMPORTANCE 的无视预算永远保留。
    输入顺序（重要度降序）在返回结果中保持不变。
    """
    keep: dict[int, dict] = {}

    for idx, t in enumerate(threads):
        if t.get("status") != "resolved":
            continue
        resolved_chapter = t.get("resolved_chapter")
        if (
            isinstance(resolved_chapter, int)
            and current_chapter - resolved_chapter > resolved_keep_window
        ):
            continue
        keep[idx] = {**t, "compact": True}

    ranked = sorted(
        ((idx, t) for idx, t in enumerate(threads) if t.get("status") != "resolved"),
        key=lambda pair: -_importance(pair[1]),
    )
    used = 0
    for idx, t in ranked:
        cost = _thread_cost(t)
        if _importance(t) >= GUARANTEED_IMPORTANCE:
            keep[idx] = t
            used += cost
            continue
        if used + cost > budget_chars:
            continue
        keep[idx] = t
        used += cost

    return [keep[idx] for idx in sorted(keep)]


def cap_glossary(
    entries: list[dict],
    *,
    budget_chars: int = GLOSSARY_BUDGET_CHARS,
) -> list[dict]:
    """词库按字符预算截断，超出预算的后续条目丢弃（保持输入顺序）。"""
    kept: list[dict] = []
    used = 0
    for g in entries:
        cost = (
            len(g.get("term") or "")
            + len(g.get("forbidden_variants") or "")
            + len(g.get("notes") or "")
            + 15
        )
        if kept and used + cost > budget_chars:
            break
        kept.append(g)
        used += cost
    return kept
