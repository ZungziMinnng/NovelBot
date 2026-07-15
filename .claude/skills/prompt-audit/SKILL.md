---
name: prompt-audit
description: 审查 NovelBot 的上下文记忆与提示词遵守度。当用户要求"审查/检查 prompt"、"上下文记忆有没有漏"、"提示词遵守度"、"为什么模型不听指令/字数不对/状态没更新"时使用。产出固定格式的发现报告，默认只审查不改代码。
---

# 上下文记忆与提示词遵守度审查

目标只有两个，所有发现都归到这两类：
1. **上下文的记忆与遵守**（信息有没有正确进入记忆库、有没有正确喂回给写手）
2. **提示词遵守度**（system / 指令 / 字数 / 角色名等约束是否真的生效）

## 审查路径（按顺序读这些文件）

1. `backend/app/services/context_builder.py`
   - `build_generation_context()`：装配 ctx（outline、rolling_summary、prev_chapter、core_setting RAG、core_rules 常驻、6 路并行 RAG、arc_summary、book_summary、worldview_changes、POV hidden_facts 隔离）
   - `format_context_for_writer()`：拼各个 `=== xxx ===` 块 + task_instruction（字数约束 90%~115%）
2. `backend/app/agents/writer.py`
   - `stream_chapter()` 的 messages 组装顺序：system → few-shot → user(参考资料) → assistant("已了解…") → user(directive) → 修订轮
   - DeepSeek 把 system 折叠进末条 user；DeepSeek 关 thinking 时 max_tokens 硬压
   - `payload_diagnostics` 各段字数
3. `backend/app/services/summarizer.py`
   - `summarize_chapter` / `update_character_states` / `update_entity_location_states`：正文截断上限、JSON 解析失败的静默跳过、状态"只增不减"合并语义、`get_rolling_summary` 窗口大小
4. `backend/app/agents/orchestrator.py`
   - critic 自动改稿 `while` 循环：是否把上一版草稿真正回传给写手
5. `backend/app/prompts/templates/*.jinja2` 与 `backend/app/agents/critic.py`

## 已知反复出现的问题类型（重点排查）

- **截断丢尾**：正文 `[:N]` 截断导致章末信息不进记忆（摘要+三个状态更新四处）
- **改稿盲写**：critic 改稿循环只回传 issues_feedback，写手看不到自己上一版草稿（writer.py 用占位符 `"[上一版本内容]"`）
- **死代码 prompt**：模块级 prompt 常量与真实 jinja2 模板分叉，改了不生效（搜 `_PROMPT_PREFIX` / `_PROMPT_SUFFIX` 等未被引用的常量）
- **字数约束**：非 DeepSeek 路径只有 prompt 文字约束、无 max_tokens 硬上限
- **多重"严格遵守"标题相互稀释**

## 产出格式

按两个目标分类，每条标严重度（🔴高 / 🟡中 / 🟢低），给 `文件:行号` 引用，给出"现象 → 原因 → 建议"。最后给优先级建议。

## 纪律

- 默认**只审查、不改代码**，除非用户明确要求落地。
- **严禁对真实章节数据跑生成/覆写做诊断**（曾覆写丢失用户原文）。
- 推荐 memory 里的具体函数/字段前，先 grep 确认它当前仍存在（代码会变）。
