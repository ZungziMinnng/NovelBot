import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Save, Trash2, Loader2, RefreshCw, Search } from 'lucide-react'
import { novelsApi, chaptersApi, charactersApi, adminApi, correctionsApi, textReplaceApi } from '@/api/client'
import type { Character, Chapter, Memory, OutlineEntry, CorrectionHit, ReplaceScope, ReplacePreview, ReplaceBackup } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'

type TabKey = 'search' | 'replace' | 'characters' | 'summaries' | 'memories' | 'outlines'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'search', label: '搜索修正' },
  { key: 'replace', label: '批量替换' },
  { key: 'characters', label: '角色状态' },
  { key: 'summaries', label: '章节摘要' },
  { key: 'memories', label: '记忆条目' },
  { key: 'outlines', label: '大纲' },
]

const SOURCE_LABEL: Record<string, string> = {
  character: '角色',
  location: '地点',
  chapter: '章节摘要',
  memory: '记忆条目',
  outline: '大纲',
}

const SOURCE_COLOR: Record<string, string> = {
  character: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
  location: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  chapter: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  memory: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  outline: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
}

const STATE_FIELDS = ['location', 'current_goal', 'titles', 'affiliation', 'known_secrets'] as const

const memoryTypeColor: Record<string, string> = {
  chapter_summary: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  scene_summary: 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300',
  volume_summary: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  world_event: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  relationship_milestone: 'bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300',
}

const memoryTypeLabel: Record<string, string> = {
  relationship_milestone: '关系里程碑',
}

export default function Admin() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('search')

  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: characters = [] } = useQuery({ queryKey: ['characters', novelId], queryFn: () => charactersApi.list(novelId) })
  const { data: chapters = [] } = useQuery({ queryKey: ['chapters', novelId], queryFn: () => chaptersApi.list(novelId) })
  const { data: memories = [], isLoading: memoriesLoading } = useQuery({ queryKey: ['memories', novelId], queryFn: () => adminApi.listMemories(novelId) })
  const { data: outlines = [], isLoading: outlinesLoading } = useQuery({ queryKey: ['outlines', novelId], queryFn: () => adminApi.listOutlines(novelId) })

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate(`/novel/${novelId}`)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 数据管理</h1>
        <button
          onClick={() => qc.invalidateQueries()}
          className="ml-auto flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors"
          title="刷新所有数据"
        >
          <RefreshCw className="w-3.5 h-3.5" /> 刷新
        </button>
        <ThemePicker />
      </header>

      {/* Tab bar */}
      <div className="border-b px-6">
        <div className="flex gap-1">
          {TABS.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
              {tab.key === 'characters' && <span className="ml-1.5 text-xs text-muted-foreground">({characters.length})</span>}
              {tab.key === 'summaries' && <span className="ml-1.5 text-xs text-muted-foreground">({chapters.length})</span>}
              {tab.key === 'memories' && <span className="ml-1.5 text-xs text-muted-foreground">({memories.length})</span>}
              {tab.key === 'outlines' && <span className="ml-1.5 text-xs text-muted-foreground">({outlines.length})</span>}
            </button>
          ))}
        </div>
      </div>

      <main className="max-w-6xl mx-auto px-6 py-6">
        {activeTab === 'search' && <SearchFixTab novelId={novelId} qc={qc} />}
        {activeTab === 'replace' && <BatchReplaceTab novelId={novelId} qc={qc} />}
        {activeTab === 'characters' && <CharacterStatesTab characters={characters} qc={qc} novelId={novelId} />}
        {activeTab === 'summaries' && <ChapterSummariesTab chapters={chapters} qc={qc} novelId={novelId} />}
        {activeTab === 'memories' && <MemoriesTab memories={memories} loading={memoriesLoading} qc={qc} novelId={novelId} />}
        {activeTab === 'outlines' && <OutlinesTab outlines={outlines} loading={outlinesLoading} qc={qc} novelId={novelId} />}
      </main>
    </div>
  )
}


