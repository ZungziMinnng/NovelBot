import { useState, useEffect, useRef } from 'react'
import { X, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import { useDevLogStore, type DevLogEntry } from '@/store/devLogStore'

interface Props {
  onClose: () => void
}

const AGENT_COLOR: Record<string, string> = {
  writer:        'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  critic:        'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
  summarizer:    'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  char_update:   'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
  entity_update: 'bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300',
}

const AGENT_LABEL: Record<string, string> = {
  writer:        'Writer',
  critic:        'Critic',
  summarizer:    'Summary',
  char_update:   'CharUpd',
  entity_update: 'EntUpd',
}

function statusIcon(s?: string) {
  switch (s) {
    case 'ok':        return <span className="text-green-600 font-semibold">&#10003;</span>
    case 'truncated': return <span className="text-yellow-500 font-semibold">&#9888;</span>
    case 'error':     return <span className="text-red-500 font-semibold">&#10007;</span>
    default:          return null
  }
}

function fmtTokens(n?: number): string {
  if (n == null) return '-'
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function fmtDuration(ms?: number): string {
  if (ms == null) return '-'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function LlmCallRow({ entry }: { entry: DevLogEntry }) {
  const [open, setOpen] = useState(false)
  const agent = entry.agent || ''
  const hasPayload = !!entry.payload
  const d = new Date(entry.ts)
  const ts = d.toLocaleTimeString('zh-CN', { hour12: false })

  return (
    <div className="border-b">
      <div
        className={`px-3 py-2 text-xs flex items-center gap-2 ${hasPayload ? 'cursor-pointer hover:bg-muted/40' : ''}`}
        onClick={hasPayload ? () => setOpen(v => !v) : undefined}
      >
        <span className="text-muted-foreground/50 shrink-0 font-mono text-[10px]">{ts}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 min-w-[52px] text-center ${AGENT_COLOR[agent] || 'bg-muted text-muted-foreground'}`}>
          {AGENT_LABEL[agent] || agent}
        </span>
        <span className="font-mono text-[11px] truncate text-muted-foreground max-w-[120px]">{entry.model || '-'}</span>
        <span className="shrink-0">{statusIcon(entry.llmStatus)}</span>
        <span className="font-mono text-[11px] shrink-0">{fmtTokens(entry.inputTokens)}<span className="text-muted-foreground/50 mx-0.5">&rarr;</span>{fmtTokens(entry.outputTokens)}</span>
        <span className="font-mono text-[11px] text-muted-foreground shrink-0 ml-auto">{fmtDuration(entry.durationMs)}</span>
        {hasPayload && (
          <span className="shrink-0 text-muted-foreground">
            {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>
      {open && entry.payload && (
        <div className="px-3 pb-2">
          <PayloadView payload={entry.payload} />
        </div>
      )}
    </div>
  )
}

function PayloadView({ payload }: { payload: Record<string, unknown> }) {
  const messages = payload.messages as Array<{ role: string; content: string }> | undefined
  const params = { ...payload }
  delete params.messages

  return (
    <div className="space-y-2">
      {Object.keys(params).length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
          {Object.entries(params).map(([k, v]) => (
            <span key={k}><span className="font-medium text-foreground/70">{k}:</span> {String(v)}</span>
          ))}
        </div>
      )}
      {messages && (
        <div className="space-y-1">
          {messages.map((m, i) => (
            <div key={i} className="text-[10px]">
              <span className={`font-medium ${m.role === 'system' ? 'text-purple-500' : m.role === 'assistant' ? 'text-green-600' : 'text-blue-600'}`}>
                [{m.role}]
              </span>
              <pre className="mt-0.5 bg-muted rounded p-1.5 overflow-x-auto max-h-32 whitespace-pre-wrap break-all leading-relaxed text-[10px]">
                {m.content}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DevPanel({ onClose }: Props) {
  const entries = useDevLogStore(s => s.entries)
  const clear = useDevLogStore(s => s.clear)
  const bottomRef = useRef<HTMLDivElement>(null)

  const llmCalls = entries.filter(e => e.type === 'llm_call')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [llmCalls.length])

  return (
    <>
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />

      <div className="fixed inset-y-0 right-0 w-[480px] bg-background border-l shadow-xl z-50 flex flex-col">
        <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0">
          <span className="text-sm font-semibold">LLM Calls</span>
          <span className="text-xs text-muted-foreground ml-1">({llmCalls.length})</span>
          <button
            onClick={clear}
            className="ml-auto flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-muted transition-colors text-muted-foreground"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {llmCalls.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center mt-8">暂无 LLM 调用记录</p>
          ) : (
            llmCalls.map(e => <LlmCallRow key={e.id} entry={e} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </>
  )
}
