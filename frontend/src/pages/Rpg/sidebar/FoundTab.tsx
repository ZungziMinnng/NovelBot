import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import type { RpgDiscovery } from '@/api/client'
import { PANEL } from '../rpgUi'
import Empty from './Empty'

const KIND_LABELS: Record<RpgDiscovery['kind'], string> = {
  npc: '角色', place: '地点', item: '道具', skill: '技能', task: '任务',
}

// 顺序写死，不按「哪类先冒出来」排：位置固定了，作者第二次进这一格才不用重新找
const KIND_ORDER: RpgDiscovery['kind'][] = ['npc', 'place', 'item', 'skill', 'task']

export default function FoundTab({
  found, onApplyDiscoveries, onDismissDiscovery, applyingDiscoveries = false,
}: {
  found: RpgDiscovery[]
  onApplyDiscoveries: (ids: string[]) => void
  onDismissDiscovery: (id: string) => void
  applyingDiscoveries?: boolean
}) {
  // 默认全不勾。这一格和向导那个预览面板不一样：那边是作者刚点的「生成」，
  // 默认全要合理；这边是 GM 自己冒出来的，多半只想收其中一两个
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const togglePick = (id: string) =>
    setPicked(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  // 勾了但已经被处理掉的（另一个标签页点过「加入」）不该还算数
  const live = [...picked].filter(id => found.some(d => d.id === id))

  if (found.length === 0) {
    return (
      <Empty>
        还没有。剧情里冒出模组里没登记过的人、地方或东西时，会记到这儿来等你决定。
      </Empty>
    )
  }

  return (
    <>
      <Empty>
        这些是剧情里出现、但模组里还没有的。加进来之后 GM 才会把它们当成正式设定，
        状态也才记得住。
      </Empty>
      {/* 按类型分块。从前是一条条平铺、每条挂个类型小标签，攒到十几条就糊成一片；
          分了块之后类型写在块头，每条上那个标签就是冗余，去掉 */}
      {KIND_ORDER.map(kind => {
        const rows = found.filter(entry => entry.kind === kind)
        if (rows.length === 0) return null
        return (
          <div key={kind} className="space-y-3">
            <p className="text-xs font-medium text-muted-foreground px-1">
              {KIND_LABELS[kind]} · {rows.length}
            </p>
            {rows.map(entry => (
              <label
                key={entry.id}
                className={`${PANEL} p-3 flex gap-2.5 cursor-pointer
                  ${picked.has(entry.id) ? 'ring-1 ring-primary/40' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={picked.has(entry.id)}
                  onChange={() => togglePick(entry.id)}
                  disabled={applyingDiscoveries}
                  className="mt-0.5 shrink-0"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{entry.name}</p>
                  {/* 原文依据。没有它作者没法判断这是谁——名字往往只是个称呼 */}
                  <p className="text-xs text-muted-foreground mt-1 leading-relaxed line-clamp-3">
                    {entry.hint}
                  </p>
                  <button
                    onClick={event => { event.preventDefault(); onDismissDiscovery(entry.id) }}
                    disabled={applyingDiscoveries}
                    className="text-[11px] text-muted-foreground hover:text-foreground mt-1.5 disabled:opacity-40"
                  >
                    不要这个
                  </button>
                </div>
              </label>
            ))}
          </div>
        )
      })}
      <button
        onClick={() => onApplyDiscoveries(live)}
        disabled={applyingDiscoveries || live.length === 0}
        title="会再调一次模型，照正文把属性、地图连接补出来"
        className="w-full text-xs py-2 rounded-lg bg-primary text-primary-foreground
          hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-1.5"
      >
        {applyingDiscoveries && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
        {applyingDiscoveries ? '正在补全档案…' : `加入模组${live.length ? `（${live.length}）` : ''}`}
      </button>
    </>
  )
}
