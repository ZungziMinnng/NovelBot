"""RPG 侧上下文的额度分配。

原先各块的额度是 rpg_context 里十几个写死的常量，改模型、改模组都动不了。
这里把它们收成一张**基准表**，按模组填的总闸等比缩放。

缩放用整数乘除（`base * total // BASELINE_TOTAL`）而不是浮点比例，是为了
`total == BASELINE_TOTAL` 时每一项都**精确等于**原来的常量——老局的 prompt
一个字不变，这条由 test_rpg_budget 守着。

**SUGGEST_* 那一组不在这里。** 它是建议模型那一份的独立总闸，读者是另一个
模型，作者也改不到；理由写在 rpg_context 那一组常量的注释里。
"""

# 这个数同时是 RpgModule.context_budget 的默认值——不填就是今天的行为。
#
# **各块额度之和（现在约 22000）本来就大于它，这是有意的**：每一块的额度是
# 「这一块写满了最多给它这么多」，而一局里不可能所有块同时写满（十个角色同框、
# 每个数值每一档都写了说明）。真同时撑爆时由 _fit_sections 按
# 重要性丢，不是按谁排在后面切。所以往上调某一块不必等额从别处扣
BASELINE_TOTAL = 21500

# 基准额度。每一项当初是怎么定的，注释留在 rpg_context 原常量那里，
# 改这里的数等于改那边的结论，两边都要看
SECTION_BASE = {
    "world": 3000,
    "summary": 2000,
    # 被提到、但人不在跟前的人的份额，不参与 summary 的均分
    "aside_summary": 300,
    "state": 880,
    "npc": 10000,
    "roster": 1500,
    # 400 是照着「note 没人填」的现状定的，而量过之后那恰好是病因：真实模组里
    # 14 档只填了标签、一个 note 都没写，这一块就已经 386/400——作者填第一句
    # 说明就溢出，溢出又是从尾部切字符，切掉的是最后几项数值的整段说明。
    # 它既不在 PROTECTED_SECTIONS 也不在 DROP_ORDER，属于「从尾部裁」那一组，
    # 所以不够用的时候没有任何提示，只是静默变短。
    # 1600 够那 14 档各写一句 60 字的说明；写满 150 字（约 3500）仍会被裁，
    # 那是有意的上界：这一块每轮都发，真要长篇解释数值该写进世界观
    "meaning": 1600,
    "scene": 400,
    "catalog": 700,
    # 单人份，由 _npc_history_lines 从尾部裁
    "npc_history": 220,
    "milestone": 400,
    # event_memory 那一块（长期事实与回忆依据）
    "memories": 1100,
}


def build_rpg_budget(total: int | None) -> dict[str, int]:
    """把总闸按基准表摊成各块额度。total 为空/非法时退回基准值。"""
    amount = max(1, int(total or BASELINE_TOTAL))
    budget = {
        key: max(1, base * amount // BASELINE_TOTAL)
        for key, base in SECTION_BASE.items()
    }
    # 总闸本身也放进去：拼完整段 system 之后的那一刀读的就是它
    budget["system"] = amount
    return budget
