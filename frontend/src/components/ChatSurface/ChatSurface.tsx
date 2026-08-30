import { useState, useRef, useEffect, Fragment, type ReactNode } from 'react'
import { Send, Loader2, Bot, User, Trash2, Square, Pencil, Check } from 'lucide-react'
import AutoTextarea from '@/components/AutoTextarea'
import ThinkingDots from './ThinkingDots'
import type { ChatSurfaceMessage } from './types'

interface Props {
  messages: ChatSurfaceMessage[]
  /** 正在收 token */
  isStreaming: boolean
  /** 已发出、首个 token 还没到 */
  waiting: boolean
  onSend: (text: string) => void
  /** 传了就在流式时显示停止按钮，否则发送键变转圈 */
  onStop?: () => void
  /** 编辑确认。按 role 分流（改用户消息=重发，改助手消息=原地存）由调用方决定 */
  onEditAt: (index: number, text: string) => void
  onClear?: () => void
  title: string
  /** 顶栏右侧：模型下拉、联网开关等 */
  headerExtra?: ReactNode
  /** 顶栏下方插槽，给可折叠的设置面板 */
  belowHeader?: ReactNode
  emptyState?: ReactNode
  placeholder?: string
}

/**
 * 模型时不时会用 markdown 排版（**加粗**、### 标题、* 列表），一堆符号糊在对话里很突兀。
 * 这里按行还原成排版效果。只认闭合的标记，流式收到一半的落单符号照原样显示，收全了自然成形
 */
function renderMarkdown(text: string): ReactNode {
  return text.split('\n').map((line, i) => (
    <Fragment key={i}>
      {i > 0 && '\n'}
      {renderLine(line)}
    </Fragment>
  ))
}

function renderLine(line: string): ReactNode {
  if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
    return <span className="block border-t my-1.5 opacity-50" />
  }
  const heading = line.match(/^#{1,6}\s+(.*)$/)
  if (heading) return <span className="font-semibold">{renderInline(heading[1])}</span>
  const bullet = line.match(/^(\s*)[*+-]\s+(.*)$/)
  if (bullet) return <>{bullet[1]}・{renderInline(bullet[2])}</>
  return renderInline(line)
}

function renderInline(text: string): ReactNode {
  if (!text.includes('*') && !text.includes('`')) return text
  // 偶数段是原文，奇数段是带标记的整段
  return text.split(/(\*\*.+?\*\*|\*[^*]+?\*|`[^`]+?`)/g).map((part, i) => {
    if (i % 2 === 0) return part
    if (part.startsWith('**')) return <strong key={i}>{part.slice(2, -2)}</strong>
    // 中文斜体和等宽都难看，只把符号去掉
    return part.slice(1, -1)
  })
}

export default function ChatSurface({
  messages,
  isStreaming,
  waiting,
  onSend,
  onStop,
  onEditAt,
  onClear,
  title,
  headerExtra,
  belowHeader,
  emptyState,
  placeholder = '输入消息... (Enter 发送，Shift+Enter 换行)',
}: Props) {
  const [input, setInput] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const submit = () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setInput('')
    onSend(text)
  }

  const startEdit = (index: number, content: string) => {
    setEditingIndex(index)
    setDraft(content)
  }

  const saveEdit = () => {
    if (editingIndex === null) return
    const text = draft.trim()
    if (!text) return
    setEditingIndex(null)
    onEditAt(editingIndex, text)
  }

  return (
    <div className="flex flex-col h-full min-w-0">
      <div className="px-4 py-2.5 border-b shrink-0 flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{title}</span>
        <div className="flex items-center gap-1.5">
          {headerExtra}
          {onClear && (
            <button
              onClick={onClear}
              disabled={messages.length === 0}
              title="清空对话"
              className="p-1.5 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {belowHeader}

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0
          ? emptyState ?? (
              <div className="text-center text-sm text-muted-foreground/60 mt-8">
                <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p>开始对话</p>
              </div>
            )
          : messages.map((msg, i) => {
              const isLast = i === messages.length - 1
              if (msg.kind === 'stage') {
                return (
                  <div key={i} className="flex items-center gap-3 py-1">
                    <div className="flex-1 h-px bg-border" />
                    <span className="text-xs text-muted-foreground shrink-0">{msg.label}</span>
                    <div className="flex-1 h-px bg-border" />
                  </div>
                )
              }
              return (
                <div
                  key={i}
                  className={`group flex gap-2.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {msg.role === 'assistant' && (
                    <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                      <Bot className="w-4 h-4 text-primary" />
                    </div>
                  )}
                  {editingIndex === i ? (
                    <div className="w-[80%] space-y-2">
                      <AutoTextarea
                        value={draft}
                        onChange={e => setDraft(e.target.value)}
                        minRows={3}
                        autoFocus
                        className="w-full text-sm border rounded-2xl px-4 py-2.5 bg-background leading-relaxed
                          focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => setEditingIndex(null)}
                          className="text-xs px-3 py-1.5 border rounded-lg hover:bg-muted"
                        >
                          取消
                        </button>
                        <button
                          onClick={saveEdit}
                          disabled={!draft.trim()}
                          className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg
                            bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                        >
                          <Check className="w-3 h-3" />
                          {msg.role === 'user' ? '保存并重发' : '保存'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      {msg.role === 'user' && !isStreaming && (
                        <button
                          onClick={() => startEdit(i, msg.content)}
                          className="self-center p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity
                            text-muted-foreground hover:text-foreground"
                          title="改这句并重发（后面的对话会重走）"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                      )}
                      <div
                        className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                          msg.role === 'user'
                            ? 'bg-primary text-primary-foreground rounded-tr-sm'
                            : 'bg-muted rounded-tl-sm select-text'
                        }`}
                      >
                        {waiting && isLast && msg.role === 'assistant'
                          ? <ThinkingDots />
                          : renderMarkdown(msg.content)}
                        {isStreaming && !waiting && isLast && msg.role === 'assistant' && (
                          <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
                        )}
                      </div>
                      {/* 空的流式占位气泡没内容可改 */}
                      {msg.role === 'assistant' && !isStreaming && msg.content && (
                        <button
                          onClick={() => startEdit(i, msg.content)}
                          className="self-center p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity
                            text-muted-foreground hover:text-foreground"
                          title="编辑这条消息"
                        >
                          <Pencil className="w-3 h-3" />
                        </button>
                      )}
                    </>
                  )}
                  {msg.role === 'user' && (
                    <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              )
            })}
        <div ref={bottomRef} />
      </div>

      <div className="border-t px-4 py-3 shrink-0">
        <div className="flex gap-2 items-end">
          <AutoTextarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={placeholder}
            minRows={2}
            disabled={isStreaming}
            className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
          {isStreaming && onStop ? (
            <button
              onClick={onStop}
              title="停止生成"
              className="flex items-center justify-center w-9 h-9 border rounded-lg hover:bg-muted transition-colors shrink-0"
            >
              <Square className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!input.trim() || isStreaming}
              className="flex items-center justify-center w-9 h-9 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-40 transition-opacity shrink-0"
            >
              {isStreaming
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Send className="w-4 h-4" />
              }
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
