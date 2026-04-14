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
| 多 Agent 写作流水线 | Writer → Critic → Memory 三阶段协作 |
| 流式 SSE 输出 | 章节内容实时流式显示，Token 逐字渲染 |
| 分级记忆管理 | 章节摘要 + ChromaDB RAG + 角色状态卡 |
| 世界观扩写 | 输入简述，AI 生成结构化设定文档 |
| 角色卡自动生成 | 根据角色描述生成完整角色设定 |
| 章节大纲规划 | 全书章节大纲自动生成 |
| 深色/亮色主题 | 默认深色，可随时切换 |
| 全局 + 逐 Agent 模型配置 | 每个 Agent 可单独指定模型 |
| 小说设置抽屉 | 自定义 Writer 系统提示词、类型、风格等 |
| Token 用量追踪 | 每次生成显示各 Agent ↑输入 ↓输出 Token |

---

## 技术栈

| 层 | 技术 |
|----|------|
| **后端框架** | FastAPI + Uvicorn |
| **数据库** | SQLite（aiosqlite 异步驱动）+ SQLAlchemy 2.0 |
| **向量检索** | ChromaDB（本地持久化） |
| **LLM 接入** | AiHubMix（OpenAI 兼容 API，`base_url=https://aihubmix.com/v1`） |
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
# 在 .env 中填入 AIHUBMIX_API_KEY 和模型名

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
│       │   ├── novel.py            # 小说表（含 writer_system_prompt）
│       │   ├── chapter.py          # 章节表
│       │   ├── character.py        # 角色表
│       │   └── memory.py           # 记忆表 + 大纲表
│       │
│       ├── schemas/                # Pydantic 请求/响应模型
│       │   ├── novel.py
│       │   ├── chapter.py
│       │   ├── character.py
│       │   └── generation.py
│       │
│       ├── api/routes/             # API 路由
│       │   ├── novels.py           # 小说 CRUD + 向导接口
│       │   ├── chapters.py         # 章节 CRUD + 确认接口
│       │   ├── characters.py       # 角色 CRUD
│       │   ├── generation.py       # SSE 流式生成接口
│       │   └── app_settings.py     # 全局配置读写接口
│       │
│       ├── agents/                 # Agent 实现
│       │   ├── orchestrator.py     # 主调度器（状态机 + SSE 输出）
│       │   ├── writer.py           # Writer Agent（流式生成章节）
│       │   ├── critic.py           # Critic Agent（质量审查）
│       │   ├── outline_agent.py    # Outline Agent（生成大纲）
│       │   ├── character_agent.py  # Character Agent（生成角色卡）
│       │   └── world_agent.py      # World Agent（扩写世界观）
│       │
│       ├── services/
│       │   ├── llm_client.py       # OpenAI SDK 封装（单例客户端 + Agent 模型路由）
│       │   ├── vector_store.py     # ChromaDB 封装（存储 + 检索）
│       │   ├── summarizer.py       # 章节摘要 + 角色状态更新
│       │   └── context_builder.py  # 生成上下文组装（6 层记忆）
│       │
│       └── prompts/
│           ├── loader.py           # Jinja2 模板加载器
│           └── templates/          # ★ Prompt 模板目录（重点）
│               ├── writer.jinja2       # Writer Agent 系统提示词
│               ├── critic.jinja2       # Critic Agent 审查提示词
│               ├── outline.jinja2      # 大纲生成提示词
│               ├── character.jinja2    # 角色卡生成提示词
│               └── initializer.jinja2  # 世界观扩写提示词
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
  1. 构建上下文（6 层记忆）
     ├── 世界观设定（core_setting）
     ├── 角色状态卡（SQLite）
     ├── 本章大纲（SQLite Outline 表）
     ├── 近期章节摘要（SQLite Memory 表，最近 5 章）
     ├── RAG 检索相关历史场景（ChromaDB）
     └── 上一章末尾 500 字（即时上下文）
     │
  2. [Writer Agent] 流式生成章节正文 → SSE token 事件推送到前端
     │
  3. [Critic Agent] 审查内容质量
     ├── PASS → 继续
     └── FAIL（有问题） → 回到 Writer 修改（最多 1 次）
     │
  4. 保存章节到数据库（draft 状态）
     │
  5. [Memory Agent]
     ├── 生成章节摘要（100 字内）→ SQLite Memory 表 + ChromaDB
     └── 更新角色状态卡（location、goal、secrets…）
     │
  SSE done 事件 → 前端刷新章节列表
