import { useEffect, useMemo, useState } from 'react'
import type { RpgLocation, RpgSession } from '@/api/client'
import { norm, visibleLocations } from './condition'
import { edgePairs, layout } from './mapLayout'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
}

const MAX_AROUND = 8

const W = 240
const H = 180

interface Painted {
  here: RpgLocation
  scoped: RpgLocation[]
  title: string
  pos: Map<number, { x: number; y: number }>
  edges: { a: RpgLocation; b: RpgLocation }[]
  visible: Set<number>
  went: Set<string>
}

/** 作者摆过坐标的地点够多，才画成真地图；否则坐标全是兜底网格，画出来是散的 */
function paint(locations: RpgLocation[], sess: RpgSession): Painted | null {
  const here = locations.find(l => norm(l.name) === norm(sess.location || ''))
  if (!here) return null
  const parentId = here.parent_id ?? null
  const scoped = locations.filter(l => (l.parent_id ?? null) === parentId)
  const placed = scoped.filter(l => l.x || l.y).length
  if (scoped.length < 3 || placed < Math.max(2, Math.ceil(scoped.length / 2))) return null
  const ids = new Set(scoped.map(l => l.id))
  return {
    here, scoped,
    title: parentId === null ? '大地图' : locations.find(l => l.id === parentId)?.name || '内部地图',
    pos: layout(scoped),
    edges: edgePairs(scoped).filter(({ a, b }) => ids.has(a.id) && ids.has(b.id)),
    visible: visibleLocations(locations, sess),
    went: new Set((sess.visited || []).map(norm)),
  }
}

