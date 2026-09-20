import { useMemo, useState } from 'react'
import { Check, X, AlertTriangle, Loader2 } from 'lucide-react'
import type { RpgCondition, RpgWizardExtract } from '@/api/client'
import type { WizardStatGroup } from './wizardApply'

/** 勾选后要写进表单的那份，形状同 RpgWizardExtract 但只含勾上的项 */
export type WizardPicked = Partial<Omit<RpgWizardExtract, 'dropped'>>

interface Props {
  draft: RpgWizardExtract
  onCancel: () => void
  onApply: (picked: WizardPicked) => void
  onMoveStat?: (from: WizardStatGroup, index: number) => boolean
  onRegenerate?: () => void
  applying?: boolean
}

const TEXT_FIELDS: Array<[keyof RpgWizardExtract, string]> = [
  ['genre', '题材'],
  ['worldview', '世界观'],
  ['opening_scene', '开场旁白'],
  ['system_instruction', 'GM 指令'],
  ['narration_sample', '叙事样例'],
]

/**
 * 全量预览，逐项勾选后写回表单。
 *
 * 逐条勾（不是整组一个勾）：五个角色里想要三个是常见需求。另外做一次**前端侧**
 * 引用校验——后端只按「聊定时的白名单」过滤过，作者在这里取消勾选某个数值之后，
 * 引用它的道具就悬空了，那是后端拦不到的，得当场提示。
 */
