import { useState } from 'react'
import toast from 'react-hot-toast'
import { Loader2, Sparkles, X } from 'lucide-react'
import { rpgApi, type RpgModule, type RpgStatDef, type RpgStatTier } from '@/api/client'
import { AddRow, DeleteButton, INPUT, NumInput } from './rpgUi'

const SELECT = 'border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none'

// 「格子」= 一格一格的进度条，配「填满时 = 标记」就是进度时钟。
// 和 rpg_state.py 的 DISPLAY_* 对齐
const DISPLAYS = ['条', '格子', '数字', '隐藏'] as const
const ON_ZERO = ['无', '死亡', '标记'] as const
// 没有「死亡」那一档：填满致死没有语义，要那个效果就用「归零时」表达。
// 和 rpg_state.py 的 ON_FULL_* 对齐
const ON_FULL = ['无', '标记'] as const

// 和 rpg_state.py 的 EFFECT_CHARS / TIER_LABEL_CHARS / TIER_NOTE_CHARS 对齐。
// 后端渲染时还会再截一刀（作者可以从别处粘进来），这里挡是为了让他当场看见
const EFFECT_MAX = 150
const LABEL_MAX = 6
const NOTE_MAX = 150

// 导出是给「套动作套装时一键补建缺的数值」用的：补出来的项必须和作者手点
// 「添加一项」长得一模一样，不能另攒一份默认值
export const newPlayerStat = (): RpgStatDef => ({
  name: '', initial: 50, min: 0, max: 100, for_check: false, on_zero: '无', display: '条',
})

export const newRelationStat = (): RpgStatDef => ({
  name: '', initial: 0, min: 0, max: 100, display: '条',
})

/** 这个编辑器实际只碰这两栏。以前写死成整个 RpgModule 是因为当时只有模组编辑页
 *  一个调用点，而套装库里没有、也不该有一个完整的模组对象 */
export type StatDraft = Pick<RpgModule, 'stat_defs' | 'relation_stat_defs'>

/**
 * 数值定义。整个游戏模块的地基就是这两张表——玩家一套，角色共用一套。
 * 定义变了不会追溯已经开的局：那一局的数值在建局时就拷走了。
 */
export default function StatDefsSection({
  form, set, example = '精力', moduleId,
}: {
  form: StatDraft
  set: <K extends keyof StatDraft>(key: K, value: StatDraft[K]) => void
  /** 空格子里的示例词，按玩法类别换（见 stylePresets.STYLE_EXAMPLES） */
  example?: string
  /** 有它才出「AI 分档」：那个端点挂在模组下（要拿模组的模型配置）。
   *  套装库里编数值是没有模组的，那儿就只有手填 */
  moduleId?: number
}) {
  return (
    <div className="space-y-6">
      <StatTable
        label="玩家数值"
        hint="资金、精力、声望这些跟着玩家走的数字。判定默认是关着的，「可判定」只有开了判定才有用。"
        defs={form.stat_defs || []}
        onChange={v => set('stat_defs', v)}
        make={newPlayerStat}
        example={example}
        moduleId={moduleId}
        full
      />
      <StatTable
        label="关系数值"
        hint="定义一次，每个角色各持一份。好感、信任、羞耻这类。角色卡里可以单独改某个人的起点。"
        defs={form.relation_stat_defs || []}
        onChange={v => set('relation_stat_defs', v)}
        make={newRelationStat}
        moduleId={moduleId}
      />
    </div>
  )
}

