import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sun, Moon, Eye, Clock, Search, Loader2, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react'
import { novelsApi, chaptersApi, type ContextPreview, type Chapter, type SearchResult } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'
import toast from 'react-hot-toast'

type Tab = 'context' | 'timeline' | 'search'

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
  const qc = useQueryClient()
  const { theme, toggleTheme } = useSettingsStore()
  const [activeTab, setActiveTab] = useState<Tab>('context')
  const [reindexing, setReindexing] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchResult, setSearchResult] = useState<SearchResult | null>(null)
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

  const maxChapterNum = chapters.length > 0 ? Math.max(...chapters.map(c => c.number)) : 0
  const effectiveChapter = chapterNum || maxChapterNum + 1

  const { data: preview, isLoading: previewLoading } = useQuery({
    queryKey: ['context-preview', novelId, effectiveChapter],
    queryFn: () => novelsApi.contextPreview(novelId, effectiveChapter),
    enabled: activeTab === 'context',
  })

  // ── Timeline extraction ──────────────────────────────────────────────────
  const timelineEntries = [...chapters]
    .sort((a, b) => a.number - b.number)
    .filter(c => c.summary)
    .map(c => ({ chapter: c.number, volume: c.volume, time: extractTime(c), summary: c.summary! }))

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
        <button
          onClick={() => setActiveTab('search')}
          className={`py-2.5 text-sm font-medium border-b-2 transition-colors ${
            activeTab === 'search' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
        >
          <Search className="w-3.5 h-3.5 inline-block mr-1.5" />
          搜索
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
                {[...chapters].sort((a, b) => a.number - b.number).map(c => (
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
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span className="px-2 py-1 bg-muted rounded-full">角色 {preview.context.characters_count} 人</span>
                  <span className="px-2 py-1 bg-muted rounded-full">实体 {preview.context.entities_count} 个</span>
                  <span className="px-2 py-1 bg-muted rounded-full">地点 {preview.context.locations_count} 个</span>
                  <span className="px-2 py-1 bg-muted rounded-full">
                    RAG {preview.context.rag_context ? Math.ceil(preview.context.rag_context.length / 250) : 0} 条
                  </span>
                  {preview.token_estimate && (
                    <span className="px-2 py-1 bg-primary/10 text-primary rounded-full font-medium">
                      预估 ~{preview.token_estimate.total.toLocaleString()} tokens
                    </span>
                  )}
                </div>

                {/* Context sections */}
                {([
                  ['世界观设定', preview.context.core_setting],
                  ['全书概要', preview.context.book_summary],
                  ['故事弧概要', preview.context.arc_summary],
                  ['本章大纲', preview.context.chapter_outline],
                  ['近期剧情摘要（滚动窗口）', preview.context.rolling_summary],
                  ['相关历史场景（RAG 检索）', preview.context.rag_context],
                  ['补充设定（NovelNote）', preview.context.notes_context],
                  ['上一章原文', preview.context.recent_text],
                ] as [string, string][]).map(([label, content]) =>
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
            {timelineEntries.length > 0 && (
              <div className="flex justify-end mb-4">
                <button
                  onClick={async () => {
                    setReindexing(true)
                    try {
                      const res = await novelsApi.reindexTimeline(novelId)
                      qc.invalidateQueries({ queryKey: ['chapters', novelId] })
                      toast.success(`已更新 ${res.updated} 章时间标记`)
                    } catch (err: any) {
                      const detail = err?.response?.data?.detail || err?.message || '未知错误'
                      toast.error(`重标注时间线失败：${detail}`, { duration: 8000 })
                    } finally {
                      setReindexing(false)
                    }
                  }}
                  disabled={reindexing}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                >
                  {reindexing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                  {reindexing ? '标注中...' : '重标注时间线'}
                </button>
              </div>
            )}
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
                          {entry.volume > 1 && `卷${entry.volume}·`}第{entry.chapter}章
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

        {/* ── Search Tab ──────────────────────────────────────────────── */}
        {activeTab === 'search' && (
          <div className="space-y-6">
            <form
              onSubmit={async e => {
                e.preventDefault()
                const q = searchInput.trim()
                if (!q) return
                setSearchQuery(q)
                setSearchLoading(true)
                try {
                  const res = await novelsApi.search(novelId, q)
                  setSearchResult(res)
                } catch (err: any) {
                  toast.error('搜索失败：' + (err?.response?.data?.detail || err?.message || '未知错误'))
                } finally {
                  setSearchLoading(false)
                }
              }}
              className="flex gap-2"
            >
              <input
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                placeholder="搜索角色、道具、设定、剧情..."
                className="flex-1 border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <button
                type="submit"
                disabled={searchLoading || !searchInput.trim()}
                className="px-4 py-2 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1.5"
              >
                {searchLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                搜索
              </button>
            </form>

            {searchLoading && (
              <div className="flex items-center justify-center py-16 text-muted-foreground">
                <Loader2 className="w-5 h-5 animate-spin mr-2" />
                搜索中...
              </div>
            )}

            {!searchLoading && searchResult && searchQuery && (
              <SearchResults result={searchResult} query={searchQuery} />
            )}

            {!searchLoading && !searchResult && (
              <div className="text-center py-20 text-muted-foreground">
                <Search className="w-8 h-8 mx-auto mb-3 opacity-30" />
                <p className="text-sm">输入关键词搜索角色、道具、设定在剧情中的出现</p>
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

// ── Search Results ─────────────────────────────────────────────────────────

const SEARCH_SECTIONS: { key: keyof SearchResult; label: string }[] = [
  { key: 'chapters', label: '相关章节' },
  { key: 'characters', label: '角色' },
  { key: 'items', label: '道具' },
  { key: 'systems', label: '系统' },
  { key: 'locations', label: '地点' },
  { key: 'factions', label: '势力' },
  { key: 'techniques', label: '功法' },
  { key: 'notes', label: '笔记 / 设定' },
]

function SearchResults({ result, query }: { result: SearchResult; query: string }) {
  const hasAny = SEARCH_SECTIONS.some(s => (result[s.key] as unknown[]).length > 0)

  if (!hasAny) {
    return (
      <div className="text-center py-16 text-muted-foreground">
        <p className="text-sm">未找到与「{query}」相关的结果</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {result.chapters.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2">相关章节</h3>
          <div className="space-y-2">
            {result.chapters.map((c, i) => (
              <div key={i} className="border rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-mono text-muted-foreground">第{c.chapter_number}章</span>
                  <span className="text-xs px-1.5 py-0.5 bg-primary/10 text-primary rounded-full">
                    {(c.score * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">{c.summary}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {result.characters.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2">角色</h3>
          <div className="space-y-2">
            {result.characters.map(c => (
              <div key={c.id} className="border rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium">{c.name}</span>
                  <span className="text-xs text-muted-foreground">{c.role}</span>
                </div>
                {c.description && <p className="text-xs text-muted-foreground">{c.description}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {(['items', 'systems', 'locations', 'factions', 'techniques'] as const).map(key => {
        const items = result[key]
        if (items.length === 0) return null
        const label = SEARCH_SECTIONS.find(s => s.key === key)!.label
        return (
          <div key={key}>
            <h3 className="text-sm font-medium mb-2">{label}</h3>
            <div className="space-y-2">
              {items.map((item) => (
                <div key={item.id} className="border rounded-lg px-4 py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium">{item.name}</span>
                    {item.type && <span className="text-xs text-muted-foreground">{item.type}</span>}
                  </div>
                  {item.description && <p className="text-xs text-muted-foreground">{item.description}</p>}
                </div>
              ))}
            </div>
          </div>
        )
      })}

      {result.notes.length > 0 && (
        <div>
          <h3 className="text-sm font-medium mb-2">笔记 / 设定</h3>
          <div className="space-y-2">
            {result.notes.map((n, i) => (
              <div key={n.id ?? `vec-${i}`} className="border rounded-lg px-4 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-medium">{n.title || '笔记'}</span>
                  {n.score != null && (
                    <span className="text-xs px-1.5 py-0.5 bg-primary/10 text-primary rounded-full">
                      {(n.score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                {n.content && <p className="text-xs text-muted-foreground whitespace-pre-wrap">{n.content}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
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
