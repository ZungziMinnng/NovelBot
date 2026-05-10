import { Eye, EyeOff, ChevronDown, ChevronUp } from 'lucide-react'

export interface AgentLogEntry {
  id: string
  agent: string
  label: string
  status: 'running' | 'done' | 'failed'
  inputTokens: number
  outputTokens: number
  passed?: boolean
}

interface Props {
  entries: AgentLogEntry[]
  totalInputTokens: number
  totalOutputTokens: number
  showTokens: boolean
  onToggleTokens: () => void
  collapsed: boolean
  onToggleCollapse: () => void
}

const AGENT_COLORS: Record<string, string> = {
  writer: 'bg-blue-500',
  critic: 'bg-purple-500',
  detail_review: 'bg-amber-500',
}

const STATUS_DOT: Record<AgentLogEntry['status'], string> = {
  running: 'bg-yellow-400 animate-pulse',
  done: 'bg-green-500',
  failed: 'bg-red-500',
}

export default function AgentLog({
  entries,
  totalInputTokens,
  totalOutputTokens,
  showTokens,
  onToggleTokens,
  collapsed,
  onToggleCollapse,
}: Props) {
  if (entries.length === 0) return null

  return (
    <div className="bg-background">
      {/* Header */}
      <div className="flex items-center gap-2 py-2 cursor-pointer hover:bg-muted/50 transition-colors" onClick={onToggleCollapse}>
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Agent 调用日志</span>
        {!collapsed && totalInputTokens > 0 && (
          <span className="text-xs text-muted-foreground ml-2">
            共 ↑{totalInputTokens} ↓{totalOutputTokens} tokens
          </span>
        )}
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={e => { e.stopPropagation(); onToggleTokens() }}
            className="p-1 rounded hover:bg-muted transition-colors"
            title={showTokens ? '隐藏 Token 数' : '显示 Token 数'}
          >
            {showTokens ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
          </button>
          {collapsed ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
        </div>
      </div>

      {!collapsed && (
        <div className="pb-3 space-y-1">
          {entries.map(entry => (
            <div key={entry.id} className="flex items-center gap-2 text-xs py-0.5">
              {/* Status dot */}
              <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT[entry.status]}`} />

              {/* Agent badge */}
              <span className={`px-1.5 py-0.5 rounded text-white text-[10px] shrink-0 ${AGENT_COLORS[entry.agent] || 'bg-gray-500'}`}>
                {entry.agent}
              </span>

              {/* Label */}
              <span className="text-muted-foreground flex-1 truncate">{entry.label}</span>

              {/* Token counts */}
              {showTokens && entry.status === 'done' && (entry.inputTokens > 0 || entry.outputTokens > 0) && (
                <span className="text-muted-foreground/60 shrink-0 font-mono">
                  ↑{entry.inputTokens} ↓{entry.outputTokens}
                </span>
              )}

              {/* Passed/failed indicator for review agents */}
              {(entry.agent === 'critic' || entry.agent === 'detail_review') && entry.status === 'done' && (
                <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded-full ${entry.passed ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300' : 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'}`}>
                  {entry.passed ? '通过' : '修改'}
                </span>
              )}
            </div>
          ))}

          {/* Total row */}
          {showTokens && totalInputTokens > 0 && (
            <div className="flex items-center gap-2 text-xs py-1 mt-1 border-t pt-1.5">
              <span className="w-2 h-2 shrink-0" />
              <span className="text-muted-foreground/60 shrink-0 w-12"></span>
              <span className="text-muted-foreground flex-1 font-medium">合计</span>
              <span className="text-foreground font-mono shrink-0">
                ↑{totalInputTokens} ↓{totalOutputTokens}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