/** 一张画出来的地图：区域是底色块，路是弯的，去过的亮、没去过的淡 */
function PaintedMap({ m, big }: { m: Painted; big: boolean }) {
  const px = (id: number) => (m.pos.get(id)!.x * W) / 100
  const py = (id: number) => (m.pos.get(id)!.y * H) / 100
  const road = ({ a, b }: { a: RpgLocation; b: RpgLocation }) => {
    const ax = px(a.id), ay = py(a.id), bx = px(b.id), by = py(b.id)
    const dx = bx - ax, dy = by - ay
    const bend = ((a.id + b.id) % 2 ? 1 : -1) * 0.14
    return `M${ax} ${ay} Q${(ax + bx) / 2 - dy * bend} ${(ay + by) / 2 + dx * bend} ${bx} ${by}`
  }
  const label = 'fill-foreground stroke-background'
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-full">
      {m.scoped.filter(l => l.is_region && m.visible.has(l.id)).map(l => (
        <circle key={l.id} cx={px(l.id)} cy={py(l.id)} r={big ? 26 : 22}
          className="fill-sky-500/10 stroke-sky-500/40" strokeDasharray="3 3" strokeWidth={1} />
      ))}
      {m.edges.filter(({ a, b }) => m.visible.has(a.id) && m.visible.has(b.id)).map(e => (
        <path key={`${e.a.id}-${e.b.id}`} d={road(e)} fill="none" stroke="currentColor"
          strokeOpacity={0.25} strokeWidth={1.5} strokeLinecap="round" className="text-muted-foreground" />
      ))}
      {m.scoped.map(l => {
        const x = px(l.id), y = py(l.id)
        if (l.id === m.here.id) {
          return (
            <g key={l.id}>
              <circle cx={x} cy={y} r={8} className="fill-primary/20" />
              <circle cx={x} cy={y} r={4.5} className="fill-primary" />
              <text x={x} y={y + 15} textAnchor="middle" fontSize={9} fontWeight={600}
                strokeWidth={2.5} paintOrder="stroke" className={label}>{l.name}</text>
            </g>
          )
        }
        if (!m.visible.has(l.id)) {
          return <circle key={l.id} cx={x} cy={y} r={2} className="fill-muted-foreground/25" />
        }
        const seen = m.went.has(norm(l.name))
        return (
          <g key={l.id}>
            <title>{seen ? l.name : `${l.name}（未到过）`}</title>
            <circle cx={x} cy={y} r={seen ? 3.5 : 3}
              className={seen ? 'fill-primary/60 stroke-primary' : 'fill-background stroke-muted-foreground/50'}
              strokeWidth={1} />
            {(seen || big) && (
              <text x={x} y={y + 11} textAnchor="middle" fontSize={8} strokeWidth={2.5}
                paintOrder="stroke" className={`${label} ${seen ? '' : 'opacity-60'}`}>{l.name}</text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

/** 侧栏小地图：作者摆过坐标的模组画成真地图（可点开放大），否则退回以当前所在地为中心，相邻的地点围成一圈。不照搬模组里摆的坐标，
 *  只拿作者摆的方位给周围的点排个先后；没有连线时退回同一层里看得见的其他地点 */
export default function MiniMap({ sess, locations }: Props) {
  const painted = useMemo(() => paint(locations, sess), [locations, sess])
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [open])
  const view = useMemo(() => {
    const here = locations.find(l => norm(l.name) === norm(sess.location || ''))
    if (!here) return null
    const parentId = here.parent_id ?? null
    const level = locations.filter(l => (l.parent_id ?? null) === parentId && l.id !== here.id)
    const visible = visibleLocations(locations, sess)
    const linked = level.filter(l =>
      (here.connections || []).some(n => norm(n) === norm(l.name))
      || (l.connections || []).some(n => norm(n) === norm(here.name)))
    const pool = (linked.length ? linked : level).filter(l => visible.has(l.id))
    if (!pool.length) return null
    // 作者摆过坐标的按相对当前点的方位角排，没摆过的排在后面
    const angle = (l: RpgLocation) =>
      (here.x || here.y) && (l.x || l.y) ? Math.atan2(l.y - here.y, l.x - here.x) : Infinity
    const sorted = [...pool].sort((a, b) => angle(a) - angle(b))
    return {
      here,
      around: sorted.slice(0, MAX_AROUND),
      more: Math.max(0, sorted.length - MAX_AROUND),
      linked: linked.length > 0,
      title: parentId === null ? '大地图' : locations.find(l => l.id === parentId)?.name || '内部地图',
      went: new Set((sess.visited || []).map(norm)),
    }
  }, [locations, sess])

  if (painted) {
    return (
      <div>
        <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
          <span>{painted.title}</span>
          <span>点开放大</span>
        </div>
        <button
          onClick={() => setOpen(true)}
          title="放大"
          className="block w-full aspect-[4/3] rounded-xl border border-border/60 bg-amber-500/[0.04] overflow-hidden
            hover:border-primary/50 transition-colors"
        >
          <PaintedMap m={painted} big={false} />
        </button>
        {open && (
          <div
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          >
            <div
              onClick={e => e.stopPropagation()}
              className="w-full max-w-[760px] aspect-[4/3] rounded-2xl border border-border/60 bg-background shadow-xl p-3"
            >
              <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                <span>{painted.title} · 实心是去过的</span>
                <button onClick={() => setOpen(false)} className="hover:text-foreground">关闭</button>
              </div>
              <div className="h-[calc(100%-1.5rem)] rounded-xl bg-amber-500/[0.04]">
                <PaintedMap m={painted} big />
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (!view) return null
  const { here, around, more, linked, title, went } = view
  const n = around.length
  const spot = (i: number) => {
    const t = -Math.PI / 2 + (i / n) * Math.PI * 2
    return { x: 50 + Math.cos(t) * 36, y: 50 + Math.sin(t) * 33 }
  }

  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{title}</span>
        <span>{linked ? '附近' : '这一带'}</span>
      </div>
      <div className="relative w-full aspect-[4/3] rounded-xl border border-border/60 bg-card/40 overflow-hidden">
        {linked && (
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
            {around.map((_, i) => {
              const p = spot(i)
              return (
                <line
                  key={i} x1={50} y1={50} x2={p.x} y2={p.y}
                  stroke="currentColor" strokeWidth={1.5} strokeOpacity={0.3}
                  vectorEffect="non-scaling-stroke"
                />
              )
            })}
          </svg>
        )}
        {around.map((loc, i) => {
          const p = spot(i)
          const seen = went.has(norm(loc.name))
          return (
            <span
              key={loc.id}
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
              title={seen ? loc.name : `${loc.name}（未到过）`}
              className={`absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center
                ${seen ? '' : 'opacity-60'}`}
            >
              <span className={`w-2 h-2 ${loc.is_region ? 'rounded-sm border border-dashed border-sky-500/70' : 'rounded-full'}
                ${seen ? 'bg-muted-foreground/70' : 'border border-muted-foreground/60 bg-background'}`} />
              <span className="mt-0.5 max-w-[72px] truncate text-[10px] leading-none text-muted-foreground">
                {loc.name}
              </span>
            </span>
          )
        })}
        <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col items-center">
          <span className="w-3.5 h-3.5 rounded-full bg-primary ring-4 ring-primary/20" />
          <span className="mt-1 max-w-[90px] truncate text-[11px] font-medium leading-none">{here.name}</span>
        </span>
        {more > 0 && (
          <span className="absolute right-2 bottom-1 text-[10px] text-muted-foreground">+{more}</span>
        )}
      </div>
    </div>
  )
}
