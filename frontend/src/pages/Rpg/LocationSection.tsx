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
import { ACCENT, AddRow, DeleteButton, INPUT, Section } from './rpgUi'
import ConditionEditor from './ConditionEditor'

/** x/y **不在这里面**，而且不能加进来：submit 是把整个 form 铺开发出去的，
 *  开着编辑表单的时候拖一下，保存就会把刚摆好的位置盖回旧值。
 *  坐标只由拖拽写（它自己单独发一次 PATCH）。 */
interface LocForm {
  name: string
  description: string
  connections: string[]
  enter_requires: RpgCondition
}

const EMPTY: LocForm = { name: '', description: '', connections: [], enter_requires: {} }

/** 地点。connections 存名字不存 id——NPC 的常驻地点本来就是字符串，
 *  用 id 会凭空多一套映射，改个地点名就对不上了。 */
export default function LocationSection({
  moduleId, statDefs, relationDefs, npcs, slotNames,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
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
      name: loc.name, description: loc.description,
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
        {locations.length > 0 && (
          <>
            <MapCanvas locations={locations} onPlace={place} />
            <p className="text-xs text-muted-foreground">
              拖着地点摆位置，玩家看到的地图就是这个样子。没摆过的先按格子排。
            </p>
          </>
        )}

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
              placeholder="地点名，如：地窖"
              className={INPUT}
            />
            <textarea
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="走进来看到什么、闻到什么、有什么不对劲……"
              className={`${INPUT} resize-y min-h-[4rem]`}
            />
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
          <AddRow onClick={() => setShowForm(true)}>添加地点</AddRow>
        )}
      </div>
    </Section>
  )
}

/**
 * 摆地图。和玩家看到的那张（LocationOverview）共用 mapLayout 里的两个纯函数，
 * 差别只有：这里能拖、没有迷雾、全部显示。
 *
 * 只绑鼠标事件，也就是说摆位只能在桌面上做——和编辑器里的关系图一样。
 * 手机上作者照样能建地点、连路，只是排不了版。
 */
function MapCanvas({ locations, onPlace }: {
  locations: RpgLocation[]
  onPlace: (id: number, x: number, y: number) => Promise<void>
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  // 拖到的位置先留在本地，等落库后的刷新回来才交还给服务端数据：
  // 松手就清的话会有一帧弹回旧坐标
  const [drag, setDrag] = useState<{ id: number; x: number; y: number } | null>(null)

  const pos = layout(locations)
  const at = (loc: RpgLocation) => (drag?.id === loc.id ? drag : pos.get(loc.id)!)

  const grab = (e: React.MouseEvent, loc: RpgLocation) => {
    e.preventDefault()          // 挡掉原生拖拽，不然光标会变成「拖文字」
    const box = boxRef.current
    if (!box) return
    const start = at(loc)
    const from = { x: e.clientX, y: e.clientY }
    let now = { x: start.x, y: start.y }
    let moved = false

    const onMove = (ev: MouseEvent) => {
      // 每次重读 rect：clientX 是视口坐标，拖的中途页面可能滚动
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

  return (
    <div
      ref={boxRef}
      className="relative w-full aspect-[3/2] overflow-hidden rounded-lg border bg-muted/20 select-none"
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
            <line
              key={`${a.id}-${b.id}`}
              x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
              stroke="currentColor" strokeWidth={1.5} strokeOpacity={0.3}
              vectorEffect="non-scaling-stroke"
            />
          )
        })}
      </svg>

      {locations.map(loc => {
        const p = at(loc)
        return (
          <button
            key={loc.id}
            onMouseDown={e => grab(e, loc)}
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
          </button>
        )
      })}
    </div>
  )
}
