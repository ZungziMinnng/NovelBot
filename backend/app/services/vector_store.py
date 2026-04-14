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


def delete_novel_collection(novel_id: int) -> None:
    client = _get_client()
    try:
        client.delete_collection(f"novel_{novel_id}")
    except Exception:
        pass
