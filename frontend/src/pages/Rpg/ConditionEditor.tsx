import type { RpgCondition, RpgNpc, RpgStatDef } from '@/api/client'
import { ANY_NPC } from './condition'
import { AddRow, CommaInput, DeleteButton, INPUT, NumInput } from './rpgUi'

/** 后端 check_condition 认得的比较符，顺序即下拉顺序 */
const OPS = ['>=', '>', '<=', '<', '==', '!='] as const

const SELECT = 'border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none'

/**
 * 统一条件编辑器。世界书的触发条件、动作按钮的可用条件、地点的进入条件
 * 是同一套格式，后端也是同一个 check_condition 在求值，所以这里只写一遍。
 *
 * 语义：列出来的每一条都要满足，全空 = 无条件。
 */
export default function ConditionEditor({
  value, onChange, statDefs, relationDefs, npcs, slotNames = [],
}: {
  value: RpgCondition
  onChange: (next: RpgCondition) => void
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  /** 模组的时段表。编辑器里没有会话可查，合法的时段名只能从这儿来 */
  slotNames?: string[]
}) {
  const stats = value.stats || {}
  const relations = value.relations || []

  const patch = (next: Partial<RpgCondition>) => onChange({ ...value, ...next })

  const setStat = (name: string, key: 'op' | 'value', v: string) => {
    const row = stats[name]
    patch({
      stats: {
        ...stats,
        [name]: key === 'op'
          ? { ...row, op: v }
          : { ...row, value: Number(v) || 0 },
      },
    })
  }

  const dropStat = (name: string) => {
    const next = { ...stats }
    delete next[name]
    patch({ stats: next })
  }

  const addStat = () => {
    const free = statDefs.find(d => !(d.name in stats))
    if (!free) return
    patch({ stats: { ...stats, [free.name]: { op: '>=', value: 0 } } })
  }

  const setRelation = (i: number, key: 'npc' | 'stat' | 'op' | 'value', v: string) =>
    patch({
      relations: relations.map((r, n) => (
        n === i ? { ...r, [key]: key === 'value' ? Number(v) || 0 : v } : r
      )),
    })

  const unusedStat = statDefs.some(d => !(d.name in stats))

  const afterDays = value.after_days || []
  const setAfter = (i: number, key: 'flag' | 'days', v: string) =>
    patch({
      after_days: afterDays.map((r, n) => (
        n === i ? { ...r, [key]: key === 'days' ? Number(v) || 0 : v } : r
      )),
    })

  return (
    <div className="space-y-3 rounded-lg border border-dashed p-3">
      <p className="text-xs text-muted-foreground">
        列出来的每一条都要满足才算数，全空就是无条件。
      </p>

      <div className="space-y-1.5">
        <span className="text-xs font-medium">数值门槛</span>
        {Object.entries(stats).map(([name, row]) => (
          <div key={name} className="flex items-center gap-2">
            <span className="text-xs w-20 shrink-0 truncate">{name}</span>
            <select value={row.op} onChange={e => setStat(name, 'op', e.target.value)} className={SELECT}>
              {OPS.map(op => <option key={op} value={op}>{op}</option>)}
            </select>
            {/* 门槛经常是负的：「好感 ≤ -20 才触发」是最常见的敌对分支写法 */}
            <NumInput
              value={row.value}
              onChange={n => setStat(name, 'value', String(n ?? 0))}
              className={`${INPUT} w-24 py-1.5`}
            />
            <DeleteButton onClick={() => dropStat(name)} />
          </div>
        ))}
        {statDefs.length === 0 ? (
          <p className="text-xs text-muted-foreground">还没定义玩家数值。</p>
        ) : unusedStat && <AddRow onClick={addStat}>加一条数值门槛</AddRow>}
      </div>

      <div className="space-y-1.5">
        <span className="text-xs font-medium">关系门槛</span>
        {relations.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <select value={row.npc} onChange={e => setRelation(i, 'npc', e.target.value)} className={SELECT}>
              <option value={ANY_NPC}>任意角色</option>
              {npcs.map(n => <option key={n.id} value={n.name}>{n.name}</option>)}
            </select>
            <select value={row.stat} onChange={e => setRelation(i, 'stat', e.target.value)} className={SELECT}>
              {relationDefs.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
            <select value={row.op} onChange={e => setRelation(i, 'op', e.target.value)} className={SELECT}>
              {OPS.map(op => <option key={op} value={op}>{op}</option>)}
            </select>
            <NumInput
              value={row.value}
              onChange={n => setRelation(i, 'value', String(n ?? 0))}
              className={`${INPUT} w-20 py-1.5`}
            />
            <DeleteButton onClick={() => patch({ relations: relations.filter((_, n) => n !== i) })} />
          </div>
        ))}
        {npcs.length === 0 || relationDefs.length === 0 ? (
          <p className="text-xs text-muted-foreground">需要先有角色和关系数值定义。</p>
        ) : (
          <AddRow onClick={() => patch({
            relations: [...relations, { npc: npcs[0].name, stat: relationDefs[0].name, op: '>=', value: 0 }],
          })}>
            加一条关系门槛
          </AddRow>
        )}
        {npcs.length > 0 && relationDefs.length > 0 && (
          <p className="text-[11px] text-muted-foreground">
            「任意角色」= 不指定是谁，有一个角色达标就算成立。放在动作的可用条件上时，
            它自动就是「你这一轮选中的那个对象」；放在世界书和地点上时，是「随便哪个角色」。
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs font-medium mb-1 block">限定时段</label>
          <CommaInput
            value={value.slots || []}
            onChange={v => patch({ slots: v })}
            placeholder={slotNames.length ? slotNames.join('，') : '这个模组没有时段'}
            disabled={slotNames.length === 0}
            className={`${INPUT} py-1.5 disabled:opacity-50`}
          />
          <p className="text-[11px] text-muted-foreground mt-1">
            {slotNames.length
              ? `留空 = 不限。名字前加 ! 表示不能在那个时段，可选：${slotNames.join(' / ')}`
              : '先在模组的「时段」里设定，这里才有东西可填。'}
          </p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">限定天数</label>
          <div className="flex items-center gap-2">
            <select
              value={value.day?.op || ''}
              onChange={e => patch({
                day: e.target.value
                  ? { op: e.target.value, value: value.day?.value ?? 1 }
                  : undefined,
              })}
              className={SELECT}
            >
              <option value="">不限</option>
              {OPS.map(op => <option key={op} value={op}>{op}</option>)}
            </select>
            {value.day && (
              <>
                <NumInput
                  value={value.day.value}
                  onChange={n => patch({ day: { op: value.day!.op, value: n ?? 0 } })}
                  className={`${INPUT} w-20 py-1`}
                />
                <span className="text-xs text-muted-foreground">天</span>
              </>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground mt-1">
            拿天数做门槛，比如「第 3 天之后才开」。
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs font-medium mb-1 block">需要的剧情标记</label>
          <CommaInput
            value={value.flags || []}
            onChange={v => patch({ flags: v })}
            placeholder="已经拿到钥匙，!门已经开了"
            className={`${INPUT} py-1.5`}
          />
          <p className="text-[11px] text-muted-foreground mt-1">名字前加 ! 表示这条不能立着。</p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">需要的道具</label>
          <CommaInput
            value={value.items || []}
            onChange={v => patch({ items: v })}
            placeholder="铁钥匙，撬棍"
            className={`${INPUT} py-1.5`}
          />
          <p className="text-[11px] text-muted-foreground mt-1">背包里有就行，不会被扣掉。</p>
        </div>
      </div>

      {/* 标记名是自由文本，没有下拉可选：flag 是结算时模型现写的，
          编辑器这边没有一份「合法标记名」的清单可查。同上面「需要的剧情标记」 */}
      <div className="space-y-1.5">
        <span className="text-xs font-medium">某件事之后过几天</span>
        {afterDays.map((row, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              value={row.flag}
              onChange={e => setAfter(i, 'flag', e.target.value)}
              placeholder="聊过电机"
              className={`${INPUT} flex-1 py-1.5`}
            />
            <span className="text-xs text-muted-foreground shrink-0">之后</span>
            <NumInput
              value={row.days}
              onChange={n => setAfter(i, 'days', String(n ?? 0))}
              // 天数没有负的，但「删到空」不该当场变 0 再拼出个 05
              clamp={n => Math.max(0, n)}
              className={`${INPUT} w-20 py-1.5`}
            />
            <span className="text-xs text-muted-foreground shrink-0">天</span>
            <DeleteButton onClick={() => patch({ after_days: afterDays.filter((_, n) => n !== i) })} />
          </div>
        ))}
        <AddRow onClick={() => patch({ after_days: [...afterDays, { flag: '', days: 1 }] })}>
          加一条等待
        </AddRow>
        <p className="text-[11px] text-muted-foreground">
          上面的「限定天数」是第几天，这条是相对的：那个标记立起来之后再过几天。
          标记还没立、或者是加这个功能之前的老存档（没记下是哪天立的），都算不满足。
        </p>
      </div>
    </div>
  )
}