export default function WizardApplyModal({ draft, onCancel, onApply, onMoveStat, onRegenerate, applying = false }: Props) {
  // 每一项一个稳定 key：文本用字段名，列表项用 "类型:下标"
  const allKeys = useMemo(() => collectKeys(draft), [draft])
  const [picked, setPicked] = useState<Set<string>>(() => new Set(allKeys))

  const toggle = (key: string) =>
    setPicked(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  const moveStat = (from: WizardStatGroup, index: number) => {
    const sourcePrefix = from === 'stat_defs' ? 'stat' : 'rel'
    const targetPrefix = from === 'stat_defs' ? 'rel' : 'stat'
    const target = from === 'stat_defs' ? 'relation_stat_defs' : 'stat_defs'
    const targetIndex = (draft[target] || []).length
    if (!onMoveStat?.(from, index)) return
    setPicked(previous => {
      const next = new Set([...previous].filter(key => !key.startsWith(`${sourcePrefix}:`)))
      ;(draft[from] || []).forEach((_, position) => {
        if (!previous.has(`${sourcePrefix}:${position}`)) return
        next.add(position === index
          ? `${targetPrefix}:${targetIndex}`
          : `${sourcePrefix}:${position > index ? position - 1 : position}`)
      })
      return next
    })
  }

  // 当前勾着的数值名 / 关系名 / 地点名，用来算悬空引用
  const live = useMemo(() => {
    const stats = new Set<string>()
    const relations = new Set<string>()
    const places = new Set<string>()
    ;(draft.stat_defs || []).forEach((s, i) => picked.has(`stat:${i}`) && stats.add(s.name))
    ;(draft.relation_stat_defs || []).forEach((s, i) => picked.has(`rel:${i}`) && relations.add(s.name))
    ;(draft.locations || []).forEach((l, i) => picked.has(`loc:${i}`) && places.add(l.name))
    return { stats, relations, places }
  }, [draft, picked])

  // 勾着的项里，引用了没勾的名字的那些——写进表单也是悬空的，提示作者
  const dangles = useMemo(() => {
    const out: string[] = []
    ;(draft.npcs || []).forEach((n, i) => {
      if (!picked.has(`npc:${i}`)) return
      Object.keys(n.initial_state || {}).forEach(k => {
        if (!live.relations.has(k)) out.push(`角色「${n.name}」的关系「${k}」没勾上`)
      })
      if (n.location && !live.places.has(n.location)) out.push(`角色「${n.name}」在的地点「${n.location}」没勾上`)
    })
    ;(draft.items || []).forEach((it, i) => {
      if (!picked.has(`item:${i}`)) return
      Object.keys(it.effects || {}).forEach(k => {
        if (!live.stats.has(k)) out.push(`道具「${it.name}」影响的「${k}」没勾上`)
      })
    })
    ;(draft.skills || []).forEach((s, i) => {
      if (!picked.has(`skill:${i}`)) return
      Object.keys(s.effects || {}).forEach(k => {
        if (!live.stats.has(k)) out.push(`技能「${s.name}」影响的「${k}」没勾上`)
      })
    })
    ;(draft.tasks || []).forEach((t, i) => {
      if (!picked.has(`task:${i}`)) return
      Object.keys(t.effects || {}).forEach(k => {
        if (!live.stats.has(k)) out.push(`任务「${t.name}」的奖励「${k}」没勾上`)
      })
    })
    ;(draft.actions || []).forEach((a, i) => {
      if (!picked.has(`action:${i}`)) return
      Object.keys(a.effects || {}).forEach(k => {
        if (!live.stats.has(k)) out.push(`动作「${a.name}」影响的「${k}」没勾上`)
      })
      Object.keys(a.relation_effects || {}).forEach(k => {
        if (!live.relations.has(k)) out.push(`动作「${a.name}」的关系「${k}」没勾上`)
      })
    })
    return out
  }, [draft, picked, live])

  const apply = () => {
    if (applying) return
    const out: WizardPicked = {}
    for (const [key] of TEXT_FIELDS) {
      if (picked.has(key as string) && draft[key]) (out as Record<string, unknown>)[key] = draft[key]
    }
    const statDefs = (draft.stat_defs || []).filter((_, i) => picked.has(`stat:${i}`))
    if (statDefs.length) out.stat_defs = statDefs
    const relDefs = (draft.relation_stat_defs || []).filter((_, i) => picked.has(`rel:${i}`))
    if (relDefs.length) out.relation_stat_defs = relDefs
    const locs = (draft.locations || []).filter((_, i) => picked.has(`loc:${i}`))
    if (locs.length) out.locations = locs
    const slots = (draft.time_slots || []).filter((_, i) => picked.has(`slot:${i}`))
    if (slots.length) out.time_slots = slots
    if (draft.default_location && picked.has('default_location')) out.default_location = draft.default_location
    const npcs = (draft.npcs || []).filter((_, i) => picked.has(`npc:${i}`))
    if (npcs.length) out.npcs = npcs
    const items = (draft.items || []).filter((_, i) => picked.has(`item:${i}`))
    if (items.length) out.items = items
    const skills = (draft.skills || []).filter((_, i) => picked.has(`skill:${i}`))
    if (skills.length) out.skills = skills
    const tasks = (draft.tasks || []).filter((_, i) => picked.has(`task:${i}`))
    if (tasks.length) out.tasks = tasks
    const actions = (draft.actions || []).filter((_, i) => picked.has(`action:${i}`))
    if (actions.length) out.actions = actions
    onApply(out)
  }

  const nothing = allKeys.length === 0

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={applying ? undefined : onCancel}>
      <div
        className="bg-background rounded-xl border shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b flex items-center justify-between shrink-0">
          <div className="min-w-0">
            <h3 className="font-medium">{onRegenerate ? '整套模组草案已生成' : '把聊定的内容填进模组'}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              {onRegenerate
                ? '先看一下这套设定。满意就回填，不满意可以换一套。'
                : '勾掉不想要的。数值是地基，取消某个数值会让引用它的道具悬空。'}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              上一轮向导填的内容会被这一轮换掉；你自己手写的同名条目会跳过。
            </p>
          </div>
          <button onClick={onCancel} disabled={applying} className="p-1.5 rounded-md hover:bg-muted shrink-0 disabled:opacity-40">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 滚动容器必须是 div：fieldset 当 flex 子项时不认 min-height:0，会顶着内容
            高度把面板撑破 max-h，一句话生成整套那种大草案就此既超出屏幕又滚不动。
            disabled 挪到里层的 fieldset 上，语义不变 */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4">
        <fieldset disabled={applying} className="space-y-4">
          {nothing && (
            <p className="text-sm text-muted-foreground py-6 text-center">
              没从对话里抽到能填的内容。多聊几轮，把设定聊具体些再试。
            </p>
          )}

          {draft.dropped.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2.5 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-medium text-amber-600">
                <AlertTriangle className="w-3.5 h-3.5" /> 生成时的修正与未采用内容
              </div>
              {draft.dropped.map((d, i) => <p key={i} className="text-muted-foreground">· {d}</p>)}
            </div>
          )}

          <Group title="设定文本">
            {TEXT_FIELDS.map(([key, label]) =>
              draft[key] ? (
                <Row key={key} on={picked.has(key as string)} onToggle={() => toggle(key as string)} title={label}>
                  <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-3">{String(draft[key])}</p>
                </Row>
              ) : null,
            )}
          </Group>

          <Group title="玩家数值（全局一份）">
            {(draft.stat_defs || []).map((s, i) => (
              <div key={i} className="space-y-1">
              <Row key={i} on={picked.has(`stat:${i}`)} onToggle={() => toggle(`stat:${i}`)}
                title={s.name}
                sub={`起始 ${s.initial}（${s.min}~${s.max ?? '∞'}）· ${s.display}${s.on_zero && s.on_zero !== '无' ? ` · 归零${s.on_zero}` : ''}`}
              />
              {onMoveStat && <button type="button" onClick={() => moveStat('stat_defs', i)}
                className="text-xs text-primary hover:underline disabled:opacity-40">
                移至关系数值
              </button>}
              </div>
            ))}
          </Group>

          <Group title="关系数值（每个 NPC 一份）">
            {(draft.relation_stat_defs || []).map((s, i) => (
              <div key={i} className="space-y-1">
              <Row key={i} on={picked.has(`rel:${i}`)} onToggle={() => toggle(`rel:${i}`)}
                title={s.name} sub={`起始 ${s.initial}（${s.min}~${s.max ?? '∞'}）`} />
              {onMoveStat && <button type="button" onClick={() => moveStat('relation_stat_defs', i)}
                className="text-xs text-primary hover:underline disabled:opacity-40">
                移至玩家数值
              </button>}
              </div>
            ))}
          </Group>
          {onMoveStat && ((draft.stat_defs?.length || 0) + (draft.relation_stat_defs?.length || 0) > 0) && (
            <p className="text-xs text-muted-foreground">调整归属会保留数值定义。回填前请核对动作引用和角色关系起点；回填后可在角色卡中启用关系数值。</p>
          )}

          <Group title="地点">
            {draft.default_location && (
              <Row on={picked.has('default_location')} onToggle={() => toggle('default_location')}
                title={`起始地点：${draft.default_location}`} />
            )}
            {(draft.locations || []).map((l, i) => (
              <Row key={i} on={picked.has(`loc:${i}`)} onToggle={() => toggle(`loc:${i}`)}
                title={l.name}
                sub={[l.parent_name ? `属于 ${l.parent_name}` : '', l.connections.length ? `通往 ${l.connections.join('、')}` : ''].filter(Boolean).join(' · ') || undefined}>
                {l.description && <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{l.description}</p>}
              </Row>
            ))}
          </Group>

          <Group title="时段">
            {(draft.time_slots || []).map((slot, i) => (
              <Row key={i} on={picked.has(`slot:${i}`)} onToggle={() => toggle(`slot:${i}`)} title={slot} />
            ))}
          </Group>

          <Group title="角色">
            {(draft.npcs || []).map((n, i) => (
              <Row key={i} on={picked.has(`npc:${i}`)} onToggle={() => toggle(`npc:${i}`)}
                title={n.name}
                sub={[n.location, ...Object.entries(n.initial_state || {}).map(([k, v]) => `${k} ${v}`)].filter(Boolean).join(' · ') || undefined}>
                {n.persona && <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{n.persona}</p>}
                {n.profile_sections && Object.entries(n.profile_sections).filter(([, text]) => text).map(([key, text]) => (
                  <p key={key} className="text-xs mt-1 text-muted-foreground line-clamp-2"><span className="font-medium">{key}</span>：{text}</p>
                ))}
                {/* 作息和说话样例都是无声写进卡里的东西，不列出来作者不知道多了这些 */}
                {n.slot_locations && Object.keys(n.slot_locations).length > 0 && (
                  <p className="text-xs mt-1 text-muted-foreground"><span className="font-medium">作息</span>：
                    {Object.entries(n.slot_locations).map(([slot, place]) => `${slot}在${place}`).join('、')}</p>
                )}
                {!!n.dialogue_examples?.length && (
                  <p className="text-xs mt-1 text-muted-foreground">说话样例 {n.dialogue_examples.length} 组</p>
                )}
              </Row>
            ))}
          </Group>

          <Group title="道具">
            {(draft.items || []).map((it, i) => (
              <Row key={i} on={picked.has(`item:${i}`)} onToggle={() => toggle(`item:${i}`)}
                title={it.name}
                sub={effectsText(it.effects) || it.category}>
                {it.description && <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{it.description}</p>}
              </Row>
            ))}
          </Group>

          <Group title="技能">
            {(draft.skills || []).map((s, i) => (
              <Row key={i} on={picked.has(`skill:${i}`)} onToggle={() => toggle(`skill:${i}`)}
                title={s.name}
                sub={[effectsText(s.effects), s.cooldown > 0 ? `冷却 ${s.cooldown} 回合` : '', requiresText(s.requires), s.category].filter(Boolean).join(' · ') || undefined}>
                {s.description && <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{s.description}</p>}
              </Row>
            ))}
          </Group>

          <Group title="任务">
            {(draft.tasks || []).map((t, i) => (
              <Row key={i} on={picked.has(`task:${i}`)} onToggle={() => toggle(`task:${i}`)}
                title={t.name}
                sub={[effectsText(t.effects), t.category].filter(Boolean).join(' · ') || undefined}>
                {t.description && <p className="text-sm mt-1 whitespace-pre-wrap line-clamp-2">{t.description}</p>}
                {/* 判定任务办完没有只看 objective 这一句，它编歪了写进去就白搭，得当场让作者看见 */}
                {t.objective && <p className="text-xs mt-1 text-muted-foreground line-clamp-2"><span className="font-medium">怎样算办完</span>：{t.objective}</p>}
              </Row>
            ))}
          </Group>

          <Group title="动作按钮">
            {(draft.actions || []).map((a, i) => (
              <Row key={i} on={picked.has(`action:${i}`)} onToggle={() => toggle(`action:${i}`)}
                title={`[${a.group || '未分栏'}] ${a.name}`}
                sub={[
                  effectsText(a.effects), effectsText(a.relation_effects),
                  a.cost_slot ? '推掉一格时段' : '', a.at_location ? `只在${a.at_location}` : '',
                ].filter(Boolean).join(' · ') || undefined} />
            ))}
          </Group>

          {dangles.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2.5 text-xs space-y-1">
              <div className="flex items-center gap-1.5 font-medium text-amber-600">
                <AlertTriangle className="w-3.5 h-3.5" /> 这些引用会悬空（数值/地点没勾）
              </div>
              {dangles.map((d, i) => <p key={i} className="text-muted-foreground">· {d}</p>)}
              <p className="text-muted-foreground/70">照样能写进去，但那些数值增减不会生效。</p>
            </div>
          )}
        </fieldset>
        </div>

        <div className="px-5 py-3 border-t flex justify-end gap-2 shrink-0">
          <button onClick={onCancel} disabled={applying} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted disabled:opacity-40">
            {onRegenerate ? '暂不回填' : '取消'}
          </button>
          {onRegenerate && (
            <button onClick={onRegenerate} disabled={applying} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted disabled:opacity-40">
              随机换一套
            </button>
          )}
          <button
            onClick={apply}
            disabled={applying || picked.size === 0}
            className="flex items-center gap-1 text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {applying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            {applying ? '回填中…' : `${onRegenerate ? '回填到模组' : '填进模组'}（${picked.size}）`}
          </button>
        </div>
      </div>
    </div>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  const arr = Array.isArray(children) ? children.flat().filter(Boolean) : children
  if (Array.isArray(arr) && arr.length === 0) return null
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1.5">{title}</p>
      <div className="space-y-2">{children}</div>
    </div>
  )
}

