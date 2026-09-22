"""RPG 长期记忆的向量召回。

小说侧那套漏斗（向量 + BM25 + 词面 → RRF → 重排）这里只搬前两样。重排不搬：
RPG 是**每回合**跑一次，不是每章跑一次，本地 GPU 懒加载那套代价放这里不对。

三条前提，破了哪条这个模块就不该存在：

1. **`RpgModule.embedding_model_ref` 为空 = 整条路关着。** 不另设开关——多一个
   开关就多出「配了却关着」这种谁也说不清的状态。没配就是一次嵌入接口都不调，
   召回退回 BM25 + 词面两路，和没有这个文件时一模一样。
2. **任何一条路径都不向上抛异常**（照抄 `reranker.py` 的姿态）。嵌入端点被墙在
   这台机器上是常态，而它发作的时刻正是玩家在等这一轮叙事。
3. **`search` 只回答「命中了哪些候选」，不回答候选长什么样。** 可见性闸门
   （事实看 `witnesses`、原文看 `present`）留在 `rpg_memory.event_memory` 的候选池
   里一处判。向量这条路要是自己再抄一份判据，两份迟早分叉，而分叉的那一次是
   把私密事实漏给不该知道的人——这是这个模块最容易写错的地方。
"""

import logging

from sqlalchemy import select

from app.models.rpg import RpgMessage, RpgSession
from app.services import vector_store
from app.services.rpg_memory import text_revision

logger = logging.getLogger(__name__)

# collection 名和缓存键的前缀。RPG 的 session id 和小说 id 是两套各自从 1 开始的
# 编号，不隔开的话 1 号存档会写进 1 号小说的库里
NAMESPACE = "rpg"
# 和 rpg_memory.BM25_TOP_K 取同一个数：两路交给 RRF 的名次长度一样，谁也不占便宜
SEARCH_TOP_K = 16
# 一次嵌入多少段。开了向量的老局第一次补要嵌几百段，一次请求塞不下
EMBED_BATCH = 64
# 指针最多为「结算还没落定」的消息让步这么多条，理由见 _up_to_settled
STALL_WINDOW = 20


def _docs(row: RpgMessage) -> list[tuple[str, str, dict]]:
    """一条消息摊成几个 doc。

    **两类候选和 `event_memory` 里的那两类逐字对齐**：结算过的消息出事实 doc
    （文本 = summary + quote，key = quote），没结算过的出原文 doc（key = `msg:id`）。
    对齐是为了让 search 回来的 key 能直接在那边的候选池里认领——认不领的一概丢掉，
    于是闸门只有那一处。
    """
    content = row.content or ""
    if not content.strip():
        return []
    report = row.settlement or {}
    # 这三道判据抄自 event_memory：审过、状态可用、原文没被改稿
    settled = (report.get("status") in {"done", "partial"}
               and report.get("revision") == text_revision(content))
    if not settled:
        return [(
            f"msg_{row.id}", content,
            {"kind": "excerpt", "mid": row.id, "key": f"msg:{row.id}"},
        )]
    docs = []
    for index, fact in enumerate(report.get("facts") or []):
        if not isinstance(fact, dict):
            continue
        quote = fact.get("quote") or ""
        if not quote or quote not in content:
            continue
        docs.append((
            f"fact_{row.id}_{index}", str(fact.get("summary") or "") + quote,
            {"kind": "fact", "mid": row.id, "key": quote},
        ))
    return docs


def _up_to_settled(rows: list[RpgMessage]) -> list[RpgMessage]:
    """指针停在第一条「结算还没落定」的 assistant 行之前。

    那种行是**将来还会变的**：现在只有原文，玩家点了「补结算」之后才会长出事实。
    指针要是越过去了，它的事实就再也不会被嵌，而向量这条路从此对那一轮失明。

    只对最近 STALL_WINDOW 条让步：一次永久失败的结算会把指针永远钉在原地，
    每轮重嵌一条越来越长的尾巴，那比漏掉一轮更糟。
    """
    recent = {row.id for row in rows[-STALL_WINDOW:]}
    for index, row in enumerate(rows):
        if row.role == "assistant" and row.settlement is None and row.id in recent:
            return rows[:index]
    return rows


async def sync_session(session_id: int) -> None:
    """把这一局还没进过向量库的消息补上。失败静默，下一轮自然重试。"""
    from app.database import AsyncSessionLocal
    from app.models.rpg import RpgModule

    try:
        async with AsyncSessionLocal() as db:
            sess = await db.get(RpgSession, session_id)
            if sess is None:
                return
            module = await db.get(RpgModule, sess.module_id)
            ref = (getattr(module, "embedding_model_ref", "") or "").strip()
            if not ref:
                return
            rows = _up_to_settled(list((await db.execute(
                select(RpgMessage)
                .where(
                    RpgMessage.session_id == session_id,
                    RpgMessage.id > (sess.vector_upto_id or 0),
                )
                .order_by(RpgMessage.id)
            )).scalars().all()))
            if not rows:
                return
            items = [doc for row in rows for doc in _docs(row)]
            await vector_store.ensure_embedding_for(NAMESPACE, session_id, ref, db)
            for start in range(0, len(items), EMBED_BATCH):
                await vector_store.astore_texts_batch(
                    session_id, items[start:start + EMBED_BATCH], NAMESPACE,
                )
            # 指针**全部写成功之后**才推。中途断了就停在原地，下一轮从头补——
            # 宁可重嵌一遍（upsert 幂等）也不能跳过，跳过的那几条从此搜不到
            sess.vector_upto_id = rows[-1].id
            await db.commit()
    except Exception:
        logger.warning(
            "RPG 局 %s 向量补写失败，这一轮的召回退回词面两路", session_id, exc_info=True,
        )


async def search(sess: RpgSession, module, query: str, db,
                 top_k: int = SEARCH_TOP_K) -> list[str]:
    """按相似度从高到低返回命中的候选 key。没配模型 / 出错一律返回空列表。"""
    ref = (getattr(module, "embedding_model_ref", "") or "").strip()
    if not ref or not (query or "").strip():
        return []
    try:
        await vector_store.ensure_embedding_for(NAMESPACE, sess.id, ref, db)
        hits = await vector_store.asearch_similar_with_meta(
            sess.id, query, top_k, namespace=NAMESPACE,
        )
    except Exception:
        logger.warning("RPG 局 %s 向量检索失败，退回词面两路", sess.id, exc_info=True)
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        key = str((hit.get("metadata") or {}).get("key") or "")
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


async def forget_after(sess: RpgSession, module, message_id: int) -> None:
    """回溯之后把 id 大于 message_id 的 doc 全删掉，指针跟着回退。

    **不接这一步会留下幽灵记忆**：被回溯掉的「未来」还躺在向量库里，下一轮照样
    检索得回来，模型会照着写玩家没经历过的事——正是 RpgSave 注释里说的
    最难查的那一类 bug。
    """
    ref = (getattr(module, "embedding_model_ref", "") or "").strip()
    if not ref:
        return
    await vector_store.adelete_where(
        sess.id, {"mid": {"$gt": int(message_id)}}, NAMESPACE,
    )
    if (sess.vector_upto_id or 0) > message_id:
        sess.vector_upto_id = int(message_id)


async def forget_message(sess: RpgSession, module, message_id: int) -> None:
    """删单条消息时删它自己的 doc。指针不动：这条没了，也没有要补回来的东西。"""
    ref = (getattr(module, "embedding_model_ref", "") or "").strip()
    if not ref:
        return
    await vector_store.adelete_where(sess.id, {"mid": int(message_id)}, NAMESPACE)
