import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X, Loader2, Save, RefreshCw } from 'lucide-react'
import { novelsApi, chaptersApi, type ContextConfigValue, type Novel } from '@/api/client'
import toast from 'react-hot-toast'

const formatCny = (value: number) => {
  if (!Number.isFinite(value) || value === 0) return '¥0.00'
  if (value < 0.0001) return `¥${value.toFixed(6)}`
  if (value < 0.01) return `¥${value.toFixed(4)}`
  return `¥${value.toFixed(2)}`
}

const CONTEXT_SECTIONS: Array<{ key: string; label: string; source: 'rag' | 'full' | 'field' | 'name' | 'mixed' }> = [
  { key: 'core_setting', label: '世界观设定', source: 'mixed' },
  { key: 'book_summary', label: '全书概要', source: 'field' },
  { key: 'arc_summary', label: '故事弧概要', source: 'full' },
  { key: 'story_threads', label: '伏笔/秘密', source: 'field' },
  { key: 'chapter_outline', label: '本章大纲', source: 'full' },
  { key: 'rolling_summary', label: '近期摘要', source: 'full' },
  { key: 'rag_context', label: 'RAG 历史检索', source: 'rag' },
  { key: 'notes_context', label: '补充设定', source: 'mixed' },
  { key: 'recent_text', label: '上一章原文', source: 'full' },
  { key: 'characters', label: '角色状态', source: 'name' },
  { key: 'items', label: '道具', source: 'name' },
  { key: 'systems', label: '系统', source: 'name' },
  { key: 'locations', label: '地点', source: 'name' },
  { key: 'factions', label: '势力', source: 'name' },
  { key: 'techniques', label: '功法', source: 'name' },
]

