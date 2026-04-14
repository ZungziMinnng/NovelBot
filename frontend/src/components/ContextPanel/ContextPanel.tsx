import { useQuery } from '@tanstack/react-query'
import { charactersApi, type Character } from '@/api/client'
import { ChevronDown, ChevronUp, User } from 'lucide-react'
import { useState } from 'react'

interface Props {
  novelId: number
  rollingStage: string
}

export default function ContextPanel({ novelId, rollingStage }: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })

  const toggle = (key: string) => setCollapsed(s => ({ ...s, [key]: !s[key] }))

  return (
    <div className="text-xs space-y-3 overflow-y-auto h-full">
      {rollingStage && (
        <div className="px-3 py-2 bg-primary/10 rounded-lg text-primary font-medium">
          {rollingStage}
        </div>
      )}

      <div>
        <button onClick={() => toggle('chars')} className="flex items-center justify-between w-full font-semibold text-foreground/80 mb-1">
          <span>角色状态</span>
          {collapsed['chars'] ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
        </button>
        {!collapsed['chars'] && (
          <div className="space-y-1.5">
            {characters.slice(0, 5).map((c: Character) => (
              <div key={c.id} className="bg-muted rounded-md p-2">
                <div className="flex items-center gap-1.5 font-medium text-foreground/90">
                  <User className="w-3 h-3" />
                  {c.name}
                  <span className="text-muted-foreground font-normal">· {c.role}</span>
                </div>
                {!!c.current_state?.location && (
                  <p className="text-muted-foreground mt-0.5">位置：{String(c.current_state.location)}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="text-muted-foreground/60 text-center pt-2">
        上下文自动管理中
      </div>
    </div>
  )
}