// ── Tab 1: Character States ──────────────────────────────────────────────

function CharacterStatesTab({ characters, qc, novelId }: { characters: Character[]; qc: ReturnType<typeof useQueryClient>; novelId: number }) {
  const [editing, setEditing] = useState<{ charId: number; field: string } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)

  const startEdit = (char: Character, field: string) => {
    const state = char.current_state || {}
    const val = state[field]
    setEditValue(typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? ''))
    setEditing({ charId: char.id, field })
  }

  const saveEdit = async () => {
    if (!editing) return
    setSaving(true)
    try {
      const char = characters.find(c => c.id === editing.charId)
      if (!char) return
      const state = { ...(char.current_state || {}) }
      let parsedValue: unknown = editValue
      try { parsedValue = JSON.parse(editValue) } catch { /* keep as string */ }
      state[editing.field] = parsedValue
      await charactersApi.update(editing.charId, { current_state: state } as Partial<Character>)
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setEditing(null)
    } finally {
      setSaving(false)
    }
  }

  if (characters.length === 0) {
    return <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">暂无角色数据</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b bg-muted/50">
            <th className="text-left px-3 py-2.5 font-medium text-muted-foreground">角色</th>
            {STATE_FIELDS.map(f => (
              <th key={f} className="text-left px-3 py-2.5 font-medium text-muted-foreground">{f}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {characters.map(char => (
            <tr key={char.id} className="border-b hover:bg-muted/30 transition-colors">
              <td className="px-3 py-2.5 font-medium whitespace-nowrap">
                {char.name}
                <span className="ml-1.5 text-xs text-muted-foreground">({char.role})</span>
              </td>
              {STATE_FIELDS.map(field => {
                const state = char.current_state || {}
                const val = state[field]
                const isEditing = editing?.charId === char.id && editing?.field === field
                const display = val == null || val === '' ? '-'
                  : typeof val === 'object' ? JSON.stringify(val)
                  : String(val)

                return (
                  <td key={field} className="px-3 py-2.5 max-w-[200px]">
                    {isEditing ? (
                      <div className="flex items-start gap-1">
                        <textarea
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          className="w-full border rounded px-2 py-1 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring min-h-[60px]"
                          autoFocus
                          onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEdit() }
                            if (e.key === 'Escape') setEditing(null)
                          }}
                        />
                        <button onClick={saveEdit} disabled={saving} className="p-1 rounded hover:bg-muted shrink-0">
                          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5 text-primary" />}
                        </button>
                      </div>
                    ) : (
                      <span
                        onClick={() => startEdit(char, field)}
                        className="cursor-pointer hover:bg-primary/10 rounded px-1 py-0.5 text-xs truncate block"
                        title={display}
                      >
                        {display}
                      </span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


// ── Tab 2: Chapter Summaries ─────────────────────────────────────────────

function ChapterSummariesTab({ chapters, qc, novelId }: { chapters: Chapter[]; qc: ReturnType<typeof useQueryClient>; novelId: number }) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [backfilling, setBackfilling] = useState(false)
  const [backfillResult, setBackfillResult] = useState('')

  const missingCount = chapters.filter(ch => !ch.summary && ch.content).length

  const runBackfill = async (mode: 'missing' | 'all' = 'missing') => {
    if (mode === 'all') {
      const total = chapters.filter(ch => ch.content).length
      if (!window.confirm(`将用新模板重写全部 ${total} 章的摘要（覆盖已有摘要），耗时较长，确定继续？`)) return
    }
    setBackfilling(true)
    setBackfillResult('')
    try {
      const r = await chaptersApi.backfillSummaries(novelId, mode)
      const parts = [`成功 ${r.done.length}/${r.total} 章`]
      if (r.failed.length > 0) {
        parts.push(`失败：${r.failed.map(f => `第${f.number}章(${f.error})`).join('、')}`)
      }
      setBackfillResult(parts.join('；'))
      qc.invalidateQueries({ queryKey: ['chapters', novelId] })
    } catch (e) {
      setBackfillResult(`补全失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBackfilling(false)
    }
  }

  const startEdit = (ch: Chapter) => {
    setEditValue(ch.summary || '')
    setEditingId(ch.id)
  }

  const saveEdit = async (chapterId: number) => {
    setSaving(true)
    try {
      await chaptersApi.update(chapterId, { summary: editValue } as Partial<Chapter>)
      qc.invalidateQueries({ queryKey: ['chapters', novelId] })
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  if (chapters.length === 0) {
    return <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">暂无章节数据</div>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <button
          onClick={() => runBackfill('missing')}
          disabled={backfilling || missingCount === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {backfilling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {backfilling ? '生成中...' : `一键补全摘要（${missingCount} 章无摘要）`}
        </button>
        <button
          onClick={() => runBackfill('all')}
          disabled={backfilling}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs border rounded-lg hover:bg-muted disabled:opacity-50"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          重写全部摘要
        </button>
        {backfillResult && <span className="text-xs text-muted-foreground">{backfillResult}</span>}
      </div>
      {chapters.map(ch => (
        <div key={ch.id} className="border rounded-lg p-4 hover:border-primary/30 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-muted-foreground font-mono">第{ch.number}章</span>
            <span className="font-medium text-sm">{ch.title}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${ch.status === 'confirmed' ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300' : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300'}`}>
              {ch.status === 'confirmed' ? '已确认' : '草稿'}
            </span>
            <span className="text-xs text-muted-foreground">{ch.word_count}字</span>
          </div>
          {editingId === ch.id ? (
            <div className="flex gap-2">
              <textarea
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                className="flex-1 border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring min-h-[80px]"
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Escape') setEditingId(null)
                }}
              />
              <div className="flex flex-col gap-1">
                <button onClick={() => saveEdit(ch.id)} disabled={saving}
                  className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '保存'}
                </button>
                <button onClick={() => setEditingId(null)} className="px-3 py-1.5 text-xs border rounded-lg hover:bg-muted">取消</button>
              </div>
            </div>
          ) : (
            <p onClick={() => startEdit(ch)}
              className="text-xs text-muted-foreground cursor-pointer hover:bg-muted/50 rounded p-1.5 transition-colors">
              {ch.summary || <span className="italic">无摘要（点击编辑）</span>}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}


// ── Tab 3: Memory Entries ────────────────────────────────────────────────

function MemoriesTab({ memories, loading, qc, novelId }: { memories: Memory[]; loading: boolean; qc: ReturnType<typeof useQueryClient>; novelId: number }) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [rangeStart, setRangeStart] = useState('')
  const [rangeEnd, setRangeEnd] = useState('')
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState('')

  const runMilestoneBackfill = async () => {
    const start = Number(rangeStart)
    const end = Number(rangeEnd)
    if (!start || !end || start > end) {
      setBackfillMsg('请填写有效的起止章号')
      return
    }
    if (!window.confirm(`将对第 ${start}-${end} 章逐章全文抽取关系里程碑（每章一次模型调用），确定继续？`)) return
    setBackfilling(true)
    let processed = 0
    let extracted = 0
    const failed: number[] = []
    try {
      for (let batchStart = start; batchStart <= end; batchStart += 10) {
        const batchEnd = Math.min(batchStart + 9, end)
        setBackfillMsg(`处理中：第 ${batchStart}-${batchEnd} 章（已完成 ${processed} 章，提取 ${extracted} 条）`)
        const r = await adminApi.backfillMilestones(novelId, batchStart, batchEnd)
        processed += r.processed
        extracted += r.extracted
        failed.push(...r.failed)
      }
      const parts = [`完成：处理 ${processed} 章，提取 ${extracted} 条里程碑`]
      if (failed.length > 0) parts.push(`失败章节：${failed.join('、')}`)
      setBackfillMsg(parts.join('；'))
      qc.invalidateQueries({ queryKey: ['memories', novelId] })
    } catch (e) {
      setBackfillMsg(`回填中断（已处理 ${processed} 章）：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBackfilling(false)
    }
  }

  const startEdit = (m: Memory) => {
    setEditValue(m.content)
    setEditingId(m.id)
  }

  const saveEdit = async (memoryId: number) => {
    setSaving(true)
    try {
      await adminApi.updateMemory(memoryId, { content: editValue })
      qc.invalidateQueries({ queryKey: ['memories', novelId] })
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (memoryId: number) => {
    if (!confirm('确认删除此记忆条目？')) return
    await adminApi.deleteMemory(memoryId)
    qc.invalidateQueries({ queryKey: ['memories', novelId] })
  }

  const toggleInContext = async (m: Memory) => {
    await adminApi.updateMemory(m.id, { in_context: !m.in_context })
    qc.invalidateQueries({ queryKey: ['memories', novelId] })
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <input
          value={rangeStart}
          onChange={e => setRangeStart(e.target.value.replace(/\D/g, ''))}
          placeholder="起始章"
          className="w-20 border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <span className="text-xs text-muted-foreground">至</span>
        <input
          value={rangeEnd}
          onChange={e => setRangeEnd(e.target.value.replace(/\D/g, ''))}
          placeholder="结束章"
          className="w-20 border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <button
          onClick={runMilestoneBackfill}
          disabled={backfilling}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          {backfilling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          {backfilling ? '回填中...' : '回填关系里程碑'}
        </button>
        {backfillMsg && <span className="text-xs text-muted-foreground">{backfillMsg}</span>}
      </div>
      {memories.length === 0 && (
        <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">暂无记忆数据</div>
      )}
      {memories.map(m => (
        <div key={m.id} className="group border rounded-lg p-4 hover:border-primary/30 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-muted-foreground font-mono">第{m.chapter_number}章</span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${memoryTypeColor[m.memory_type] || 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}`}>
              {memoryTypeLabel[m.memory_type] || m.memory_type}
            </span>
            {m.memory_type === 'relationship_milestone' && (
              <button
                onClick={() => toggleInContext(m)}
                title={m.in_context ? '点击排除：不再注入写作/审核上下文' : '点击恢复：重新注入上下文'}
                className={`text-xs px-1.5 py-0.5 rounded-full border transition-colors ${
                  m.in_context
                    ? 'border-green-300 text-green-700 hover:bg-green-50 dark:border-green-800 dark:text-green-300 dark:hover:bg-green-950/40'
                    : 'border-gray-300 text-muted-foreground hover:bg-muted dark:border-gray-700'
                }`}
              >
                {m.in_context ? '已注入' : '已排除'}
              </button>
            )}
            <span className="text-xs text-muted-foreground ml-auto">{new Date(m.created_at).toLocaleString()}</span>
            <button onClick={() => handleDelete(m.id)}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-all"
              title="删除">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          {editingId === m.id ? (
            <div className="flex gap-2">
              <textarea
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                className="flex-1 border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring min-h-[80px]"
                autoFocus
                onKeyDown={e => { if (e.key === 'Escape') setEditingId(null) }}
              />
              <div className="flex flex-col gap-1">
                <button onClick={() => saveEdit(m.id)} disabled={saving}
                  className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '保存'}
                </button>
                <button onClick={() => setEditingId(null)} className="px-3 py-1.5 text-xs border rounded-lg hover:bg-muted">取消</button>
              </div>
            </div>
          ) : (
            <p onClick={() => startEdit(m)}
              className={`text-xs text-muted-foreground cursor-pointer hover:bg-muted/50 rounded p-1.5 transition-colors whitespace-pre-wrap ${m.in_context ? '' : 'opacity-50 line-through'}`}>
              {m.content}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}


// ── Tab 4: Outlines ──────────────────────────────────────────────────────

function OutlinesTab({ outlines, loading, qc, novelId }: { outlines: OutlineEntry[]; loading: boolean; qc: ReturnType<typeof useQueryClient>; novelId: number }) {
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  const startEdit = (o: OutlineEntry) => {
    setEditTitle(o.title)
    setEditContent(o.content)
    setEditingId(o.id)
  }

  const saveEdit = async (outlineId: number) => {
    setSaving(true)
    try {
      await adminApi.updateOutline(outlineId, { title: editTitle, content: editContent })
      qc.invalidateQueries({ queryKey: ['outlines', novelId] })
      setEditingId(null)
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
  }

  if (outlines.length === 0) {
    return <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">暂无大纲数据</div>
  }

  return (
    <div className="space-y-2">
      {outlines.map(o => (
        <div key={o.id} className="border rounded-lg p-4 hover:border-primary/30 transition-colors">
          {editingId === o.id ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground font-mono shrink-0">第{o.chapter_number}章</span>
                <input
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  className="flex-1 border rounded px-2 py-1 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  placeholder="章节标题"
                />
              </div>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring min-h-[80px]"
                autoFocus
                onKeyDown={e => { if (e.key === 'Escape') setEditingId(null) }}
              />
              <div className="flex gap-2 justify-end">
                <button onClick={() => setEditingId(null)} className="px-3 py-1.5 text-xs border rounded-lg hover:bg-muted">取消</button>
                <button onClick={() => saveEdit(o.id)} disabled={saving}
                  className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                  {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '保存'}
                </button>
              </div>
            </div>
          ) : (
            <div onClick={() => startEdit(o)} className="cursor-pointer hover:bg-muted/50 rounded p-1 transition-colors">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs text-muted-foreground font-mono">第{o.chapter_number}章</span>
                <span className="font-medium text-sm">{o.title}</span>
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground">{o.level}</span>
              </div>
              <p className="text-xs text-muted-foreground whitespace-pre-wrap">{o.content}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}


// ── Tab: Batch Replace ───────────────────────────────────────────────────

const SCOPE_OPTIONS: { key: ReplaceScope; label: string; hint: string }[] = [
  { key: 'content', label: '章节正文', hint: '小说正文' },
  { key: 'summary', label: '章节摘要', hint: '喂给后续章节的上下文' },
  { key: 'outline', label: '大纲', hint: '全书/卷/章大纲' },
  { key: 'memory', label: '记忆条目', hint: '里程碑、世界事件等' },
]

function BatchReplaceTab({ novelId, qc }: { novelId: number; qc: ReturnType<typeof useQueryClient> }) {
  const [find, setFind] = useState('')
  const [replace, setReplace] = useState('')
  const [scope, setScope] = useState<ReplaceScope[]>(['content', 'summary', 'outline', 'memory'])
  const [preview, setPreview] = useState<ReplacePreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'apply' | 'undo' | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [lastBackupId, setLastBackupId] = useState<number | null>(null)

  const { data: backups = [], refetch: refetchBackups } = useQuery({
    queryKey: ['replace-backups', novelId],
    queryFn: () => textReplaceApi.backups(novelId),
  })

  const toggleScope = (key: ReplaceScope) => {
    setPreview(null)
    setScope(prev => prev.includes(key) ? prev.filter(s => s !== key) : [...prev, key])
  }

  const errMsg = (e: any) => e?.response?.data?.detail || e?.message || '操作失败'

  const runPreview = async () => {
    if (!find.trim() || scope.length === 0) return
    setBusy('preview'); setError(''); setPreview(null)
    try {
      setPreview(await textReplaceApi.preview(novelId, find, scope))
    } catch (e: any) {
      setError(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['chapters', novelId] })
    qc.invalidateQueries({ queryKey: ['memories', novelId] })
    qc.invalidateQueries({ queryKey: ['outlines', novelId] })
    qc.invalidateQueries({ queryKey: ['novel', novelId] })
  }

  const runApply = async () => {
    setBusy('apply'); setError(''); setConfirming(false)
    try {
      const r = await textReplaceApi.apply(novelId, find, replace, scope)
      setLastBackupId(r.backup_id)
      setPreview(null)
      invalidateAll()
      await refetchBackups()
    } catch (e: any) {
      setError(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  const runUndo = async (backupId: number) => {
    setBusy('undo'); setError('')
    try {
      await textReplaceApi.undo(novelId, backupId)
      if (backupId === lastBackupId) setLastBackupId(null)
      invalidateAll()
      await refetchBackups()
    } catch (e: any) {
      setError(errMsg(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <BatchReplaceForm
        find={find} setFind={setFind} replace={replace} setReplace={setReplace}
        scope={scope} toggleScope={toggleScope} busy={busy}
        onPreview={runPreview} onReset={() => setPreview(null)}
      />

      {error && (
        <div className="text-sm text-destructive border border-destructive/30 rounded-lg px-3 py-2">{error}</div>
      )}

      {busy === 'preview' && (
        <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
      )}

      {preview && preview.total_occurrences === 0 && (
        <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">
          未找到「{preview.find}」
        </div>
      )}

      {preview && preview.total_occurrences > 0 && (
        <ReplacePreviewPanel
          preview={preview} replace={replace} busy={busy}
          onConfirm={() => setConfirming(true)}
        />
      )}

      {confirming && preview && (
        <ConfirmReplaceDialog
          preview={preview} find={find} replace={replace}
          onCancel={() => setConfirming(false)} onConfirm={runApply}
        />
      )}

      <ReplaceHistory backups={backups} busy={busy} onUndo={runUndo} />
    </div>
  )
}


function BatchReplaceForm({
  find, setFind, replace, setReplace, scope, toggleScope, busy, onPreview, onReset,
}: {
  find: string; setFind: (v: string) => void
  replace: string; setReplace: (v: string) => void
  scope: ReplaceScope[]; toggleScope: (k: ReplaceScope) => void
  busy: string | null; onPreview: () => void; onReset: () => void
}) {
  return (
    <div className="border rounded-lg p-4 space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">查找</span>
          <input
            value={find}
            onChange={e => { setFind(e.target.value); onReset() }}
            onKeyDown={e => { if (e.key === 'Enter') onPreview() }}
            placeholder="要替换掉的词，如 林月华"
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-muted-foreground">替换为（留空则删除该词）</span>
          <input
            value={replace}
            onChange={e => setReplace(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') onPreview() }}
            placeholder="新的词，如 林砚"
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-muted-foreground">范围</span>
        {SCOPE_OPTIONS.map(opt => (
          <label key={opt.key} className="flex items-center gap-1.5 text-sm cursor-pointer" title={opt.hint}>
            <input
              type="checkbox"
              checked={scope.includes(opt.key)}
              onChange={() => toggleScope(opt.key)}
              className="rounded border-input"
            />
            {opt.label}
          </label>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onPreview}
          disabled={!find.trim() || scope.length === 0 || busy !== null}
          className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          预览命中
        </button>
        <span className="text-xs text-muted-foreground">
          纯文本匹配，不支持正则。执行前必须先预览，替换后可撤销。
        </span>
      </div>
    </div>
  )
}


const TABLE_LABEL: Record<string, string> = {
  chapters: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  outlines: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  memories: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
}

function ReplacePreviewPanel({
  preview, replace, busy, onConfirm,
}: {
  preview: ReplacePreview; replace: string; busy: string | null; onConfirm: () => void
}) {
  return (
    <>
      <div className="flex items-center gap-3 flex-wrap">
        <div className="text-sm">
          共 <span className="font-bold text-primary">{preview.total_occurrences}</span> 处，
          分布在 <span className="font-bold">{preview.affected_rows}</span> 个位置
        </div>
        <button
          onClick={onConfirm}
          disabled={busy !== null}
          className="ml-auto px-4 py-2 text-sm bg-destructive text-destructive-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          确认替换
        </button>
      </div>

      {preview.truncated && (
        <div className="text-xs text-amber-600 dark:text-amber-400">
          位置过多，以下只列出前 {preview.rows.length} 个。执行时仍会替换全部 {preview.total_occurrences} 处。
        </div>
      )}

      <div className="space-y-2">
        {preview.rows.map(row => (
          <div key={`${row.table}:${row.row_id}:${row.field}`} className="border rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <span className={`text-xs px-1.5 py-0.5 rounded-full ${TABLE_LABEL[row.table] || 'bg-muted'}`}>
                {row.label}
              </span>
              <span className="text-xs text-muted-foreground">{row.count} 处</span>
            </div>
            {row.snippets.map((sn, i) => (
              <p key={i} className="text-xs text-muted-foreground font-mono leading-relaxed">
                …{sn.split(preview.find).map((seg, j, arr) => (
                  <span key={j}>
                    {seg}
                    {j < arr.length - 1 && (
                      <>
                        <span className="bg-destructive/20 line-through px-0.5">{preview.find}</span>
                        <span className="bg-emerald-500/20 px-0.5">{replace}</span>
                      </>
                    )}
                  </span>
                ))}…
              </p>
            ))}
          </div>
        ))}
      </div>
    </>
  )
}


function ConfirmReplaceDialog({
  preview, find, replace, onCancel, onConfirm,
}: {
  preview: ReplacePreview; find: string; replace: string
  onCancel: () => void; onConfirm: () => void
}) {
  const scopeLabels = preview.scope
    .map(s => SCOPE_OPTIONS.find(o => o.key === s)?.label || s)
    .join('、')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onCancel}>
      <div className="bg-background border rounded-xl p-5 max-w-md w-full space-y-3" onClick={e => e.stopPropagation()}>
        <h3 className="font-bold">确认全书替换</h3>
        <div className="text-sm space-y-1.5">
          <p>
            将把 <span className="font-mono bg-destructive/20 px-1 rounded">{find}</span>
            {' → '}
            <span className="font-mono bg-emerald-500/20 px-1 rounded">{replace || '（删除）'}</span>
          </p>
          <p className="text-muted-foreground">
            影响 <span className="font-bold text-foreground">{preview.total_occurrences}</span> 处，
            <span className="font-bold text-foreground">{preview.affected_rows}</span> 个位置
          </p>
          <p className="text-muted-foreground">范围：{scopeLabels}</p>
        </div>
        <p className="text-xs text-muted-foreground border-t pt-2">
          原文会自动备份，替换后可在下方「替换历史」一键撤销。
        </p>
        <div className="flex gap-2 justify-end pt-1">
          <button onClick={onCancel} className="px-4 py-2 text-sm border rounded-lg hover:bg-muted">
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-destructive text-destructive-foreground rounded-lg hover:opacity-90"
          >
            执行替换
          </button>
        </div>
      </div>
    </div>
  )
}


function ReplaceHistory({
  backups, busy, onUndo,
}: {
  backups: ReplaceBackup[]; busy: string | null; onUndo: (id: number) => void
}) {
  if (backups.length === 0) return null
  return (
    <div className="border-t pt-4 space-y-2">
      <h3 className="text-sm font-medium">替换历史</h3>
      {backups.map(b => (
        <div key={b.id} className="flex items-center gap-2 text-sm border rounded-lg px-3 py-2 flex-wrap">
          <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{b.find_text}</span>
          <span className="text-muted-foreground">→</span>
          <span className="font-mono text-xs bg-muted px-1.5 py-0.5 rounded">{b.replace_text || '（删除）'}</span>
          <span className="text-xs text-muted-foreground">
            {b.total_occurrences} 处 / {b.affected_rows} 个位置
          </span>
          <span className="text-xs text-muted-foreground">
            {new Date(b.created_at).toLocaleString('zh-CN')}
          </span>
          {b.undone_at ? (
            <span className="ml-auto text-xs text-muted-foreground">已撤销</span>
          ) : (
            <button
              onClick={() => onUndo(b.id)}
              disabled={busy !== null}
              className="ml-auto text-xs px-2.5 py-1 border rounded-md hover:bg-muted disabled:opacity-50"
            >
              {busy === 'undo' ? '撤销中…' : '撤销'}
            </button>
          )}
        </div>
      ))}
    </div>
  )
}


// ── Tab 0: Search & Fix ──────────────────────────────────────────────────

function SearchFixTab({ novelId, qc }: { novelId: number; qc: ReturnType<typeof useQueryClient> }) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [editKey, setEditKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [saving, setSaving] = useState(false)

  const { data: hits = [], isFetching, refetch } = useQuery({
    queryKey: ['corrections-search', novelId, query],
    queryFn: () => correctionsApi.search(novelId, query),
    enabled: query.length > 0,
  })

  const runSearch = () => setQuery(input.trim())

  const keyOf = (h: CorrectionHit) => `${h.source}:${h.id}:${h.field}`

  const startEdit = (h: CorrectionHit) => {
    setEditValue(h.value)
    setEditKey(keyOf(h))
  }

  const saveEdit = async (h: CorrectionHit) => {
    setSaving(true)
    try {
      await correctionsApi.apply(novelId, { source: h.source, id: h.id, field: h.field, value: editValue })
      // 修改可能影响角色/章节/记忆等缓存，统一失效
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      qc.invalidateQueries({ queryKey: ['chapters', novelId] })
      qc.invalidateQueries({ queryKey: ['memories', novelId] })
      qc.invalidateQueries({ queryKey: ['outlines', novelId] })
      setEditKey(null)
      await refetch()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') runSearch() }}
            placeholder="搜索一个事实关键词（如 皇城、北方），跨记忆/摘要/角色/地点查找并修正"
            className="w-full border rounded-lg pl-9 pr-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </div>
        <button
          onClick={runSearch}
          disabled={!input.trim()}
          className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50"
        >
          搜索
        </button>
      </div>

      {isFetching && (
        <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
      )}

      {!isFetching && query && hits.length === 0 && (
        <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">
          未找到包含「{query}」的内容
        </div>
      )}

      {!isFetching && hits.length > 0 && (
        <>
          <div className="text-xs text-muted-foreground">共 {hits.length} 条命中</div>
          <div className="space-y-2">
            {hits.map(h => {
              const isEditing = editKey === keyOf(h)
              return (
                <div key={keyOf(h)} className="border rounded-lg p-4 hover:border-primary/30 transition-colors">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${SOURCE_COLOR[h.source] || 'bg-muted'}`}>
                      {SOURCE_LABEL[h.source] || h.source}
                    </span>
                    <span className="font-medium text-sm">{h.title}</span>
                    <span className="text-xs text-muted-foreground">{h.context}</span>
                    <span className="text-xs font-mono text-muted-foreground/70">{h.field}</span>
                    <span className={`ml-auto text-xs px-1.5 py-0.5 rounded-full ${
                      h.match === 'semantic'
                        ? 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300'
                        : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'
                    }`}>
                      {h.match === 'semantic' ? `语义${h.score != null ? ` ${h.score}` : ''}` : '关键词'}
                    </span>
                  </div>
                  {isEditing ? (
                    <div className="flex gap-2">
                      <textarea
                        value={editValue}
                        onChange={e => setEditValue(e.target.value)}
                        className="flex-1 border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring min-h-[80px]"
                        autoFocus
                        onKeyDown={e => { if (e.key === 'Escape') setEditKey(null) }}
                      />
                      <div className="flex flex-col gap-1">
                        <button onClick={() => saveEdit(h)} disabled={saving}
                          className="px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '保存'}
                        </button>
                        <button onClick={() => setEditKey(null)} className="px-3 py-1.5 text-xs border rounded-lg hover:bg-muted">取消</button>
                      </div>
                    </div>
                  ) : (
                    <p onClick={() => startEdit(h)}
                      className="text-xs text-muted-foreground cursor-pointer hover:bg-muted/50 rounded p-1.5 transition-colors whitespace-pre-wrap">
                      {h.value || <span className="italic">（空，点击编辑）</span>}
                    </p>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
