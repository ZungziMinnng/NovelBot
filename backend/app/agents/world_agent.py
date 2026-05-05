"""World Agent: 世界观扩写"""
from app.models.novel import Novel
from app.services import llm_client, vector_store
from app.prompts.loader import render


async def expand_world_setting(
    novel: Novel,
    raw_setting: str,
    raw_rules: str = "",
) -> str:
    """将用户输入的世界观简述扩写为结构化设定文档"""
    prompt = render(
        "initializer.jinja2",
        raw_setting=raw_setting,
        raw_rules=raw_rules,
        premise=novel.premise,
        genre=novel.genre,
    )

    model, api_format = llm_client.get_agent_client("world", novel.fast_model)
    result = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=800,
    )
    return result.strip()


async def optimize_world_setting(novel: Novel, core_setting: str) -> str:
    """用 fast 模型优化世界观设定，core_setting 为当前文本（可能未保存到 DB）"""
    prompt = render(
        "world_optimizer.jinja2",
        core_setting=core_setting,
        premise=novel.premise,
        genre=novel.genre,
    )
    model, api_format = llm_client.get_agent_client("world", novel.fast_model)
    result = await llm_client.dispatch_chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        api_format=api_format,
        temperature=0.7,
        max_tokens=1000,
    )
    return result.strip()


async def embed_world_setting(novel_id: int, core_setting: str) -> None:
    """将世界观分块写入向量库，支持按需 RAG 检索"""
    # 清理旧向量（旧的单条 + 分块）
    old_ids = [f"world_setting_{novel_id}"]
    old_ids.extend(f"world_setting_{novel_id}_chunk_{i}" for i in range(50))
    await vector_store.adelete_docs(novel_id, old_ids)

    if not core_setting.strip():
        return

    # 按双换行分段，合并过短的段落
    raw_chunks = [p.strip() for p in core_setting.split("\n\n") if p.strip()]
    chunks: list[str] = []
    for chunk in raw_chunks:
        if chunks and len(chunks[-1]) < 30:
            chunks[-1] += "\n\n" + chunk
        else:
            chunks.append(chunk)

    items = [
        (f"world_setting_{novel_id}_chunk_{i}", text, {"type": "world_setting", "chunk_index": i})
        for i, text in enumerate(chunks)
    ]
    await vector_store.astore_texts_batch(novel_id, items)
