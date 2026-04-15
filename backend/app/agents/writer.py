"""Writer Agent: 负责生成章节正文，支持流式输出"""
from typing import AsyncIterator, Union
from app.services import llm_client
from app.services.context_builder import format_context_for_writer
from app.prompts.loader import render


async def stream_chapter(
    ctx: dict,
    instruction: str,
    target_words: int,
    writer_model: str = "",
    issues_feedback: str = "",
    writer_system_prompt: str = "",
    temperature: float = 0.85,
    max_tokens: int = 4096,
) -> AsyncIterator[Union[str, tuple[int, int]]]:
    """
    流式生成章节内容。
    yield str  → token
    yield (int, int) → (input_tokens, output_tokens) 最后一条
    """
    base_system = render(
        "writer.jinja2",
        genre=ctx.get("genre", ""),
        writing_style=ctx.get("writing_style", ""),
        target_words=target_words,
    )
    custom = writer_system_prompt.strip()
    # 有自定义提示词时完整替换，不填才使用默认模板
    system_content = custom if custom else base_system

    user_content = format_context_for_writer(ctx, instruction, target_words)

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]

    if issues_feedback:
        messages.append({
            "role": "assistant",
            "content": "[上一版本内容]"
        })
        messages.append({
            "role": "user",
            "content": (
                f"审稿编辑发现以下问题，请修正后重新创作：\n{issues_feedback}\n\n"
                f"⚠️ 以下用户原始要求必须严格遵守（尤其是角色姓名不得更改）：\n{instruction}\n\n"
                "请重新输出完整章节正文。"
            )
        })

    model, api_format = llm_client.get_agent_client("writer", writer_model)
    async for item in llm_client.dispatch_chat_stream_with_usage(
        messages=messages,
        model=model,
        api_format=api_format,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        yield item
