import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sun, Moon, Save, Trash2, Loader2, RefreshCw } from 'lucide-react'
import { novelsApi, chaptersApi, charactersApi, adminApi } from '@/api/client'
import type { Character, Chapter, Memory, OutlineEntry } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

type TabKey = 'characters' | 'summaries' | 'memories' | 'outlines'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'characters', label: '角色状态' },
  { key: 'summaries', label: '章节摘要' },
  { key: 'memories', label: '记忆条目' },
  { key: 'outlines', label: '大纲' },
]

const STATE_FIELDS = ['location', 'current_goal', 'titles', 'affiliation', 'known_secrets'] as const

const memoryTypeColor: Record<string, string> = {
  chapter_summary: 'bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300',
  scene_summary: 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300',
  volume_summary: 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300',
  world_event: 'bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
}

export default function Admin() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme } = useSettingsStore()

  const [activeTab, setActiveTab] = useState<TabKey>('characters')

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
        <button onClick={toggleTheme} className="p-2 rounded-md hover:bg-muted transition-colors"
          title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}>
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
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

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
  }

  if (memories.length === 0) {
    return <div className="text-sm text-muted-foreground text-center py-12 border rounded-lg border-dashed">暂无记忆数据</div>
  }

  return (
    <div className="space-y-2">
      {memories.map(m => (
        <div key={m.id} className="group border rounded-lg p-4 hover:border-primary/30 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-muted-foreground font-mono">第{m.chapter_number}章</span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full ${memoryTypeColor[m.memory_type] || 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'}`}>
              {m.memory_type}
            </span>
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
              className="text-xs text-muted-foreground cursor-pointer hover:bg-muted/50 rounded p-1.5 transition-colors whitespace-pre-wrap">
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
