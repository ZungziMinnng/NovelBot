import { useQuery } from '@tanstack/react-query'
import { charactersApi, type Character, type ContextStepData } from '@/api/client'
import { ChevronDown, ChevronUp, User, Check, Ban, Loader2 } from 'lucide-react'
import { useState } from 'react'

interface Props {
  novelId: number
  rollingStage: string
  contextSteps: ContextStepData[]
}

const SOURCE_BADGE: Record<string, { text: string; cls: string }> = {
  name:  { text: '名称匹配', cls: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  rag:   { text: 'RAG', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  full:  { text: '全量', cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' },
  field: { text: '字段', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
}

export default function ContextPanel({ novelId, rollingStage, contextSteps }: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })

  const toggle = (key: string) => setCollapsed(s => ({ ...s, [key]: !s[key] }))

  const isBuilding = rollingStage === 'building_context'

  return (
    <div className="text-xs space-y-3 overflow-y-auto h-full">
      {rollingStage && (
        <div className="px-3 py-2 bg-primary/10 rounded-lg text-primary font-medium">
          {rollingStage}
        </div>
      )}

      {/* Context Build Steps */}
      {contextSteps.length > 0 && (
        <div>
          <button onClick={() => toggle('ctx_build')} className="flex items-center justify-between w-full font-semibold text-foreground/80 mb-1">
            <span className="flex items-center gap-1.5">
              上下文构建
              {isBuilding && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
              {!isBuilding && (
                <span className="font-normal text-muted-foreground">
                  {contextSteps.filter(s => s.detail !== '已跳过').length}/{contextSteps.length}
                </span>
              )}
            </span>
            {collapsed['ctx_build'] ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
          </button>
          {!collapsed['ctx_build'] && (
            <div className="space-y-0.5">
              {contextSteps.map((step) => {
                const skipped = step.detail === '已跳过'
                const empty = step.detail === '空'
                const badge = SOURCE_BADGE[step.source]
                const items = step.items || []
                const itemsText = items.length > 2
                  ? `${items.slice(0, 2).join('、')} 等`
                  : items.join('、')
                const expandable = !skipped && (items.length > 2 || !!step.content)
                const expanded = !collapsed[`step-${step.key}`]
                return (
                  <div key={step.key}>
                    <div
                      onClick={expandable ? () => toggle(`step-${step.key}`) : undefined}
                      className={`flex items-start gap-1.5 px-2 py-1 rounded ${skipped ? 'opacity-40' : ''} ${expandable ? 'cursor-pointer hover:bg-muted/50' : ''}`}
                    >
                      {skipped ? (
                        <Ban className="w-3 h-3 mt-0.5 text-muted-foreground shrink-0" />
                      ) : (
                        <Check className={`w-3 h-3 mt-0.5 shrink-0 ${empty ? 'text-muted-foreground' : 'text-green-600 dark:text-green-400'}`} />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1">
                          <span className="font-medium truncate">{step.label}</span>
                          {badge && !skipped && (
                            <span className={`text-[9px] px-1 py-px rounded leading-tight ${badge.cls}`}>{badge.text}</span>
                          )}
                        </div>
                        <div className="text-muted-foreground truncate">
                          {skipped ? '已跳过' : itemsText || step.detail}
                        </div>
                      </div>
                    </div>
                    {expandable && expanded && (
                      <div className="ml-[18px] px-2 pb-1 text-muted-foreground leading-relaxed">
                        {items.length > 2 && (
                          <p className="break-words">{items.join('、')}</p>
                        )}
                        {step.content && (
                          <p className="break-words whitespace-pre-line">{step.content}</p>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      <div>
        <button onClick={() => toggle('chars')} className="flex items-center justify-between w-full font-semibold text-foreground/80 mb-1">
          <span>角色状态 <span className="font-normal text-muted-foreground">{characters.length}</span></span>
          {collapsed['chars'] ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />}
        </button>
        {!collapsed['chars'] && (
          <div className="space-y-0.5">
            {characters.map((c: Character) => {
              const expanded = !collapsed[`char-${c.id}`]
              const st = c.current_state as Record<string, string> | undefined
              const loc = st?.location
              return (
                <div key={c.id}>
                  <button
                    onClick={() => toggle(`char-${c.id}`)}
                    className="flex items-center gap-1.5 w-full px-2 py-1 rounded hover:bg-muted text-left"
                  >
                    {c.avatar_url ? (
                      <img src={c.avatar_url} alt="" className="w-4 h-4 rounded-full object-cover shrink-0" />
                    ) : (
                      <User className="w-3 h-3 shrink-0" />
                    )}
                    <span className="font-medium truncate">{c.name}</span>
                    <span className="text-muted-foreground font-normal truncate">· {c.role}</span>
                    {loc && <span className="text-muted-foreground ml-auto truncate max-w-[80px]">{loc}</span>}
                  </button>
                  {expanded && (
                    <div className="ml-6 px-2 py-1 text-muted-foreground space-y-0.5">
                      {loc && <p>位置：{loc}</p>}
                      {st?.current_goal && <p>目标：{st.current_goal}</p>}
                      {st?.affiliation && <p>所属：{st.affiliation}</p>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="text-muted-foreground/60 text-center pt-2">
        上下文自动管理中
      </div>
    </div>
  )
}
