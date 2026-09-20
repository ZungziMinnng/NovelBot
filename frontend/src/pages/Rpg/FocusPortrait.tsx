import { useState } from 'react'
import { MapPin } from 'lucide-react'
import type { RpgNpc, RpgStatDef } from '@/api/client'
import ImageLightbox from './ImageLightbox'
import { bandOf } from './StatBar'

const HIDDEN = '隐藏'

/**
 * 你正盯着的那个人的立绘，钉在对话右边。
 *
 * 只在**确实只有一个人**的时候出现：「只看某人」的视角，或者私聊。GM 那段
 * 叙事是一整块旁白，里头可能好几个人在说话，消息上也没有「说话人」这个字段
 * ——所以没法按气泡配立绘，只能按「当前锁定了谁」来挂。
 *
 * 没立绘就整列不渲染：这一列的全部意义就是那张图，留个空框只是占地方，
 * 名字和数值在左边状态栏里本来就有。
 */
export default function FocusPortrait({
  npc, relationDefs = [], npcStates = {}, place, here,
}: {
  npc: RpgNpc
  relationDefs?: RpgStatDef[]
  npcStates?: Record<string, Record<string, number | boolean>>
  place?: string
  /** 就在你面前还是隔着一张地图。私聊时必然在场，「只看某人」时不一定 */
  here?: boolean
}) {
  const [viewing, setViewing] = useState(false)
  if (!npc.avatar_url) return null

  // 数值照 StatePanel 那套规矩筛：隐藏的是给幕后计数器用的，画出来等于
  // 提前把伏笔说了；这个人自己限定了名单就只显示名单里那几项
  const rels = npc.relation_enabled === false ? [] : (relationDefs || [])
    .filter(d => d.name && d.display !== HIDDEN)
    .filter(d => !npc.relation_stat_names?.length || npc.relation_stat_names.includes(d.name))

  return (
    <div className="flex flex-col gap-2 border-t border-border/50
      bg-background/30 px-3 py-4">
      {/* 立绘是 2:3 竖图，用 object-cover 裁成同一个比例，免得每个人一个高度
          把下面的数值顶得参差不齐 */}
      <button
        onClick={() => setViewing(true)}
        title="看原图"
        className="w-full aspect-[2/3] rounded-xl overflow-hidden ring-1 ring-primary/20
          hover:ring-primary/50 transition-shadow"
      >
        <img src={npc.avatar_url} alt={npc.name} className="w-full h-full object-cover" />
      </button>

      <div className="min-w-0">
        <p className="text-sm font-semibold truncate">{npc.name}</p>
        <p className="text-[11px] text-muted-foreground flex items-center gap-1 truncate">
          <MapPin className="w-3 h-3 shrink-0" />
          {place || '行踪不定'}
        </p>
        {/* 隔着地图的时候明说。「只看某人」是筛历史，不代表他此刻就在跟前，
            不标一句的话看着像他在对面站着 */}
        {here === false && (
          <p className="text-[11px] text-muted-foreground/80 mt-0.5">不在你跟前</p>
        )}
      </div>

      {rels.length > 0 && (
        <div className="space-y-1 border-t border-border/40 pt-2">
          {rels.map(def => {
            const value = Number(
              npcStates[String(npc.id)]?.[def.name]
                ?? npc.initial_state?.[def.name]
                ?? def.initial,
            )
            const label = bandOf(def, value)?.label
            return (
              <div key={def.name} className="flex items-baseline gap-1.5 text-[11px]">
                <span className="text-muted-foreground shrink-0">{def.name}</span>
                <span className="font-medium tabular-nums">{value}</span>
                {label && <span className="text-primary truncate">{label}</span>}
              </div>
            )
          })}
        </div>
      )}

      {viewing && (
        <ImageLightbox url={npc.avatar_url} alt={npc.name} onClose={() => setViewing(false)} />
      )}
    </div>
  )
}
