import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { tavernApi } from '@/api/client'
import CardAvatar from './CardAvatar'

/** 勾角色卡的列表。建群聊和"共用世界书"两处都要，字段不同但形状一样。
 *
 * lockedId 那张永远勾着且点不动：建群聊时是主卡，选世界书时是自己。
 */
export default function CardMultiSelect({
  selected, onChange, lockedId, excludeId, empty,
}: {
  selected: number[]
  onChange: (ids: number[]) => void
  lockedId?: number
  excludeId?: number
  empty: string
}) {
  const { data: cards = [], isLoading } = useQuery({
    queryKey: ['tavern-cards'],
    queryFn: tavernApi.cards.list,
  })

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> 读取角色卡…
      </div>
    )
  }

  const list = cards.filter(c => c.id !== excludeId)
  if (list.length === 0) {
    return <p className="text-xs text-muted-foreground">{empty}</p>
  }

  return (
    <div className="space-y-1.5 max-h-52 overflow-y-auto">
      {list.map(c => {
        const locked = c.id === lockedId
        return (
          <label
            key={c.id}
            className={`flex items-center gap-2.5 border rounded-lg px-3 py-2 ${
              locked ? 'opacity-70' : 'cursor-pointer hover:bg-muted/50'
            }`}
          >
            <input
              type="checkbox"
              checked={locked || selected.includes(c.id)}
              disabled={locked}
              onChange={() => toggle(c.id)}
              className="accent-pink-500"
            />
            <CardAvatar name={c.name} url={c.avatar_url} size="sm" />
            <span className="text-sm truncate flex-1">{c.name}</span>
            {locked && <span className="text-[10px] text-muted-foreground shrink-0">主角色</span>}
          </label>
        )
      })}
    </div>
  )
}
