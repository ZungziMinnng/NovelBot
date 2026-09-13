import { useState, useRef, useCallback, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bot, Loader2, ChevronRight, SkipForward } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  streamRpgWizard, modelLibraryApi,
  type ChatSSEMessage, type RpgWizardExtract, type RpgWizardKnown, type RpgPlayStyle, type RpgWorldScope,
} from '@/api/client'
import { rpgApi } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'
import ChatSurface from '@/components/ChatSurface/ChatSurface'
import type { ChatSurfaceMessage } from '@/components/ChatSurface/types'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import WizardApplyModal, { type WizardPicked } from './WizardApplyModal'
import { WIZARD_STAGES } from './wizardStages'

interface Props {
  moduleId: number
  playStyle: RpgPlayStyle
  /** 把勾选后的内容写进模组：主表字段走 set，子表走各自的 create */
  onApply: (picked: WizardPicked) => void
}

const EMPTY_DRAFT: RpgWizardExtract = { dropped: [] }

export default function WizardPanel({ moduleId, playStyle, onApply }: Props) {
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)

  const [messages, setMessages] = useState<ChatSurfaceMessage[]>([])
  const [stage, setStage] = useState(-1)
  const [worldScope, setWorldScope] = useState<RpgWorldScope>('region')
  const [oneShotMode, setOneShotMode] = useState(false)
  const [generatingFull, setGeneratingFull] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const [model, setModel] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [fullInstruction, setFullInstruction] = useState('')
  // 跨步累积的抽取结果。每步只抽自己那一摊，合并进来，最后一次性预览
  const [draft, setDraft] = useState<RpgWizardExtract>(EMPTY_DRAFT)
  const [preview, setPreview] = useState<RpgWizardExtract | null>(null)

  const lastStage = WIZARD_STAGES.length - 1

  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const chatModels = modelLibrary.filter(m => m.model_type !== 'embedding')

  const abortRef = useRef<AbortController | null>(null)
  const fullRequestRef = useRef(0)
  useEffect(() => () => { abortRef.current?.abort() }, [])

  /** 前面几步已定的名字，喂给后面步骤的抽取当白名单 */
  const knownFromDraft = useCallback((d: RpgWizardExtract): RpgWizardKnown => ({
    stat_names: (d.stat_defs || []).map(s => s.name),
    relation_names: (d.relation_stat_defs || []).map(s => s.name),
    location_names: (d.locations || []).map(l => l.name),
  }), [])

  /** 已确认清单转成给对话模型的一段文字，避免它自相矛盾或重复问 */
  const confirmedText = useCallback((d: RpgWizardExtract): string => {
    const parts: string[] = []
    if (d.genre) parts.push(`题材：${d.genre}`)
    if (d.worldview) parts.push(`世界观：${d.worldview}`)
    const stats = (d.stat_defs || []).map(s => s.name)
    if (stats.length) parts.push(`玩家数值：${stats.join('、')}`)
    const rels = (d.relation_stat_defs || []).map(s => s.name)
    if (rels.length) parts.push(`关系数值：${rels.join('、')}`)
    const locs = (d.locations || []).map(l => l.name)
    if (locs.length) parts.push(`地点：${locs.join('、')}`)
    if (d.time_slots?.length) parts.push(`时段：${d.time_slots.join('、')}`)
    const npcs = (d.npcs || []).map(n => n.name)
    if (npcs.length) parts.push(`角色：${npcs.join('、')}`)
    return parts.join('\n')
  }, [])

  const run = useCallback((history: ChatSurfaceMessage[], stageIndex: number, confirmed: string) => {
    setMessages([...history, { role: 'assistant', content: '' }])
    setIsStreaming(true)
    setWaiting(true)
    const stageId = stageIndex >= 0 ? WIZARD_STAGES[stageIndex].id : ''

    abortRef.current = streamRpgWizard(
      moduleId,
      {
        messages: history.map(m => ({ role: m.role, content: m.content })),
        model,
        nsfw: nsfwMode,
        stage: stageId,
        confirmed: stageId ? confirmed : '',
        play_style: playStyle,
        world_scope: worldScope,
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
  }, [moduleId, model, nsfwMode, playStyle, worldScope])

  const generateFull = useCallback(async (text: string, originalInstruction = text) => {
    if (!text || isStreaming || generatingFull) return
    const history = [...messages, { role: 'user' as const, content: text }]
    setMessages([...history, { role: 'assistant', content: '' }])
    setGeneratingFull(true)
    setIsStreaming(true)
    setWaiting(true)
    const requestId = ++fullRequestRef.current
    try {
      const result = await rpgApi.modules.wizardGenerate(moduleId, {
        instruction: text,
        nsfw: nsfwMode,
        model,
        world_scope: worldScope,
      })
      if (requestId !== fullRequestRef.current) return
      setMessages([...history, {
        role: 'assistant',
        content: fullDraftIntro(result),
      }])
      setFullInstruction(originalInstruction)
      setDraft(result)
      setPreview(result)
    } catch (err) {
      if (requestId !== fullRequestRef.current) return
      setMessages([...history, {
        role: 'assistant',
        content: `[生成失败] ${String(err)}`,
      }])
      toast.error(`整套生成失败：${String(err)}`)
    } finally {
      if (requestId === fullRequestRef.current) {
        setGeneratingFull(false)
        setIsStreaming(false)
        setWaiting(false)
      }
    }
  }, [messages, moduleId, model, nsfwMode, worldScope, isStreaming, generatingFull])

  const send = useCallback((text: string, base?: ChatSurfaceMessage[]) => {
    if (!text || isStreaming || generatingFull) return
    if (stage < 0) {
      if (oneShotMode) {
        void generateFull(text)
      } else {
        toast.error('请先选择“开始分步构思”或“一句话生成整套”')
      }
      return
    }
    run([...(base ?? messages), { role: 'user', content: text }], stage, confirmedText(draft))
  }, [isStreaming, generatingFull, oneShotMode, generateFull, messages, stage, run, draft, confirmedText])

  const goToStage = useCallback((index: number, base?: ChatSurfaceMessage[], d?: RpgWizardExtract) => {
    const target = WIZARD_STAGES[index]
    setOneShotMode(false)
    setStage(index)
    run([
      ...(base ?? messages),
      { role: 'user', content: target.opener, kind: 'stage', label: `第 ${index + 1} 步 · ${target.label}` },
    ], index, confirmedText(d ?? draft))
  }, [messages, run, draft, confirmedText])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    fullRequestRef.current += 1
    setGeneratingFull(false)
    setIsStreaming(false)
    setWaiting(false)
  }, [])

  /** 抽当前这一步，合并进 draft。返回合并后的 draft（调用方接着用它进下一步） */
  const extractCurrent = useCallback(async (): Promise<RpgWizardExtract> => {
    const stageId = WIZARD_STAGES[stage].id
    const transcript = messages.filter(m => m.kind !== 'stage' && m.content)
    const result = await rpgApi.modules.wizardExtract(moduleId, {
      stage: stageId,
      messages: transcript.map(m => ({ role: m.role, content: m.content })),
      known: knownFromDraft(draft),
      model,
    })
    const merged = mergeStage(draft, result)
    setDraft(merged)
    return merged
  }, [stage, messages, moduleId, draft, knownFromDraft, model])

  const handleNext = useCallback(async () => {
    if (isStreaming || extracting || stage >= lastStage) return
    setExtracting(true)
    let merged = draft
    try {
      merged = await extractCurrent()
      const n = countStage(merged, WIZARD_STAGES[stage].id)
      toast.success(n ? `这步收下了 ${n} 项` : '这步还没聊出能收的内容')
    } catch (err) {
      toast.error(`这步没抽出来，先往下走：${err}`)
    } finally {
      setExtracting(false)
    }
    goToStage(stage + 1, undefined, merged)
  }, [isStreaming, extracting, stage, lastStage, draft, extractCurrent, goToStage])

  const handleSkip = useCallback(() => {
    if (isStreaming || extracting || stage >= lastStage) return
    goToStage(stage + 1)
  }, [isStreaming, extracting, stage, lastStage, goToStage])

  /** 最后一步：抽这步 + 弹全量预览 */
  const handleFinish = useCallback(async () => {
    if (isStreaming || extracting) return
    setExtracting(true)
    try {
      const merged = stage >= 0 ? await extractCurrent() : draft
      setPreview(merged)
    } catch (err) {
      toast.error(`抽取失败：${err}`)
    } finally {
      setExtracting(false)
    }
  }, [isStreaming, extracting, stage, draft, extractCurrent])

  const handleEditAt = useCallback(async (index: number, text: string) => {
    if (messages[index]?.role === 'assistant') {
      setMessages(prev => prev.map((m, i) => (i === index ? { ...m, content: text } : m)))
      return
    }
    const dropped = messages.length - index - 1
    if (dropped > 0) {
      const ok = await confirmDialog({ title: `改这句会删掉后面 ${dropped} 条对话`, confirmText: '改并重发', danger: true })
      if (!ok) return
    }
    send(text, messages.slice(0, index))
  }, [messages, send])

  const handleClear = useCallback(async () => {
    if (messages.length > 0) {
      const ok = await confirmDialog({ title: '清空对话重来', detail: '已经填进模组的内容不受影响。', confirmText: '清空', danger: true })
      if (!ok) return
    }
    stop()
    setMessages([])
    setStage(-1)
    setOneShotMode(false)
    setWorldScope('region')
    setGeneratingFull(false)
    setFullInstruction('')
    setDraft(EMPTY_DRAFT)
  }, [messages.length, stop])

  const handleApply = useCallback((picked: WizardPicked) => {
    setPreview(null)
    onApply(picked)
  }, [onApply])

  const handleRegenerate = useCallback(() => {
    if (!fullInstruction || generatingFull) return
    setPreview(null)
    void generateFull(`请基于上次想法重新随机生成一套不同方案：${fullInstruction}`, fullInstruction)
  }, [fullInstruction, generatingFull, generateFull])

  const busy = isStreaming || extracting || generatingFull
  const current = stage >= 0 ? WIZARD_STAGES[stage] : null

  return (
    <>
      <ChatSurface
        title="构思向导"
        messages={messages}
        isStreaming={isStreaming}
        waiting={waiting}
        waitingLabel={generatingFull ? '正在生成整套模组，请稍候…' : undefined}
        onSend={send}
        onStop={stop}
        onEditAt={handleEditAt}
        onClear={handleClear}
        placeholder={current
          ? '回答上面的问题，或者说“我不知道，你帮我定”… (Enter 发送)'
          : oneShotMode
            ? '例如：一个发生在雨夜港口的失忆侦探故事'
            : '请选择一种构思方式后再输入...'}
        headerExtra={
          <select
            value={model}
            onChange={e => setModel(e.target.value)}
            disabled={isStreaming}
            className="text-xs border rounded px-2 py-1 bg-background focus:outline-none max-w-[160px]"
          >
            <option value="">模组默认模型</option>
            {chatModels.map(m => (
              <option key={m.id} value={String(m.id)}>[{m.provider}] {m.display_name || m.model_id}</option>
            ))}
          </select>
        }
        belowHeader={current && (
          <div className="px-4 py-2.5 border-b bg-muted/30 shrink-0 space-y-2">
            <div className="flex items-center gap-1">
              {WIZARD_STAGES.map((s, i) => (
                <div
                  key={s.id}
                  title={s.label}
                  className={`h-1.5 flex-1 rounded-full ${i < stage ? 'bg-primary/40' : i === stage ? 'bg-primary' : 'bg-border'}`}
                />
              ))}
            </div>
            <div className="flex items-end justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium">第 {stage + 1}/{WIZARD_STAGES.length} 步 · {current.label}</p>
                <p className="text-xs text-muted-foreground truncate">{current.hint}</p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {stage >= 0 && (
                  <button
                    onClick={handleFinish}
                    disabled={busy}
                    title="提取当前对话并预览回填内容"
                    className="text-xs border rounded px-2 py-1 text-primary transition-colors hover:bg-primary/10 disabled:opacity-40"
                  >
                    预览并回填
                  </button>
                )}
                {stage < lastStage && (
                  <button
                    onClick={handleSkip}
                    disabled={busy}
                    title="这步不聊了，直接进下一步"
                    className="flex items-center gap-1 text-xs border rounded px-2 py-1 text-muted-foreground transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
                  >
                    <SkipForward className="w-3.5 h-3.5" /> 跳过
                  </button>
                )}
                <button
                  onClick={stage < lastStage ? handleNext : handleFinish}
                  disabled={busy}
                  title={stage < lastStage ? '收下这步，进下一步' : '把整套方案核对一遍写进模组'}
                  className="flex items-center gap-1 text-xs rounded px-2.5 py-1 bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  {extracting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ChevronRight className="w-3.5 h-3.5" />}
                  {stage < lastStage ? '下一步' : '完成并核对'}
                </button>
              </div>
            </div>
          </div>
        )}
        emptyState={
          <div className="mt-6">
            <div className="text-center text-sm text-muted-foreground/70">
              <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
              {oneShotMode ? (
                <>
                  <p className="font-medium text-foreground">一句话生成整套模组</p>
                  <p>输入一个简单想法，AI 会生成完整草案供你预览回填。</p>
                </>
              ) : (
                <>
                  <p>选择一种方式开始构思：</p>
                  <p>分步讨论，或用一句话直接生成整套模组。</p>
                </>
              )}
            </div>
            <div className="mt-5 rounded-lg border bg-muted/20 p-3">
              <p className="text-xs font-medium mb-2">先选择世界规模</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button
                  onClick={() => setWorldScope('world')}
                  className={`text-left rounded-lg border px-3 py-2 transition-colors ${worldScope === 'world' ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted'}`}
                >
                  <span className="block text-sm font-medium">完整世界</span>
                  <span className="block text-xs opacity-70 mt-0.5">大陆、区域、组织和多人物的完整骨架</span>
                </button>
                <button
                  onClick={() => setWorldScope('region')}
                  className={`text-left rounded-lg border px-3 py-2 transition-colors ${worldScope === 'region' ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted'}`}
                >
                  <span className="block text-sm font-medium">一块区域的故事</span>
                  <span className="block text-xs opacity-70 mt-0.5">聚焦一个宗门、城市或聚落</span>
                </button>
              </div>
            </div>
            {oneShotMode ? (
              <button
                onClick={() => setOneShotMode(false)}
                className="mt-6 w-full text-sm rounded-lg px-3 py-2.5 border hover:bg-muted transition-colors"
              >
                返回选择构思方式
              </button>
            ) : (
              <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-2">
                <button
                  onClick={() => goToStage(0)}
                  className="text-sm rounded-lg px-3 py-2.5 bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
                >
                  开始分步构思
                </button>
                <button
                  onClick={() => setOneShotMode(true)}
                  className="text-sm rounded-lg px-3 py-2.5 border border-primary/40 text-primary hover:bg-primary/10 transition-colors"
                >
                  一句话生成整套
                </button>
              </div>
            )}
            {!oneShotMode && (
              <ol className="mt-4 space-y-1">
                {WIZARD_STAGES.map((s, i) => (
                  <li key={s.id} className="text-xs text-muted-foreground/70">
                    {i + 1}. {s.label}<span className="text-muted-foreground/50">　{s.hint}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        }
      />
      {preview && (
        <WizardApplyModal
          draft={preview}
          onCancel={() => setPreview(null)}
          onApply={handleApply}
          onRegenerate={oneShotMode ? handleRegenerate : undefined}
        />
      )}
    </>
  )
}

function fullDraftIntro(draft: RpgWizardExtract): string {
  const lines = ['我根据你的想法生成了一套模组草案。']
  if (draft.genre) lines.push(`题材：${draft.genre}`)
  if (draft.worldview) lines.push(`世界观：${draft.worldview}`)
  const groups = [
    ['数值', (draft.stat_defs?.length || 0) + (draft.relation_stat_defs?.length || 0)],
    ['地点', draft.locations?.length || 0],
    ['时段', draft.time_slots?.length || 0],
    ['角色', draft.npcs?.length || 0],
    ['道具', draft.items?.length || 0],
    ['动作按钮', draft.actions?.length || 0],
  ]
  const counts = groups.filter(([, count]) => count).map(([label, count]) => `${label}${count}项`)
  if (counts.length) lines.push(`已生成：${counts.join('、')}。`)
  lines.push('请在弹出的预览中勾选要回填的内容；不满意可以换一套。')
  return lines.join('\n')
}

function patchLast(msgs: ChatSurfaceMessage[], updater: (content: string) => string): ChatSurfaceMessage[] {
  const last = msgs[msgs.length - 1]
  if (!last || last.role !== 'assistant') return msgs
  return [...msgs.slice(0, -1), { ...last, content: updater(last.content) }]
}

/** 把一步的抽取合并进累积 draft。每步字段不重叠，dropped 追加去重 */
function mergeStage(base: RpgWizardExtract, step: RpgWizardExtract): RpgWizardExtract {
  const merged: RpgWizardExtract = { ...base, ...stripEmpty(step) }
  merged.dropped = Array.from(new Set([...(base.dropped || []), ...(step.dropped || [])]))
  return merged
}

/** 空串/空列表是「这步没聊到」，别用它盖掉之前定的 */
function stripEmpty(step: RpgWizardExtract): Partial<RpgWizardExtract> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(step)) {
    if (k === 'dropped') continue
    if (typeof v === 'string' && v) out[k] = v
    else if (Array.isArray(v) && v.length) out[k] = v
  }
  return out as Partial<RpgWizardExtract>
}

/** 某一步收下了几项，用于 toast */
function countStage(d: RpgWizardExtract, stageId: string): number {
  switch (stageId) {
    case 'world': return ['genre', 'worldview', 'opening_scene', 'system_instruction', 'narration_sample'].filter(k => d[k as keyof RpgWizardExtract]).length
    case 'stats': return (d.stat_defs?.length || 0) + (d.relation_stat_defs?.length || 0)
    case 'places': return d.locations?.length || 0
    case 'slots': return d.time_slots?.length || 0
    case 'cast': return d.npcs?.length || 0
    case 'things': return (d.items?.length || 0) + (d.actions?.length || 0)
    default: return 0
  }
}
