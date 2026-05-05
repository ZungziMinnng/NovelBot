import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Sun, Moon, Eye, Clock, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { novelsApi, chaptersApi, type ContextPreview, type Chapter } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

type Tab = 'context' | 'timeline'

function extractTime(chapter: Chapter): string | null {
  const text = chapter.summary || ''
  const m = text.match(/【(.+?)】/)
  return m ? m[1] : null
}

export default function Outline() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { theme, toggleTheme } = useSettingsStore()
  const [activeTab, setActiveTab] = useState<Tab>('context')
  const [chapterNum, setChapterNum] = useState(() => {
    const cn = searchParams.get('chapter')
    return cn ? Number(cn) : 0
  })

  const { data: novel } = useQuery({
    queryKey: ['novel', novelId],
    queryFn: () => novelsApi.get(novelId),
  })

  const { data: chapters = [] } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  const effectiveChapter = chapterNum || (novel?.current_chapter || 0) + 1

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ['context-preview', novelId, effectiveChapter],
    queryFn: () => novelsApi.contextPreview(novelId, effectiveChapter),
    enabled: activeTab === 'context',
  })

  // ── Timeline extraction ──────────────────────────────────────────────────
  const timelineEntries = chapters
    .filter(c => c.summary)
    .map(c => ({ chapter: c.number, time: extractTime(c), summary: c.summary! }))

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 上下文 & 时间线</h1>
        <button
          onClick={toggleTheme}
          className="ml-auto p-2 rounded-md hover:bg-muted transition-colors"
          title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </header>

      {/* Tabs */}
      <div className="border-b px-6 flex gap-4">
        <button
          onClick={() => setActiveTab('context')}
          className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'context' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Eye className="w-3.5 h-3.5 inline-block mr-1.5" />
          上下文预览
        </button>
        <button
          onClick={() => setActiveTab('timeline')}
          className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'timeline' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Clock className="w-3.5 h-3.5 inline-block mr-1.5" />
          时间线
        </button>
      </div>

      <main className="max-w-3xl mx-auto px-6 py-8">
        {/* ── Context Preview Tab ───────────────────────────────────────── */}
        {activeTab === 'context' && (
          <div className="space-y-6">
            {/* Chapter selector */}
            <div className="flex items-center gap-3">
              <label className="text-sm font-medium shrink-0">预览章节：</label>
              <select
                value={chapterNum || ''}
                onChange={e => setChapterNum(Number(e.target.value) || 0)}
                className="border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="0">第 {effectiveChapter} 章（下一章）</option>
                {chapters.map(c => (
                  <option key={c.id} value={c.number}>第 {c.number} 章</option>
                ))}
              </select>
              {preview?.writer_model && (
                <span className="text-xs text-muted-foreground ml-auto">
                  Writer: {preview.writer_model}
                </span>
              )}
            </div>

            {previewLoading ? (
              <div className="flex items-center justify-center py-20 text-muted-foreground">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                加载上下文...
              </div>
            ) : preview ? (
              <>
                {/* Stats bar */}
                <div className="flex gap-3 text-xs text-muted-foreground">
                  <span className="px-2 py-1 bg-muted rounded-full">角色 {preview.context.characters_count} 人</span>
                  <span className="px-2 py-1 bg-muted rounded-full">实体 {preview.context.entities_count} 个</span>
                  <span className="px-2 py-1 bg-muted rounded-full">
                    RAG {preview.context.rag_context ? Math.ceil(preview.context.rag_context.length / 250) : 0} 条
                  </span>
                </div>

                {/* Context sections */}
                {[
                  ['世界观设定', preview.context.core_setting],
                  ['全书概要', preview.context.book_summary],
                  ['故事弧概要', preview.context.arc_summary],
                  ['本章大纲', preview.context.chapter_outline],
                  ['近期剧情摘要（滚动窗口）', preview.context.rolling_summary],
                  ['相关历史场景（RAG 检索）', preview.context.rag_context],
                  ['上一章原文', preview.context.recent_text],
                ].map(([label, content]) =>
                  content ? (
                    <CollapsibleSection key={label} label={label} defaultOpen={false}>
                      <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed text-muted-foreground">
                        {content}
                      </pre>
                    </CollapsibleSection>
                  ) : (
                    <div key={label} className="text-xs text-muted-foreground/50 italic">
                      {label}：空
                    </div>
                  ),
                )}

                {/* Writer messages (what LLM actually receives) */}
                <CollapsibleSection label="Writer 收到的 4 条消息" defaultOpen={true}>
                  <div className="space-y-3">
                    {preview.writer_messages.map((msg, i) => (
                      <div key={i}>
                        <div className="text-xs font-medium text-muted-foreground mb-1">
                          [{i}] {msg.role} {i === 0 ? '(system prompt)' : ''}
                        </div>
                        <pre className="text-xs whitespace-pre-wrap font-sans leading-relaxed bg-muted/50 rounded-lg p-3 max-h-60 overflow-y-auto">
                          {msg.content || '（空）'}
                        </pre>
                      </div>
                    ))}
                  </div>
                </CollapsibleSection>
              </>
            ) : (
              <div className="text-center py-20 text-muted-foreground">
                <p>暂无上下文数据</p>
              </div>
            )}
          </div>
        )}

        {/* ── Timeline Tab ───────────────────────────────────────────────── */}
        {activeTab === 'timeline' && (
          <div>
            {timelineEntries.length === 0 ? (
              <div className="text-center py-20 text-muted-foreground">
                <p>暂无章节数据，生成章节后自动填充</p>
              </div>
            ) : (
              <div className="relative">
                {/* Vertical line */}
                <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-border" />
                <div className="space-y-0">
                  {timelineEntries.map((entry) => (
                    <div key={entry.chapter} className="relative pl-10 py-3">
                      {/* Dot on the line */}
                      <div className="absolute left-2.5 top-5 w-3 h-3 rounded-full bg-primary border-2 border-background -translate-x-1/2" />
                      <div className="flex items-baseline gap-2 mb-1">
                        <span className="text-xs font-mono text-muted-foreground">
                          第{entry.chapter}章
                        </span>
                        {entry.time && (
                          <span className="text-xs font-medium bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                            {entry.time}
                          </span>
                        )}
                        {!entry.time && (
                          <span className="text-xs text-muted-foreground/50 italic">
                            无时间标注
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground leading-relaxed">
                        {entry.summary}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty state: no novel data */}
        {activeTab === 'context' && !previewLoading && !preview && !novel && (
          <div className="text-center py-20 text-muted-foreground">
            <p>小说数据未加载</p>
          </div>
        )}
      </main>
    </div>
  )
}

// ── Collapsible Section ────────────────────────────────────────────────────

function CollapsibleSection({
  label,
  children,
  defaultOpen = false,
}: {
  label: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border rounded-lg">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-muted/50 transition-colors rounded-lg"
      >
        <span className="text-sm font-medium">{label}</span>
        {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}
