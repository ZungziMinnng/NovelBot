import type { RpgModule, RpgStatDef, RpgStatTier } from '@/api/client'
import { AddRow, DeleteButton, INPUT } from './rpgUi'

const SELECT = 'border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none'

const DISPLAYS = ['条', '数字', '隐藏'] as const
const ON_ZERO = ['无', '死亡', '标记'] as const

// 和 rpg_state.py 的 EFFECT_CHARS / TIER_LABEL_CHARS / TIER_NOTE_CHARS 对齐。
// 后端渲染时还会再截一刀（作者可以从别处粘进来），这里挡是为了让他当场看见
const EFFECT_MAX = 30
const LABEL_MAX = 6
const NOTE_MAX = 20

const newPlayerStat = (): RpgStatDef => ({
  name: '', initial: 50, min: 0, max: 100, for_check: false, on_zero: '无', display: '条',
})

const newRelationStat = (): RpgStatDef => ({
  name: '', initial: 0, min: 0, max: 100, display: '条',
})

/**
 * 数值定义。整个 RPG 的地基就是这两张表——玩家一套，角色共用一套。
 * 定义变了不会追溯已经开的局：那一局的数值在建局时就拷走了。
 */
export default function StatDefsSection({
  form, set, example = '精力',
}: {
  form: RpgModule
  set: <K extends keyof RpgModule>(key: K, value: RpgModule[K]) => void
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
                  <label className="flex items-center gap-1.5 cursor-pointer self-end pb-1.5">
                    <input
                      type="checkbox"
                      checked={!!def.for_check}
                      onChange={e => patch(i, { for_check: e.target.checked })}
                      className="accent-[hsl(var(--primary))]"
                    />
                    <span className="text-xs text-muted-foreground">可判定</span>
                  </label>
                  {/* 只在有上限的行上出现：「回满」得有个满可回 */}
                  {def.max != null && (
                    <label
                      className="flex items-center gap-1.5 cursor-pointer self-end pb-1.5"
                      title="过了一天就回到上限。精力、饱食度这类"
                    >
                      <input
                        type="checkbox"
                        checked={!!def.reset_daily}
                        onChange={e => patch(i, { reset_daily: e.target.checked })}
                        className="accent-[hsl(var(--primary))]"
                      />
                      <span className="text-xs text-muted-foreground">跨天回满</span>
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
