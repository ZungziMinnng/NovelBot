import { useState } from 'react'
import { Loader2, Wand2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgApi, type RpgNpc, type RpgNpcRefineField, type RpgNpcRefineItem } from '@/api/client'
import { INPUT, PANEL } from './rpgUi'

const FIELD_LABEL: Record<RpgNpcRefineField, string> = {
  persona: '性格',
  appearance: '外貌',
  description: '身份',
}
const ALL_FIELDS: RpgNpcRefineField[] = ['persona', 'appearance', 'description']
const DEFAULT_FIELDS: RpgNpcRefineField[] = ['persona', 'appearance']
// 后端 _REFINE_MAX_NPCS，超了直接 400，前端先拦住
const MAX_NPCS = 12

const keyOf = (npcId: number, field: string) => `${npcId}:${field}`

/**
 * 「批量 AI 优化」：挑几个角色、挑几栏，一人一栏单独重写。
 *
 * 和单栏「AI 优化」用同一套写法和上下文，只是并发跑。端点只回预览，
 * 作者改完、勾完，这里才按人 PATCH 回去——AI 不该悄悄改掉人家写好的设定。
 */
export default function NpcBatchRefine({ moduleId, npcs, onDone }: {
  moduleId: number
  npcs: RpgNpc[]
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [fields, setFields] = useState<Set<RpgNpcRefineField>>(new Set(DEFAULT_FIELDS))
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)
  const [items, setItems] = useState<RpgNpcRefineItem[] | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [writing, setWriting] = useState(false)

  const reset = () => {
    setOpen(false); setChecked(new Set()); setFields(new Set(DEFAULT_FIELDS)); setInstruction('')
    setItems(null); setDraft({}); setPicked(new Set())
  }

  const toggle = <T,>(set: React.Dispatch<React.SetStateAction<Set<T>>>, v: T) => set(prev => {
    const next = new Set(prev)
    next.has(v) ? next.delete(v) : next.add(v)
    return next
  })

  const allChecked = npcs.length > 0 && checked.size === npcs.length
  const tooMany = checked.size > MAX_NPCS

  const run = async () => {
    setBusy(true)
    try {
      // 按列表顺序发，回来的预览顺序就和上面勾的顺序一致
      const res = await rpgApi.npcs.refine(moduleId, {
        npc_ids: npcs.filter(n => checked.has(n.id)).map(n => n.id),
        fields: ALL_FIELDS.filter(f => fields.has(f)),
        instruction,
      })
      setItems(res.items)
      setDraft(Object.fromEntries(res.items.map(i => [keyOf(i.npc_id, i.field), i.text])))
      setPicked(new Set(res.items.filter(i => !i.error).map(i => keyOf(i.npc_id, i.field))))
      if (!res.items.some(i => !i.error)) toast.error('这次一条都没写成，看看每条下面的原因')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'AI 优化失败')
    } finally {
      setBusy(false)
    }
  }

  const chosen = (items || []).filter(i => !i.error && picked.has(keyOf(i.npc_id, i.field))
    && (draft[keyOf(i.npc_id, i.field)] || '').trim())

  const write = async () => {
    // 同一个人的几栏合成一次 PATCH，只发改了的那几栏
    const byNpc = new Map<number, Partial<Record<RpgNpcRefineField, string>>>()
    for (const it of chosen) {
      byNpc.set(it.npc_id, { ...byNpc.get(it.npc_id), [it.field]: draft[keyOf(it.npc_id, it.field)].trim() })
    }
    setWriting(true)
    let done = 0
    try {
      for (const [id, patch] of byNpc) {
        await rpgApi.npcs.update(id, patch)
        done += 1
      }
      toast.success(`写回了 ${done} 个角色`)
      onDone()
      reset()
    } catch (e: any) {
      // 逐个人发的，前面成功的已经进库了，照实说
      toast.error(`写到第 ${done + 1} 个人时出错，前 ${done} 个已经写进去了`)
      onDone()
    } finally {
      setWriting(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
          border-primary/30 rounded-lg text-primary hover:bg-primary/5"
      >
        <Wand2 className="w-3.5 h-3.5" /> 批量 AI 优化
      </button>
    )
  }

  const groups = items
    ? npcs.filter(n => items.some(i => i.npc_id === n.id))
        .map(n => ({ npc: n, rows: items.filter(i => i.npc_id === n.id) }))
    : []

  return (
    <div className={`${PANEL} p-3 space-y-3`} style={{ borderColor: 'hsl(var(--primary) / 0.3)' }}>
      <div className="flex items-center gap-1.5">
        <Wand2 className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="text-xs font-medium text-primary">批量 AI 优化</span>
        <button onClick={reset} aria-label="收起" className="ml-auto p-1 rounded-md hover:bg-primary/10 text-muted-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {!items && (
        <>
          <div className="space-y-1">
            <div className="flex items-center">
              <span className="text-xs text-muted-foreground">改谁（一次最多 {MAX_NPCS} 个）</span>
              <button
                onClick={() => setChecked(allChecked ? new Set() : new Set(npcs.map(n => n.id)))}
                className="ml-auto text-xs text-primary hover:underline"
              >
                {allChecked ? '全不选' : '全选'}
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto border rounded-lg divide-y">
              {npcs.map(npc => (
                <label key={npc.id} className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-muted/40">
                  <input
                    type="checkbox" checked={checked.has(npc.id)} onChange={() => toggle(setChecked, npc.id)}
                    disabled={busy} className="accent-[hsl(var(--primary))]"
                  />
                  <span className="text-sm">{npc.name}</span>
                  {npc.role === 'protagonist' && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">
                      主角模板
                    </span>
                  )}
                </label>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-muted-foreground">改哪几栏</span>
            {ALL_FIELDS.map(f => (
              <button
                key={f} type="button" aria-pressed={fields.has(f)} onClick={() => toggle(setFields, f)} disabled={busy}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  fields.has(f) ? 'border-primary/50 bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted'
                }`}
              >
                {FIELD_LABEL[f]}
              </button>
            ))}
          </div>

          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">额外要求（选填）</span>
            <textarea
              value={instruction}
              onChange={e => setInstruction(e.target.value)}
              placeholder="想怎么改？比如：外貌写得更有辨识度，性格加点反差"
              className={`${INPUT} resize-y min-h-[3.5rem]`}
              disabled={busy}
            />
          </label>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={run}
              disabled={busy || checked.size === 0 || fields.size === 0 || tooMany}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-md
                bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
              开始优化（{checked.size} 人 × {fields.size} 栏）
            </button>
            <span className={`text-[11px] ${tooMany ? 'text-amber-600' : 'text-muted-foreground'}`}>
              {tooMany ? `超过 ${MAX_NPCS} 个了，分两批来` : '一人一栏一次调用，人多要等几分钟'}
            </span>
          </div>
        </>
      )}

      {groups.map(({ npc, rows }) => (
        <div key={npc.id} className="border rounded-lg p-2.5 space-y-2.5">
          <div className="text-sm font-medium">{npc.name}</div>
          {rows.map(it => {
            const k = keyOf(it.npc_id, it.field)
            return (
              <div key={k} className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                    {FIELD_LABEL[it.field]}
                  </span>
                  {!it.error && (
                    <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground cursor-pointer">
                      <input
                        type="checkbox" checked={picked.has(k)} onChange={() => toggle(setPicked, k)}
                        disabled={writing} className="accent-[hsl(var(--primary))]"
                      />
                      用这版
                    </label>
                  )}
                </div>
                <p className="text-xs text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                  原文：{it.original || '（空着）'}
                </p>
                {it.error ? (
                  <p className="text-xs text-amber-600">{it.error}</p>
                ) : (
                  <textarea
                    aria-label={`${npc.name}的${FIELD_LABEL[it.field]}新版`}
                    value={draft[k] ?? ''}
                    onChange={e => setDraft(prev => ({ ...prev, [k]: e.target.value }))}
                    className={`${INPUT} resize-y min-h-[5rem] leading-relaxed`}
                    disabled={writing}
                  />
                )}
              </div>
            )
          })}
        </div>
      ))}

      {items && (
        <div className="flex justify-end gap-2">
          <button
            onClick={() => { setItems(null); setDraft({}); setPicked(new Set()) }}
            disabled={writing}
            className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted disabled:opacity-40"
          >
            返回重选
          </button>
          <button
            onClick={write}
            disabled={writing || chosen.length === 0}
            className="flex items-center gap-1 text-sm px-4 py-1.5 rounded-lg
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {writing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            写入（{chosen.length} 条）
          </button>
        </div>
      )}
    </div>
  )
}
