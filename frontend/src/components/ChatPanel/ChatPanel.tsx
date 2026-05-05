import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Send, Loader2, Bot, User, Settings, Trash2, RotateCcw } from 'lucide-react'
import { streamChat, modelLibraryApi, type ChatSSEMessage } from '@/api/client'
import type { Novel } from '@/api/client'
import { useChatStore, getChatSettings, getChatMessages } from '@/store/chatStore'

interface Props {
  novelId: number
  novel: Novel
}

export default function ChatPanel({ novelId, novel }: Props) {
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const chatSettings = useChatStore((s) => getChatSettings(s, novelId))
  const messages = useChatStore((s) => getChatMessages(s, novelId))
  const updateSettings = useChatStore((s) => s.updateSettings)
  const resetSettings = useChatStore((s) => s.resetSettings)
  const appendMessage = useChatStore((s) => s.appendMessage)
  const updateLastAssistant = useChatStore((s) => s.updateLastAssistant)
  const clearMessages = useChatStore((s) => s.clearMessages)

  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const streamingRef = useRef(false)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = useCallback(() => {
    const text = input.trim()
    if (!text || isStreaming) return

    // Append user message + empty assistant placeholder to store
    appendMessage(novelId, { role: 'user', content: text })
    appendMessage(novelId, { role: 'assistant', content: '' })
    setInput('')
    setIsStreaming(true)
    streamingRef.current = true

    // Build history for API (all messages including the new user message, excluding the empty assistant)
    const history = [...messages, { role: 'user' as const, content: text }].map(m => ({
      role: m.role,
      content: m.content,
    }))

    abortRef.current = streamChat(
      {
        novel_id: novelId,
        messages: history,
        model: chatSettings.model,
        system_prompt: chatSettings.systemPrompt,
        temperature: chatSettings.temperature,
        max_tokens: chatSettings.maxTokens,
        context_rounds: chatSettings.contextRounds,
      },
      (msg: ChatSSEMessage) => {
        if (msg.event === 'token') {
          updateLastAssistant(novelId, (prev) => prev + msg.data)
        } else if (msg.event === 'error') {
          updateLastAssistant(novelId, () => `[错误] ${msg.data}`)
        }
      },
      () => {
        setIsStreaming(false)
        streamingRef.current = false
      },
    )
  }, [input, isStreaming, messages, novelId, chatSettings, appendMessage, updateLastAssistant])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="px-4 py-2 border-b shrink-0 flex items-center justify-between gap-2">
        <span className="text-sm font-medium">AI 对话</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => { clearMessages(novelId); abortRef.current?.abort() }}
            disabled={isStreaming || messages.length === 0}
            title="清空对话"
            className="p-1.5 rounded-md hover:bg-muted transition-colors disabled:opacity-30"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setShowSettings(s => !s)}
            title="对话设置"
            className={`p-1.5 rounded-md transition-colors ${showSettings ? 'bg-muted text-primary' : 'hover:bg-muted'}`}
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Settings panel (collapsible) */}
      {showSettings && (
        <div className="border-b px-4 py-3 space-y-3 bg-muted/30 shrink-0 max-h-[50%] overflow-y-auto">
          {/* System prompt */}
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">助手提示词</label>
            <textarea
              value={chatSettings.systemPrompt}
              onChange={e => updateSettings(novelId, { systemPrompt: e.target.value })}
              placeholder="留空使用默认提示词（基于小说设定的创作助手）。自定义内容会追加到默认上下文之后。"
              rows={3}
              className="w-full text-xs border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y"
            />
          </div>

          {/* Model */}
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">模型</label>
            <select
              value={chatSettings.model}
              onChange={e => updateSettings(novelId, { model: e.target.value })}
              disabled={isStreaming}
              className="w-full text-xs border rounded px-2 py-1.5 bg-background focus:outline-none"
            >
              <option value="">默认 Writer 模型</option>
              {modelLibrary.map(m => (
                <option key={m.id} value={m.model_id}>
                  [{m.provider}] {m.display_name || m.model_id}
                </option>
              ))}
            </select>
          </div>

          {/* Temperature + Max Tokens row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">
                Temperature <span className="text-muted-foreground/60">{chatSettings.temperature.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={chatSettings.temperature}
                onChange={e => updateSettings(novelId, { temperature: parseFloat(e.target.value) })}
                className="w-full h-1.5 accent-primary"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">最大 Tokens</label>
              <input
                type="number"
                min={256}
                max={32768}
                step={256}
                value={chatSettings.maxTokens}
                onChange={e => updateSettings(novelId, { maxTokens: parseInt(e.target.value) || 4096 })}
                className="w-full text-xs border rounded px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          </div>

          {/* Context rounds */}
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">对话轮次限制 <span className="text-muted-foreground/60">（0 = 不限）</span></label>
            <input
              type="number"
              min={0}
              max={100}
              value={chatSettings.contextRounds}
              onChange={e => updateSettings(novelId, { contextRounds: parseInt(e.target.value) || 0 })}
              className="w-full text-xs border rounded px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          {/* Reset */}
          <button
            onClick={() => resetSettings(novelId)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <RotateCcw className="w-3 h-3" /> 恢复默认设置
          </button>
        </div>
      )}

      {/* Message list */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-sm text-muted-foreground/60 mt-8">
            <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p>与 AI 对话，可询问世界观、角色、情节建议等</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <Bot className="w-4 h-4 text-primary" />
              </div>
            )}
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground rounded-tr-sm'
                  : 'bg-muted rounded-tl-sm'
              }`}
            >
              {msg.content}
              {isStreaming && i === messages.length - 1 && msg.role === 'assistant' && (
                <span className="inline-block w-0.5 h-4 bg-current ml-0.5 animate-pulse align-middle" />
              )}
            </div>
            {msg.role === 'user' && (
              <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-0.5">
                <User className="w-4 h-4" />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="border-t px-4 py-3 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入消息... (Enter 发送，Shift+Enter 换行)"
            rows={2}
            disabled={isStreaming}
            className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-none disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="flex items-center justify-center w-9 h-9 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-40 transition-opacity shrink-0"
          >
            {isStreaming
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <Send className="w-4 h-4" />
            }
          </button>
        </div>
      </div>
    </div>
  )
}
