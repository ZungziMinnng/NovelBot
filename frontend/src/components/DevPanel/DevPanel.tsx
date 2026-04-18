import { useState, useEffect, useRef } from 'react'
import { X, Trash2, ChevronDown, ChevronRight } from 'lucide-react'
import { useDevLogStore, type DevLogEntry } from '@/store/devLogStore'

interface Props {
  onClose: () => void
}

type Tab = 'http' | 'sse'

const METHOD_COLOR: Record<string, string> = {
  GET:    'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  POST:   'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  PATCH:  'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
  DELETE: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
}

const STATUS_COLOR = (s: number) =>
  s >= 500 ? 'text-red-500' : s >= 400 ? 'text-orange-500' : s >= 200 ? 'text-green-600' : 'text-muted-foreground'

const EVENT_COLOR: Record<string, string> = {
  stage:          'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  done:           'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  error:          'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  agent_start:    'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300',
  agent_done:     'bg-indigo-100 text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300',
  total_usage:    'bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300',
  original_draft: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
  llm_request:    'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
}

function ExpandableJson({ data }: { data: unknown }) {
  const [open, setOpen] = useState(false)
  if (data === undefined || data === null) return null
  const text = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  const preview = typeof data === 'string' ? data.slice(0, 60) : JSON.stringify(data).slice(0, 60)
  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        {open ? '收起' : `${preview}${preview.length < text.length ? '…' : ''}`}
      </button>
      {open && (
        <pre className="mt-1 text-[10px] bg-muted rounded p-2 overflow-x-auto max-h-48 whitespace-pre-wrap break-all leading-relaxed">
          {text}
        </pre>
      )}
    </div>
  )
}

function HttpEntry({ entry }: { entry: DevLogEntry }) {
  const isReq = entry.type === 'request'
  const method = entry.method || ''
  const shortUrl = entry.url?.replace('/api', '') || ''
  const ts = new Date(entry.ts).toLocaleTimeString('zh-CN', { hour12: false, fractionalSecondDigits: 2 })

  return (
    <div className={`px-3 py-2 border-b text-xs ${isReq ? '' : 'bg-muted/30'}`}>
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-muted-foreground/50 shrink-0 font-mono text-[10px]">{ts}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${METHOD_COLOR[method] || 'bg-muted text-muted-foreground'}`}>
          {method}
        </span>
        {!isReq && entry.status !== undefined && (
          <span className={`font-mono font-semibold shrink-0 ${STATUS_COLOR(entry.status)}`}>
            {entry.status}
          </span>
        )}
        <span className="font-mono truncate text-foreground">{shortUrl}</span>
      </div>
      {isReq && entry.reqBody !== undefined && <ExpandableJson data={entry.reqBody} />}
      {!isReq && entry.resData !== undefined && <ExpandableJson data={entry.resData} />}
    </div>
  )
}

function SseEntry({ entry }: { entry: DevLogEntry }) {
  const event = entry.event || ''
  const ts = new Date(entry.ts).toLocaleTimeString('zh-CN', { hour12: false, fractionalSecondDigits: 2 })
  return (
    <div className="px-3 py-2 border-b text-xs">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-muted-foreground/50 shrink-0 font-mono text-[10px]">{ts}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium shrink-0 ${EVENT_COLOR[event] || 'bg-muted text-muted-foreground'}`}>
          {event}
        </span>
      </div>
      {entry.eventData !== undefined && <ExpandableJson data={entry.eventData} />}
    </div>
  )
}

export default function DevPanel({ onClose }: Props) {
  const entries = useDevLogStore(s => s.entries)
  const clear = useDevLogStore(s => s.clear)
  const [tab, setTab] = useState<Tab>('http')
  const bottomRef = useRef<HTMLDivElement>(null)

  const httpEntries = entries.filter(e => e.type === 'request' || e.type === 'response')
  const sseEntries = entries.filter(e => e.type === 'sse')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries.length])

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed inset-y-0 right-0 w-[440px] bg-background border-l shadow-xl z-50 flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0">
          <span className="text-sm font-semibold">开发者视图</span>
          <span className="text-xs text-muted-foreground ml-1">({entries.length} 条记录)</span>
          <button
            onClick={clear}
            className="ml-auto flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-muted transition-colors text-muted-foreground"
          >
            <Trash2 className="w-3.5 h-3.5" /> 清空
          </button>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b shrink-0">
          {([['http', `HTTP (${httpEntries.length})`], ['sse', `流式事件 (${sseEntries.length})`]] as [Tab, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-4 py-2 text-xs border-b-2 transition-colors ${
                tab === key
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {tab === 'http' ? (
            httpEntries.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center mt-8">暂无 HTTP 记录</p>
            ) : (
              httpEntries.map(e => <HttpEntry key={e.id} entry={e} />)
            )
          ) : (
            sseEntries.length === 0 ? (
              <p className="text-xs text-muted-foreground text-center mt-8">暂无流式事件记录</p>
            ) : (
              sseEntries.map(e => <SseEntry key={e.id} entry={e} />)
            )
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </>
  )
}
