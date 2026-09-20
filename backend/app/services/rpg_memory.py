import hashlib
import re

from app.services.context_budget import truncate_to_token_budget
from app.services.text_ranking import bm25_rank, rrf_fuse

# BM25 只取前 16 名：回忆池很小，再靠后的名次基本是噪声
BM25_TOP_K = 16
# 原文摘录没经过结算审核，不许靠名次挤掉审过的事实，所以单独设上限
EXCERPT_LINE_CAP = 3
# 单条摘录长度上限：摘录只是线索，太长会把 1100 token 的回忆块吃光
EXCERPT_CHARS = 80
# 切句保留句末标点：摘录要能原样引给模型看
_SENTENCE_END = re.compile(r"(?<=[。！？；!?;\n])")


def text_revision(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def invalidate_summaries(sess) -> None:
    sess.summary = ""
    sess.summarized_upto_id = 0
    sess.thread_summaries = {}
    sess.thread_upto = {}


def _best_snippet(content: str, query: str) -> str:
    """原文摘录取最贴题的一句：复用 bm25_rank 选句，不另写一套排序。

    单句选不出来就退回开头（BM25Okapi 语料只有一条时 idf 恒为负，命中会被
    bm25_rank 的 score>0 滤掉）——那种情况下整条消息本来就只有一句。
    """
    sentences = [s.strip() for s in _SENTENCE_END.split(content or "") if s.strip()]
    hits = bm25_rank(query, [{"text": s} for s in sentences], 1)
    snippet = hits[0]["text"] if hits else (content or "").strip()
    return snippet[:EXCERPT_CHARS]


def event_memory(history, audience: set[int], query: str, budget: int = 1100,
                 window_ids: set[int] | None = None,
                 out_participants: set[int] | None = None) -> str:
    # out_participants：传一个 set 进来，函数把**入选**往事牵涉到的 NPC id 塞进去。
    # 这是第二跳的数据出口——「提到往事 → 往事里的人也加载」靠调用方拿这份 id 补卡。
    # 用出参而非改返回：十几处调用把返回值直接当字符串用，改签名会连坐全破
    recall = bool(re.search(r"记得|还记|当时|那次|以前|曾经|承诺|答应|为什么|如何认识", query))
    terms = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()))
    terms.update(query[index:index + 2] for index in range(len(query) - 1)
                 if all("一" <= char <= "鿿" for char in query[index:index + 2]))
    window_ids = window_ids or set()
    pool = []
    for row in history:
        content = row.content or ""
        report = getattr(row, "settlement", None) or {}
        # 结算过的消息只收「审过且原文没被改稿」的事实。这三道是审计链和隐私边界
        settled = (report.get("status") in {"done", "partial"}
                   and report.get("revision") == text_revision(content))
        if settled:
            for fact in report.get("facts") or []:
                if not isinstance(fact, dict):
                    continue
                quote = fact.get("quote") or ""
                if not quote or quote not in content:
                    continue
                witnesses = set(fact.get("witnesses") or [])
                if audience and fact.get("visibility") != "public" and not audience.issubset(witnesses):
                    continue
                searchable = str(fact.get("summary") or "") + quote
                score = sum(term in searchable.lower() for term in terms)
                if fact.get("kind") in {"relationship", "promise", "rescue", "death"}:
                    score += 2
                # 事实是结算时审过的，0 分也保留：在 RRF 里 0 分只是名次靠后，不会消失
                pool.append({"key": quote, "text": searchable, "surface": score,
                             "message_id": row.id, "fact": fact})
        # 正文此前从未进过索引：结算失败、改稿后 revision 对不上、或没被任何事实
        # 引用的消息，在旧实现里完全搜不到。这里把原文本身补成候选，补的就是这个洞
        #
        # 结算有效的消息**不**补原文候选：witnesses 会被结算收窄到比在场名单更小
        # （见 test_private_promise_retains_witnesses_and_source），补了原文就等于
        # 开了一条绕过 witnesses 闸门的路；顺带也免了同一回合出两行
        if settled or row.id in window_ids or not content.strip():
            continue
        # 可见性判据镜像上面那道非公开事实闸门。故意不 import rpg_context 的
        # message_slots：那边反向 import 本模块，会成环
        #
        # ponytail: 这条判据比事实闸门更严——消息没有 visibility 字段，只能要求
        # 本轮听众全部在当时的在场名单里。天花板是玩家独自经历的那些消息，在 NPC
        # 在跟前时搜不到。升级路径：给 RpgMessage 补 visibility，或结算时给消息
        # 本身打公开标记，那时这里就能照事实那样放过公开消息
        if audience and not audience.issubset(set(getattr(row, "present", None) or [])):
            continue
        pool.append({"key": f"msg:{row.id}", "text": content,
                     "surface": sum(term in content.lower() for term in terms),
                     "message_id": row.id})
    # bm25_rank 返回的是加了 bm25_score 的拷贝，而 rrf_fuse 保留 surface 侧的原始
    # dict，所以「被 BM25 捞到」这件事只能另记一份 key 集合
    bm25_ranked = bm25_rank(query, pool, BM25_TOP_K)
    bm25_keys = {c["key"] for c in bm25_ranked}
    # 原文摘录必须确有词面相关性才留下，事实不受此限：没审过的原文 0 分入选
    # 就是往 prompt 里倒垃圾。
    #
    # 入场口刻意只认 surface，不认 BM25：中文按 query 的二字滑窗做子串匹配，
    # 召回本来就宽，BM25 在这里的价值是**排序**（idf 让「药园」压过「你」「把」），
    # 不是召回。让它单独当入场口的话，jieba 切出来的单字停用词会把无关消息顶进
    # 那 3 行摘录额度——实测问「答应过什么、药园那把火」会捞回「买了一把断刃」
    pool = [c for c in pool if "fact" in c or c["surface"] > 0]
    # 两个列表必须同筛：rrf_fuse 取的是并集，只筛 pool 的话被淘汰的候选会从
    # BM25 那一路原样回来
    kept = {c["key"] for c in pool}
    bm25_ranked = [c for c in bm25_ranked if c["key"] in kept]
    # +2 的类型加成在 RRF 下依然生效：它抬高的是 surface 侧的名次，而 RRF 只看名次
    surface_ranked = sorted(pool, key=lambda c: (c["surface"], c["message_id"]), reverse=True)
    fused = rrf_fuse(surface_ranked, bm25_ranked, key=lambda c: c["key"])
    lines = []
    excerpts = 0
    for cand in fused:
        if len(lines) >= 8:
            break
        fact = cand.get("fact")
        if fact is None:
            if excerpts >= EXCERPT_LINE_CAP:
                continue
            excerpts += 1
            lines.append(
                f"- 回合消息 #{cand['message_id']}（原文摘录）：「{_best_snippet(cand['text'], query)}」"
            )
            continue
        if out_participants is not None:
            out_participants.update(
                p for p in (fact.get("participants") or []) if isinstance(p, int)
            )
        scope = "已公开" if fact.get("visibility") == "public" else "仅当时知情者知晓"
        line = f"- 回合消息 #{cand['message_id']}（{scope}）：{fact.get('summary') or cand['key']}"
        if recall or cand["surface"] > 0 or cand["key"] in bm25_keys:
            line += f"\n  原文依据：「{cand['key']}」"
        lines.append(line)
    if not lines:
        return ""
    return truncate_to_token_budget(
        "【长期事实与回忆依据】\n以下是已发生的往事，不是本轮新增变化；"
        "现状以当前状态为准。不得让未获知的人知道私下事件。\n" + "\n".join(lines), budget,
    )
