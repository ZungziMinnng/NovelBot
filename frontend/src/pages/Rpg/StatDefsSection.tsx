import type { RpgModule, RpgStatDef } from '@/api/client'
import { AddRow, DeleteButton, INPUT } from './rpgUi'

const SELECT = 'border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none'

const DISPLAYS = ['条', '数字', '隐藏'] as const
const ON_ZERO = ['无', '死亡', '标记'] as const

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
  form, set,
}: {
  form: RpgModule
  set: <K extends keyof RpgModule>(key: K, value: RpgModule[K]) => void
}) {
  return (
    <div className="space-y-6">
      <StatTable
        label="玩家数值"
        hint="资金、精力、声望这些跟着玩家走的数字。判定默认是关着的，「可判定」只有开了判定才有用。"
        defs={form.stat_defs || []}
        onChange={v => set('stat_defs', v)}
        make={newPlayerStat}
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
  label, hint, defs, onChange, make, full,
}: {
  label: string
  hint: string
  defs: RpgStatDef[]
  onChange: (next: RpgStatDef[]) => void
  make: () => RpgStatDef
  /** 玩家数值才有「可判定」和「归零时」两列 */
  full?: boolean
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
                placeholder="名字，如：精力"
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
                </>
              )}
            </div>
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
