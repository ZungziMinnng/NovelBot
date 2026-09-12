import type { RpgLocation } from '@/api/client'
import { norm } from './condition'

/** 坐标是百分比。夹进 3..97 而不是 0..100：节点按中心定位，
 *  贴到边上会有半张卡片被画布的 overflow-hidden 切掉 */
export const clampPct = (n: number) => Math.min(97, Math.max(3, Math.round(Number(n) || 0)))

/**
 * 每个地点画在哪（百分比）。作者摆过的按原样，没摆过的落一张确定性网格。
 *
 * 兜底网格是必须的：题材预设批量建的地点一个坐标都没有，全按 0 画就叠成
 * 左上角一坨。格位按**在整份列表里的下标**算，不是「未摆放的第几个」——
 * 后者会让作者摆好第一个之后剩下的全体重新洗牌。
 */
export function layout(locations: RpgLocation[]): Map<number, { x: number; y: number }> {
  const total = Math.max(1, locations.length)
  const cols = Math.max(1, Math.ceil(Math.sqrt(total)))
  const rows = Math.max(1, Math.ceil(total / cols))
  return new Map(locations.map((loc, i) => {
    if (loc.x || loc.y) return [loc.id, { x: clampPct(loc.x), y: clampPct(loc.y) }]
    return [loc.id, {
      x: clampPct(((i % cols) + 0.5) / cols * 100),
      y: clampPct((Math.floor(i / cols) + 0.5) / rows * 100),
    }]
  }))
}

/**
 * 要画的路，一条一对。
 *
 * 必须去重：connections 两边都能写，实际数据里「走廊→校长办公室」和
 * 「校长办公室→走廊」常常都存着，画两遍在半透明下就是一条明显更黑的线。
 * 连到不存在的地点（作者改名之后留下的悬空名字）直接跳过——没法画。
 */
export function edgePairs(locations: RpgLocation[]): { a: RpgLocation; b: RpgLocation }[] {
  const byName = new Map(locations.map(l => [norm(l.name), l]))
  const seen = new Set<string>()
  const out: { a: RpgLocation; b: RpgLocation }[] = []
  for (const a of locations) {
    for (const name of a.connections || []) {
      const b = byName.get(norm(name))
      if (!b || b.id === a.id) continue
      const key = [a.id, b.id].sort((m, n) => m - n).join('-')
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ a, b })
    }
  }
  return out
}