function Row({ on, onToggle, title, sub, children }: {
  on: boolean; onToggle: () => void; title: string; sub?: string; children?: React.ReactNode
}) {
  return (
    <label className={`block border rounded-lg px-3 py-2 cursor-pointer transition-colors ${on ? 'border-primary/50 bg-primary/5' : 'opacity-60'}`}>
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={on} onChange={onToggle} className="accent-primary" />
        <span className="text-sm font-medium">{title}</span>
        {sub && <span className="text-xs text-muted-foreground truncate">{sub}</span>}
      </div>
      {children}
    </label>
  )
}

function effectsText(effects?: Record<string, number>): string {
  const e = Object.entries(effects || {})
  if (!e.length) return ''
  return e.map(([k, v]) => `${k}${v >= 0 ? '+' : ''}${v}`).join(' ')
}

/** 技能门槛写成一句话。抽取只会给出 stats / items 两个子形状，别的不用管 */
function requiresText(requires?: RpgCondition): string {
  const parts = Object.entries(requires?.stats || {}).map(([name, c]) => `${name}${c.op}${c.value}`)
  if (requires?.items?.length) parts.push(`要有${requires.items.join('、')}`)
  return parts.length ? `需 ${parts.join(' ')}` : ''
}

function collectKeys(draft: RpgWizardExtract): string[] {
  const keys: string[] = []
  for (const [key] of TEXT_FIELDS) if (draft[key]) keys.push(key as string)
  ;(draft.stat_defs || []).forEach((_, i) => keys.push(`stat:${i}`))
  ;(draft.relation_stat_defs || []).forEach((_, i) => keys.push(`rel:${i}`))
  ;(draft.locations || []).forEach((_, i) => keys.push(`loc:${i}`))
  ;(draft.time_slots || []).forEach((_, i) => keys.push(`slot:${i}`))
  if (draft.default_location) keys.push('default_location')
  ;(draft.npcs || []).forEach((_, i) => keys.push(`npc:${i}`))
  ;(draft.items || []).forEach((_, i) => keys.push(`item:${i}`))
  ;(draft.skills || []).forEach((_, i) => keys.push(`skill:${i}`))
  ;(draft.tasks || []).forEach((_, i) => keys.push(`task:${i}`))
  ;(draft.actions || []).forEach((_, i) => keys.push(`action:${i}`))
  return keys
}
