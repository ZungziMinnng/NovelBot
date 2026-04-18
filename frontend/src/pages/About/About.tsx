import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, PenTool, Search, Brain, Users, MessageSquare, Layers, Globe, FileText, ScrollText, Database, Zap } from 'lucide-react'

function Section({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div className="border rounded-xl bg-card p-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold mb-4">
        <Icon className="w-5 h-5 text-primary" />
        {title}
      </h2>
      {children}
    </div>
  )
}

function Item({ icon: Icon, label, children }: { icon: React.ElementType; label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-3">
      <Icon className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
      <div>
        <div className="font-medium text-sm">{label}</div>
        <div className="text-muted-foreground text-sm mt-0.5">{children}</div>
      </div>
    </div>
  )
}

export default function About() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-md hover:bg-muted transition-colors"
          title="返回主页"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-primary" />
          <h1 className="text-lg font-bold">架构说明</h1>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {/* Context pipeline */}
        <Section icon={Layers} title="上下文构建流程">
          <p className="text-muted-foreground text-sm mb-4">
            每次生成章节时，系统按以下顺序组装上下文，送入 Writer Agent。各模块独立获取、按优先级排列，确保 LLM 在有限 token 窗口内获得最相关的信息。
          </p>
          <div className="divide-y">
            <Item icon={Globe} label="世界观设定 (core_setting)">
              小说创建时设置的世界观描述，每次生成时始终携带（截取前 1000 字）。提供故事的基础规则和背景框架。
            </Item>
            <Item icon={ScrollText} label="全书概要 (book_summary)">
              由 Memory Agent 将所有已确认章节的摘要整合而成的长程记忆。超过 50 章时自动分批概括再合并，支持百章级别的主线剧情追踪。
            </Item>
            <Item icon={FileText} label="本章大纲 (chapter_outline)">
              大纲系统中对应当前章节的写作目标。如果已在大纲页面设定了该章的剧情安排，会作为核心指引送入 Writer。
            </Item>
            <Item icon={Layers} label="滚动摘要 (rolling_summary)">
              最近 N 章的章节摘要（N 可在设置中调整），提供中程记忆。每章只取最新一条摘要，避免重复确认导致窗口被挤压。
            </Item>
            <Item icon={Search} label="RAG 检索 (rag_context)">
              基于当前章节大纲或场景提示，从向量库中检索语义最相关的历史章节摘要。自动排除滚动摘要已覆盖的章节，避免冗余。检索数量（top_k）可在设置中调整，设为 0 则关闭。
            </Item>
            <Item icon={Users} label="角色状态 (characters)">
              包含角色描述、详细设定卡（full_sheet: 性格/动机/技能/外貌/说话风格）以及动态状态（current_state: 位置/目标/称谓/已知秘密/关系变化）。每次确认章节后由 Memory Agent 自动更新动态状态。
            </Item>
            <Item icon={Zap} label="上章结尾 (recent_text)">
              上一章末尾 500 字原文，提供场景级衔接细节（人物在哪、在做什么、对话停在哪），让 Writer 自然承接。仅当原文为空时回退到摘要。
            </Item>
          </div>
          <div className="mt-4 p-3 bg-muted/50 rounded-lg">
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">消息分层策略：</span>上下文中的角色描述、写作指令和章节原文通过 assistant/model 角色传递，纯净的结构性内容（世界观、大纲、摘要）通过 user 角色传递。这种分层设计可以有效避免 Gemini 的输入侧安全过滤误触发。
            </p>
          </div>
        </Section>

        {/* Agents */}
        <Section icon={Brain} title="Agent 介绍">
          <p className="text-muted-foreground text-sm mb-4">
            系统采用多 Agent 协作架构，由 Orchestrator 统一调度。各 Agent 职责明确、独立运行。
          </p>
          <div className="space-y-4">
            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <PenTool className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Writer Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500">核心</span>
              </div>
              <p className="text-muted-foreground text-sm">
                负责生成章节正文。接收完整的上下文（世界观、角色、大纲、摘要等），支持流式输出。可自定义系统提示词（Writer Prompt）、生成温度、thinking 模式。当 Critic 发现问题时，Writer 会根据反馈修订。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Search className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Critic Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-500">质检</span>
              </div>
              <p className="text-muted-foreground text-sm">
                对 Writer 生成的章节进行质量审查，检查剧情连贯性、角色一致性、与大纲的匹配度。发现问题时会将反馈返回 Writer 进行修订。可在设置中关闭（skip critic）。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Database className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Memory Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">记忆</span>
              </div>
              <p className="text-muted-foreground text-sm">
                在章节确认后自动运行，负责两项工作：(1) 生成章节摘要并存入 Memory 表和向量库；(2) 更新角色动态状态（位置、目标、称谓、已知秘密、关系变化）。摘要和原文分段都会写入向量库供 RAG 检索。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Users className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Character Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-500">角色</span>
              </div>
              <p className="text-muted-foreground text-sm">
                生成角色详细设定卡（full_sheet），包含性格、动机、技能、外貌、说话风格等字段。支持从章节内容中自动发现新角色并初始化状态卡。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <MessageSquare className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Chat Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-500">对话</span>
              </div>
              <p className="text-muted-foreground text-sm">
                对话助手，基于小说的完整上下文（世界观、角色、已写章节）回答创作相关的问题。对话上下文轮数可在设置中独立调整，不影响章节生成的上下文配置。
              </p>
            </div>
          </div>
        </Section>

        {/* Data flow */}
        <Section icon={Zap} title="数据流向">
          <div className="text-sm text-muted-foreground space-y-2">
            <p>
              <span className="font-medium text-foreground">生成阶段：</span>
              Orchestrator 调用 context_builder 组装上下文 → Writer 流式生成 → Critic 审查（可选）→ Writer 修订（如有问题）→ 返回终稿
            </p>
            <p>
              <span className="font-medium text-foreground">确认阶段：</span>
              用户确认章节 → Memory Agent 并行执行：生成摘要 + 更新角色状态 → 写入 Memory 表 + 向量库 + Character 表
            </p>
            <p>
              <span className="font-medium text-foreground">向量检索：</span>
              章节摘要和原文分段（每 500 字）均存入 ChromaDB。生成时按语义相似度检索，自动排除已在滚动窗口中的章节。
            </p>
          </div>
        </Section>
      </main>
    </div>
  )
}
