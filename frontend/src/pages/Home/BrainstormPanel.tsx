import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot, Globe, ArrowLeftToLine, Loader2, Wand2, MessageSquare, ChevronRight, SkipForward } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  streamBrainstorm, modelLibraryApi, brainstormApi,
  type ChatSSEMessage, type BrainstormExtract,
} from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'
import { useBrainstormStore, formatConfirmed } from '@/store/brainstormStore'
import ChatSurface from '@/components/ChatSurface/ChatSurface'
import type { ChatSurfaceMessage } from '@/components/ChatSurface/types'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ApplyExtractModal, { LABELS, TEXT_KEYS, type FormSnapshot } from './ApplyExtractModal'
import { WIZARD_STAGES } from './wizardStages'

interface Props {
  /** 读左边表单当前值。向导用它判断哪些栏位还空着，预览用它显示"会被换掉什么" */
  getFormSnapshot: () => FormSnapshot
  /** 把用户勾选的字段写进表单 */
  onApply: (picked: Partial<BrainstormExtract>) => void
}

const STARTERS = [
  '我还没想好写什么，帮我出三个能开起来的点子',
  '按现在填的内容，第一章该怎么开场',
  '这个金手指够不够撑一本长篇',
  '帮我把结局和主角变化定下来',
]

const LAST_STAGE = WIZARD_STAGES.length - 1

