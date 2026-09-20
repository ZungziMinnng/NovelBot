import {
  Dices, MapPin, Package, Zap, type LucideIcon,
} from 'lucide-react'
import type { RpgSuggestion } from '@/api/client'

/**
 * 建议条的收口与展示。
 *
 * 和 `condition.ts` 一个定位：纯函数，不认识 React，也不发请求。
 *
 * **为什么要有一个收口函数**：`RpgMessage.suggestions` 是 JSON 列，加结构化
 * 之前写进去的是 `string[]`，没有做数据迁移。后端也不在读取时转换——那是列表
 * 接口每条消息都要走的路径，白付一遍成本。所以「老数据长什么样」这件事只在前端
 * 认一次，认在这里。
 *
 * 去重和条数上限也在这一层：后端两条路都已经各自做过一遍，但**老存档里的数组
 * 没做过**，而前端是唯一同时看得见老数组和新对象的地方。
 */

const EMPTY: RpgSuggestion[] = []

/** 四种结构化意图，外加自由文本。认不出的一律落到 free */
const KNOWN: Record<string, true> = {
  free: true, skill: true, item: true, move: true, action: true,
}

/**
 * 把任意形状的原始数组收成 `RpgSuggestion[]`。
 *
 * 输入是 `(RpgSuggestion | string)[] | null | undefined`——联合类型是故意写
 * 老实的那种，好让编译器揪出每一个绕开这个函数的消费点。单个元素认不出来就丢
 * 那一条、不丢整批：数组里混进一个 null 不该让另外两条好建议一起消失。
 */
export function normalizeSuggestions(
  raw: (RpgSuggestion | string)[] | null | undefined,
): RpgSuggestion[] {
  if (!Array.isArray(raw)) return EMPTY
  const out: RpgSuggestion[] = []
  const seen = new Set<string>()
  for (const row of raw) {
    const item = coerce(row)
    if (!item || !item.text || seen.has(item.text)) continue
    seen.add(item.text)
    out.push(item)
    // 6 = 主动路的 3 条能点的 + 3 句台词。结算那条路后端仍只发 3 条，放宽对它无影响
    if (out.length >= 6) break
  }
  return out.length ? out : EMPTY
}

function coerce(row: RpgSuggestion | string | null | undefined): RpgSuggestion | null {
  // 字符串就是老存档 / 老覆写的形状，等价于 kind=free
  if (typeof row === 'string') {
    const text = row.trim()
    return text ? { text, kind: 'free', name: '', action_id: null } : null
  }
  if (!row || typeof row !== 'object') return null
  const kind = KNOWN[String(row.kind ?? '')] ? String(row.kind) : 'free'
  const text = String(row.text ?? '').trim()
  const name = String(row.name ?? '').trim()
  // 结构化那几种必须带 name / action_id，缺了就退回自由文本：点下去没东西可发
  if (kind === 'action') {
    const id = Number(row.action_id)
    if (!Number.isInteger(id) || id <= 0) return { text, kind: 'free', name: '', action_id: null }
    return { text, kind, name: '', action_id: id }
  }
  if (kind !== 'free' && !name) return { text, kind: 'free', name: '', action_id: null }
  // free 没有正文就是空条，丢掉
  return text ? { text, kind, name, action_id: null } : null
}

/**
 * 结构化和平文本分两行。**不重排**：保留后端给的先后。
 *
 * 分开的理由是交互不同——上面那行点下去直接走引擎，下面那行只是替你把话打出来。
 * 混在一行里玩家得靠颜色猜，那正是要避免的。
 *
 * 键叫 `structured` 而不是 `actions`：调用方那边 `actions` 已经是「模组定义的
 * 动作表」了，重名会让人以为这两个是一回事
 */
export function splitSuggestions(
  tips: RpgSuggestion[],
): { structured: RpgSuggestion[]; plain: RpgSuggestion[] } {
  return {
    structured: tips.filter(tip => tip.kind !== 'free'),
    plain: tips.filter(tip => tip.kind === 'free'),
  }
}

/**
 * 每种意图的图标和前缀。图标**复用页面已有的游戏语义符号**，不另发明一套，
 * 玩家才不用重新学：`action` 用 `Dices`（同「快捷行动」那一栏的头），
 * `move` 用 `MapPin`（同移动菜单）。`Sparkles` 已经占给分栏标题，这里不用
 */
export const KIND_META: Record<string, { icon: LucideIcon; label: string }> = {
  action: { icon: Dices, label: '动作' },
  skill: { icon: Zap, label: '技能' },
  item: { icon: Package, label: '道具' },
  move: { icon: MapPin, label: '前往' },
  free: { icon: Zap, label: '' },
}

/** 认不出的 kind 用的兜底，别让渲染层每处都写一遍 `?? KIND_META.free` */
export const kindMeta = (kind: string) => KIND_META[kind] ?? KIND_META.free

/**
 * 药丸上那个前缀：「技能·暗影步」。自由文本没有前缀，返回空串。
 *
 * `action` 的 `name` 是空的（后端只给 `action_id`，那个才是引擎认的键），
 * 所以调用方把查出来的动作名递进来。动作已经被作者删掉时它也是空的，
 * 那时只显示「动作」两个字——药丸还在，点下去 `runSuggestedAction` 会静默
 * 收场，不报错也不发一句空话
 */
export function suggestionLabel(tip: RpgSuggestion, actionName = ''): string {
  if (tip.kind === 'free') return ''
  const meta = kindMeta(tip.kind)
  const name = tip.name || actionName
  return name ? `${meta.label}·${name}` : meta.label
}