const SOURCE_BADGE: Record<string, { text: string; cls: string }> = {
  name:  { text: '名称匹配', cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  rag:   { text: 'RAG', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  full:  { text: '全量', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  field: { text: '字段', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  mixed: { text: '混合', cls: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300' },
}

const ENTITY_TOP_K_SECTIONS: Array<{ configKey: string; label: string; defaultVal: number }> = [
  { configKey: 'characters_top_k', label: '角色', defaultVal: 8 },
  { configKey: 'items_top_k', label: '道具', defaultVal: 5 },
  { configKey: 'systems_top_k', label: '系统', defaultVal: 3 },
  { configKey: 'locations_top_k', label: '地点', defaultVal: 5 },
  { configKey: 'factions_top_k', label: '势力', defaultVal: 4 },
  { configKey: 'techniques_top_k', label: '功法', defaultVal: 4 },
  { configKey: 'notes_top_k', label: '补充设定', defaultVal: 5 },
]

interface ContextConfigContentProps {
  novelId: number
  novel: Novel
}

export function ContextConfigContent({ novelId, novel }: ContextConfigContentProps) {
  const qc = useQueryClient()

  const { data: chapters = [] } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  const maxChapterNum = chapters.length > 0 ? Math.max(...chapters.map(c => c.number)) : 0
  const [chapterNum, setChapterNum] = useState(() => maxChapterNum + 1)
  const [targetWords, setTargetWords] = useState(5000)
  const [config, setConfig] = useState<Record<string, ContextConfigValue>>({})
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [reindexing, setReindexing] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)

  useEffect(() => {
    const cfg: Record<string, ContextConfigValue> = {}
    for (const s of CONTEXT_SECTIONS) {
      cfg[s.key] = novel.context_config?.[s.key] ?? true
    }
    for (const s of ENTITY_TOP_K_SECTIONS) {
      cfg[s.configKey] = novel.context_config?.[s.configKey] ?? s.defaultVal
    }
    setConfig(cfg)
    setDirty(false)
  }, [novel.id])

  const { data: preview, isLoading } = useQuery({
    queryKey: ['context-preview', novelId, chapterNum, targetWords],
    queryFn: () => novelsApi.contextPreview(novelId, chapterNum, '', targetWords),
  })

  const toggle = (key: string) => {
    setConfig(prev => ({ ...prev, [key]: !prev[key] }))
    setDirty(true)
  }

  const setTopK = (key: string, val: number) => {
    setConfig(prev => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await novelsApi.update(novelId, { context_config: config })
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
  const pricing = preview?.pricing
  const priceConfigured = Boolean(pricing?.configured)
  const sectionCost = (tokenCount: number) => (
    tokenCount * (pricing?.input_price_cny_per_million || 0) / 1_000_000
  )
  const metaSourceMap: Record<string, string> = Object.fromEntries(
    (preview?.meta || []).map((m: any) => [m.key, m.source])
  )

  return (
    <div className="space-y-4">
      {/* Chapter selector */}
      <div className="flex items-center gap-2">
        <label className="text-xs font-medium shrink-0">预览章节</label>
        <select
          value={chapterNum}
          onChange={e => setChapterNum(Number(e.target.value))}
          className="flex-1 border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value={maxChapterNum + 1}>
            第 {maxChapterNum + 1} 章（下一章）
          </option>
          {[...chapters].sort((a, b) => a.number - b.number).map(c => (
            <option key={c.id} value={c.number}>第 {c.number} 章</option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-2">
        <label className="text-xs font-medium shrink-0">目标字数</label>
        <input
          type="number"
          min={3500}
          max={8000}
          step={500}
          value={targetWords}
          onChange={e => setTargetWords(Math.max(3500, Math.min(8000, Number(e.target.value) || 5000)))}
          className="flex-1 border rounded-lg px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* Estimated chapter cost */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> 计算中...
        </div>
      ) : !priceConfigured ? (
        <div className="border border-amber-200 bg-amber-50/70 dark:border-amber-900 dark:bg-amber-950/30 rounded-lg px-3 py-2.5">
          <p className="text-xs font-medium text-amber-800 dark:text-amber-300">当前 Writer 未配置 Token 价格</p>
          <p className="text-[11px] text-muted-foreground mt-1">
            {pricing?.model_name || '未解析 Writer 模型'} · 当前上下文约 {totalTokens.toLocaleString()} tokens
          </p>
        </div>
      ) : (
        <div className="border rounded-lg px-3 py-3 bg-muted/20">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground truncate">{pricing?.model_name || 'Writer 模型'}</p>
              <p className="text-[11px] text-muted-foreground mt-1">
                输入 {formatCny(pricing?.input_cost_cny || 0)} + 预计输出 {formatCny(pricing?.output_cost_cny || 0)}
              </p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-[11px] text-muted-foreground">预计本章</p>
              <p className="text-base font-semibold tabular-nums">{formatCny(pricing?.total_cost_cny || 0)}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2 pt-2 border-t text-[11px] text-muted-foreground tabular-nums">
            <span>输入约 {totalTokens.toLocaleString()} tokens</span>
            <span>输出预留 {(pricing?.expected_output_tokens || 0).toLocaleString()} tokens</span>
            {preview?.dynamic_budget?.input_budget ? (
              <span>输入预算上限 {formatCny(pricing?.budget_input_cost_cny || 0)}</span>
            ) : null}
          </div>
        </div>
      )}

      {/* Section list */}
      <div className="space-y-1">
        {CONTEXT_SECTIONS.map(({ key, label, source: defaultSource }) => {
          const tok = tokens[key] ?? 0
          const enabled = Boolean(config[key] ?? true)
          const actualSource = metaSourceMap[key] || defaultSource
          const badge = SOURCE_BADGE[actualSource]
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
              {badge && <span className={`text-[10px] px-1.5 py-0.5 rounded ${badge.cls}`}>{badge.text}</span>}
              <span className={`w-24 text-right tabular-nums ${tok > 0 ? 'text-muted-foreground' : 'text-muted-foreground/40'}`}>
                <span className="block text-xs">{priceConfigured ? formatCny(sectionCost(tok)) : '未计价'}</span>
                <span className="block text-[10px]">{tok > 0 ? `~${tok.toLocaleString()} tokens` : '0 tokens'}</span>
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
            <span className="text-right tabular-nums text-muted-foreground">
              <span className="block text-xs">{priceConfigured ? formatCny(sectionCost(tok)) : '未计价'}</span>
              <span className="block text-[10px]">~{tok.toLocaleString()} tokens</span>
            </span>
          </div>
        ))}
      </div>

      {/* Total */}
      <div className="border-t pt-3 flex items-start justify-between px-3 gap-4">
        <div>
          <span className="text-xs font-medium">上下文输入合计</span>
          {priceConfigured && pricing && (
            <p className="text-[10px] text-muted-foreground mt-0.5">
              不含预计输出 {formatCny(pricing.output_cost_cny)}
            </p>
          )}
        </div>
        <div className="text-right tabular-nums">
          <span className="block text-xs font-medium">{priceConfigured ? formatCny(pricing?.input_cost_cny || 0) : '未计价'}</span>
          <span className="block text-[10px] text-muted-foreground">~{totalTokens.toLocaleString()} tokens</span>
        </div>
      </div>

      {/* Per-entity RAG top_k */}
      <div className="border-t pt-3">
        <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">实体 RAG 检索数量</label>
        <p className="text-xs text-muted-foreground mb-3">名称匹配优先，未匹配时使用 RAG 检索前 N 条</p>
        <div className="space-y-2">
          {ENTITY_TOP_K_SECTIONS.map(({ configKey, label, defaultVal }) => (
            <div key={configKey} className="flex items-center justify-between px-3">
              <span className="text-xs">{label}</span>
              <input
                type="number"
                min={0}
                max={20}
                value={Number(config[configKey] ?? defaultVal)}
                onChange={e => setTopK(configKey, Math.max(0, Math.min(20, Number(e.target.value) || 0)))}
                className="w-14 text-center border rounded-lg px-2 py-1 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Actions */}
      <div className="border-t pt-3 space-y-2">
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
        <button
          onClick={async () => {
            if (!confirm('将删除并按当前嵌入模型重建整本书的向量库（实体+设定+全部摘要），可能耗时较久。用于修复维度不匹配导致的写入失败。确认继续？')) return
            setRebuilding(true)
            try {
              await novelsApi.rebuildVectors(novelId)
              toast.success('向量库已重建')
            } catch {
              toast.error('重建向量库失败')
            } finally {
              setRebuilding(false)
            }
          }}
          disabled={rebuilding}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 border rounded-lg text-sm hover:bg-muted transition-colors disabled:opacity-50"
        >
          {rebuilding ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          {rebuilding ? '重建中...' : '重建向量库'}
        </button>
      </div>
    </div>
  )
}

interface TokenPanelProps {
  novelId: number
  novel: Novel
  onClose: () => void
}

export default function TokenPanel({ novelId, novel, onClose }: TokenPanelProps) {
  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" />
      <div className="fixed right-0 top-0 h-full w-full sm:w-[560px] bg-background border-l shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-sm font-semibold">上下文配置</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          <ContextConfigContent novelId={novelId} novel={novel} />
        </div>
      </div>
    </>
  )
}
