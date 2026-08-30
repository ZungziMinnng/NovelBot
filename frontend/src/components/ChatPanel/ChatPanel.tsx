import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Settings, RotateCcw, Globe, Bot } from 'lucide-react'
import { streamChat, modelLibraryApi, findModelEntry, type ChatSSEMessage } from '@/api/client'
import type { Novel } from '@/api/client'
import { useChatStore, getChatSettings, getChatMessages, type ChatMessage } from '@/store/chatStore'
import AutoTextarea from '@/components/AutoTextarea'
import ChatSurface from '@/components/ChatSurface/ChatSurface'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'

interface Props {
  novelId: number
  novel: Novel
  chapterNumber: number
}

export default function ChatPanel({ novelId, novel, chapterNumber }: Props) {
  const [isStreaming, setIsStreaming] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const chatSettings = useChatStore((s) => getChatSettings(s, novelId))
  const messages = useChatStore((s) => getChatMessages(s, novelId))
  const updateSettings = useChatStore((s) => s.updateSettings)
  const resetSettings = useChatStore((s) => s.resetSettings)
  const appendMessage = useChatStore((s) => s.appendMessage)
  const updateLastAssistant = useChatStore((s) => s.updateLastAssistant)
  const updateMessageAt = useChatStore((s) => s.updateMessageAt)
  const truncateFrom = useChatStore((s) => s.truncateFrom)
  const clearMessages = useChatStore((s) => s.clearMessages)

  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const chatModelLibrary = modelLibrary.filter(m => m.model_type !== 'embedding')
  // chatSettings.model 可能是 ModelEntry.id（新）或旧 model_id；解析到条目后用 id 作 select value
  const chatEntry = findModelEntry(modelLibrary, chatSettings.model)
  const selectedChatModel = chatEntry && chatEntry.model_type !== 'embedding' ? String(chatEntry.id) : ''
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  // base 显式传入：从中间某句重发时，闭包里的 messages 还是截断前的旧值
  const send = useCallback((text: string, base?: ChatMessage[]) => {
    if (!text || isStreaming) return
    const history = [...(base ?? messages), { role: 'user' as const, content: text }]

    appendMessage(novelId, { role: 'user', content: text })
    appendMessage(novelId, { role: 'assistant', content: '' })
    setIsStreaming(true)
    setWaiting(true)

    abortRef.current = streamChat(
      {
        novel_id: novelId,
        messages: history.map(m => ({ role: m.role, content: m.content })),
        model: selectedChatModel,
        system_prompt: chatSettings.systemPrompt,
        temperature: chatSettings.temperature,
        max_tokens: chatSettings.maxTokens,
        context_rounds: chatSettings.contextRounds,
        chapter_number: chapterNumber,
        web_search: chatSettings.webSearch,
      },
      (msg: ChatSSEMessage) => {
        if (msg.event === 'token') {
          setWaiting(false)
          updateLastAssistant(novelId, (prev) => prev + msg.data)
        } else if (msg.event === 'warning') {
          setWaiting(false)
          updateLastAssistant(novelId, (prev) => `⚠ ${msg.data}\n\n${prev}`)
        } else if (msg.event === 'error') {
          setWaiting(false)
          updateLastAssistant(novelId, () => `[错误] ${msg.data}`)
        }
      },
      () => { setIsStreaming(false); setWaiting(false) },
    )
  }, [isStreaming, messages, novelId, chapterNumber, chatSettings, selectedChatModel, appendMessage, updateLastAssistant])

  const handleEditAt = useCallback(async (index: number, text: string) => {
    if (messages[index]?.role === 'assistant') {
      updateMessageAt(novelId, index, text)
      return
    }
    const dropped = messages.length - index - 1
    if (dropped > 0) {
      const ok = await confirmDialog({
        title: `改这句会删掉后面 ${dropped} 条对话`,
        detail: '删掉的内容无法恢复。',
        confirmText: '改并重发',
        danger: true,
      })
      if (!ok) return
    }
    const base = messages.slice(0, index)
    truncateFrom(novelId, index)
    send(text, base)
  }, [messages, novelId, updateMessageAt, truncateFrom, send])

  return (
    <ChatSurface
      title="AI 对话"
      messages={messages}
      isStreaming={isStreaming}
      waiting={waiting}
      onSend={send}
      onEditAt={handleEditAt}
      onClear={() => { abortRef.current?.abort(); clearMessages(novelId) }}
      emptyState={
        <div className="text-center text-sm text-muted-foreground/60 mt-8">
          <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
          <p>与 AI 对话，可询问世界观、角色、情节建议等</p>
        </div>
      }
      headerExtra={
        <>
          <button
            onClick={() => updateSettings(novelId, { webSearch: !chatSettings.webSearch })}
            title={chatSettings.webSearch ? '联网搜索已开：每次提问先搜一次，结果仅作参考资料，不会写进设定' : '联网搜索已关'}
            className={`flex items-center gap-1 text-xs border rounded px-2 py-1 transition-colors ${
              chatSettings.webSearch
                ? 'border-primary text-primary bg-primary/10'
                : 'text-muted-foreground hover:border-primary'
            }`}
          >
            <Globe className="w-3.5 h-3.5" />
            联网
          </button>
          <button
            onClick={() => setShowSettings(s => !s)}
            title="对话设置"
            className={`p-1.5 rounded-md transition-colors ${showSettings ? 'bg-muted text-primary' : 'hover:bg-muted'}`}
          >
            <Settings className="w-3.5 h-3.5" />
          </button>
        </>
      }
      belowHeader={showSettings && (
        <div className="border-b px-4 py-3 space-y-3 bg-muted/30 shrink-0 max-h-[50%] overflow-y-auto">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">助手提示词</label>
            <AutoTextarea
              value={chatSettings.systemPrompt}
              onChange={e => updateSettings(novelId, { systemPrompt: e.target.value })}
              placeholder="留空使用默认提示词（基于小说设定的创作助手）。自定义内容会追加到默认上下文之后。"
              minRows={3}
              className="w-full text-xs border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">模型</label>
            <select
              value={selectedChatModel}
              onChange={e => updateSettings(novelId, { model: e.target.value })}
              disabled={isStreaming}
              className="w-full text-xs border rounded px-2 py-1.5 bg-background focus:outline-none"
            >
              <option value="">默认 Writer 模型</option>
              {chatModelLibrary.map(m => (
                <option key={m.id} value={String(m.id)}>
                  [{m.provider}] {m.display_name || m.model_id}
                </option>
              ))}
            </select>
          </div>

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

          <button
            onClick={() => resetSettings(novelId)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <RotateCcw className="w-3 h-3" /> 恢复默认设置
          </button>
        </div>
      )}
    />
  )
}
