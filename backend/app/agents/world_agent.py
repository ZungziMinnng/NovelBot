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

    client, model = llm_client.get_agent_client("world", novel.fast_model)
    result = await llm_client.chat_complete(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        client=client,
        temperature=0.7,
        max_tokens=800,
    )
    return result.strip()


async def embed_world_setting(novel_id: int, core_setting: str) -> None:
    """将世界观写入向量库"""
    vector_store.store_text(
        novel_id=novel_id,
        doc_id=f"world_setting_{novel_id}",
        text=core_setting,
        metadata={"type": "world_setting"},
    )
