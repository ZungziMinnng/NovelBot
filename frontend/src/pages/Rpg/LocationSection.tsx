import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MapPin, X } from 'lucide-react'
import {
  rpgApi, type RpgCondition, type RpgLocation, type RpgNpc, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { norm } from './condition'
import { clampPct, edgePairs, layout } from './mapLayout'
import { ACCENT, AddRow, Assist, DeleteButton, INPUT, Section } from './rpgUi'
import ConditionEditor from './ConditionEditor'
import BatchGenerate from './BatchGenerate'

/** x/y **不在这里面**，而且不能加进来：submit 是把整个 form 铺开发出去的，
 *  开着编辑表单的时候拖一下，保存就会把刚摆好的位置盖回旧值。
 *  坐标只由拖拽写（它自己单独发一次 PATCH）。 */
interface LocForm {
  name: string
  description: string
  parent_id: number | null
  connections: string[]
  enter_requires: RpgCondition
}

const EMPTY: LocForm = { name: '', description: '', parent_id: null, connections: [], enter_requires: {} }

/** 地点。connections 存名字不存 id——NPC 的常驻地点本来就是字符串，
 *  用 id 会凭空多一套映射，改个地点名就对不上了。 */
export default function LocationSection({
  moduleId, statDefs, relationDefs, npcs, slotNames, example = '地窖', assistContext,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
  /** 空格子里的示例词，按玩法类别换（见 stylePresets.STYLE_EXAMPLES） */
  example?: string
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
}) {
  const qc = useQueryClient()
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<LocForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-locations', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  const startEdit = (loc: RpgLocation) => {
    setEditingId(loc.id)
    setForm({
      name: loc.name, description: loc.description, parent_id: loc.parent_id || null,
      connections: loc.connections || [], enter_requires: loc.enter_requires || {},
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      if (editingId) {
        await rpgApi.locations.update(editingId, { ...form, name: form.name.trim() })
      } else {
        await rpgApi.locations.create(moduleId, {
          ...form, name: form.name.trim(), sort_order: locations.length + 1,
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存地点失败')
    }
  }

  const remove = async (loc: RpgLocation) => {
    if (!await confirmDialog({
      title: `确认删除地点「${loc.name}」？`,
      detail: '别的地点连到它的那条路也会断掉。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.locations.delete(loc.id)
      refresh()
    } catch {
      toast.error('删除地点失败')
    }
  }

  /** 拖完落库。只有真的挪了才会走到这儿（见 MapCanvas） */
  const place = async (id: number, x: number, y: number) => {
    try {
      await rpgApi.locations.update(id, { x, y })
      await refresh()
    } catch {
      toast.error('保存位置失败')
    }
  }

  /** 画布上改了连接，而下面的表单正开着同一个地点：表单里那份是旧的，
   *  它 submit 时会把整个 form 铺开发出去，刚连的路会被盖回去 */
  const syncForm = (id: number, connections: string[]) =>
    setForm(prev => (editingId === id ? { ...prev, connections } : prev))

  /** 画布空白处双击：当场建一个占位地点，坐标就是落点，然后把表单打开让作者填名字。
   *
   *  名字必须去重 —— connections 是按名字匹配的，两个「新地点」会让连接指向歧义。 */
  const createAt = async (x: number, y: number) => {
    let name = '新地点'
    for (let i = 2; locations.some(l => norm(l.name) === norm(name)); i++) name = `新地点 ${i}`
    try {
      const created = await rpgApi.locations.create(moduleId, {
        name, x, y, sort_order: locations.length + 1,
      })
      await refresh()
      startEdit(created)
    } catch {
      toast.error('新建地点失败')
    }
  }

  /** 从把手拖到另一个地点。只写在源地点上：连接是无向的，edgePairs 已经去重，
   *  两头都写会在数据里留两份，改名时只改得掉一头。 */
  const link = async (from: RpgLocation, to: RpgLocation) => {
    const current = from.connections || []
    const already = current.some(n => norm(n) === norm(to.name))
      || (to.connections || []).some(n => norm(n) === norm(from.name))
    if (already) return
    const next = [...current, to.name]
    try {
      await rpgApi.locations.update(from.id, { connections: next })
      syncForm(from.id, next)
      await refresh()
    } catch {
      toast.error('连接失败')
    }
  }

  /** 点线断开。两头都要清 —— 实际数据里常常两头都写着，只删一头线还在。 */
  const unlink = async (a: RpgLocation, b: RpgLocation) => {
    if (!await confirmDialog({
      title: `断开「${a.name}」和「${b.name}」之间的路？`,
      detail: '两头的连接都会清掉，地点本身不动。连接只管画地图和散迷雾，断了照样能走过去。',
      confirmText: '断开',
    })) return
    try {
      for (const [self, other] of [[a, b], [b, a]] as const) {
        const next = (self.connections || []).filter(n => norm(n) !== norm(other.name))
        if (next.length === (self.connections || []).length) continue
        await rpgApi.locations.update(self.id, { connections: next })
        syncForm(self.id, next)
      }
      await refresh()
    } catch {
      toast.error('断开失败')
    }
  }

  const names = new Set(locations.map(l => norm(l.name)))
  const others = locations.filter(l => l.id !== editingId).map(l => l.name)
  const toggleLink = (name: string) => setForm(prev => ({
    ...prev,
    connections: prev.connections.includes(name)
      ? prev.connections.filter(n => n !== name)
      : [...prev.connections, name],
  }))

  return (
    <Section
      title="地点"
      desc="玩家点一下就能去任何地点。连接不拦路，只用来在地图上画路、顺带把邻居从迷雾里点亮；要拦就用进入条件。"
      icon={MapPin}
      accent={ACCENT.map}
    >
      <div className="space-y-2">
        <MapCanvas
          locations={locations}
          onPlace={place}
          onCreate={createAt}
          onLink={link}
          onUnlink={unlink}
        />
        <p className="text-xs text-muted-foreground">
          玩家看到的地图就是这个样子。空白处<b>双击</b>建一个地点，拖着地点摆位置，
          从地点右边那个小圆点拖到另一个地点连一条路，点已有的线可以断开。没摆过的先按格子排。
          （摆位和连线只能用鼠标，手机上请用下面的表单。）
        </p>

        {locations.map(loc => (
          <div key={loc.id} className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{loc.name}</span>
                {/* 连到一个不存在的地点（改过名之后留下的悬空名字）标红：
                    地图上这条路会直接不画，不标的话作者只会觉得「怎么没显示」 */}
                {(loc.connections || []).map(c => (
                  <span
                    key={c}
                    title={names.has(norm(c)) ? undefined : '没有这个地点，这条路画不出来'}
                    className={`text-[11px] px-2 py-0.5 rounded-full ${
                      names.has(norm(c))
                        ? 'bg-primary/10 text-primary'
                        : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                    }`}
                  >
                    → {c}
                  </span>
                ))}
                {Object.keys(loc.enter_requires || {}).length > 0 && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">
                    有进入条件
                  </span>
                )}
              </div>
              {loc.description && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{loc.description}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(loc)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(loc)} />
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑地点' : '新增地点'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder={`地点名，如：${example}`}
              className={INPUT}
            />
            <div>
              <label className="text-xs font-medium mb-1.5 block">所属地点（可选）</label>
              <select
                value={form.parent_id ?? ''}
                onChange={e => setForm({ ...form, parent_id: e.target.value ? Number(e.target.value) : null })}
                className={INPUT}
              >
                <option value="">顶层地点（大地图）</option>
                {locations.filter(loc => loc.id !== editingId).map(loc => (
                  <option key={loc.id} value={loc.id}>{loc.name}</option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground mt-1">设置后，这个地点会显示在父地点的内部小地图中。</p>
            </div>
            <div>
              <textarea
                value={form.description}
                onChange={e => setForm({ ...form, description: e.target.value })}
                placeholder="走进来看到什么、闻到什么、有什么不对劲……"
                className={`${INPUT} resize-y min-h-[4rem]`}
              />
              <Assist
                moduleId={moduleId}
                field="location_description"
                context={() => ({ ...assistContext(), 地点名: form.name })}
                value={form.description}
                onApply={v => setForm(f => ({ ...f, description: v }))}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1.5 block">和哪儿连着</label>
              {others.length === 0 ? (
                <p className="text-xs text-muted-foreground">先多加几个地点，才能连起来。</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {others.map(name => (
                    <button
                      key={name}
                      onClick={() => toggleLink(name)}
                      className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                        form.connections.includes(name)
                          ? 'bg-primary/15 text-primary border-primary/40'
                          : 'hover:bg-muted text-muted-foreground'
                      }`}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground mt-1.5">
                连线是双向的，不用两头都点一遍。
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1.5 block">进入条件</label>
              <ConditionEditor
                value={form.enter_requires}
                onChange={v => setForm({ ...form, enter_requires: v })}
                statDefs={statDefs}
                relationDefs={relationDefs}
                npcs={npcs}
                slotNames={slotNames}
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button
                onClick={submit}
                disabled={!form.name.trim()}
                className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {editingId ? '保存' : '添加'}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加地点</AddRow>
            <BatchGenerate<{ name: string; description: string; connections: string[] }>
              moduleId={moduleId}
              kind="location"
              placeholder="想生成什么地点？比如：生成霍格沃兹的地点，五个"
              renderRow={(loc) => loc.connections?.length
                ? <span className="text-xs text-muted-foreground truncate">通往 {loc.connections.join('、')}</span>
                : null}
              onApply={async (locs) => {
                for (const loc of locs) {
                  await rpgApi.locations.create(moduleId, {
                    name: loc.name, description: loc.description,
                    connections: loc.connections, sort_order: locations.length + 1,
                  })
                }
                await refresh()
              }}
            />
          </div>
        )}
      </div>
    </Section>
  )
}

/**
 * 摆地图。和玩家看到的那张（LocationOverview）共用 mapLayout 里的两个纯函数，
 * 差别是：这里能拖、能建、能连、没有迷雾、全部显示。
 *
 * 只绑鼠标事件，也就是说摆位和连线只能在桌面上做——和编辑器里的关系图一样。
 * 手机上作者照样能用下面的表单建地点、点 chip 连路，只是排不了版。
 */
function MapCanvas({ locations, onPlace, onCreate, onLink, onUnlink }: {
  locations: RpgLocation[]
  onPlace: (id: number, x: number, y: number) => Promise<void>
  onCreate: (x: number, y: number) => Promise<void>
  onLink: (from: RpgLocation, to: RpgLocation) => Promise<void>
  onUnlink: (a: RpgLocation, b: RpgLocation) => Promise<void>
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  // 拖到的位置先留在本地，等落库后的刷新回来才交还给服务端数据：
  // 松手就清的话会有一帧弹回旧坐标
  const [drag, setDrag] = useState<{ id: number; x: number; y: number } | null>(null)
  // 正在拉的那条橡皮筋。from 是源地点 id，x/y 是光标现在在哪（百分比）
  const [rubber, setRubber] = useState<{ from: number; x: number; y: number } | null>(null)

  const pos = layout(locations)
  const at = (loc: RpgLocation) => (drag?.id === loc.id ? drag : pos.get(loc.id)!)

  /** 视口坐标 → 画布百分比。每次重读 rect：拖的中途页面可能滚动 */
  const pctOf = (clientX: number, clientY: number) => {
    const rect = boxRef.current?.getBoundingClientRect()
    if (!rect?.width || !rect.height) return null
    return {
      x: clampPct((clientX - rect.left) / rect.width * 100),
      y: clampPct((clientY - rect.top) / rect.height * 100),
    }
  }

  const grab = (e: React.MouseEvent, loc: RpgLocation) => {
    e.preventDefault()          // 挡掉原生拖拽，不然光标会变成「拖文字」
    const box = boxRef.current
    if (!box) return
    const start = at(loc)
    const from = { x: e.clientX, y: e.clientY }
    let now = { x: start.x, y: start.y }
    let moved = false

    const onMove = (ev: MouseEvent) => {
      const rect = box.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      now = {
        x: clampPct(start.x + (ev.clientX - from.x) / rect.width * 100),
        y: clampPct(start.y + (ev.clientY - from.y) / rect.height * 100),
      }
      moved = true
      setDrag({ id: loc.id, ...now })
    }
    const onUp = async () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      // 没挪动就什么都不发：不判的话每次点一下都会写一行
      if (moved && (now.x !== start.x || now.y !== start.y)) {
        await onPlace(loc.id, now.x, now.y)
      }
      setDrag(null)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  /** 从把手开始拉线。松手落在哪个节点上，靠 elementFromPoint 查
   *  —— 按坐标猜最近的那个在节点挨着时会连错人 */
  const startLink = (e: React.MouseEvent, from: RpgLocation) => {
    e.preventDefault()
    e.stopPropagation()         // 别让它变成「拖节点」
    const start = at(from)
    setRubber({ from: from.id, x: start.x, y: start.y })

    const onMove = (ev: MouseEvent) => {
      const p = pctOf(ev.clientX, ev.clientY)
      if (p) setRubber({ from: from.id, ...p })
    }
    const onUp = async (ev: MouseEvent) => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      setRubber(null)
      const holder = (document.elementFromPoint(ev.clientX, ev.clientY) as Element | null)
        ?.closest('[data-loc-id]')
      const to = locations.find(l => l.id === Number(holder?.getAttribute('data-loc-id')))
      if (to && to.id !== from.id) await onLink(from, to)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const rubberFrom = rubber ? locations.find(l => l.id === rubber.from) : undefined

  return (
    <div
      ref={boxRef}
      // 双击而不是单击：拖节点松手常常落在空白上，单击建点会满地误建
      onDoubleClick={e => {
        const p = pctOf(e.clientX, e.clientY)
        if (p) onCreate(p.x, p.y)
      }}
      className="relative w-full aspect-[3/2] overflow-hidden rounded-lg border bg-muted/20 select-none"
      title="空白处双击建一个地点"
    >
      {/* 连线层。viewBox 0..100 + preserveAspectRatio="none" 让一个 SVG 单位
          等于一个百分点，线才和 left:x% 的节点对得上；代价是非等比缩放，
          所以里面只放 <line> 并且都要 non-scaling-stroke */}
      <svg
        className="absolute inset-0 w-full h-full text-muted-foreground"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        {edgePairs(locations).map(({ a, b }) => {
          const pa = at(a)
          const pb = at(b)
          return (
            <g key={`${a.id}-${b.id}`}>
              {/* 看得见的那条 1.5px 的线点不中，所以底下垫一条透明的粗线当命中区。
                  stroke 给 transparent（不是 none）才会参与命中测试 */}
              <line
                x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                stroke="transparent" strokeWidth={10}
                vectorEffect="non-scaling-stroke"
                className="cursor-pointer"
                onClick={() => onUnlink(a, b)}
                onDoubleClick={ev => ev.stopPropagation()}
              >
                <title>{`${a.name} — ${b.name}（点一下断开）`}</title>
              </line>
              <line
                x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                stroke="currentColor" strokeWidth={1.5} strokeOpacity={0.3}
                vectorEffect="non-scaling-stroke"
                pointerEvents="none"
              />
            </g>
          )
        })}

        {/* 跟手的虚线。没落到节点上就什么都不会发生 */}
        {rubber && rubberFrom && (
          <line
            x1={at(rubberFrom).x} y1={at(rubberFrom).y} x2={rubber.x} y2={rubber.y}
            stroke="hsl(var(--primary))" strokeWidth={1.5} strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke" pointerEvents="none"
          />
        )}
      </svg>

      {locations.map(loc => {
        const p = at(loc)
        return (
          <button
            key={loc.id}
            data-loc-id={loc.id}
            onMouseDown={e => grab(e, loc)}
            onDoubleClick={e => e.stopPropagation()}
            style={{ left: `${p.x}%`, top: `${p.y}%` }}
            title="拖着摆位置"
            className={`absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1
              px-2 py-1 rounded-lg border bg-card text-xs whitespace-nowrap cursor-grab
              ${drag?.id === loc.id
                ? 'border-primary ring-2 ring-primary/30 cursor-grabbing'
                : 'border-border/70 hover:border-primary/50'}`}
          >
            <MapPin className="w-3 h-3 shrink-0" />
            {loc.name}
            {/* 连线的把手。必须独立于节点：拖节点已经占了节点的 mousedown，
                不给把手就只能按修饰键，没人会发现。用 span 不用 button
                —— 它在一个 button 里面 */}
            <span
              role="presentation"
              onMouseDown={e => startLink(e, loc)}
              title="拖到另一个地点，连一条路"
              className="w-2.5 h-2.5 -mr-0.5 rounded-full shrink-0 cursor-crosshair
                bg-primary/40 hover:bg-primary ring-1 ring-primary/40"
            />
          </button>
        )
      })}

      {locations.length === 0 && (
        <p className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">
          还没有地点。在这块画布上双击就能建一个。
        </p>
      )}
    </div>
  )
}
