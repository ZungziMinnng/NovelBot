import asyncio
import logging
from pathlib import Path

import chromadb
import httpx
import openai
from chromadb.utils import embedding_functions
from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None
# 键是 (namespace, id)。加 namespace 是因为 RPG 也要用这套库，而它的 session id
# 和小说 id 是两套各自从 1 开始的编号——裸 id 当键的话，1 号存档会读到 1 号小说的
# 嵌入函数、写进 1 号小说的 collection
_novel_ef_cache: dict[tuple[str, int], chromadb.EmbeddingFunction] = {}
# 本地默认嵌入函数的惰性状态：实例 = 可用，字符串 = 不可用及原因，None = 还没探测
_default_ef_state: "chromadb.EmbeddingFunction | str | None" = None


def _local_default_ef() -> chromadb.EmbeddingFunction:
    """未配置嵌入模型时的兜底：chromadb 自带的本地小模型，仅在已下载过时可用。

    chromadb 的 DefaultEmbeddingFunction 首次调用会去 AWS S3 拉 167MB onnx 包，
    没代理的机器上必然失败，且失败发生在用户正在生成章节的时候。这里改成只用
    已存在的本地缓存，缺失就立刻抛出"请配置嵌入模型"，不联网。
    """
    global _default_ef_state
    if _default_ef_state is not None:
        if isinstance(_default_ef_state, str):
            raise ValueError(_default_ef_state)
        return _default_ef_state

    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

    onnx_dir = Path(ONNXMiniLM_L6_V2.DOWNLOAD_PATH) / ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME
    if not (onnx_dir / "model.onnx").exists():
        _default_ef_state = (
            "这本小说还没有配置嵌入模型。请在小说设置里选一个嵌入模型（模型库中"
            "标记为 embedding 的条目），否则无法建立和检索向量索引。"
        )
        raise ValueError(_default_ef_state)

    _default_ef_state = embedding_functions.DefaultEmbeddingFunction()
    return _default_ef_state


def _build_embedding_http_client(use_proxy: bool = True) -> httpx.Client:
    """同步 httpx 客户端，复用与 LLM 调用一致的 NOVELBOT 代理设置。
    use_proxy=False 时即使配了全局代理也直连（供可直连的嵌入供应商用）。"""
    mounts: dict = {}
    if use_proxy and settings.https_proxy:
        mounts["https://"] = httpx.HTTPTransport(proxy=settings.https_proxy)
    if use_proxy and settings.http_proxy:
        mounts["http://"] = httpx.HTTPTransport(proxy=settings.http_proxy)
    return httpx.Client(mounts=mounts or None, trust_env=False)


class _FastOpenAIEmbeddingFunction:
    """OpenAI 兼容嵌入函数：短超时、零重试、显式 NOVELBOT 代理且忽略 OS 环境代理。
    不复用 chromadb 的 OpenAIEmbeddingFunction —— 其默认 client 会读取 OS 环境代理
    （trust_env=True），遇到 httpx 不支持的 scheme（如 socks4）会在构造时直接崩溃；
    且默认 600s×2 重试会在嵌入端点慢/不可达时拖垮整章生成。"""

    def __init__(self, api_key: str, model_name: str, api_base: str, use_proxy: bool = True):
        self._model_name = model_name
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=settings.embedding_timeout,
            max_retries=0,
            http_client=_build_embedding_http_client(use_proxy),
        ).embeddings

    def __call__(self, input: list[str]) -> list[list[float]]:
        texts = [t.replace("\n", " ") for t in input]
        resp = self._client.create(input=texts, model=self._model_name)
        data = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in data]


# chromadb 0.5.23 按老签名调 posthog.capture(id, event, props)，posthog 7.x 只收一个位置参数，
# 于是每次建 collection / 每次检索都刷一条 ERROR。anonymized_telemetry=False 只设了 posthog.disabled，
# 新版 posthog 不认这个属性，抛错发生在检查之前，所以还得把这个 logger 静音才真正干净。
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
    return _client


def configure_embedding(
    novel_id: int,
    model_id: str,
    api_key: str = "",
    base_url: str = "",
    use_proxy: bool = True,
    namespace: str = "novel",
):
    """注册小说的嵌入函数。空 model_id 使用本地默认模型。"""
    if not model_id:
        _novel_ef_cache.pop((namespace, novel_id), None)
        return
    _novel_ef_cache[(namespace, novel_id)] = _FastOpenAIEmbeddingFunction(
        api_key=api_key,
        model_name=model_id,
        api_base=base_url or "https://api.openai.com/v1",
        use_proxy=use_proxy,
    )


