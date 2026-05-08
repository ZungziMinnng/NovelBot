import asyncio
import logging

import chromadb
from chromadb.utils import embedding_functions
from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.chroma_path)
    return _client


def _get_collection(novel_id: int):
    client = _get_client()
    ef = embedding_functions.DefaultEmbeddingFunction()
    return client.get_or_create_collection(
        name=f"novel_{novel_id}",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def store_text(
    novel_id: int,
    doc_id: str,
    text: str,
    metadata: dict | None = None,
) -> None:
    """写入一段文本到向量库"""
    collection = _get_collection(novel_id)
    try:
        collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
    except Exception:
        logger.warning(
            "向量文档写入失败: novel_id=%s doc_id=%s metadata=%s",
            novel_id,
            doc_id,
            metadata,
            exc_info=True,
        )
        raise


def search_similar(
    novel_id: int,
    query: str,
    top_k: int = 3,
    where: dict | None = None,
) -> list[str]:
    """语义检索，返回相关文本列表"""
    collection = _get_collection(novel_id)
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
        )
        docs = results.get("documents", [[]])[0]
        return [d for d in docs if d]
    except Exception:
        logger.warning(
            "向量检索失败: novel_id=%s top_k=%s where=%s",
            novel_id,
            top_k,
            where,
            exc_info=True,
        )
        return []


def search_similar_with_meta(
    novel_id: int,
    query: str,
    top_k: int = 10,
    where: dict | None = None,
) -> list[dict]:
    """语义检索，返回 [{text, metadata, distance}]"""
    collection = _get_collection(novel_id)
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        return [
            {"text": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
            if d
        ]
    except Exception:
        logger.warning(
            "向量检索失败: novel_id=%s top_k=%s where=%s include_meta=1",
            novel_id,
            top_k,
            where,
            exc_info=True,
        )
        return []


def store_texts_batch(
    novel_id: int,
    items: list[tuple[str, str, dict]],
) -> None:
    """批量写入多段文本到向量库。items: [(doc_id, text, metadata), ...]"""
    if not items:
        return
    collection = _get_collection(novel_id)
    ids = [item[0] for item in items]
    documents = [item[1] for item in items]
    metadatas = [item[2] for item in items]
    try:
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
    except Exception:
        logger.warning(
            "向量文档批量写入失败: novel_id=%s count=%s ids=%s",
            novel_id,
            len(items),
            ids,
            exc_info=True,
        )
        raise


def delete_docs(novel_id: int, doc_ids: list[str]) -> None:
    """按 ID 列表删除向量库中的文档"""
    if not doc_ids:
        return
    collection = _get_collection(novel_id)
    try:
        collection.delete(ids=doc_ids)
    except Exception:
        logger.warning(
            "向量文档删除失败: novel_id=%s doc_ids=%s",
            novel_id,
            doc_ids,
            exc_info=True,
        )


def delete_novel_collection(novel_id: int) -> None:
    client = _get_client()
    try:
        client.delete_collection(f"novel_{novel_id}")
    except Exception:
        logger.warning(
            "向量集合删除失败: novel_id=%s",
            novel_id,
            exc_info=True,
        )


# ─── 异步包装（避免阻塞事件循环）─────────────────────────────────────────────

async def astore_text(novel_id: int, doc_id: str, text: str, metadata: dict | None = None) -> None:
    await asyncio.to_thread(store_text, novel_id, doc_id, text, metadata)


async def astore_texts_batch(novel_id: int, items: list[tuple[str, str, dict]]) -> None:
    await asyncio.to_thread(store_texts_batch, novel_id, items)


async def asearch_similar(novel_id: int, query: str, top_k: int = 3, where: dict | None = None) -> list[str]:
    return await asyncio.to_thread(search_similar, novel_id, query, top_k, where)


async def asearch_similar_with_meta(novel_id: int, query: str, top_k: int = 10, where: dict | None = None) -> list[dict]:
    return await asyncio.to_thread(search_similar_with_meta, novel_id, query, top_k, where)


async def adelete_docs(novel_id: int, doc_ids: list[str]) -> None:
    await asyncio.to_thread(delete_docs, novel_id, doc_ids)
