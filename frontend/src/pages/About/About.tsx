import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, PenTool, Search, Brain, Users, MessageSquare, Layers, Globe, FileText, ScrollText, Database, Zap, Map, Shield, Swords, StickyNote, RefreshCw, Sparkles, Eye } from 'lucide-react'

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
            每次生成章节时，系统按以下顺序组装上下文，送入 Writer Agent。各模块独立获取、按优先级排列，均可在设置中单独开关。角色、道具、地点等实体通过 RAG 自动筛选与本章相关的条目，避免无关信息占用 token 窗口。
          </p>
          <div className="divide-y">
            <Item icon={Globe} label="世界观设定 (core_setting)">
              小说创建时设置的世界观描述。生成时通过向量检索取回与当前章节最相关的 3 段世界观片段；无向量数据时回退到前 500 字。
            </Item>
            <Item icon={ScrollText} label="全书概要 (book_summary)">
              将所有已确认章节的摘要整合而成的长程记忆。超过 50 章时自动分批概括再合并，支持百章级别的主线剧情追踪。每 5 章自动刷新。
            </Item>
            <Item icon={RefreshCw} label="故事弧概要 (arc_summary)">
              每 15 章自动生成一次的中间粒度摘要，覆盖最近一段连续章节的主线进展。在全书概要和滚动摘要之间提供中程定位。
            </Item>
            <Item icon={FileText} label="本章大纲 (chapter_outline)">
              大纲系统中对应当前章节的写作目标。如果已在大纲页面设定了该章的剧情安排，会作为核心指引送入 Writer。
            </Item>
            <Item icon={Layers} label="滚动摘要 (rolling_summary)">
              最近 N 章的章节摘要（N 可在设置中调整），提供近程记忆。每章只取最新一条摘要，避免重复确认导致窗口被挤压。
            </Item>
            <Item icon={Search} label="RAG 检索 (rag_context)">
              基于当前章节大纲或场景提示，从向量库中检索语义最相关的历史章节摘要。自动排除滚动摘要已覆盖的章节，避免冗余。检索数量（top_k）可在设置中调整，设为 0 则关闭。
            </Item>
            <Item icon={Users} label="角色状态 (characters)">
              通过 RAG 筛选与本章相关的角色。包含角色描述、详细设定卡（性格/动机/技能/外貌/说话风格）以及动态状态（位置/目标/称谓/关系）。每次确认章节后自动更新动态状态。
            </Item>
            <Item icon={Sparkles} label="道具与系统 (items / systems)">
              世界实体分为道具和系统两类，各自独立开关。通过 RAG 筛选与本章相关的实体，携带描述、属性和动态状态（持有者/能力/等级变化）。
            </Item>
            <Item icon={Map} label="地点 (locations)">
              通过 RAG 筛选与本章相关的地点，携带地点描述和类型信息。
            </Item>
            <Item icon={Shield} label="势力 (factions)">
              通过 RAG 筛选与本章相关的势力/组织，携带描述、领导者和目标信息。
            </Item>
            <Item icon={Swords} label="功法 (techniques)">
              通过 RAG 筛选与本章相关的功法/武技，携带描述和修炼者信息。
            </Item>
            <Item icon={StickyNote} label="补充设定 (notes)">
              用户在笔记页面添加的补充设定条目。通过向量检索筛选与本章相关的笔记，作为额外的世界观补充。
            </Item>
            <Item icon={Zap} label="上章原文 (recent_text)">
              上一章全文（去除末尾剧情建议），提供场景级衔接细节。仅当原文为空时回退到摘要。
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
            系统采用多 Agent 协作架构，由 Orchestrator 统一调度。各 Agent 职责明确、独立运行，可在设置中为每个 Agent 指定不同的模型。
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
                对 Writer 生成的章节进行质量审查，检查剧情连贯性、角色一致性、与大纲的匹配度。发现问题时会将反馈返回 Writer 进行修订。可在设置中关闭。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Database className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Memory（记忆系统）</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">记忆</span>
              </div>
              <p className="text-muted-foreground text-sm">
                在章节确认后自动运行，依次执行：(1) 生成章节摘要并存入 Memory 表和向量库；(2) 更新角色动态状态（位置/目标/称谓/关系）；(3) 更新世界实体状态（持有者/能力/等级）；(4) 更新地点状态（局势/控制方）。各步骤独立提交，避免长事务锁。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Users className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Character Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-500">发现</span>
              </div>
              <p className="text-muted-foreground text-sm">
                生成角色详细设定卡（性格/动机/技能/外貌/说话风格）。章节确认后并行扫描新出现的角色、道具/系统、地点和功法，自动提示用户是否加入对应库。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Globe className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">World Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-teal-500/10 text-teal-500">世界观</span>
              </div>
              <p className="text-muted-foreground text-sm">
                处理世界观设定的扩写、优化，并将世界观按段落切分嵌入向量库，供生成时 RAG 检索最相关的世界观片段。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <FileText className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Outline Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-500">大纲</span>
              </div>
              <p className="text-muted-foreground text-sm">
                为小说生成章节级大纲，根据已有剧情和世界观规划后续章节的写作目标。
              </p>
            </div>

            <div className="border rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Eye className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-sm">Review Agent</h3>
                <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/10 text-red-500">审查</span>
              </div>
              <p className="text-muted-foreground text-sm">
                全文审查 Agent，按可配置的章节间隔自动触发，对已写内容进行全局一致性检查（剧情矛盾、角色行为不一致、时间线错误等）。可在设置中开关和调整触发间隔。
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
              Orchestrator 调用 context_builder 组装上下文 → Writer 流式生成 → Critic 审查（可选）→ Writer 修订（如有问题）→ 保存终稿 + 状态快照
            </p>
            <p>
              <span className="font-medium text-foreground">确认阶段：</span>
              用户确认章节 → 依次执行：生成章节摘要 → 更新角色状态 → 更新实体状态 → 更新地点状态（各步独立提交）→ 并行发现新角色/实体/地点/功法 → 自动刷新弧摘要（每 15 章）和全书概要（每 5 章）
            </p>
            <p>
              <span className="font-medium text-foreground">向量检索：</span>
              章节摘要存入 ChromaDB，世界观按段落切分嵌入。生成时按语义相似度检索，自动排除已在滚动窗口中的章节。角色、道具、地点等实体也通过向量检索筛选与当前章节相关的条目。
            </p>
          </div>
        </Section>
      </main>
    </div>
  )
}
