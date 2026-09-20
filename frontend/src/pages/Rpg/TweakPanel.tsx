import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Minus, Plus, X } from 'lucide-react'
import { rpgApi } from '@/api/client'
import type { RpgLocation, RpgModule, RpgNpc, RpgSession } from '@/api/client'
import { npcPlace } from './condition'

/** 背包里的一行。fresh = 玩家刚在「加一件」里敲出来、还没提交的那几行——
 *  它们和已经躺在背包里的东西长得一样，只有提交时拿什么当「原来有几件」不同 */
interface BagRow {
  name: string
  qty: string
  fresh: boolean
}

/** 处境的一行。val 为 null = 玩家按了叉，提交时发给后端的也是 null（这条不存在）。
 *  这种行不画出来，但得留在 state 里：「还原」要能把它们捞回来 */
interface FlagRow {
  key: string
  val: boolean | null
}

/** 数字框一律留成字符串：中途会出现空串和单独一个负号，受控成 number 的话
 *  玩家每敲一个字都会被我们的转换吃掉。空串和解析不出来的当「这一项没动」，
 *  **不能当 0**——玩家把框清空是想重打一遍，不是想把它改成 0 */
function parseNum(raw: string): number | null {
  const t = raw.trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

/** ±1。框里还是半截输入时以真实值为准，不然按一下加号会把 50 变成 1 */
function bump(raw: string | undefined, fallback: number, delta: number): string {
  return String((parseNum(raw || '') ?? fallback) + delta)
}

const INPUT = 'w-16 px-1.5 py-0.5 text-xs rounded border bg-background'
const FREE_INPUT = 'flex-1 min-w-0 px-1.5 py-0.5 text-xs rounded border bg-background'
const BTN = 'px-2 py-0.5 text-xs rounded border hover:bg-muted'

/** 修改器。宽度由外面那个浮层给，这里只管内部布局 */
export default function TweakPanel({
  sessionId, sess, module, npcs, locations, locked, onApplied,
}: {
  sessionId: number
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  locations: RpgLocation[]
  /** 生成中。半轮里改数值会被这一轮的结算盖掉，所以这时候不让点「应用」 */
  locked: boolean
  /** 改完了，把新会话交回去（父组件会写回 query cache） */
  onApplied: (next: RpgSession) => void
}) {
  const statDefs = (module?.stat_defs || []).filter(d => d.name)

  // 关系数值只认模组里定义过的名字：对象状态里还混着别的键，那些不是数值
  const relDefs = (module?.relation_stat_defs || []).filter(d => d.name)
  const stateOf = (npcId: string) => sess.npc_states?.[npcId] || {}
  const relDefsOf = (npc: RpgNpc) => npc.relation_stat_names?.length
    ? relDefs.filter(d => npc.relation_stat_names.includes(d.name))
    : relDefs

  // 下拉里只列**已经带着关系值**的人：后端对没启用关系数值的人是直接拒绝的，
  // 列出来只会换回一句「这个角色没有启用关系数值」，白让玩家点一次。
  // 一个人都没有时这一段连标题一起不渲染——空下拉比不显示更让人困惑
  const related = npcs.filter(n => n.relation_enabled !== false && relDefsOf(n).length > 0)

  // 这个人的关系数值按模组定义的顺序取，不跟着状态对象的插入顺序走
  const relKeysOf = (npc: RpgNpc) => relDefsOf(npc).map(d => d.name)
  const relInitial = (npc: RpgNpc, name: string) => {
    const value = npc.initial_state?.[name]
    if (typeof value === 'number') return value
    return relDefs.find(d => d.name === name)?.initial ?? 0
  }

  const [statInputs, setStatInputs] = useState<Record<string, string>>({})
  const [relNpcId, setRelNpcId] = useState('')
  const [relInputs, setRelInputs] = useState<Record<string, Record<string, string>>>({})
  const [bagRows, setBagRows] = useState<BagRow[]>([])
  const [bagName, setBagName] = useState('')
  const [bagQty, setBagQty] = useState('1')
  const [flagRows, setFlagRows] = useState<FlagRow[]>([])
  const [flagName, setFlagName] = useState('')
  const [busy, setBusy] = useState(false)
  const [placeNpcId, setPlaceNpcId] = useState('')
  const [placeInputs, setPlaceInputs] = useState<Record<string, string | null>>({})
  const movableNpcs = npcs.filter(npc => npc.role !== 'protagonist')
  const selectedNpc = movableNpcs.find(npc => String(npc.id) === placeNpcId) || movableNpcs[0]
  const selectedId = selectedNpc ? String(selectedNpc.id) : ''
  const currentPlace = selectedNpc
    ? npcPlace(selectedNpc, sess.slot, sess.npc_places, sess.npc_followers, sess.location)
    : ''
  const hasPlaceEdit = Object.prototype.hasOwnProperty.call(placeInputs, selectedId)
  const selectedPlace = hasPlaceEdit ? placeInputs[selectedId] ?? '' : currentPlace
  const placeNames = Array.from(new Set(locations.map(place => place.name).filter(Boolean)))

  /** 把面板整个铺回当前的真实数值。「还原」按钮跑的就是这个，不是第二套逻辑 */
  const reset = () => {
    const st: Record<string, string> = {}
    for (const d of statDefs) st[d.name] = String(sess.stats?.[d.name] ?? d.initial)
    setStatInputs(st)

    const rel: Record<string, Record<string, string>> = {}
    for (const n of related) {
      const id = String(n.id)
      const cur = stateOf(id)
      const one: Record<string, string> = {}
      for (const name of relKeysOf(n)) one[name] = String(cur[name] ?? relInitial(n, name))
      rel[id] = one
    }
    setRelInputs(rel)
    // 原先选中的人还在就留着：每铺一次都把下拉弹回第一个人很难用
    setRelNpcId(prev => (prev && rel[prev] ? prev : related[0] ? String(related[0].id) : ''))

    setBagRows((sess.inventory || []).map(
      it => ({ name: it.name, qty: String(it.qty), fresh: false }),
    ))
    setBagName('')
    setBagQty('1')

    setFlagRows(Object.entries(sess.flags || {}).map(([key, val]) => ({ key, val: !!val })))
    setFlagName('')
    setPlaceInputs({})
  }

  // sess 换了（应用完、或者刚打完一轮）就重铺，免得面板上停着一份过期的数字
  useEffect(() => {
    reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sess])

  /** 选中那个人身上某一项的当前真实值。− / + 拿它当兜底 */
  const curRel = (name: string) => {
    const npc = related.find(n => String(n.id) === relNpcId)
    const v = sess.npc_states?.[relNpcId]?.[name]
    return typeof v === 'number' ? v : npc ? relInitial(npc, name) : 0
  }

  const setRel = (name: string, v: string) =>
    setRelInputs(s => ({ ...s, [relNpcId]: { ...(s[relNpcId] || {}), [name]: v } }))

  const toggleFlag = (key: string) =>
    setFlagRows(rows => rows.map(r => (r.key === key ? { ...r, val: !(r.val === true) } : r)))

  // 叉掉的行不从列表里删、只把 val 置成 null：null 就是后端认的「这条不存在」，
  // 而且留着它「还原」才捞得回来
  const dropFlag = (key: string) =>
    setFlagRows(rows => rows.map(r => (r.key === key ? { ...r, val: null } : r)))

  const addFlag = () => {
    const key = flagName.trim()
    if (!key) return
    setFlagRows(rows => {
      // 已经有这条了（可能刚被叉掉）：捞回来置成 true，别出两行一样的键
      if (rows.some(r => r.key === key)) {
        return rows.map(r => (r.key === key ? { ...r, val: true } : r))
      }
      return [...rows, { key, val: true }]
    })
    setFlagName('')
  }

  const addBag = () => {
    const name = bagName.trim()
    if (!name) return
    // 只是往本地列表里追一行，真正提交在「应用」时一起发。
    // 名字已经在列表里的就改那一行的件数——两行同名的话，发出去的是
    // 两个互相覆盖的目标件数，玩家看到的结果全看谁在后面
    setBagRows(rows => {
      const qty = bagQty.trim() || '1'
      if (rows.some(r => r.name === name)) {
        return rows.map(r => (r.name === name ? { ...r, qty } : r))
      }
      return [...rows, { name, qty, fresh: true }]
    })
    setBagName('')
    setBagQty('1')
  }

  const apply = async () => {
    setBusy(true)
    try {
      // 各项都只装**真的动过**的项。全量发过去的话，玩家根本没碰过的
      // 越界旧值也会被后端念一句「被限制在 X」——他什么都没干
      const stats: Record<string, number> = {}
      for (const d of statDefs) {
        const next = parseNum(statInputs[d.name] ?? '')
        if (next === null) continue
        if (next !== (sess.stats?.[d.name] ?? d.initial)) stats[d.name] = next
      }

      // 键用 id 的字符串形式，和 npc_states 那边保持一致
      const relations: Record<string, Record<string, number>> = {}
      for (const [id, one] of Object.entries(relInputs)) {
        const cur = stateOf(id)
        const npc = related.find(n => String(n.id) === id)
        const patch: Record<string, number> = {}
        for (const [name, raw] of Object.entries(one)) {
          const next = parseNum(raw)
          if (next === null) continue
          const before = cur[name] ?? (npc ? relInitial(npc, name) : 0)
          if (next !== before) patch[name] = next
        }
        if (Object.keys(patch).length > 0) relations[id] = patch
      }

      // 发的是**目标件数**，和 stats 一个口径：后端自己算差多少
      const inventory: { name: string; qty: number }[] = []
      for (const row of bagRows) {
        const next = parseNum(row.qty)
        if (next === null) continue
        if (row.fresh) {
          // 刚加的那几行背包里本来没有，件数是正的就得发
          if (next > 0) inventory.push({ name: row.name, qty: next })
          continue
        }
        const cur = (sess.inventory || []).find(it => it.name === row.name)?.qty ?? 0
        if (next !== cur) inventory.push({ name: row.name, qty: next })
      }

      const flags: Record<string, boolean | null> = {}
      const before = sess.flags || {}
      for (const row of flagRows) {
        const had = Object.prototype.hasOwnProperty.call(before, row.key)
        if (row.val === null) {
          // 叉掉的：本来就没有这条就不用发
          if (had) flags[row.key] = null
        } else if (!had || !!before[row.key] !== row.val) {
          flags[row.key] = row.val
        }
      }

      const res = await rpgApi.sessions.tweak(sessionId, {
        stats, relations, inventory, flags, npc_places: placeInputs,
      })
      onApplied(res.session)
      // notes 是后端那几句「哪一项被夹到了 X」，逐条说出来；
      // 一句都没有说明各项原样收下了
      if (res.notes.length > 0) res.notes.forEach(n => toast(n))
      else toast.success('改好了')
    } catch {
      toast.error('改不动，再试一次')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-[11px] text-muted-foreground">
        修改器：改完立刻生效，GM 不会知道你动过手。
      </p>

      {selectedNpc && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium">人物位置</p>
          <select
            aria-label="选择位置修改对象"
            value={selectedId}
            onChange={event => setPlaceNpcId(event.target.value)}
            className={`${FREE_INPUT} w-full`}
          >
            {movableNpcs.map(npc => (
              <option key={npc.id} value={String(npc.id)}>{npc.name}</option>
            ))}
          </select>
          <p className="text-[11px] text-muted-foreground">当前位置：{currentPlace || '未安排'}</p>
          <select
            aria-label="人物目标地点"
            value={selectedPlace}
            onChange={event => setPlaceInputs(previous => ({
              ...previous, [selectedId]: event.target.value || null,
            }))}
            className={`${FREE_INPUT} w-full`}
          >
            <option value="">恢复作息 / 常驻地点（解除跟随）</option>
            {selectedPlace && !placeNames.includes(selectedPlace) && (
              <option value={selectedPlace} disabled>{selectedPlace}（未登记地点）</option>
            )}
            {placeNames.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
          <div className="flex gap-2">
            <button
              className={BTN}
              disabled={!placeNames.includes(sess.location)}
              onClick={() => setPlaceInputs(previous => ({ ...previous, [selectedId]: sess.location }))}
            >移到我这里</button>
            <button
              className={BTN}
              onClick={() => setPlaceInputs(previous => ({ ...previous, [selectedId]: null }))}
            >恢复日常安排</button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            包含未出场人物。应用后改变本局当前位置；移到别处会解除跟随，后续仍按剧情、作息或随机移动活动。
          </p>
          {Object.keys(placeInputs).length > 0 && (
            <p className="text-[11px] text-primary">待应用：{Object.keys(placeInputs).length} 人的位置</p>
          )}
        </div>
      )}

      {statDefs.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium">玩家数值</p>
          {statDefs.map(d => (
            <div key={d.name} className="flex items-center gap-1.5">
              {/* 隐藏项照样列出来：侧栏那份过滤是为了不剧透作者埋的伏笔，
                  而修改器整个存在的意义就是能碰到那些格子，在这儿再滤一遍等于白开 */}
              <span className="text-xs flex-1 min-w-0 truncate">
                {d.name}
                {d.display === '隐藏' && <span className="text-[10px] opacity-60 ml-1">隐藏</span>}
                {d.max != null && (
                  <span className="text-[10px] opacity-60 ml-1">{d.min}~{d.max}</span>
                )}
              </span>
              <input
                value={statInputs[d.name] ?? ''}
                onChange={e => setStatInputs(s => ({ ...s, [d.name]: e.target.value }))}
                className={INPUT}
              />
              <button
                onClick={() => setStatInputs(s => ({
                  ...s,
                  [d.name]: bump(s[d.name], sess.stats?.[d.name] ?? d.initial, -1),
                }))}
                className={BTN}
              >
                <Minus className="w-3 h-3" />
              </button>
              <button
                onClick={() => setStatInputs(s => ({
                  ...s,
                  [d.name]: bump(s[d.name], sess.stats?.[d.name] ?? d.initial, 1),
                }))}
                className={BTN}
              >
                <Plus className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {related.length > 0 && (
        <>
          <div className="border-t border-border/60" />
          <div className="space-y-1.5">
            <p className="text-xs font-medium">角色关系</p>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">对象</span>
              <select
                value={relNpcId}
                onChange={e => setRelNpcId(e.target.value)}
                className={FREE_INPUT}
              >
                {related.map(n => (
                  <option key={n.id} value={String(n.id)}>{n.name}</option>
                ))}
              </select>
            </div>
            {Object.entries(relInputs[relNpcId] || {}).map(([name, val]) => (
              <div key={name} className="flex items-center gap-1.5">
                <span className="text-xs flex-1 min-w-0 truncate">{name}</span>
                <input value={val} onChange={e => setRel(name, e.target.value)} className={INPUT} />
                <button onClick={() => setRel(name, bump(val, curRel(name), -1))} className={BTN}>
                  <Minus className="w-3 h-3" />
                </button>
                <button onClick={() => setRel(name, bump(val, curRel(name), 1))} className={BTN}>
                  <Plus className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="border-t border-border/60" />
      <div className="space-y-1.5">
        <p className="text-xs font-medium">背包</p>
        {bagRows.map((row, i) => (
          <div key={`${row.name}-${i}`} className="flex items-center gap-1.5">
            <span className="text-xs flex-1 min-w-0 truncate">
              {row.name}
              {row.fresh && <span className="text-[10px] opacity-60 ml-1">待加</span>}
            </span>
            <input
              value={row.qty}
              onChange={e => setBagRows(
                rows => rows.map((r, j) => (j === i ? { ...r, qty: e.target.value } : r)),
              )}
              className={INPUT}
            />
            <button
              onClick={() => setBagRows(rows => rows.map((r, j) => (j === i ? { ...r, qty: '0' } : r)))}
              title="把件数改成 0，应用之后这件东西就没了"
              className={BTN}
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <input
            value={bagName}
            onChange={e => setBagName(e.target.value)}
            placeholder="加一件"
            className={FREE_INPUT}
          />
          <input value={bagQty} onChange={e => setBagQty(e.target.value)} className={INPUT} />
          <button onClick={addBag} className={BTN}>加</button>
        </div>
      </div>

      <div className="border-t border-border/60" />
      <div className="space-y-1.5">
        <p className="text-xs font-medium">处境</p>
        {flagRows.filter(r => r.val !== null).map(row => (
          <div key={row.key} className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={row.val === true}
              onChange={() => toggleFlag(row.key)}
              className="w-3.5 h-3.5 accent-primary"
            />
            <span className="text-xs flex-1 min-w-0 truncate">{row.key}</span>
            <button onClick={() => dropFlag(row.key)} title="应用之后这条会被删掉" className={BTN}>
              <X className="w-3 h-3" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <input
            value={flagName}
            onChange={e => setFlagName(e.target.value)}
            placeholder="加一条"
            className={FREE_INPUT}
          />
          <button onClick={addFlag} className={BTN}>加</button>
        </div>
      </div>

      <div className="flex gap-2 pt-1">
        <button
          onClick={apply}
          disabled={locked || busy}
          title={locked ? '这一轮还在生成，现在改会被这一次的结算盖掉，等它说完' : undefined}
          className="flex-1 px-2 py-1 text-xs rounded bg-primary text-primary-foreground
            hover:opacity-90 disabled:opacity-40"
        >
          {busy ? '改…' : '应用'}
        </button>
        <button
          onClick={reset}
          title="把面板填回当前的真实数值。这不是撤销刚才那次应用——已经生效的改动只能再改一次"
          className="px-2 py-1 text-xs rounded border hover:bg-muted"
        >
          还原
        </button>
      </div>
    </div>
  )
}
