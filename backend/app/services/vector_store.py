import asyncio
import chromadb
from chromadb.utils import embedding_functions
from app.config import settings

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
    collection.upsert(
        ids=[doc_id],
        documents=[text],
        metadatas=[metadata or {}],
    )


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
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)


def delete_docs(novel_id: int, doc_ids: list[str]) -> None:
    """按 ID 列表删除向量库中的文档"""
    if not doc_ids:
        return
    collection = _get_collection(novel_id)
    try:
        collection.delete(ids=doc_ids)
    except Exception:
        pass


def delete_novel_collection(novel_id: int) -> None:
    client = _get_client()
    try:
        client.delete_collection(f"novel_{novel_id}")
    except Exception:
        pass


# ─── 异步包装（避免阻塞事件循环）─────────────────────────────────────────────

async def astore_text(novel_id: int, doc_id: str, text: str, metadata: dict | None = None) -> None:
    await asyncio.to_thread(store_text, novel_id, doc_id, text, metadata)


async def astore_texts_batch(novel_id: int, items: list[tuple[str, str, dict]]) -> None:
    await asyncio.to_thread(store_texts_batch, novel_id, items)


async def asearch_similar(novel_id: int, query: str, top_k: int = 3, where: dict | None = None) -> list[str]:
    return await asyncio.to_thread(search_similar, novel_id, query, top_k, where)


async def adelete_docs(novel_id: int, doc_ids: list[str]) -> None:
    await asyncio.to_thread(delete_docs, novel_id, doc_ids)
