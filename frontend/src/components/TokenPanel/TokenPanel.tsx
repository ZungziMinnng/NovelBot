import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Loader2, Save, RefreshCw } from 'lucide-react'
import { novelsApi, chaptersApi, type Novel } from '@/api/client'
import toast from 'react-hot-toast'

const CONTEXT_SECTIONS: Array<{ key: string; label: string; source: 'rag' | 'full' | 'field' }> = [
  { key: 'core_setting', label: '世界观设定', source: 'rag' },
  { key: 'book_summary', label: '全书概要', source: 'field' },
  { key: 'arc_summary', label: '故事弧概要', source: 'full' },
  { key: 'chapter_outline', label: '本章大纲', source: 'full' },
  { key: 'rolling_summary', label: '近期摘要', source: 'full' },
  { key: 'rag_context', label: 'RAG 历史检索', source: 'rag' },
  { key: 'notes_context', label: '补充设定', source: 'rag' },
  { key: 'recent_text', label: '上一章原文', source: 'full' },
  { key: 'characters', label: '角色状态', source: 'rag' },
  { key: 'items', label: '道具', source: 'rag' },
  { key: 'systems', label: '系统', source: 'rag' },
  { key: 'locations', label: '地点', source: 'rag' },
  { key: 'factions', label: '势力', source: 'rag' },
  { key: 'techniques', label: '功法', source: 'rag' },
]

const SOURCE_BADGE: Record<string, { text: string; cls: string }> = {
  rag:   { text: 'RAG', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  full:  { text: '全量', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  field: { text: '字段', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
}

interface TokenPanelProps {
  novelId: number
  novel: Novel
  onClose: () => void
}

export default function TokenPanel({ novelId, novel, onClose }: TokenPanelProps) {
  const qc = useQueryClient()

  const { data: chapters = [] } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  const [chapterNum, setChapterNum] = useState(() => (novel.current_chapter || 0) + 1)
  const [config, setConfig] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [reindexing, setReindexing] = useState(false)

  useEffect(() => {
    const cfg: Record<string, boolean> = {}
    for (const s of CONTEXT_SECTIONS) {
      cfg[s.key] = novel.context_config?.[s.key] ?? true
    }
    setConfig(cfg)
    setDirty(false)
  }, [novel.id])

  const { data: preview, isLoading } = useQuery({
    queryKey: ['context-preview', novelId, chapterNum],
    queryFn: () => novelsApi.contextPreview(novelId, chapterNum),
  })

  const toggle = (key: string) => {
    setConfig(prev => ({ ...prev, [key]: !prev[key] }))
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await novelsApi.update(novelId, { context_config: config } as any)
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
      qc.invalidateQueries({ queryKey: ['context-preview', novelId] })
      setDirty(false)
      toast.success('上下文配置已保存')
    } catch {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const tokens = preview?.token_estimate || {}
  const totalTokens = tokens.total || 0

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-96 bg-background border-l shadow-2xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-sm font-semibold">上下文配置</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Chapter selector */}
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium shrink-0">预览章节</label>
            <select
              value={chapterNum}
              onChange={e => setChapterNum(Number(e.target.value))}
              className="flex-1 border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value={(novel.current_chapter || 0) + 1}>
                第 {(novel.current_chapter || 0) + 1} 章（下一章）
              </option>
              {chapters.map(c => (
                <option key={c.id} value={c.number}>第 {c.number} 章</option>
              ))}
            </select>
          </div>

          {/* Total token badge */}
          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> 计算中...
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">预估总量</span>
              <span className="px-2 py-0.5 text-xs font-medium bg-primary/10 text-primary rounded-full">
                ~{totalTokens.toLocaleString()} tokens
              </span>
            </div>
          )}

          {/* Section list */}
          <div className="space-y-1">
            {CONTEXT_SECTIONS.map(({ key, label, source }) => {
              const tok = tokens[key] ?? 0
              const enabled = config[key] ?? true
              const badge = SOURCE_BADGE[source]
              return (
                <label
                  key={key}
                  className={`flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
                    enabled ? 'hover:bg-muted/50' : 'opacity-50 hover:opacity-70'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={() => toggle(key)}
                    className="rounded border-gray-300 text-primary focus:ring-primary/50 h-3.5 w-3.5"
                  />
                  <span className="text-xs flex-1">{label}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${badge.cls}`}>{badge.text}</span>
                  <span className={`text-xs tabular-nums w-14 text-right ${tok > 0 ? 'text-muted-foreground' : 'text-muted-foreground/40'}`}>
                    {tok > 0 ? `~${tok.toLocaleString()}` : '0'}
                  </span>
                </label>
              )
            })}
          </div>

          {/* Fixed sections (always on) */}
          <div className="border-t pt-3 space-y-1">
            <span className="text-xs text-muted-foreground font-medium">固定区块</span>
            {([
              ['系统提示', tokens.system_prompt ?? 0],
              ['写作任务', tokens.task_instruction ?? 0],
            ] as [string, number][]).map(([label, tok]) => (
              <div key={label} className="flex items-center gap-3 px-3 py-2">
                <span className="text-xs flex-1 text-muted-foreground">{label}</span>
                <span className="text-xs tabular-nums text-muted-foreground">
                  ~{tok.toLocaleString()}
                </span>
              </div>
            ))}
          </div>

          {/* Total */}
          <div className="border-t pt-3 flex items-center justify-between px-3">
            <span className="text-xs font-medium">合计</span>
            <span className="text-xs font-medium tabular-nums">
              ~{totalTokens.toLocaleString()} tokens
            </span>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t shrink-0 space-y-2">
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            {dirty ? '保存配置' : '无变更'}
          </button>
          <button
            onClick={async () => {
              setReindexing(true)
              try {
                const counts = await novelsApi.reindexEntities(novelId)
                const total = Object.values(counts).reduce((a, b) => a + b, 0)
                toast.success(`已重建 ${total} 条实体索引`)
              } catch {
                toast.error('重建实体索引失败')
              } finally {
                setReindexing(false)
              }
            }}
            disabled={reindexing}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 border rounded-lg text-sm hover:bg-muted transition-colors disabled:opacity-50"
          >
            {reindexing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            {reindexing ? '重建中...' : '重建实体索引'}
          </button>
        </div>
      </div>
    </>
  )
}