```

### 6 层记忆体系

| 层级 | 存储位置 | 内容 | Token 消耗 |
|------|---------|------|-----------|
| 世界观 | SQLite novels.core_setting | 完整设定文档（截取前 1000 字） | ~500 |
| 角色状态卡 | SQLite characters.current_state | 结构化 JSON（位置/目标/秘密/关系） | ~200 |
| 章节大纲 | SQLite outlines | 当前章节目标描述 | ~100 |
| 滚动摘要 | SQLite memories | 最近 5 章摘要（各 100 字） | ~500 |
| RAG 检索 | ChromaDB | 语义相关历史片段（top-3） | ~300 |
| 即时上下文 | 动态查询 | 上一章末尾 500 字 | ~500 |

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

### 修改 Critic 的 summarizer Prompt（代码中内联）

`summarizer.py` 中有两段内联 Prompt（非 Jinja2 模板文件），可直接编辑：

- **`CHAPTER_SUMMARY_PROMPT`**（第 12 行）：控制章节摘要的长度和侧重点
- **`CHARACTER_UPDATE_PROMPT`**（第 21 行）：控制角色状态更新时关注哪些维度

---

## 审查机制（Critic）说明

### 工作原理

每次 Writer 生成章节后，Critic Agent 会自动审查内容：

1. **输入**：角色状态卡 + 本章大纲 + 近期剧情摘要 + 生成正文（前 3000 字）
2. **判断**：LLM 输出 `PASS` 或具体问题列表
3. **处理**：
   - `PASS` → 直接保存章节
   - 有问题 → 将问题列表反馈给 Writer，要求修改
4. **限制**：最多重写 **1 次**（即 Writer 最多执行两次），避免无限循环浪费 Token

### Token 消耗估算（单次生成）

| 阶段 | 模型 | 估算 Token |
|------|------|-----------|
| Writer（首次） | Writer 模型 | ↑1500 / ↓1000 |
| Critic 审查 | Fast 模型 | ↑1200 / ↓100 |
| Writer（修改，如有） | Writer 模型 | ↑2000 / ↓1000 |
| Memory 摘要 | Fast 模型 | ↑600 / ↓150 |
| 角色状态更新 | Fast 模型 | ↑800 / ↓200 |
| **合计（无修改）** | — | **~4550** |
| **合计（有修改）** | — | **~8000** |

### 调整审查严格度

**方法一：关闭 Critic**（最省 Token）

编辑 `backend/app/agents/orchestrator.py`，注释掉 Critic 相关代码块（Node 3 部分），将 `passed` 直接设为 `True`。

**方法二：减少审查维度**

编辑 `backend/app/prompts/templates/critic.jinja2`，删减审查条目（第 4-7 行的 1-4 项），减少 Critic 触发修改的概率。

**方法三：调整重试次数**

在 `backend/.env` 中设置：
```env
MAX_CRITIC_RETRIES=0   # 0 = 不重写，即使 Critic 发现问题也直接保存
MAX_CRITIC_RETRIES=1   # 1 = 默认，最多重写一次（共写 2 次）
MAX_CRITIC_RETRIES=2   # 2 = 最多重写两次（共写 3 次）
```

---

## 配置参考

所有配置项在 `backend/.env` 文件中（也可在 UI 设置页修改，会自动同步写入 `.env`）：

```env
# ── API 接入 ──────────────────────────────────────────────────────
AIHUBMIX_API_KEY=sk-xxxxxxxxxxxxxxxx
AIHUBMIX_BASE_URL=https://aihubmix.com/v1

# ── 默认模型（未单独配置的 Agent 回退到此）──────────────────────────
DEFAULT_WRITER_MODEL=gemini-2.5-pro-preview-03-25   # 高质量生成
DEFAULT_FAST_MODEL=gemini-2.0-flash                  # 摘要/审查/规划

# ── 各 Agent 独立模型（留空则使用上方默认）────────────────────────────
AGENT_WRITER_MODEL=
AGENT_CRITIC_MODEL=
AGENT_MEMORY_MODEL=
AGENT_OUTLINE_MODEL=
AGENT_CHARACTER_MODEL=
AGENT_ORCHESTRATOR_MODEL=

# ── 生成参数 ─────────────────────────────────────────────────────
MAX_CRITIC_RETRIES=1   # Writer 最多执行次数 = MAX_CRITIC_RETRIES + 1
```

### 模型推荐（AiHubMix 可用模型）

| 用途 | 推荐模型 | 说明 |
|------|---------|------|
| Writer（高质量） | `gemini-2.5-pro-preview-03-25` | 最强中文写作 |
| Writer（均衡） | `gemini-2.0-flash` | 速度快、质量好 |
| Fast（便宜） | `gemini-2.0-flash` 或 `gpt-4o-mini` | 摘要/审查用 |

---

## 常见问题

### Q: 保存设置后需要重启后端吗？
**A**: 不需要。设置页的「保存配置」会立即更新内存中的值，同时写入 `.env` 文件确保重启后生效。

### Q: 生成时出现 401 / API Key 无效？
**A**: 前往设置页，重新输入 API Key 并保存。注意模型名称要使用 AiHubMix 支持的完整名称（可在 AiHubMix 控制台查看）。

### Q: 如何关闭 Critic 审查节省 Token？
**A**: 将 `MAX_CRITIC_RETRIES=0` 设置后，即使 Critic 发现问题也不会触发重写。或参考[调整审查严格度](#调整审查严格度)章节。

### Q: 角色/世界观对生成没有影响？
**A**: 需要先通过「向导」完成世界观扩写和角色卡生成，才能有效注入上下文。如跳过了向导，可在编辑器右上角「设置」中手动填写世界观。

### Q: ChromaDB 报 `Number of requested results > elements in index` 警告？
**A**: 这是正常日志，表示向量库中的文档数量少于查询数量（例如刚开始创作时）。不影响功能，系统会自动调整返回数量。

### Q: 日志出现 `AsyncHttpxClientWrapper has no attribute '_transport'`？
**A**: 已通过单例客户端修复（`llm_client.py`）。若仍出现，是 openai SDK 与 httpx 版本的已知兼容问题，不影响生成功能。
