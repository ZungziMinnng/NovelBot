import type { RpgModule, RpgStatDef, RpgStatTier } from '@/api/client'
import { AddRow, DeleteButton, INPUT } from './rpgUi'

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
const NOTE_MAX = 20

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
  form, set, example = '精力',
}: {
  form: StatDraft
  set: <K extends keyof StatDraft>(key: K, value: StatDraft[K]) => void
  /** 空格子里的示例词，按玩法类别换（见 stylePresets.STYLE_EXAMPLES） */
  example?: string
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
        full
      />
      <StatTable
        label="关系数值"
        hint="定义一次，每个角色各持一份。好感、信任、羞耻这类。角色卡里可以单独改某个人的起点。"
        defs={form.relation_stat_defs || []}
        onChange={v => set('relation_stat_defs', v)}
        make={newRelationStat}
      />
    </div>
  )
}

function StatTable({
  label, hint, defs, onChange, make, full, example = '精力',
}: {
  label: string
  hint: string
  defs: RpgStatDef[]
  onChange: (next: RpgStatDef[]) => void
  make: () => RpgStatDef
  /** 玩家数值才有「可判定」和「归零时」两列 */
  full?: boolean
  example?: string
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
                <input
                  type="number"
                  value={def.max ?? ''}
                  onChange={e => patch(i, {
                    max: e.target.value === '' ? null : Number(e.target.value) || 0,
                  })}
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
                <input
                  type="number"
                  value={def.step_max ?? ''}
                  onChange={e => patch(i, {
                    step_max: e.target.value === '' ? null : Math.abs(Number(e.target.value) || 0),
                  })}
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
  tiers, max, onChange,
}: {
  tiers: RpgStatTier[]
  max: number | null
  onChange: (next: RpgStatTier[]) => void
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

  // 一档都没有的时候只留一个按钮：绝大多数数值用不上分档，
  // 摊开一张空表会让作者以为这是必填的
  if (tiers.length === 0) {
    return (
      <button
        onClick={() => onChange([{ at: 0, label: '', note: '' }])}
        className="text-[11px] text-muted-foreground hover:text-foreground"
      >
        + 分档（到多少会怎样）
      </button>
    )
  }

  return (
    <div className="rounded-lg bg-muted/30 px-2.5 py-2 space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-muted-foreground flex-1">分档（推出来的范围 → 标签 · 表现）</span>
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
          <input
            type="number"
            value={typeof tier?.at === 'number' ? tier.at : ''}
            onChange={e => patch(i, { at: e.target.value === '' ? undefined : Number(e.target.value) })}
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

function NumBox({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <span className="text-[11px] text-muted-foreground block mb-0.5">{label}</span>
      <input
        type="number"
        value={value}
        onChange={e => onChange(Number(e.target.value) || 0)}
        className={`${INPUT} w-20 py-1`}
      />
    </div>
  )
}
