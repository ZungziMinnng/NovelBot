import { useState } from 'react'
import { MapPin } from 'lucide-react'
import type { RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { checkCondition, knownNpcs, norm, npcPlace, visibleLocations } from './condition'
import { edgePairs, layout } from './mapLayout'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
  npcs: RpgNpc[]
  locked: boolean
  /** 有一次瞬移正在路上。纯引擎请求很快，但连点两下会发两个 */
  busy: boolean
  /** 真的过去，并且直接翻到那个地点页。纯引擎瞬移，不产生叙事 */
  onGo: (name: string) => void
  /** 进当前所在地点的地点页。只有「你在这里」那张卡能点 */
  onPick: () => void
  /** 当前查看的地图层级；null 是大地图 */
  parentId?: number | null
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
 * **点一下只是选中**，地图下面展开那个地点的详情，再点【移动到这里】人才真的过去——
 * 从前是点一下就走，于是「只想看看那儿有谁」会把人直接瞬移过去。
 * 连不连着都一样，connections 只管画线和散迷雾。
 * 进入条件在这里提前判一次，只为把进不去的地方标出来并写明原因；
 * 判定权始终在后端，这里放行了后端照样会拦。
 */
export default function LocationOverview({
  sess, locations, npcs, locked, busy, onGo, onPick, parentId = null,
}: Props) {
  // 选中态是组件私有的：外面两个调用点（RpgPlay 的总览、PlacePage 的内部地图）
  // 只关心「玩家最后决定去哪」，不关心他在地图上点过谁
  const [picked, setPicked] = useState<number | null>(null)
  const scoped = locations.filter(loc => (loc.parent_id ?? null) === parentId)
  if (scoped.length === 0) {
    return (
      <p className="text-center text-sm text-muted-foreground py-20">
        这个模组还没定义地点。回模组页的「地点」里加几个，这里就会有了。
      </p>
    )
  }

  const here = scoped.find(l => norm(l.name) === norm(sess.location || ''))
  const isHere = (loc: RpgLocation) => !!here && loc.id === here.id
  const pos = layout(scoped)
  const visible = new Set([
    ...visibleLocations(locations, sess),
    ...(parentId === null ? [] : scoped.map(loc => loc.id)),
  ])

  /** 这个地点上站着谁。只看得到见过面的人——没见过的不该被抖出来 */
  const known = knownNpcs(npcs, sess)
  // 站在这个点上的人。onstage 是「在玩家当前地点」，这里要的是「在这个地点」，
  // 所以拿 sess 换成这个点本身比较——走的仍是 npcPlace 那一套（含作息表）
  const faces = (loc: RpgLocation) =>
    known.filter(n => norm(npcPlace(n, sess.slot, sess.npc_places)) === norm(loc.name))

  /** 进不去的话，那句理由。空串 = 能进 */
  const blockedWhy = (loc: RpgLocation) => {
    const [ok, why] = checkCondition(loc.enter_requires, sess, npcs)
    return ok ? '' : why
  }

  // 也要过 visible：换地图层级（parentId 变了）之后旧的选中 id 不在这一层里，
  // 这里自然就取不到，面板跟着收起来
  const pick = scoped.find(loc => loc.id === picked && visible.has(loc.id))
  const detail = pick && (() => {
    const mine = isHere(pick)
    const people = faces(pick)
    const why = mine ? '' : blockedWhy(pick)
    const hasChildren = locations.some(child => child.parent_id === pick.id)
    return (
      <div className="rounded-2xl border border-border/60 bg-card/40 px-4 py-3 space-y-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <MapPin className="w-4 h-4 shrink-0 text-primary" />
          {pick.name}
          {mine && <span className="text-xs font-normal text-muted-foreground">· 你在这里</span>}
          {hasChildren && <span className="text-xs font-normal text-muted-foreground">· 有内部地图</span>}
        </div>
        {!!pick.description && (
          <p className="text-xs text-muted-foreground whitespace-pre-wrap">{pick.description}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {people.length > 0 ? `这里有：${people.map(n => n.name).join('、')}` : '这里暂时没有你认识的人'}
        </p>
        {!!why && <p className="text-xs text-amber-600 dark:text-amber-400">{why}</p>}
        <div className="flex justify-end">
          <button
            // 当前地点那个是导航（翻自己的地点页），不受 locked/busy 管——
            // 一局结束之后历史还得能翻
            onClick={() => (mine ? onPick() : onGo(pick.name))}
            disabled={!mine && (locked || busy || !!why)}
            title={mine ? '翻到这个地点的详情页' : '直接过去，不产生剧情。想要一段过场就用输入框上方的「移动」'}
            className="rounded-lg border border-primary/60 bg-primary/10 px-3 py-1.5 text-xs
              font-medium hover:bg-primary/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mine ? '看看这里有谁 →' : why ? '进不去' : '移动到这里 →'}
          </button>
        </div>
      </div>
    )
  })()

  return (
    <div className="space-y-3">
      <div className="relative w-full aspect-[3/2] overflow-hidden rounded-2xl border
        border-border/60 bg-card/40">
        <svg
          className="absolute inset-0 w-full h-full text-muted-foreground"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          {edgePairs(scoped).map(({ a, b }) => {
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

        {scoped.map(loc => {
          const p = pos.get(loc.id)!
          const style = { left: `${p.x}%`, top: `${p.y}%` }
          const hasChildren = locations.some(child => child.parent_id === loc.id)

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
              // 点哪儿都只是选中，连进不去的地方也能选——看看那儿有谁、差什么条件，
              // 本来就该允许。真要动身是下面那个按钮的事
              onClick={() => setPicked(loc.id)}
              title={`看看${loc.name}`}
              className={`absolute -translate-x-1/2 -translate-y-1/2 flex items-center gap-1
                px-2 py-1 rounded-lg border text-xs whitespace-nowrap transition-colors
                ${picked === loc.id ? 'ring-2 ring-primary ring-offset-1 ring-offset-background' : ''}
                ${mine
                  ? 'bg-primary text-primary-foreground border-primary shadow-sm font-medium'
                  : why
                    // 进不去的：不灰成看不见，条件写在下面的详情面板里
                    ? 'bg-card/60 border-dashed border-border/60 text-muted-foreground'
                    : 'bg-card/95 border-border/70 hover:border-primary/50'}`}
            >
              <MapPin className="w-3 h-3 shrink-0" />
              {loc.name}
              {mine && <span className="font-normal">· 你在这里</span>}
              {hasChildren && <span className="font-normal">· 有内部地图</span>}
              {/* 有认识的人在，就挂一个点。名字塞不进节点，放在 title 里 */}
              {!mine && people.length > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />
              )}
            </button>
          )
        })}
      </div>

      {detail}

      <p className="text-xs text-muted-foreground text-center">
        点一个地点先看看那儿有什么，想好了再按【移动到这里】。
        虚线框的地方有进入条件，灰点是还没探到的，走近了自然会显出来。
      </p>
    </div>
  )
}