export default function BrainstormPanel({ getFormSnapshot, onApply }: Props) {
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
  const mode = useBrainstormStore((s) => s.mode)
  const stage = useBrainstormStore((s) => s.stage)
  const messages = useBrainstormStore((s) => s.messages)
  const confirmed = useBrainstormStore((s) => s.confirmed)
  const { setMode, setStage, setMessages, mergeConfirmed, clearConversation } = useBrainstormStore.getState()

  const [isStreaming, setIsStreaming] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [model, setModel] = useState('')
  const [webSearch, setWebSearch] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [extract, setExtract] = useState<BrainstormExtract | null>(null)

  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const chatModels = modelLibrary.filter(m => m.model_type !== 'embedding')

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => { abortRef.current?.abort() }, [])

  // stageIndex 显式传入：推进阶段时 store 的 stage 还没同步到这里的闭包
  const run = useCallback((history: ChatSurfaceMessage[], stageIndex: number) => {
    setMessages([...history, { role: 'assistant', content: '' }])
    setIsStreaming(true)
    setWaiting(true)

    const stageId = mode === 'wizard' && stageIndex >= 0 ? WIZARD_STAGES[stageIndex].id : ''

    abortRef.current = streamBrainstorm(
      {
        messages: history.map(m => ({ role: m.role, content: m.content })),
        model,
        nsfw: nsfwMode,
        web_search: webSearch,
        stage: stageId,
        confirmed: stageId ? formatConfirmed(confirmed) : '',
      },
      (msg: ChatSSEMessage) => {
        if (msg.event === 'token') {
          setWaiting(false)
          setMessages(prev => patchLast(prev, c => c + msg.data))
        } else if (msg.event === 'warning') {
          setWaiting(false)
          setMessages(prev => patchLast(prev, c => `⚠ ${msg.data}\n\n${c}`))
        } else if (msg.event === 'error') {
          setWaiting(false)
          setMessages(prev => patchLast(prev, () => `[错误] ${msg.data}`))
        }
      },
      () => { setIsStreaming(false); setWaiting(false) },
    )
  }, [mode, model, nsfwMode, webSearch, confirmed, setMessages])

  // base 显式传入：从中间某句重发时，闭包里的 messages 还是截断前的旧值
  const send = useCallback((text: string, base?: ChatSurfaceMessage[]) => {
    if (!text || isStreaming) return
    run([...(base ?? messages), { role: 'user', content: text }], stage)
  }, [isStreaming, messages, stage, run])

  /** 切到第 index 步：插一条分隔消息（它同时就是发给模型的引导语），让 AI 提这步的第一个问题 */
  const goToStage = useCallback((index: number, base?: ChatSurfaceMessage[]) => {
    const target = WIZARD_STAGES[index]
    setStage(index)
    run([
      ...(base ?? messages),
      {
        role: 'user',
        content: target.opener,
        kind: 'stage',
        label: `第 ${index + 1} 步 · ${target.label}`,
      },
    ], index)
  }, [messages, run, setStage])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setIsStreaming(false)
    setWaiting(false)
  }, [])

  const handleEditAt = useCallback(async (index: number, text: string) => {
    if (messages[index]?.role === 'assistant') {
      setMessages(prev => prev.map((m, i) => (i === index ? { ...m, content: text } : m)))
      return
    }
    const dropped = messages.length - index - 1
    if (dropped > 0) {
      const ok = await confirmDialog({
        title: `改这句会删掉后面 ${dropped} 条对话`,
        confirmText: '改并重发',
        danger: true,
      })
      if (!ok) return
    }
    send(text, messages.slice(0, index))
  }, [messages, send, setMessages])

  const handleExtract = useCallback(async () => {
    if (messages.length === 0 || isStreaming || extracting) return
    setExtracting(true)
    try {
      setExtract(await brainstormApi.extract(toTranscript(messages), model))
    } catch (err) {
      toast.error(String(err))
    } finally {
      setExtracting(false)
    }
  }, [messages, model, isStreaming, extracting])

  const handleApply = useCallback((picked: Partial<BrainstormExtract>) => {
    setExtract(null)
    onApply(picked)
    mergeConfirmed(picked)
    toast.success('已填进表单')
  }, [onApply, mergeConfirmed])

  /** 只往表单里还空着的栏位填，不动作者手打的内容。返回填了哪几栏 */
  const fillEmptyFields = useCallback((result: BrainstormExtract): string[] => {
    const current = getFormSnapshot()
    const picked: Partial<BrainstormExtract> = {}
    const filled: string[] = []

    for (const key of TEXT_KEYS) {
      if (result[key] && !current[key].trim()) {
        picked[key] = result[key]
        filled.push(LABELS[key])
      }
    }
    // 每步都是按全部对话抽的，已经填过的别再填一遍：牌会重复堆积，角色会盖掉作者的改动
    const knownCards = new Set((confirmed.endgame_cards ?? []).map(c => c.text))
    const newCards = result.endgame_cards.filter(c => !knownCards.has(c.text))
    if (newCards.length) {
      picked.endgame_cards = newCards
      filled.push(`${newCards.length} 张后手牌`)
    }
    const knownNames = new Set((confirmed.characters ?? []).map(c => c.name))
    const newChars = result.characters.filter(c => !knownNames.has(c.name))
    if (newChars.length) {
      picked.characters = newChars
      filled.push(`${newChars.length} 个角色`)
    }

    if (Object.keys(picked).length) onApply(picked)
    return filled
  }, [getFormSnapshot, onApply, confirmed])

  /** 这步聊定的东西先落进表单和已确认清单，再进下一步 */
  const handleNext = useCallback(async () => {
    if (isStreaming || extracting || stage >= LAST_STAGE) return
    setExtracting(true)
    try {
      const result = await brainstormApi.extract(toTranscript(messages), model)
      const filled = fillEmptyFields(result)
      mergeConfirmed(stripEmpty(result))
      toast.success(filled.length ? `已填进表单：${filled.join('、')}` : '这步还没聊出能填表单的结论')
    } catch (err) {
      toast.error(`这步的结论没抽出来，先往下走：${err}`)
    } finally {
      setExtracting(false)
    }
    goToStage(stage + 1)
  }, [isStreaming, extracting, stage, messages, model, fillEmptyFields, mergeConfirmed, goToStage])

  const handleSkip = useCallback(() => {
    if (isStreaming || extracting || stage >= LAST_STAGE) return
    goToStage(stage + 1)
  }, [isStreaming, extracting, stage, goToStage])

  /** 回到走过的某一步重聊：截掉那条分隔消息之后的所有对话，重新提问 */
  const handleRewind = useCallback(async (index: number) => {
    if (isStreaming || extracting || index >= stage) return
    const cut = stageMessageIndex(messages, index)
    if (cut < 0) return
    const ok = await confirmDialog({
      title: `回到「${WIZARD_STAGES[index].label}」重聊`,
      detail: `会删掉后面 ${messages.length - cut} 条对话。已经填进左边表单的内容不会撤销，需要的话自己改。`,
      confirmText: '回去重聊',
      danger: true,
    })
    if (!ok) return
    stop()
    goToStage(index, messages.slice(0, cut))
  }, [isStreaming, extracting, stage, messages, stop, goToStage])

  const handleClear = useCallback(() => {
    stop()
    clearConversation()
  }, [stop, clearConversation])

  const isWizard = mode === 'wizard'
  const busy = isStreaming || extracting
  const current = stage >= 0 ? WIZARD_STAGES[stage] : null

  return (
    <>
    <ChatSurface
      title={isWizard ? '构思向导' : '构思探讨'}
      messages={messages}
      isStreaming={isStreaming}
      waiting={waiting}
      onSend={send}
      onStop={stop}
      onEditAt={handleEditAt}
      onClear={handleClear}
      placeholder={
        isWizard && current
          ? '回答上面的问题，或者说“我不知道，你帮我定”... (Enter 发送)'
          : '聊聊你想写什么... (Enter 发送，Shift+Enter 换行)'
      }
      headerExtra={
        <>
          <button
            onClick={() => setMode(isWizard ? 'free' : 'wizard')}
            title={isWizard ? '切成自由聊天：不分步骤，想聊什么聊什么' : '切回向导：AI 带着你一步步定'}
            className="flex items-center gap-1 text-xs border rounded px-2 py-1 transition-colors hover:border-primary"
          >
            {isWizard ? <Wand2 className="w-3.5 h-3.5" /> : <MessageSquare className="w-3.5 h-3.5" />}
            {isWizard ? '向导' : '自由聊'}
          </button>
          <button
            onClick={handleExtract}
            disabled={messages.length === 0 || busy}
            title="把聊定的结论抽成表单字段，逐条核对后写回"
            className="flex items-center gap-1 text-xs border rounded px-2 py-1 transition-colors hover:border-primary disabled:opacity-40"
          >
            {extracting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ArrowLeftToLine className="w-3.5 h-3.5" />}
            写回表单
          </button>
          <button
            onClick={() => setWebSearch(!webSearch)}
            title={webSearch ? '联网搜索已开：每次提问先搜一次，结果仅作参考资料' : '联网搜索已关'}
            className={`flex items-center gap-1 text-xs border rounded px-2 py-1 transition-colors ${
              webSearch
                ? 'border-primary text-primary bg-primary/10'
                : 'text-muted-foreground hover:border-primary'
            }`}
          >
            <Globe className="w-3.5 h-3.5" />
            联网
          </button>
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            disabled={isStreaming}
            className="text-xs border rounded px-2 py-1 bg-background focus:outline-none max-w-[160px]"
          >
            <option value="">默认 Writer 模型</option>
            {chatModels.map(m => (
              <option key={m.id} value={String(m.id)}>
                [{m.provider}] {m.display_name || m.model_id}
              </option>
            ))}
          </select>
        </>
      }
      belowHeader={isWizard && current && (
        <div className="px-4 py-2.5 border-b bg-muted/30 shrink-0 space-y-2">
          <div className="flex items-center gap-1">
            {WIZARD_STAGES.map((s, i) => (
              <button
                key={s.id}
                onClick={() => handleRewind(i)}
                disabled={i >= stage || busy}
                title={i < stage ? `回到「${s.label}」重聊` : s.label}
                className={`h-1.5 flex-1 rounded-full transition-colors ${
                  i < stage
                    ? 'bg-primary/40 hover:bg-primary cursor-pointer'
                    : i === stage ? 'bg-primary' : 'bg-border'
                }`}
              />
            ))}
          </div>
          <div className="flex items-end justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xs font-medium">
                第 {stage + 1}/{WIZARD_STAGES.length} 步 · {current.label}
              </p>
              <p className="text-xs text-muted-foreground truncate">{current.hint}</p>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {stage < LAST_STAGE && (
                <button
                  onClick={handleSkip}
                  disabled={busy}
                  title="这步不聊了，直接进下一步"
                  className="flex items-center gap-1 text-xs border rounded px-2 py-1 text-muted-foreground transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
                >
                  <SkipForward className="w-3.5 h-3.5" />
                  跳过
                </button>
              )}
              <button
                onClick={stage < LAST_STAGE ? handleNext : handleExtract}
                disabled={busy}
                title={stage < LAST_STAGE ? '把这步聊定的填进表单，然后进下一步' : '把整套方案核对一遍写回表单'}
                className="flex items-center gap-1 text-xs rounded px-2.5 py-1 bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {extracting
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <ChevronRight className="w-3.5 h-3.5" />}
                {stage < LAST_STAGE ? '下一步' : '完成并核对'}
              </button>
            </div>
          </div>
        </div>
      )}
      emptyState={
        isWizard ? (
          <div className="mt-6">
            <div className="text-center text-sm text-muted-foreground/70">
              <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>只有一个模糊想法也没关系。</p>
              <p>AI 会一步步问你，每步聊定的自动填进左边表单。</p>
            </div>
            <button
              onClick={() => goToStage(0)}
              className="mt-6 w-full text-sm rounded-lg px-3 py-2.5 bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
            >
              开始构思
            </button>
            <ol className="mt-4 space-y-1">
              {WIZARD_STAGES.map((s, i) => (
                <li key={s.id} className="text-xs text-muted-foreground/70">
                  {i + 1}. {s.label}
                  <span className="text-muted-foreground/50">　{s.hint}</span>
                </li>
              ))}
            </ol>
          </div>
        ) : (
          <div className="mt-6">
            <div className="text-center text-sm text-muted-foreground/70">
              <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>边填边聊，聊定的用「写回表单」收进左边。</p>
            </div>
            <div className="mt-6 space-y-2">
              {STARTERS.map(s => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="w-full text-left text-xs border rounded-lg px-3 py-2 text-muted-foreground hover:border-primary hover:text-foreground transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )
      }
    />
    {extract && (
      <ApplyExtractModal
        extract={extract}
        current={getFormSnapshot()}
        onCancel={() => setExtract(null)}
        onApply={handleApply}
      />
    )}
  </>
  )
}

function patchLast(
  msgs: ChatSurfaceMessage[],
  updater: (content: string) => string,
): ChatSurfaceMessage[] {
  const last = msgs[msgs.length - 1]
  if (!last || last.role !== 'assistant') return msgs
  return [...msgs.slice(0, -1), { ...last, content: updater(last.content) }]
}

/** 抽取只看真正的对话，阶段引导语（"进入 xx 这一步"）是流程指令，不是聊出来的内容 */
function toTranscript(msgs: ChatSurfaceMessage[]) {
  return msgs
    .filter(m => m.kind !== 'stage' && m.content)
    .map(m => ({ role: m.role, content: m.content }))
}

/** 第 index 步那条分隔消息在 messages 里的位置，没有返回 -1 */
function stageMessageIndex(msgs: ChatSurfaceMessage[], index: number): number {
  let seen = -1
  return msgs.findIndex(m => m.kind === 'stage' && ++seen === index)
}

/** 空串/空数组是"没聊到"，别用它盖掉之前已经定下来的 */
function stripEmpty(result: BrainstormExtract): Partial<BrainstormExtract> {
  const out: Partial<BrainstormExtract> = {}
  for (const key of TEXT_KEYS) {
    if (result[key]) out[key] = result[key]
  }
  if (result.endgame_cards.length) out.endgame_cards = result.endgame_cards
  if (result.characters.length) out.characters = result.characters
  return out
}
