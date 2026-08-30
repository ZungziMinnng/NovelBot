"""规则广场解析：把本书启用的规则拼成可直接进 Writer system prompt 的文本。

设计要点：任何异常或"疑似配置缺失"都回退到 writer_guardrails.jinja2。
去 AI 味护栏静默消失是这里最坏的结果——用户不会立刻发现，只会觉得模型忽然变差。
"""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.novel import Novel
from app.models.prompt_rule import PromptRule
from app.prompts.loader import render

logger = logging.getLogger(__name__)

_FALLBACK_TEMPLATE = "writer_guardrails.jinja2"


def _fallback() -> str:
    return render(_FALLBACK_TEMPLATE).strip()


async def resolve_rules_block(session: AsyncSession, novel: Novel) -> str:
    """解析本书启用的规则。

    三态语义（不可互相塌陷）：
      None → 从未配置（老书/新书），走内置默认
      []   → 用户显式全关，尊重，返回空
      [id] → 显式勾选，与 enabled 求交
    """
    try:
        # 不写 `or []`：那会把 None 塌成 []，正是要防的静默退化
        selection = novel.enabled_rule_ids

        rules = (await session.execute(
            select(PromptRule)
            .where(PromptRule.user_id == novel.user_id, PromptRule.enabled.is_(True))
            .order_by(PromptRule.sort_order, PromptRule.id)
        )).scalars().all()

        if selection is None:
            chosen = [r for r in rules if r.is_builtin]
        else:
            wanted = {int(i) for i in selection}
            # 顺序取库里的 sort_order，勾选数组只当集合用
            chosen = [r for r in rules if r.id in wanted]

        block = "\n\n".join(r.content.strip() for r in chosen if r.content.strip())
        if block:
            return block

        # 空结果且用户从未配置 → 说明种子没跑/跑失败/表是空的，兜底
        if selection is None:
            logger.warning(
                "小说 %s 未配置规则且无可用内置规则，回退到 %s", novel.id, _FALLBACK_TEMPLATE
            )
            return _fallback()

        # selection 是 [] 或勾选项全被停用/删除：那是用户的选择，尊重
        return ""
    except Exception:
        logger.exception("规则解析失败，回退到 %s", _FALLBACK_TEMPLATE)
        return _fallback()


