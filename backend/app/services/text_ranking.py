"""与业务无关的排名函数：BM25 关键词检索 + RRF 名次融合。

从 relevance_selector 拆出来，是因为那个模块为了小说侧的正文清理 import 了
summarizer，而 summarizer 又拖进向量库和一大票模型。游戏侧的 rpg_memory 只
要这两个纯函数，不该为此间接加载整条小说链路。
"""
from typing import Any, Callable

import jieba
from rank_bm25 import BM25Okapi


def bm25_rank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """BM25 关键词检索：向量检索对专有名词（人名/功法名）不敏感，这里按词频
    精确匹配补一路排名。candidates 与向量 hits 同构（text + metadata），
    摘要语料小（每章一条），每次请求内存现建索引即可。"""
    if top_k <= 0 or not query or not candidates:
        return []
    query_tokens = [t for t in jieba.lcut_for_search(query) if t.strip()]
    if not query_tokens:
        return []
    docs = [
        (c, tokens)
        for c in candidates
        if (tokens := [t for t in jieba.lcut_for_search(c.get("text") or "") if t.strip()])
    ]
    if not docs:
        return []
    bm25 = BM25Okapi([tokens for _, tokens in docs])
    scores = bm25.get_scores(query_tokens)
    scored = sorted(
        ((float(score), i) for i, score in enumerate(scores) if score > 0),
        key=lambda pair: -pair[0],
    )
    results = []
    for score, i in scored[:top_k]:
        hit = dict(docs[i][0])
        hit["bm25_score"] = score
        results.append(hit)
    return results


def rrf_fuse(
    ranked_a: list[dict],
    ranked_b: list[dict],
    key: Callable[[dict], Any],
    k: int = 60,
) -> list[dict]:
    """RRF 名次融合：每条得分 = Σ 1/(k+名次)，按 key 去重。只看名次不看原始分，
    规避向量距离与 BM25 分数量纲不可比的问题。同 key 保留先出现的（ranked_a
    优先，向量侧 dict 带 similarity 等字段）。"""
    scores: dict = {}
    keep: dict = {}
    for ranked in (ranked_a, ranked_b):
        for rank, hit in enumerate(ranked):
            key_val = key(hit)
            scores[key_val] = scores.get(key_val, 0.0) + 1.0 / (k + rank + 1)
            keep.setdefault(key_val, hit)
    return sorted(keep.values(), key=lambda h: -scores[key(h)])
