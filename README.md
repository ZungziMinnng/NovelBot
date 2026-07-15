# NovelBot

AI 驱动的中文长篇小说创作工具，基于多 Agent 协作架构，支持流式生成、记忆管理和世界观维护。

---

## 目录

- [功能概述](#功能概述)
- [技术栈](#技术栈)
- [快速启动](#快速启动)
- [目录结构](#目录结构)
- [核心架构](#核心架构)
- [Prompt 模板位置与修改指南](#prompt-模板位置与修改指南)
- [审查机制（Critic）说明](#审查机制critic说明)
- [配置参考](#配置参考)
- [常见问题](#常见问题)

---

## 功能概述

| 功能 | 说明 |
|------|------|
| 多 Agent 写作流水线 | Writer → Critic → 细节审查 → Memory 多阶段协作 |
| 流式 SSE 输出 | 章节内容实时流式显示，Token 逐字渲染 |
| 分级记忆管理 | 章节摘要 → 故事弧概要 → 全书概要三级压缩 + ChromaDB RAG + 状态卡 + 结构化事实层（详见 [docs/memory.md](docs/memory.md)） |
| 多维世界观 | 角色 / 道具 / 系统 / 地点 / 势力 / 功法 / 设定笔记 分类管理，AI 扩写结构化设定 |
| 角色卡自动生成 | 根据角色描述生成完整角色设定，支持角色经历、文生图提示词 |
| 章节大纲规划 | 全书 / 分卷 / 单章多级大纲自动生成 |
| 三级质量审查 | Critic 单章审查 + 剧情细节审查（近 N 章）+ 全文审查（按间隔触发） |
| 多供应商 / 多格式接入 | OpenAI 兼容 / Gemini 原生 / Anthropic 原生，DB 管理多个供应商与模型库 |
| 全局 + 逐 Agent 模型配置 | 每个 Agent 可单独指定模型，含独立嵌入模型 |
| 深色/亮色主题 | 默认深色，可随时切换 |
| 小说设置抽屉 | 自定义 Writer 提示词、上下文区块开关、生成参数等 |
| Token 用量追踪 | 每次生成显示各 Agent ↑输入 ↓输出 Token |

---

## 技术栈

| 层 | 技术 |
|----|------|
| **后端框架** | FastAPI + Uvicorn |
| **数据库** | SQLite（aiosqlite 异步驱动）+ SQLAlchemy 2.0 |
| **向量检索** | ChromaDB（本地持久化，按小说分集合） |
| **LLM 接入** | 多供应商 / 多格式：OpenAI 兼容、Gemini 原生、Anthropic 原生（供应商与模型库存于 DB，`.env` 仅作首次迁移源） |
| **Prompt 模板** | Jinja2 |
| **前端框架** | React 18 + TypeScript + Vite |
| **UI 组件** | TailwindCSS + shadcn/ui（CSS 变量主题） |
| **状态管理** | Zustand（持久化到 localStorage） |
| **数据请求** | Axios + TanStack Query |
| **流式通信** | Server-Sent Events（SSE） |

---

## 快速启动

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd NovelBot
```

### 2. 启动后端

```bash
cd backend

# 安装依赖（使用清华镜像）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制并编辑配置
cp .env.example .env
# 在 .env 中填入至少一种 API Key（OPENAI_API_KEY / GEMINI_API_KEY / ANTHROPIC_API_KEY）
# 及默认模型名。也可启动后在 UI「设置」页管理供应商与模型库。

# 启动
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install --registry https://registry.npmmirror.com
npm run dev
```

### 4. 访问

浏览器打开 `http://localhost:5173`，在**设置**页面填入 API Key 和模型名，点击**保存配置**验证连接后即可使用。

---

## 目录结构

```
NovelBot/
├── backend/
│   ├── .env                        # 运行配置（API Key、模型名等）
│   ├── .env.example                # 配置模板
│   ├── requirements.txt
│   ├── data/                       # 运行时数据（自动生成，勿提交）
│   │   ├── novelbot.db             # SQLite 数据库
│   │   └── chroma/                 # ChromaDB 向量索引
│   └── app/
│       ├── main.py                 # FastAPI 入口，路由注册，CORS
│       ├── config.py               # 全局配置（pydantic-settings 读取 .env）
│       ├── database.py             # SQLAlchemy 引擎 + DDL 迁移
│       │
│       ├── models/                 # SQLAlchemy ORM 模型
│       │   ├── novel.py            # 小说表（含模型配置、上下文开关、生成参数）
│       │   ├── chapter.py          # 章节表
│       │   ├── character.py        # 角色表
│       │   ├── world_entity.py     # 世界实体（道具/系统）
│       │   ├── location.py         # 地点表
│       │   ├── faction.py          # 势力表
│       │   ├── technique.py        # 功法/武技表
│       │   ├── novel_note.py       # 补充设定笔记
│       │   ├── volume.py           # 分卷表
│       │   ├── memory.py           # 记忆表（摘要/快照）+ 大纲表
│       │   ├── memory_item.py      # 结构化事实表（状态机）
│       │   ├── api_provider.py     # API 供应商表
│       │   ├── model_library.py    # 模型库表
│       │   └── writer_preset.py    # Writer 预设表
│       │
│       ├── schemas/                # Pydantic 请求/响应模型（与各 model 对应）
│       │
│       ├── api/routes/             # API 路由
│       │   ├── novels.py           # 小说 CRUD + 向导接口
│       │   ├── chapters.py         # 章节 CRUD + 确认接口
│       │   ├── generation.py       # SSE 流式生成接口
│       │   ├── characters.py / world_entities.py / locations.py
│       │   ├── factions.py / techniques.py / volumes.py / outlines.py
│       │   ├── memory_items.py / novel_notes.py
│       │   ├── api_providers.py / model_library.py    # 供应商与模型库管理
│       │   ├── writer_presets.py / prompts.py / chat.py
│       │   ├── app_settings.py     # 全局配置读写接口
│       │   └── admin.py            # 管理接口
│       │
│       ├── agents/                 # Agent 实现
│       │   ├── orchestrator.py     # 主调度器（状态机 + SSE 输出）
│       │   ├── writer.py           # Writer Agent（流式生成 + 批注重写）
│       │   ├── critic.py           # Critic Agent（单章质量审查）
│       │   ├── review_agent.py     # 剧情细节审查 + 全文审查
│       │   ├── outline_agent.py    # Outline Agent（多级大纲）
│       │   ├── character_agent.py  # 角色卡 + 新实体发现
│       │   ├── world_agent.py      # World Agent（扩写世界观）
│       │   └── build_agent.py      # 构建模式（批量生成设定）
│       │
│       ├── services/
│       │   ├── llm_client.py       # 多格式 LLM 封装（供应商缓存 + Agent 模型路由）
│       │   ├── vector_store.py     # ChromaDB 封装（按小说分集合 + 嵌入配置）
│       │   ├── summarizer.py       # 章节/弧/全书摘要 + 角色/实体/地点状态更新
│       │   ├── memory_item_writer.py  # 结构化事实写入与状态机
│       │   ├── relevance_selector.py  # 名称匹配→RAG→全量 选择策略
│       │   ├── entity_embeddings.py   # 实体向量化
│       │   └── context_builder.py  # 生成上下文组装（多层记忆）
│       │
│       └── prompts/
│           ├── loader.py           # Jinja2 模板加载器
│           └── templates/          # ★ Prompt 模板目录（重点，见下文）
│
├── docs/
│   └── memory.md                   # ★ 记忆体系架构详解
│
└── frontend/
    ├── src/
    │   ├── main.tsx                # React 入口
    │   ├── App.tsx                 # 路由 + 主题 class 切换
    │   ├── index.css               # CSS 变量（亮色/深色 token）
    │   │
    │   ├── api/
    │   │   └── client.ts           # Axios 客户端 + SSE 消费 + 类型定义
    │   │
    │   ├── store/
    │   │   ├── novelStore.ts       # 小说列表状态
    │   │   └── settingsStore.ts    # 主题 + 模型缓存
    │   │
    │   ├── pages/
    │   │   ├── Home/
    │   │   │   ├── Home.tsx            # 小说列表页
    │   │   │   └── NovelWizard.tsx     # 4 步创建向导（含跳过选项）
    │   │   ├── Editor/
    │   │   │   └── Editor.tsx          # 主编辑器（SSE + Agent 日志）
    │   │   ├── Characters/
    │   │   │   └── Characters.tsx      # 角色管理页
    │   │   ├── Outline/
    │   │   │   └── Outline.tsx         # 大纲查看页
    │   │   └── Settings/
    │   │       └── Settings.tsx        # 全局配置页
    │   │
    │   └── components/
    │       ├── AgentStatus/
    │       │   └── AgentStatus.tsx     # 生成阶段状态指示器
    │       ├── AgentLog/
    │       │   └── AgentLog.tsx        # Agent 调用日志 + Token 统计
    │       ├── ContextPanel/
    │       │   └── ContextPanel.tsx    # 上下文状态面板（右侧）
    │       └── NovelSettingsDrawer/
    │           └── NovelSettingsDrawer.tsx  # 小说设置抽屉
    │
    ├── package.json
    └── vite.config.ts              # 开发代理：/api → http://localhost:8000
```

---

## 核心架构

### 生成流水线（每次点击「生成章节」）

```
用户点击生成
     │
     ▼
[Orchestrator]
  1. 状态预清理 + 快照回滚（若为重新生成，从 state_snapshot 恢复角色/实体/地点状态）
     │
  2. 构建上下文（多层记忆，详见 docs/memory.md）
     ├── 世界观设定（RAG 检索）
     ├── 角色/道具/系统/地点/势力/功法/笔记（名称匹配→RAG→全量）
     ├── 本章大纲（Outline 表）
     ├── 近期滚动摘要 + 故事弧概要 + 全书概要
     ├── RAG 检索相关历史场景（ChromaDB）
     └── 上一章原文（即时上下文）
     │
  3. [Writer Agent] 流式生成章节正文 → SSE token 事件推送到前端
     │
  4. [Critic Agent]（可选）审查内容质量
     ├── PASS → 继续
     └── FAIL → 回到 Writer 修改（最多 MAX_CRITIC_RETRIES 次）
     │
  5. [剧情细节审查]（可选）对照近 N 章检查矛盾，不通过则触发修订
     │
  6. 保存章节（draft 状态）+ 保存 state_snapshot
     │
  7. [Memory] 分步更新并各自 commit：
     ├── 章节摘要 → memories 表 + ChromaDB
     ├── 角色 / 实体 / 地点状态卡更新
     ├── 结构化事实（memory_items）
     ├── 每 15 章刷新故事弧概要、每 5 章刷新全书概要
     └── 发现新角色/实体/地点/功法 → 推送候选给前端
     │
  8. 全文审查（可选，按 REVIEW_INTERVAL 间隔触发）
     │
  SSE done 事件 → 前端刷新章节列表
```

### 分级记忆体系

记忆体系是 NovelBot 最核心的子系统，采用**分级压缩 + 按需检索**，让 AI 在百章级别仍保持连贯。完整说明见 **[docs/memory.md](docs/memory.md)**，要点：

| 层级 | 存储位置 | 内容 |
|------|---------|------|
| 全书概要 | novels.book_summary | 全书 ~500 字，每 5 章刷新 |
| 故事弧概要 | memories(arc_summary) | 每 15 章一段 ~500 字 |
| 章节摘要 | memories(chapter_summary) + ChromaDB | 每章 ~250 字 |
| 状态卡 | characters/world_entities/locations.current_state | 角色/实体/地点动态状态 JSON |
| 结构化事实 | memory_items | 带状态机的事实变更日志 |
| RAG 检索 | ChromaDB | 语义相关历史片段 |
| 即时上下文 | 动态查询 | 上一章原文 |

各类设定的检索遵循统一策略：**名称匹配优先 → RAG 向量兜底 → 全量回退**，每类 top_k 可在小说设置中单独配置。

---

## Prompt 模板位置与修改指南

所有 Prompt 模板位于 `backend/app/prompts/templates/`，使用 **Jinja2** 语法，`{{ 变量名 }}` 为模板变量。

### `writer.jinja2` — Writer Agent 系统提示词

**作用**：Writer Agent 的 System Prompt，控制写作风格和基本规则。

**可用变量**：
- `{{ genre }}` — 小说类型（如"玄幻"）
- `{{ writing_style }}` — 写作风格（如"严肃厚重"）
- `{{ target_words }}` — 目标字数

**修改建议**：
- 调整行文规则（视角、语言风格、禁用词汇）
- 添加特定场景写法要求（如动作场景处理方式）
- 修改字数控制指令

**⚠️ 注意**：若只需针对某本小说调整，请使用编辑器页面的**「设置」→「自定义 Writer 提示词」**，无需改动模板文件。

---

### `critic.jinja2` — Critic Agent 审查提示词

**作用**：Critic Agent 的完整 Prompt（User 消息），判断章节是否通过审查。

**可用变量**：
- `{{ character_summary }}` — 角色状态摘要字符串
- `{{ chapter_outline }}` — 本章大纲目标
- `{{ rolling_summary }}` — 近期章节摘要
- `{{ chapter_content }}` — 待审章节正文（截取前 3000 字）

**审查逻辑**：
- 输出 `PASS`（大小写不敏感前缀）→ 通过，直接保存
- 输出问题列表 → 不通过，将问题反馈给 Writer 重新修改

**修改建议**：
- 增减审查维度（如增加"对话是否符合人物身份"）
- 调整审查严格度（减少审查项 → 更少修改 → 更省 Token）
- 如果审查过于严格导致反复修改，可以删减检查项 1-4

---

### `outline.jinja2` — Outline Agent 大纲生成提示词

**作用**：Outline Agent 生成全书章节大纲。

**可用变量**：
- `{{ title }}` — 小说标题
- `{{ genre }}` — 类型
- `{{ target_length }}` — 目标长度（短篇/中篇/长篇）
- `{{ writing_style }}` — 写作风格
- `{{ premise }}` — 故事前提
- `{{ core_setting }}` — 世界观摘要（前 500 字）
- `{{ characters_summary }}` — 角色列表
- `{{ chapter_count }}` — 目标章节数

---

### `character.jinja2` — Character Agent 角色卡生成提示词

**作用**：根据角色基本信息生成完整角色卡（JSON 格式）。

**可用变量**：
- `{{ name }}` — 角色姓名
- `{{ role }}` — 角色定位（主角/配角/反派等）
- `{{ age }}` — 年龄
- `{{ description }}` — 一句话描述
- `{{ core_setting }}` — 世界观摘要
- `{{ premise }}` — 故事前提

**角色卡 JSON 结构**（由 LLM 输出）：
```json
{
  "personality": "性格描述",
  "background": "背景故事",
  "motivation": "核心动机",
  "skills": ["技能列表"],
  "relationships": {},
  "appearance": "外貌描述"
}
```

---

### `initializer.jinja2` — World Agent 世界观扩写提示词

**作用**：将用户输入的简短世界观描述扩写为结构化设定文档。

**可用变量**：
- `{{ raw_setting }}` — 用户输入的时代背景
- `{{ raw_rules }}` — 用户输入的核心规则
- `{{ premise }}` — 故事前提
- `{{ genre }}` — 类型

---

### 动态修改 Writer 提示词（无需改文件）

在编辑器右上角点击**「设置」**，打开小说设置抽屉，找到**「自定义 Writer 提示词」**输入框。

此处的内容会追加到 `writer.jinja2` 模板末尾，**优先级最高**，适合为单本小说定制写作规则，例如：

```
叙述视角：严格第一人称，使用"我"而非"他/她"
对话风格：古文风格，主角使用文言文
禁止词：不得出现现代词汇如"手机"、"汽车"
特别要求：每章结尾留一个悬念钩子
```

---

### 摘要与状态更新的 Prompt（已外置为模板文件）

章节摘要、角色/实体/地点状态更新的 Prompt 已从代码内联迁移到 `templates/` 下的模板文件，可直接编辑：

- `chapter_summary_prefix.jinja2` / `chapter_summary_suffix.jinja2` — 章节摘要的长度、时间线标注规范
- `character_update_prefix.jinja2` / `character_update_suffix.jinja2` — 角色状态更新关注的维度与输出 JSON 结构
- `entity_location_update_*` — 实体与地点状态更新（单次调用二合一）
- `arc_summary.jinja2` / `book_summary.jinja2` / `book_summary_merge.jinja2` — 故事弧/全书概要

记忆体系的完整说明见 **[docs/memory.md](docs/memory.md)**。

---

## 审查机制说明

NovelBot 有三道可独立开关的审查，由弱到强：

### 1. Critic 单章审查（默认开启）

每次 Writer 生成后自动审查当前章节：

1. **输入**：角色状态摘要 + 设定库摘要 + 本章大纲 + 近期剧情摘要 + 生成正文（前 3000 字）
2. **判断**：LLM 输出 `PASS`（大小写不敏感前缀）或具体问题列表
3. **处理**：`PASS` → 继续；有问题 → 反馈给 Writer 修改
4. **限制**：最多重写 `MAX_CRITIC_RETRIES` 次（默认 1）

模板：`backend/app/prompts/templates/critic.jinja2`。

### 2. 剧情细节审查（默认关闭）

由 `review_agent.review_generated_with_recent_chapters` 实现，把新生成正文对照**近 20 章**（`DETAIL_REVIEW_WINDOW`）检查情节矛盾、角色不一致等问题，不通过则把问题作为修订反馈触发重写。在小说设置中通过 `enable_detail_review` 开启。

### 3. 全文审查（默认关闭）

由 `review_agent.run_fulltext_review` 实现，分批（`BATCH_SIZE=20`）扫描全书，检测六类全局问题：情节矛盾、角色不一致、遗忘伏笔、时间线错误、设定违背、其他。按 `REVIEW_INTERVAL` 间隔自动触发（如每 10 章一次），结果以 `review_result` 事件推给前端。在 `.env` 中通过 `ENABLE_REVIEW` / `REVIEW_INTERVAL` 控制。

### 调整审查严格度

- **关闭 Critic**：在小说设置中关闭 `enable_critic`（无需改代码）。
- **减少审查维度**：编辑 `critic.jinja2` 删减审查条目，降低触发修改的概率。
- **调整重试次数**：在 `backend/.env` 设置 `MAX_CRITIC_RETRIES`：

```env
MAX_CRITIC_RETRIES=0   # 0 = 不重写，即使发现问题也直接保存
MAX_CRITIC_RETRIES=1   # 1 = 默认，最多重写一次（共写 2 次）
MAX_CRITIC_RETRIES=2   # 2 = 最多重写两次（共写 3 次）
```

---

## 配置参考

所有配置项在 `backend/.env` 文件中（也可在 UI 设置页修改，会自动同步写入 `.env`）。供应商与模型库主要由 DB 管理，`.env` 仅提供首次启动的迁移源与默认值：

```env
# ── API 接入（按格式分别配置，至少填一种）──────────────────────────
# OpenAI 兼容（OpenAI / DeepSeek / AiHubMix 等中转）
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://api.openai.com/v1
# Gemini 原生
GEMINI_API_KEY=
GEMINI_BASE_URL=https://generativelanguage.googleapis.com
# Anthropic 原生
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=https://api.anthropic.com

# ── 默认模型（未单独配置的 Agent 回退到此）──────────────────────────
DEFAULT_WRITER_MODEL=gpt-4o        # 高质量生成
DEFAULT_FAST_MODEL=gpt-4o-mini     # 摘要/审查/规划

# ── 各 Agent 独立模型（留空则使用上方默认）────────────────────────────
AGENT_WRITER_MODEL=
AGENT_CRITIC_MODEL=
AGENT_MEMORY_MODEL=
AGENT_OUTLINE_MODEL=
AGENT_CHARACTER_MODEL=
AGENT_ORCHESTRATOR_MODEL=
AGENT_REVIEW_MODEL=

# ── 网络代理（开启 VPN 时填写，用 NOVELBOT_ 前缀避免与系统变量冲突）──
NOVELBOT_HTTPS_PROXY=
NOVELBOT_HTTP_PROXY=

# ── 生成参数 / 审查 ───────────────────────────────────────────────
MAX_CRITIC_RETRIES=1   # Writer 最多执行次数 = MAX_CRITIC_RETRIES + 1
ENABLE_REVIEW=false    # 是否启用全文审查
REVIEW_INTERVAL=10     # 全文审查触发间隔（章）
```

> 兼容性：旧的 `AIHUBMIX_API_KEY` / `AIHUBMIX_BASE_URL` 仍会被 `app/config.py` 自动迁移到对应字段，但新部署建议直接用上面的 `OPENAI_*` / `GEMINI_*` / `ANTHROPIC_*`。

### 模型推荐

| 用途 | 推荐模型 | 说明 |
|------|---------|------|
| Writer（高质量） | `gemini-2.5-pro` 等长文本强模型 | 中文写作质量优先 |
| Writer（均衡） | `gemini-2.0-flash` / `gpt-4o` | 速度与质量兼顾 |
| Fast（便宜） | `gemini-2.0-flash` / `gpt-4o-mini` | 摘要/审查/状态更新 |
| Embedding | 任一 embedding 模型 | 在模型库中标记 `model_type=embedding` 后按小说配置 |

---

## 常见问题

### Q: 保存设置后需要重启后端吗？
**A**: 不需要。设置页的「保存配置」会立即更新内存中的值，同时写入 `.env` 文件确保重启后生效。

### Q: 生成时出现 401 / API Key 无效？
**A**: 前往设置页检查供应商的 API Key 与 Base URL，并确认模型名为该供应商支持的完整名称。模型库中的每个模型需关联到正确的供应商。

### Q: 如何关闭 Critic 审查节省 Token？
**A**: 将 `MAX_CRITIC_RETRIES=0` 设置后，即使 Critic 发现问题也不会触发重写。或参考[调整审查严格度](#调整审查严格度)章节。

### Q: 角色/世界观对生成没有影响？
**A**: 需要先通过「向导」完成世界观扩写和角色卡生成，才能有效注入上下文。如跳过了向导，可在编辑器右上角「设置」中手动填写世界观。

### Q: ChromaDB 报 `Number of requested results > elements in index` 警告？
**A**: 这是正常日志，表示向量库中的文档数量少于查询数量（例如刚开始创作时）。不影响功能，系统会自动调整返回数量。

### Q: 日志出现 `AsyncHttpxClientWrapper has no attribute '_transport'`？
**A**: 已通过单例客户端修复（`llm_client.py`）。若仍出现，是 openai SDK 与 httpx 版本的已知兼容问题，不影响生成功能。