function StatTable({
  label, hint, defs, onChange, make, full, example = '精力', moduleId,
}: {
  label: string
  hint: string
  defs: RpgStatDef[]
  onChange: (next: RpgStatDef[]) => void
  make: () => RpgStatDef
  /** 玩家数值才有「可判定」和「归零时」两列 */
  full?: boolean
  example?: string
  moduleId?: number
}) {
  const patch = (i: number, next: Partial<RpgStatDef>) =>
    onChange(defs.map((d, n) => (n === i ? { ...d, ...next } : d)))

  return (
    <div>
      <label className="text-xs font-medium mb-1.5 block">{label}</label>
      <div className="space-y-2">
        {defs.map((def, i) => (
          <div key={i} className="rounded-lg border px-3 py-2.5 space-y-2">
            <div className="flex items-center gap-2">
              <input
                value={def.name}
                onChange={e => patch(i, { name: e.target.value })}
                placeholder={`名字，如：${example}`}
                className={`${INPUT} flex-1 py-1.5`}
              />
              <select
                value={def.display || '条'}
                onChange={e => patch(i, { display: e.target.value })}
                className={SELECT}
                title="怎么显示给玩家"
              >
                {DISPLAYS.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
              <DeleteButton onClick={() => onChange(defs.filter((_, n) => n !== i))} />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <NumBox
                label="初始"
                value={def.initial}
                onChange={v => patch(i, { initial: v })}
              />
              <NumBox label="下限" value={def.min} onChange={v => patch(i, { min: v })} />
              <div>
                <span className="text-[11px] text-muted-foreground block mb-0.5">上限</span>
                <NumInput
                  value={def.max}
                  onChange={n => patch(i, { max: n })}
                  allowEmpty
                  placeholder="无"
                  className={`${INPUT} w-20 py-1`}
                  title="留空 = 无上限（钱、声望这种）"
                />
              </div>
              {/* 「上限」夹的是结果（好感不超过 100），这一栏夹的是**一轮能动多少**。
                  不设的话，模型一句「她彻底原谅了你」就能把好感从 0 推到顶，
                  作者排的那条成长曲线直接作废 */}
              <div>
                <span className="text-[11px] text-muted-foreground block mb-0.5">每轮最多变</span>
                <NumInput
                  value={def.step_max}
                  onChange={n => patch(i, { step_max: n })}
                  allowEmpty
                  // 「一轮最多变多少」是个幅度，负数没有意义
                  clamp={Math.abs}
                  placeholder="不限"
                  className={`${INPUT} w-20 py-1`}
                  title="只管住 AI 的结算：一轮最多让它动这么多点，超出的直接截掉。动作和道具上写死的加减不受这里限制。填 0 = 这一项只能靠动作和道具改"
                />
              </div>
              {full && (
                <>
                  <div>
                    <span className="text-[11px] text-muted-foreground block mb-0.5">归零时</span>
                    <select
                      value={def.on_zero || '无'}
                      onChange={e => patch(i, { on_zero: e.target.value })}
                      className={SELECT}
                    >
                      {ON_ZERO.map(z => <option key={z} value={z}>{z}</option>)}
                    </select>
                  </div>
                  {/* 只在有上限的行上出现，同「跨天恢复」那个勾选框的判据：
                      没上限的项（钱、声望）永远填不满，给个下拉是误导 */}
                  {def.max != null && (
                    <div>
                      <span className="text-[11px] text-muted-foreground block mb-0.5">填满时</span>
                      <select
                        value={def.on_full || '无'}
                        onChange={e => patch(i, { on_full: e.target.value })}
                        className={SELECT}
                        title="选「标记」就立一条「这一项满了」的 flag，这项数值就成了进度时钟——世界书触发、动作可用性、地点进入条件都能引用它"
                      >
                        {ON_FULL.map(z => <option key={z} value={z}>{z}</option>)}
                      </select>
                    </div>
                  )}
                  <label className="flex items-center gap-1.5 cursor-pointer self-end pb-1.5">
                    <input
                      type="checkbox"
                      checked={!!def.for_check}
                      onChange={e => patch(i, { for_check: e.target.checked })}
                      className="accent-[hsl(var(--primary))]"
                    />
                    <span className="text-xs text-muted-foreground">可判定</span>
                  </label>
                  {/* 只在有上限的行上出现：按上限的成数算，得有个上限可算 */}
                  {def.max != null && (
                    <label
                      className="flex items-center gap-1.5 cursor-pointer self-end pb-1.5"
                      title="过了一天恢复到上限的七成，不是回满——睡一觉就满血的话，数值扣了不疼。已经高于七成的不会掉"
                    >
                      <input
                        type="checkbox"
                        checked={!!def.reset_daily}
                        onChange={e => patch(i, { reset_daily: e.target.checked })}
                        className="accent-[hsl(var(--primary))]"
                      />
                      <span className="text-xs text-muted-foreground">跨天恢复</span>
                    </label>
                  )}
                </>
              )}
            </div>

            <div>
              <span className="text-[11px] text-muted-foreground block mb-0.5">影响</span>
              <input
                value={def.effect || ''}
                onChange={e => patch(i, { effect: e.target.value })}
                maxLength={EFFECT_MAX}
                placeholder="这个数值影响什么，如：决定她愿不愿意帮你"
                className={`${INPUT} py-1.5 text-xs`}
                title="每轮发给模型一句，让数字带上意思。不写就没有"
              />
            </div>

            <TierEditor
              tiers={def.tiers || []}
              max={def.max}
              onChange={tiers => patch(i, { tiers })}
              moduleId={moduleId}
              spec={def}
            />
          </div>
        ))}
        <AddRow onClick={() => onChange([...defs, make()])}>添加一项</AddRow>
      </div>
      <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>
      {full && (
        <p className="text-xs text-muted-foreground mt-1">
          「隐藏」是给幕后计数器用的：玩家看不见，但能拿来触发世界书词条（比如怀疑度到 60 就有人来敲门）。
          「归零时 = 标记」会写一条剧情标记，剧情自己接；「死亡」直接结束这一局。
          「格子」+「填满时 = 标记」= 进度时钟：上限填小一点（比如 8），推满就立一条标记，
          世界书触发、动作可用性、地点进入条件都能引用它。
        </p>
      )}
    </div>
  )
}

/**
 * 分档。只写「到多少算这一档」，不写区间——区间让作者留得出空隙和重叠，
 * 落进空隙就是「没有档」、落进重叠就是「两个档」，而且都不会报错。
 *
 * 左边那个范围是**推出来的**，不是作者填的：下一档的下界减一。所以乱序
 * 填的时候它会看着乱——那正是提示他该理一理，因为后端也是按这个算的。
 */
function TierEditor({
  tiers, max, onChange, moduleId, spec,
}: {
  tiers: RpgStatTier[]
  max: number | null
  onChange: (next: RpgStatTier[]) => void
  /** 空 = 没有模组可挂（套装库），「AI 分档」整个不出现 */
  moduleId?: number
  /** 整条数值定义，发给后端当分档的依据（名字、上下限、「影响」那句话） */
  spec: RpgStatDef
}) {
  const under = tiers
    .map(t => t?.at)
    .filter((v): v is number => typeof v === 'number')
    .sort((a, b) => a - b)

  const rangeOf = (at: number) => {
    const next = under.find(v => v > at)
    if (next !== undefined) return `${at}–${next - 1}`
    if (max != null && max >= at) return `${at}–${max}`
    return `${at} 以上`
  }

  const patch = (i: number, next: Partial<RpgStatTier>) =>
    onChange(tiers.map((t, n) => (n === i ? { ...t, ...next } : t)))

  const ai = moduleId != null && (spec.name || '').trim()
    ? <TierAssist moduleId={moduleId} spec={spec} onApply={onChange} />
    : null

  // 一档都没有的时候只留两个按钮：绝大多数数值用不上分档，
  // 摊开一张空表会让作者以为这是必填的
  if (tiers.length === 0) {
    return (
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => onChange([{ at: 0, label: '', note: '' }])}
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          + 分档（到多少会怎样）
        </button>
        {ai}
      </div>
    )
  }

  return (
    <div className="rounded-lg bg-muted/30 px-2.5 py-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-muted-foreground flex-1">分档（推出来的范围 → 标签 · 表现）</span>
        {ai}
        <button
          onClick={() => onChange([])}
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          不用分档
        </button>
      </div>
      {tiers.map((tier, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground tabular-nums w-16 shrink-0 text-right">
            {typeof tier?.at === 'number' ? rangeOf(tier.at) : '待填'}
          </span>
          {/* 档位阈值经常是负的：好感 -50 算「厌恶」正是这一栏要填的东西 */}
          <NumInput
            value={typeof tier?.at === 'number' ? tier.at : null}
            onChange={n => patch(i, { at: n ?? undefined })}
            allowEmpty
            placeholder="≥"
            className={`${INPUT} w-16 py-1 text-xs`}
            title="到这个数（含）算这一档"
          />
          <input
            value={tier?.label || ''}
            onChange={e => patch(i, { label: e.target.value })}
            maxLength={LABEL_MAX}
            placeholder="标签，如：亲近"
            className={`${INPUT} w-24 py-1 text-xs`}
            title="display 在数字后面，玩家看得见"
          />
          <input
            value={tier?.note || ''}
            onChange={e => patch(i, { note: e.target.value })}
            maxLength={NOTE_MAX}
            placeholder="这一档什么表现"
            className={`${INPUT} flex-1 py-1 text-xs`}
            title="只给模型看，玩家看不见"
          />
          <DeleteButton onClick={() => onChange(tiers.filter((_, n) => n !== i))} />
        </div>
      ))}
      <AddRow onClick={() => onChange([...tiers, { at: 0, label: '', note: '' }])}>添加一档</AddRow>
    </div>
  )
}

