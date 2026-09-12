import { useState } from 'react'
import { Loader2, Sparkles, X, AlertTriangle } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgApi, type RpgGenerateKind, type RpgWizardExtract } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'
import { INPUT, PANEL } from './rpgUi'

/** 一摊里 kind 对应的字段名，取回来的那一摊列表就在这个键上 */
const LIST_KEY: Record<RpgGenerateKind, keyof RpgWizardExtract> = {
  location: 'locations',
  npc: 'npcs',
  item: 'items',
  action: 'actions',
}

/**
 * 某一摊（地点/角色/道具/动作）的「AI 生成」入口。
 *
 * 和构思向导共用后端清洗：引用的数值名/地点名对不上会被丢进 dropped，这里照样
 * 显示给作者看，不咽下去。白名单由后端查库，前端不用管。
 *
 * 生成完就地预览、逐条勾选，确认后才交给 onApply 建行——AI 不该悄悄往库里塞东西。
 */
export default function BatchGenerate<T extends { name: string }>({
  moduleId, kind, placeholder, renderRow, onApply,
}: {
  moduleId: number
  kind: RpgGenerateKind
  /** 指令框的示例词 */
  placeholder: string
  /** 预览里每条怎么显示。名字之外的那点信息（效果、地点、关系）由各摊自己拼 */
  renderRow: (row: T) => React.ReactNode
  /** 勾上的那些交给父组件建行 + 刷新 */
  onApply: (rows: T[]) => Promise<void>
}) {
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)

  const [open, setOpen] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [count, setCount] = useState(3)
  const [busy, setBusy] = useState(false)
  const [rows, setRows] = useState<T[] | null>(null)
  const [dropped, setDropped] = useState<string[]>([])
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [applying, setApplying] = useState(false)

  const reset = () => {
    setOpen(false); setInstruction(''); setCount(3)
    setRows(null); setDropped([]); setPicked(new Set())
  }

  const run = async () => {
    setBusy(true)
    try {
      const res = await rpgApi.modules.generate(moduleId, kind, {
        instruction, count, nsfw: nsfwMode,
      })
      const list = (res[LIST_KEY[kind]] as T[] | undefined) || []
      setRows(list)
      setDropped(res.dropped || [])
      setPicked(new Set(list.map((_, i) => i)))
      if (!list.length) toast('这次没生成出能用的内容，把要求写具体点再试', { icon: '🤔' })
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'AI 生成失败')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (i: number) => setPicked(prev => {
    const next = new Set(prev)
    next.has(i) ? next.delete(i) : next.add(i)
    return next
  })

  const apply = async () => {
    if (!rows) return
    const chosen = rows.filter((_, i) => picked.has(i))
    if (!chosen.length) return
    setApplying(true)
    try {
      await onApply(chosen)
      toast.success(`填进了 ${chosen.length} 项`)
      reset()
    } catch {
      toast.error('填入时出错，部分内容可能没建上')
    } finally {
      setApplying(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
          border-primary/30 rounded-lg text-primary hover:bg-primary/5"
      >
        <Sparkles className="w-3.5 h-3.5" /> AI 生成
      </button>
    )
  }

  return (
    <div className={`${PANEL} p-3 space-y-3`} style={{ borderColor: 'hsl(var(--primary) / 0.3)' }}>
      <div className="flex items-center gap-1.5">
        <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="text-xs font-medium text-primary">AI 生成</span>
        <button onClick={reset} className="ml-auto p-1 rounded-md hover:bg-primary/10 text-muted-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <textarea
        value={instruction}
        onChange={e => setInstruction(e.target.value)}
        placeholder={placeholder}
        className={`${INPUT} resize-y min-h-[3.5rem]`}
        disabled={busy}
      />
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground shrink-0">数量 {count}</span>
        <input
          type="range" min={1} max={10} value={count}
          onChange={e => setCount(Number(e.target.value))}
          disabled={busy}
          className="flex-1 accent-[hsl(var(--primary))]"
        />
        <button
          onClick={run}
          disabled={busy}
          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-md
            bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40 shrink-0"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          {rows ? '重新生成' : '生成'}
        </button>
      </div>

      {rows && rows.length > 0 && (
        <div className="space-y-1.5">
          {rows.map((row, i) => (
            <label
              key={i}
              className={`block border rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                picked.has(i) ? 'border-primary/50 bg-primary/5' : 'opacity-60'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" checked={picked.has(i)} onChange={() => toggle(i)}
                  className="accent-[hsl(var(--primary))]"
                />
                <span className="text-sm font-medium">{row.name}</span>
                {renderRow(row)}
              </div>
            </label>
          ))}
        </div>
      )}

      {dropped.length > 0 && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2.5 text-xs space-y-1">
          <div className="flex items-center gap-1.5 font-medium text-amber-600">
            <AlertTriangle className="w-3.5 h-3.5" /> 有些引用对不上，去掉了
          </div>
          {dropped.map((d, i) => <p key={i} className="text-muted-foreground">· {d}</p>)}
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="flex justify-end gap-2">
          <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
            取消
          </button>
          <button
            onClick={apply}
            disabled={applying || picked.size === 0}
            className="flex items-center gap-1 text-sm px-4 py-1.5 rounded-lg
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {applying && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            填入（{picked.size}）
          </button>
        </div>
      )}
    </div>
  )
}
