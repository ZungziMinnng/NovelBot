"""联网搜索：调智谱 web_search 接口，给对话补充外部资料。

只服务于对话场景（新建小说的构思探讨、编辑器写作对话），不进生成链路。
搜索失败一律降级为「没搜到」，由调用方照常回答，不让对话中断。
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_provider import ApiProvider
from app.services import llm_client

_PROVIDER_NAME = "智谱"
_SEARCH_PATH = "/web_search"
_ENGINE = "search_std"
# 单条正文截断长度：智谱一条能给到 1000 字上下，全塞进 prompt 太占预算
_MAX_CONTENT = 600


@dataclass
class SearchItem:
    title: str
    content: str
    link: str
    media: str
    publish_date: str

    def source_label(self) -> str:
        """来源标注：link/media 部分内容会缺，缺了就退回标题+日期"""
        parts = [p for p in (self.media, self.publish_date) if p]
        head = "，".join(parts)
        if self.link:
            return f"{head}｜{self.link}" if head else self.link
        return head or self.title[:20]


@dataclass
class SearchOutcome:
    items: list[SearchItem]
    error: str = ""


async def search(session: AsyncSession, query: str, count: int = 5) -> SearchOutcome:
    """搜一次。任何失败都返回带 error 的空结果，调用方据此发 warning 而非中断。"""
    query = query.strip()
    if not query:
        return SearchOutcome(items=[], error="搜索词为空")

    provider = (
        await session.execute(select(ApiProvider).where(ApiProvider.name == _PROVIDER_NAME))
    ).scalars().first()
    if not provider or not provider.api_key:
        return SearchOutcome(items=[], error=f"没有配置「{_PROVIDER_NAME}」供应商或缺少 API Key，联网搜索不可用")

    url = provider.base_url.rstrip("/") + _SEARCH_PATH
    try:
        async with llm_client._build_httpx_client(provider.use_proxy) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {provider.api_key}"},
                json={"search_engine": _ENGINE, "search_query": query, "count": count},
                timeout=20,
            )
        if resp.status_code != 200:
            return SearchOutcome(items=[], error=f"搜索接口返回 {resp.status_code}")
        raw = resp.json().get("search_result") or []
    except Exception as e:
        return SearchOutcome(items=[], error=f"搜索请求失败：{type(e).__name__}")

    items = [
        SearchItem(
            title=(r.get("title") or "").strip(),
            content=(r.get("content") or "").strip()[:_MAX_CONTENT],
            link=(r.get("link") or "").strip(),
            media=(r.get("media") or "").strip(),
            publish_date=(r.get("publish_date") or "").strip(),
        )
        for r in raw
    ]
    items = [it for it in items if it.content or it.title]
    if not items:
        return SearchOutcome(items=[], error="没搜到相关内容")
    return SearchOutcome(items=items)


def format_block(query: str, items: list[SearchItem]) -> str:
    """拼成塞进 system prompt 的资料块。

    两段约束都是必需的：
    1. 搜来的是现实世界资料，不能被当成这本小说的既定设定，否则会污染后续所有生成。
    2. 必须给出今天的日期、并要求「新的覆盖旧的」。模型的训练知识比搜索结果旧，
       如果不点明这点，它会拿旧印象否掉刚搜到的新事实（例如把已确认的消息说成传闻）。
    """
    today = date.today().isoformat()
    lines = [f"=== 联网搜索结果（搜索词：{query}｜今天是 {today}）==="]
    for i, it in enumerate(items, 1):
        stamp = it.publish_date or "日期不详"
        lines.append(f"[资料{i}]（{stamp}）{it.title}")
        lines.append(f"来源：{it.source_label()}")
        lines.append(it.content)
        lines.append("")
    lines.append(
        f"以上是刚搜到的现实资料。今天是 {today}，你的训练知识比这些资料旧，"
        "凡是和现实时间线有关的判断都以资料为准，不要用印象纠正它们：\n"
        "- 每条都标了发布日期。同一件事新旧资料说法不一致时，以最新的为准，"
        "别把已经落定的事说成「还只是传闻」「预计将会」。\n"
        "- 只有在日期相近、说法确实对立时才指出分歧；旧闻被新闻推翻不算分歧。\n"
        "- 引用时说明来源和日期，不要含糊地说「据说」「有资料显示」。\n"
        "- 这些是现实世界的信息，不是这本小说的设定。除非作者明确要采纳，"
        "不要把它们当成书里已经成立的事实。\n"
        "- 资料没覆盖到作者问的东西时，直接说没搜到，不要用资料硬凑，"
        "也不要拿训练知识冒充搜索结果。"
    )
    return "\n".join(lines)