async def _resolve_embedding_entry(ref: str, db):
    """把「嵌入模型」那个字段解析成 (model_id, api_key, base_url, use_proxy)。

    从 ensure_embedding_configured 里抽出来，好让 RPG 那边复用同一套解析——
    它读的是 RpgModule.embedding_model_ref，字段名不同，规则一模一样。
    """
    from app.models.model_library import ModelEntry
    from app.models.api_provider import ApiProvider
    from sqlalchemy import select

    # ref 可能是 ModelEntry.id（新方案，精确定位供应商）或旧的 model_id 字符串
    entry = None
    if ref.isdigit():
        entry = await db.get(ModelEntry, int(ref))
        if entry and entry.model_type != "embedding":
            entry = None
    if entry is None:
        result = await db.execute(
            select(ModelEntry)
            .where(
                ModelEntry.model_id == ref,
                ModelEntry.model_type == "embedding",
            )
            .order_by(ModelEntry.id)  # 同名 model_id 时取最早注册者，新增供应商不劫持已有路由
            .limit(1)
        )
        entry = result.scalar_one_or_none()
    if not entry:
        raise ValueError(f"嵌入模型未在模型库中配置或未标记为 embedding: {ref}")

    api_key = ""
    base_url = ""
    use_proxy = True
    if entry.provider_id:
        provider = await db.get(ApiProvider, entry.provider_id)
        if provider:
            api_key = provider.api_key
            base_url = provider.base_url
            use_proxy = provider.use_proxy

    if not api_key or not base_url:
        raise ValueError(f"嵌入模型缺少供应商 API Key 或 Base URL: {ref}")

    return entry.model_id, api_key, base_url, use_proxy


async def ensure_embedding_for(namespace: str, key_id: int, ref: str, db) -> None:
    """按 ref 把嵌入函数装进 (namespace, key_id) 这一格。已装过则跳过。"""
    if (namespace, key_id) in _novel_ef_cache:
        return
    if not (ref or "").strip():
        return
    model_id, api_key, base_url, use_proxy = await _resolve_embedding_entry(ref.strip(), db)
    configure_embedding(key_id, model_id, api_key, base_url, use_proxy, namespace)


async def ensure_embedding_configured(novel_id: int, db) -> None:
    """从 DB 加载小说的嵌入模型配置到缓存。已缓存则跳过。"""
    if ("novel", novel_id) in _novel_ef_cache:
        return
    from app.models.novel import Novel

    novel = await db.get(Novel, novel_id)
    if not novel or not novel.embedding_model:
        return
    await ensure_embedding_for("novel", novel_id, novel.embedding_model, db)