/**
 * 「AI 分档」：按这一项的名字、上下限和「影响」那句话划出整张档表。
 *
 * 先预览再写回，同这一摊其他几个生成入口（BatchGenerate、Assist）：**这是一次
 * 整表替换**，直接落下去会把作者已经调好的档一起冲掉，而这一栏是自动保存的、
 * 没有撤销。落在范围外和下界撞车的档由后端剔掉并说明，照样显示出来。
 */
function TierAssist({
  moduleId, spec, onApply,
}: {
  moduleId: number
  spec: RpgStatDef
  onApply: (tiers: RpgStatTier[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [instruction, setInstruction] = useState('')
  const [count, setCount] = useState(4)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<RpgStatTier[] | null>(null)
  const [dropped, setDropped] = useState<string[]>([])

  const reset = () => { setOpen(false); setInstruction(''); setDraft(null); setDropped([]) }

  const run = async () => {
    setBusy(true)
    try {
      const res = await rpgApi.modules.tiers(moduleId, { spec, instruction, count })
      setDraft(res.tiers)
      setDropped(res.dropped || [])
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'AI 分档失败')
    } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-[11px] text-primary hover:underline flex items-center gap-1 shrink-0"
        title="按这一项的名字、范围和「影响」划出整张档表"
      >
        <Sparkles className="w-3 h-3" /> AI 分档
      </button>
    )
  }

  return (
    <div
      className="w-full rounded-lg border px-2.5 py-2 space-y-2"
      style={{ borderColor: 'hsl(var(--primary) / 0.3)', background: 'hsl(var(--primary) / 0.04)' }}
    >
      <div className="flex items-center gap-1.5">
        <Sparkles className="w-3 h-3 text-primary shrink-0" />
        <span className="text-[11px] font-medium text-primary flex-1">给「{spec.name}」分档</span>
        <button onClick={reset} className="p-0.5 rounded hover:bg-primary/10 text-muted-foreground">
          <X className="w-3 h-3" />
        </button>
      </div>
      <div className="flex items-center gap-1.5">
        <input
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          placeholder="想怎么分（选填），如：从暗恋到热恋"
          className={`${INPUT} flex-1 py-1 text-xs`}
          disabled={busy}
        />
        <NumInput
          value={count}
          onChange={n => setCount(n ?? 4)}
          clamp={n => Math.max(2, Math.min(8, n))}
          className={`${INPUT} w-12 py-1 text-xs`}
          title="分几档"
          disabled={busy}
        />
        <button
          onClick={run}
          disabled={busy}
          className="text-xs px-2.5 py-1 rounded-md bg-primary text-primary-foreground
            hover:opacity-90 disabled:opacity-40 flex items-center gap-1 shrink-0"
        >
          {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
          {draft ? '重新分' : '分档'}
        </button>
      </div>

      {draft && (
        <div className="space-y-1">
          {draft.map((tier, i) => (
            <p key={i} className="text-[11px] text-muted-foreground leading-relaxed">
              <span className="tabular-nums text-foreground">{tier.at} 起</span>
              {tier.label && <span className="text-foreground"> {tier.label}</span>}
              {tier.note && ` — ${tier.note}`}
            </p>
          ))}
        </div>
      )}

      {dropped.length > 0 && (
        <div className="text-[11px] text-amber-600 dark:text-amber-400 space-y-0.5">
          {dropped.map((d, i) => <p key={i}>· {d}</p>)}
        </div>
      )}

      {draft && (
        <div className="flex justify-end gap-1.5">
          <button onClick={reset} className="text-xs px-2 py-1 rounded-md text-muted-foreground hover:bg-muted">
            不用
          </button>
          <button
            onClick={() => { onApply(draft); reset() }}
            className="text-xs px-2.5 py-1 rounded-md bg-primary text-primary-foreground hover:opacity-90"
            title="整张档表换成这个，原来的档会没掉"
          >
            用这套
          </button>
        </div>
      )}
    </div>
  )
}

function NumBox({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <span className="text-[11px] text-muted-foreground block mb-0.5">{label}</span>
      {/* 「下限」走的也是这里，负数是正常值（欠债、负面情绪都能到 -100） */}
      <NumInput
        value={value}
        onChange={n => onChange(n ?? 0)}
        className={`${INPUT} w-20 py-1`}
      />
    </div>
  )
}
