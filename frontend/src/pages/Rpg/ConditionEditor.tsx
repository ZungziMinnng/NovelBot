import type { RpgCondition, RpgNpc, RpgStatDef } from '@/api/client'
import { AddRow, DeleteButton, INPUT } from './rpgUi'

/** 后端 check_condition 认得的比较符，顺序即下拉顺序 */
const OPS = ['>=', '>', '<=', '<', '==', '!='] as const

const SELECT = 'border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none'

/** 逗号分隔的一行文本 ↔ 字符串数组。flags 和 items 都只是一串名字，
 *  给每个名字配一行输入框反而更难填 */
const splitList = (text: string) => text.split(/[,，、;；]+/).map(s => s.trim()).filter(Boolean)

/**
 * 统一条件编辑器。世界书的触发条件、动作按钮的可用条件、地点的进入条件
 * 是同一套格式，后端也是同一个 check_condition 在求值，所以这里只写一遍。
 *
 * 语义：列出来的每一条都要满足，全空 = 无条件。
 */
export default function ConditionEditor({
  value, onChange, statDefs, relationDefs, npcs,
}: {
  value: RpgCondition
  onChange: (next: RpgCondition) => void
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
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
            <input
              type="number"
              value={row.value}
              onChange={e => setStat(name, 'value', e.target.value)}
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
              {npcs.map(n => <option key={n.id} value={n.name}>{n.name}</option>)}
            </select>
            <select value={row.stat} onChange={e => setRelation(i, 'stat', e.target.value)} className={SELECT}>
              {relationDefs.map(d => <option key={d.name} value={d.name}>{d.name}</option>)}
            </select>
            <select value={row.op} onChange={e => setRelation(i, 'op', e.target.value)} className={SELECT}>
              {OPS.map(op => <option key={op} value={op}>{op}</option>)}
            </select>
            <input
              type="number"
              value={row.value}
              onChange={e => setRelation(i, 'value', e.target.value)}
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
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs font-medium mb-1 block">需要的剧情标记</label>
          <input
            value={(value.flags || []).join('，')}
            onChange={e => patch({ flags: splitList(e.target.value) })}
            placeholder="已经拿到钥匙，!门已经开了"
            className={`${INPUT} py-1.5`}
          />
          <p className="text-[11px] text-muted-foreground mt-1">名字前加 ! 表示这条不能立着。</p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">需要的道具</label>
          <input
            value={(value.items || []).join('，')}
            onChange={e => patch({ items: splitList(e.target.value) })}
            placeholder="铁钥匙，撬棍"
            className={`${INPUT} py-1.5`}
          />
          <p className="text-[11px] text-muted-foreground mt-1">背包里有就行，不会被扣掉。</p>
        </div>
      </div>
    </div>
  )
}
