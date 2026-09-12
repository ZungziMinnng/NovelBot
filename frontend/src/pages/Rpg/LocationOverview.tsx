import { MapPin } from 'lucide-react'
import type { RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { checkCondition, knownNpcs, norm, visibleLocations } from './condition'
import { edgePairs, layout } from './mapLayout'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
  npcs: RpgNpc[]
  locked: boolean
  /** 有一次瞬移正在路上。纯引擎请求很快，但连点两下会发两个 */
  busy: boolean
  /** 点一下就过去，并且直接翻到那个地点页。纯引擎，不产生叙事 */
  onGo: (name: string) => void
  /** 进当前所在地点的地点页。只有「你在这里」那张卡能点 */
  onPick: () => void
}

/**
 * 地图。地点画在作者摆的位置上，连接画成路，「你在这里」标出来。
 *
 * 坐标是百分比，节点是绝对定位的 HTML，连线是底下一层 viewBox="0 0 100 100"
 * 且 preserveAspectRatio="none" 的 SVG——这样一个 SVG 单位就等于一个百分点，
 * 线和节点才会焊在一起。代价是非等比缩放，所以这一层里只放 <line>
 * （文字、圆、箭头都有自身几何，会被拉变形），而且每条线都要
 * vector-effect="non-scaling-stroke"，否则横竖线粗细不一样。
 *
 * 没去过、也不挨着去过的地方只画一个灰点：名字、描述、有谁，一概不给。
 *
 * **点一下就过去**，连不连着都一样——connections 只管画线和散迷雾。
 * 进入条件在这里提前判一次，只为把进不去的地方灰掉并写明原因；
 * 判定权始终在后端，这里放行了后端照样会拦。
 */
export default function LocationOverview({
  sess, locations, npcs, locked, busy, onGo, onPick,
}: Props) {
  if (locations.length === 0) {
    return (
      <p className="text-center text-sm text-muted-foreground py-20">
        这个模组还没定义地点。回模组页的「地点」里加几个，这里就会有了。
      </p>
    )
  }

  const here = locations.find(l => norm(l.name) === norm(sess.location || ''))
  const isHere = (loc: RpgLocation) => !!here && loc.id === here.id
  const pos = layout(locations)
  const visible = visibleLocations(locations, sess)

  /** 这个地点上站着谁。只看得到见过面的人——没见过的不该被抖出来 */
  const known = knownNpcs(npcs, sess)
  const faces = (loc: RpgLocation) => known.filter(n => norm(n.location) === norm(loc.name))

  /** 进不去的话，那句理由。空串 = 能进 */
  const blockedWhy = (loc: RpgLocation) => {
    const [ok, why] = checkCondition(loc.enter_requires, sess, npcs)
    return ok ? '' : why
  }

  return (
    <div className="space-y-3">
      <div className="relative w-full aspect-[3/2] overflow-hidden rounded-2xl border
        border-border/60 bg-card/40">
        <svg
          className="absolute inset-0 w-full h-full text-muted-foreground"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          {edgePairs(locations).map(({ a, b }) => {
            // 两头都看得见才画。只亮一头的话，未探索区域的形状会从线里被读出来
            if (!visible.has(a.id) || !visible.has(b.id)) return null
            const pa = pos.get(a.id)!
            const pb = pos.get(b.id)!
            const onRoute = isHere(a) || isHere(b)
            return (
              <line
                key={`${a.id}-${b.id}`}
                x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                stroke="currentColor"
                strokeWidth={onRoute ? 2 : 1.5}
                strokeOpacity={onRoute ? 0.55 : 0.25}
                vectorEffect="non-scaling-stroke"
              />
            )
          })}
        </svg>

        {locations.map(loc => {
          const p = pos.get(loc.id)!
          const style = { left: `${p.x}%`, top: `${p.y}%` }

          // 迷雾里的点必须是惰性的：名字、title（那句理由里带着地点名）、
          // 有谁、能不能点，一样都不能漏出去
          if (!visible.has(loc.id)) {
            return (
              <span
                key={loc.id}
                style={style}
                className="absolute -translate-x-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full
                  bg-muted-foreground/25"
              />
            )
          }

          const mine = isHere(loc)
          const people = faces(loc)
          const why = mine ? '' : blockedWhy(loc)
          return (
            <button
              key={loc.id}
              style={style}
              // 「你在这里」那张翻自己的地点页（导航，不受 locked 管）；
              // 别的点一下直接过去，过去之后也停在那个地点页
              onClick={() => (mine ? onPick() : onGo(loc.name))}
              disabled={!mine && (locked || busy || !!why)}
              title={mine
                ? '看看这里有谁'
                : why || (people.length > 0
                  ? `去${loc.name}（这里有：${people.map(n => n.name).join('、')}）`
                  : `去${loc.name}`)}
              className={`absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1
                px-2 py-1 rounded-lg border text-xs whitespace-nowrap transition-colors
                disabled:cursor-not-allowed
                ${mine
                  ? 'bg-primary text-primary-foreground border-primary shadow-sm font-medium'
                  : why
                    // 进不去的：不灰成看不见，理由在 title 里，点一下也没用
                    ? 'bg-card/60 border-dashed border-border/60 text-muted-foreground'
                    : 'bg-card/95 border-border/70 hover:border-primary/50 disabled:opacity-50'}`}
            >
              <MapPin className="w-3 h-3 shrink-0" />
              {loc.name}
              {mine && <span className="font-normal">· 你在这里</span>}
              {/* 有认识的人在，就挂一个点。名字塞不进节点，放在 title 里 */}
              {!mine && people.length > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
              )}
            </button>
          )
        })}
      </div>

      <p className="text-xs text-muted-foreground text-center">
        点一个地点就直接过去。虚线框的地方有进入条件，鼠标停上去看要什么。
        灰点是还没探到的，走近了自然会显出来。
      </p>
    </div>
  )
}
