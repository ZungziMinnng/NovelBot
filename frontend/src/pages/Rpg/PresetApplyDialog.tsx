import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check, Loader2, X } from 'lucide-react'
import { rpgApi, type RpgActionPreset, type RpgActionSeed, type RpgStatDef } from '@/api/client'
import { BUILTIN_ACTION_PACKS, missingStats, type ActionPack } from './presetLib'
import { effectChips } from './effectChips'

/**
 * 套用动作套装：先选一套，再逐个勾。
 *
 * 两步而不是一步：套装里十来个动作，作者通常只想要其中几个；直接全塞进去
 * 再让他去动作列表里删，是把工作推给了他。
 */
export default function PresetApplyDialog({
  existingNames, statDefs, relationDefs, onCancel, onApply,
}: {
  /** 模组里已有的动作名，用来把同名的默认取消勾选 */
  existingNames: string[]
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  onCancel: () => void
  onApply: (picked: RpgActionSeed[], fill: { stats: string[]; relations: string[] }) => Promise<void>
}) {
  const { data: presets } = useQuery({ queryKey: ['rpg-action-presets'], queryFn: rpgApi.actionPresets.list })

  // 内置在前：第一次打开时列表里总得有东西可看。自己的套装是攒出来的，
  // 排在后面也一直够得着
  const packs = useMemo<ActionPack[]>(() => [
    ...BUILTIN_ACTION_PACKS,
    ...(presets ?? []).map((p: RpgActionPreset) => ({
      id: p.id, name: p.name, note: p.note, actions: p.actions,
    })),
  ], [presets])

  // 存下标而不是存套装对象：下拉列表会随着新增套装重建，对象引用留不住
  const [packIdx, setPackIdx] = useState<number | null>(null)
  const [picked, setPicked] = useState<Set<number>>(() => new Set())
  // 默认补建：缺数值直接套进去就是「点了按钮数字不动、也不报错」，
  // 而作者这会儿想的是赶紧把这套用上，不如默认补好，不想要还能取消勾
  const [fillMissing, setFillMissing] = useState(true)
  const [busy, setBusy] = useState(false)

  const pack = packIdx === null ? null : packs[packIdx] ?? null

  const choosePack = (i: number) => {
    const p = packs[i]
    setPackIdx(i)
    // 同名的默认不勾，但不静默去掉——名字一样效果不同是合法的，
    // 留一份还是两份由作者自己决定
    setPicked(new Set(p.actions.map((_, j) => j).filter(j => !existingNames.includes(p.actions[j].name))))
  }

  const toggle = (i: number) =>
    setPicked(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })

  // 按套装里的原始顺序取：这个顺序就是落库时的 sort_order，
  // 界面上看到的先后和套进模组之后的先后得是同一个
  const pickedActions = useMemo(
    () => (pack ? [...picked].sort((a, b) => a - b).map(i => pack.actions[i]) : []),
    [pack, picked],
  )

  const miss = useMemo(
    () => missingStats(pickedActions, statDefs, relationDefs),
    [pickedActions, statDefs, relationDefs],
  )

  const handleApply = async () => {
    setBusy(true)
    try {
      // onApply 负责关弹窗（它知道落库完还要刷新哪些列表），这里只防连点
      await onApply(pickedActions, fillMissing ? miss : { stats: [], relations: [] })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onCancel}>
      <div
        className="bg-background rounded-xl border shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b flex items-center justify-between shrink-0">
          <div className="min-w-0">
            <h3 className="font-medium">从套装库套用动作</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {pack
                ? '勾掉这次不要的。套进来的是副本，以后改库不会动这个模组。'
                : '挑一套。套进来的是副本，以后改库不会动这个模组。'}
            </p>
          </div>
          <button onClick={onCancel} className="p-1.5 rounded-md hover:bg-muted shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {packIdx === null ? (
            <div className="space-y-2">
              {packs.map((p, i) => (
                <button
                  key={p.key ?? p.id ?? i}
                  onClick={() => choosePack(i)}
                  className="w-full text-left border rounded-lg px-3 py-2.5 hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{p.name}</span>
                    {i < BUILTIN_ACTION_PACKS.length && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">内置</span>
                    )}
                    <span className="text-xs text-muted-foreground ml-auto shrink-0">{p.actions.length} 个动作</span>
                  </div>
                  {p.note && <p className="text-xs text-muted-foreground mt-1">{p.note}</p>}
                  <div className="flex flex-wrap gap-1 mt-2">
                    {p.actions.slice(0, 6).map((a, j) => (
                      <span key={j} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                        {a.name}
                      </span>
                    ))}
                    {p.actions.length > 6 && (
                      <span className="text-[11px] px-2 py-0.5 text-muted-foreground">+{p.actions.length - 6}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          ) : pack && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">{pack.name}</span>
                {/* 换一套只退回列表，不留着上一套勾了一半的状态：回头选回来时
                    重新按「同名的默认不勾」初始化，比半套残留更好猜 */}
                <button
                  onClick={() => setPackIdx(null)}
                  className="text-xs px-2 py-1 border rounded-lg hover:bg-muted ml-auto"
                >
                  换一套
                </button>
              </div>

              {pack.actions.map((a, i) => (
                <Row
                  key={i}
                  on={picked.has(i)}
                  onToggle={() => toggle(i)}
                  title={a.name}
                  sub={<>{effectChips(a.effects)}{effectChips(a.relation_effects, true)}</>}
                >
                  {existingNames.includes(a.name) && (
                    <span className="text-xs text-amber-600">模组里已经有同名的</span>
                  )}
                  {a.prompt_hint && (
                    <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{a.prompt_hint}</p>
                  )}
                </Row>
              ))}
            </div>
          )}

          {(miss.stats.length > 0 || miss.relations.length > 0) && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2.5 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-medium text-amber-600">
                <AlertTriangle className="w-3.5 h-3.5" /> 这套动作用到了这个模组还没有的数值
              </div>
              {miss.stats.length > 0 && <p className="text-muted-foreground">玩家数值：{miss.stats.join('、')}</p>}
              {miss.relations.length > 0 && <p className="text-muted-foreground">关系数值：{miss.relations.join('、')}</p>}
              <label className="flex items-center gap-2 text-muted-foreground cursor-pointer pt-0.5">
                <input
                  type="checkbox"
                  checked={fillMissing}
                  onChange={e => setFillMissing(e.target.checked)}
                  className="accent-primary"
                />
                一并补建这些数值（按 0–100 的默认值建，建完可以在数值表里改）
              </label>
              <p className="text-muted-foreground/70">不补建也能套用，只是点了按钮时这几项不会生效。</p>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t flex justify-end gap-2 shrink-0">
          <button onClick={onCancel} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
          <button
            onClick={handleApply}
            disabled={picked.size === 0 || busy}
            className="flex items-center gap-1 text-sm px-4 py-1.5 rounded-lg
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            套进模组（{picked.size}）
          </button>
        </div>
      </div>
    </div>
  )
}

/** 勾选行。和 WizardApplyModal 那个是同一套壳子，只是 sub 这儿要放效果标签，
 *  放宽成 ReactNode——那边那个只吃字符串，所以没法直接复用 */
function Row({ on, onToggle, title, sub, children }: {
  on: boolean
  onToggle: () => void
  title: string
  sub?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <label className={`block border rounded-lg px-3 py-2 cursor-pointer transition-colors ${on ? 'border-primary/50 bg-primary/5' : 'opacity-60'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <input type="checkbox" checked={on} onChange={onToggle} className="accent-primary" />
        <span className="text-sm font-medium">{title}</span>
        {sub}
      </div>
      {children}
    </label>
  )
}
