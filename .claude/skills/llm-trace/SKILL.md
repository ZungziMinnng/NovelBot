---
name: llm-trace
description: 梳理 NovelBot 一次 LLM 调用的 messages 组装顺序与各段字数。当用户问"这次生成发了什么给模型"、"messages 怎么拼的"、"system/few-shot/参考资料/指令的顺序和字数"、"为什么某段没进 prompt"时使用。默认只分析、不改代码。
---

# LLM 调用链路追踪

目标：把"发给模型的到底是什么、按什么顺序、各段多少字"讲清楚，定位某段内容是否缺失或被放错位置。

## writer（章节生成）messages 组装顺序

见 `backend/app/agents/writer.py` 的 `stream_chapter()`：

1. `system`：模板 `writer.jinja2`（或自定义 writer_system_prompt + 文章风格）
2. **few-shot 示例轮**：`_build_example_turns(writer_examples)`，插在 `messages[1:1]`（system 之后、参考资料之前），user/assistant 成对
3. `user`：参考资料 = context_block + chars_block + 上章结尾（recent_text）
4. `assistant`："已了解上述背景资料、角色设定和近期剧情，准备按要求创作。"
5. `user`：directive = 写作方向(instruction) + task_instruction（字数约束）
6. 若有 `issues_feedback`（critic 改稿）：追加 assistant 占位 + user 修订指令

**分支差异**：
- `api_format == "gemini"`：参考资料和 directive 合并成单条 user
- DeepSeek：system 折叠进末条 user（`=== 写作要求（严格遵守）===`）；关 thinking 时 max_tokens 按字数硬压

## 各段字数来源

writer.py 里 `payload_diagnostics` 已经算好每段字符数和 `message_roles` / `message_chars`，并通过 `yield {"llm_payload": ...}` 发给前端 DevPanel。复用它的字段，不要自己重新数。

## context 是怎么来的

ctx 由 `backend/app/services/context_builder.py` 的 `build_generation_context()` 装配，`format_context_for_writer()` 拼成 context_block / chars_block / task_instruction。要追"某段为什么没进去"，回到这两个函数看对应分支是否被跳过（空值、RAG 未命中、POV 隔离等）。

## 其它调用方

- 摘要/状态更新：`backend/app/services/summarizer.py`，统一走 `_build_analysis_messages()`（单条 user，正文放 user 不放 assistant）
- 改写（手动注释）：`writer.py` 的 `stream_chapter_rewrite()`，原文带段落编号整段传入
- critic：`backend/app/agents/critic.py` + `critic.jinja2`

## 纪律

默认只读代码 + 解释，**不实际发起 LLM 调用、不碰真实章节数据**。需要真实 payload 时，引导用户在 DevPanel 看 `llm_request` 事件。
