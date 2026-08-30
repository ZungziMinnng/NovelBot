from dataclasses import asdict, dataclass
from math import ceil


DEFAULT_CONTEXT_WINDOW = 65536
MIN_INPUT_BUDGET = 18000
MAX_INPUT_BUDGET = 36000
SAFETY_RATIO = 0.10

# recent_text（上一章原文）强制完整注入，不参与预算分配
SECTION_RATIOS = {
    "instructions": 0.12,
    "hard_facts": 0.18,
    "current_state": 0.15,
    "rolling_summary": 0.08,
    "rag_context": 0.11,
    "rag_fulltext": 0.05,
    "overview": 0.05,
    "relationship_milestones": 0.04,
    "recall_evidence": 0.06,
}


def estimate_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate for mixed Chinese/Latin text."""
    if not text:
        return 0
    chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = len(text) - chinese
    return ceil(chinese * 1.5 + other * 0.25)


def truncate_to_token_budget(text: str, token_budget: int, *, keep_end: bool = False) -> str:
    if not text or token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text

    # Binary search on character count because Chinese and Latin token densities differ.
    low, high = 1, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = text[-mid:] if keep_end else text[:mid]
        if estimate_tokens(candidate) <= token_budget:
            low = mid
        else:
            high = mid - 1
    body = text[-low:] if keep_end else text[:low]
    return ("…" + body) if keep_end else (body + "…")


@dataclass(frozen=True)
class ContextBudget:
    target_words: int
    context_window: int
    output_reserve: int
    thinking_reserve: int
    safety_reserve: int
    input_budget: int
    allocations: dict[str, int]

    def to_dict(self) -> dict:
        return asdict(self)


def build_context_budget(
    *,
    target_words: int,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    writer_max_tokens: int = 16384,
    thinking_enabled: bool = True,
) -> ContextBudget:
    words = max(1, int(target_words or 5000))
    window = max(16384, int(context_window or DEFAULT_CONTEXT_WINDOW))
    estimated_output = ceil(words * 1.5)
    configured_output = max(2048, int(writer_max_tokens or estimated_output))
    output_reserve = min(estimated_output, configured_output)
    thinking_reserve = ceil(output_reserve * 0.25) if thinking_enabled else 0
    safety_reserve = ceil(window * SAFETY_RATIO)

    candidate = max(MIN_INPUT_BUDGET, min(MAX_INPUT_BUDGET, ceil(estimated_output * 2.5)))
    available = max(8000, window - output_reserve - thinking_reserve - safety_reserve)
    input_budget = min(candidate, available)
    allocations = {
        key: max(1, int(input_budget * ratio))
        for key, ratio in SECTION_RATIOS.items()
    }
    return ContextBudget(
        target_words=words,
        context_window=window,
        output_reserve=output_reserve,
        thinking_reserve=thinking_reserve,
        safety_reserve=safety_reserve,
        input_budget=input_budget,
        allocations=allocations,
    )