def _get_collection(novel_id: int, namespace: str = "novel"):
    client = _get_client()
    ef = _novel_ef_cache.get((namespace, novel_id)) or _local_default_ef()
    return client.get_or_create_collection(
        name=f"{namespace}_{novel_id}",
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


def embed_query(novel_id: int, query: str) -> list | None:
    """预计算查询向量，供同一查询的多路检索复用（避免重复调用嵌入端点）。
    失败返回 None，调用方回退到 query_texts 由 Chroma 内部嵌入。"""
    try:
        ef = _novel_ef_cache.get(("novel", novel_id)) or _local_default_ef()
    except ValueError:
        return None
    try:
        return ef([query])[0]
    except Exception:
        logger.warning("查询向量预计算失败: novel_id=%s", novel_id, exc_info=True)
        return None


def search_similar(
    novel_id: int,
    query: str,
    top_k: int = 3,
    where: dict | None = None,
    query_embedding: list | None = None,
) -> list[str]:
    """语义检索，返回相关文本列表"""
    try:
        collection = _get_collection(novel_id)
        results = collection.query(
            **(
                {"query_embeddings": [query_embedding]}
                if query_embedding is not None
                else {"query_texts": [query]}
            ),
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
    query_embedding: list | None = None,
    namespace: str = "novel",
) -> list[dict]:
    """语义检索，返回 [{text, metadata, distance}]"""
    try:
        collection = _get_collection(novel_id, namespace)
        results = collection.query(
            **(
                {"query_embeddings": [query_embedding]}
                if query_embedding is not None
                else {"query_texts": [query]}
            ),
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
    namespace: str = "novel",
) -> None:
    """批量写入多段文本到向量库。items: [(doc_id, text, metadata), ...]"""
    if not items:
        return
    collection = _get_collection(novel_id, namespace)
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


def update_metadata(novel_id: int, doc_id: str, metadata: dict) -> None:
    """仅更新已有文档的 metadata，不重新嵌入文本（回填重要性等场景）。"""
    try:
        collection = _get_collection(novel_id)
        collection.update(ids=[doc_id], metadatas=[metadata])
    except Exception:
        logger.warning(
            "向量文档标签更新失败: novel_id=%s doc_id=%s metadata=%s",
            novel_id,
            doc_id,
            metadata,
            exc_info=True,
        )


def delete_docs(novel_id: int, doc_ids: list[str], namespace: str = "novel") -> None:
    """按 ID 列表删除向量库中的文档"""
    if not doc_ids:
        return
    try:
        collection = _get_collection(novel_id, namespace)
        collection.delete(ids=doc_ids)
    except Exception:
        logger.warning(
            "向量文档删除失败: novel_id=%s doc_ids=%s",
            novel_id,
            doc_ids,
            exc_info=True,
        )


def delete_where(novel_id: int, where: dict, namespace: str = "novel") -> None:
    """按 metadata 条件删除。回溯要删的是「这条消息之后的全部」，而一条消息会
    摊成好几个 doc（原文一个、每条事实一个），id 数不出来，只能按条件删。"""
    if not where:
        return
    try:
        collection = _get_collection(novel_id, namespace)
        collection.delete(where=where)
    except Exception:
        logger.warning(
            "向量文档条件删除失败: namespace=%s id=%s where=%s",
            namespace,
            novel_id,
            where,
            exc_info=True,
        )


def get_all_docs(novel_id: int) -> dict:
    """读取整个集合的 ids/embeddings/documents/metadatas（复制小说用）。"""
    try:
        collection = _get_collection(novel_id)
        res = collection.get(include=["embeddings", "documents", "metadatas"])
        return {
            "ids": res.get("ids", []) or [],
            "embeddings": res.get("embeddings", []) or [],
            "documents": res.get("documents", []) or [],
            "metadatas": res.get("metadatas", []) or [],
        }
    except Exception:
        logger.warning("向量集合读取失败: novel_id=%s", novel_id, exc_info=True)
        return {"ids": [], "embeddings": [], "documents": [], "metadatas": []}


def add_with_embeddings(
    novel_id: int,
    ids: list[str],
    embeddings: list,
    documents: list[str],
    metadatas: list[dict],
) -> None:
    """直接写入向量（不重新嵌入），用于复制已有文档到新集合。"""
    if not ids:
        return
    collection = _get_collection(novel_id)
    try:
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
    except Exception:
        logger.warning(
            "向量直接写入失败: novel_id=%s count=%s",
            novel_id,
            len(ids),
            exc_info=True,
        )
        raise


def delete_novel_collection(novel_id: int, namespace: str = "novel") -> None:
    client = _get_client()
    try:
        client.delete_collection(f"{namespace}_{novel_id}")
    except Exception:
        logger.warning(
            "向量集合删除失败: namespace=%s novel_id=%s",
            namespace,
            novel_id,
            exc_info=True,
        )
    _novel_ef_cache.pop((namespace, novel_id), None)


# ─── 异步包装（避免阻塞事件循环）─────────────────────────────────────────────

async def astore_text(novel_id: int, doc_id: str, text: str, metadata: dict | None = None) -> None:
    await asyncio.to_thread(store_text, novel_id, doc_id, text, metadata)


async def astore_texts_batch(novel_id: int, items: list[tuple[str, str, dict]],
                             namespace: str = "novel") -> None:
    await asyncio.to_thread(store_texts_batch, novel_id, items, namespace)


async def aembed_query(novel_id: int, query: str) -> list | None:
    return await asyncio.to_thread(embed_query, novel_id, query)


async def asearch_similar(novel_id: int, query: str, top_k: int = 3, where: dict | None = None, query_embedding: list | None = None) -> list[str]:
    return await asyncio.to_thread(search_similar, novel_id, query, top_k, where, query_embedding)


async def asearch_similar_with_meta(novel_id: int, query: str, top_k: int = 10, where: dict | None = None, query_embedding: list | None = None, namespace: str = "novel") -> list[dict]:
    return await asyncio.to_thread(search_similar_with_meta, novel_id, query, top_k, where, query_embedding, namespace)


async def aupdate_metadata(novel_id: int, doc_id: str, metadata: dict) -> None:
    await asyncio.to_thread(update_metadata, novel_id, doc_id, metadata)


async def adelete_docs(novel_id: int, doc_ids: list[str], namespace: str = "novel") -> None:
    await asyncio.to_thread(delete_docs, novel_id, doc_ids, namespace)


async def adelete_where(novel_id: int, where: dict, namespace: str = "novel") -> None:
    await asyncio.to_thread(delete_where, novel_id, where, namespace)


async def aget_all_docs(novel_id: int) -> dict:
    return await asyncio.to_thread(get_all_docs, novel_id)


async def aadd_with_embeddings(
    novel_id: int,
    ids: list[str],
    embeddings: list,
    documents: list[str],
    metadatas: list[dict],
) -> None:
    await asyncio.to_thread(add_with_embeddings, novel_id, ids, embeddings, documents, metadatas)
