import { useState, useRef, useCallback, useEffect } from 'react'
import { Plus, Zap, Loader2, Square, RotateCcw, X, MessageSquareQuote, PenLine, Shield, FileSearch, SlidersHorizontal, AlertTriangle } from 'lucide-react'
import AgentStatus from '@/components/AgentStatus/AgentStatus'
import AutoTextarea from '@/components/AutoTextarea'
import type { Annotation } from '@/store/editorStore'
import type { ModelEntry } from '@/api/client'
import { modelSelectValue, findModelEntry } from '@/api/client'

export interface EntityItem { name: string; type: string; typeLabel: string; description: string }

export type BarMode = 'write' | 'rewrite'

interface GenerationBarProps {
  // Mode
  barMode: BarMode
  onBarModeChange: (mode: BarMode) => void
  hasChapterContent: boolean

  // Generation
  agentStage: string
  isCurrentlyGenerating: boolean
  isOtherGenerating: boolean
  justFinishedHere: boolean
  instruction: string
  targetWords: number
  onInstructionChange: (v: string) => void
  onTargetWordsChange: (v: number) => void
  pov: string
  onPovChange: (v: string) => void
  povOptions: string[]
  onGenerate: () => void
  onAbortOrGenerate: () => void

  // 本章有没有细纲。没有就提示补一份，不拦着写
  hasChapterOutline: boolean
  draftingOutline: boolean
  onDraftOutline: () => void

  // Rewrite
  annotations: Annotation[]
  onRemoveAnnotation: (id: string) => void
  onClearAnnotations: () => void
  onAddGlobalAnnotation: (text: string) => void
  onRewrite: () => void
  rewriteModel: string
  onRewriteModelChange: (v: string) => void
  writerModel: string
  onWriterModelChange: (v: string) => void
  modelLibrary: ModelEntry[]

  // Entity autocomplete
  entities: EntityItem[]

  // Review toggles (inline next to generate button)
  enableCritic: boolean
  enableDetailReview: boolean
  onToggleCritic: () => void
  onToggleDetailReview: () => void

  // Quick generation params
  writerTemperature: number
  writerUseCustomTemperature: boolean
  geminiThinkingLevel: string
  deepseekThinkingLevel: string
  onQuickParamsChange: (patch: Partial<{
    writer_temperature: number
    writer_use_custom_temperature: boolean
    gemini_thinking_level: string
    deepseek_thinking_level: string
  }>) => void
}

const CIRCLED_NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

// 按供应商名字聚合并排序，返回 <optgroup> 列表
function groupModelsByProvider(models: ModelEntry[]) {
  const groups = new Map<string, ModelEntry[]>()
  for (const m of models.filter(m => m.model_type !== 'embedding')) {
    const key = m.provider || '未分组'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(m)
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'zh-Hans-CN'))
    .map(([provider, items]) => ({
      provider,
      items: items.sort((a, b) =>
        (a.display_name || a.model_id).localeCompare(b.display_name || b.model_id, 'zh-Hans-CN'),
      ),
    }))
}

export default function GenerationBar({
  barMode,
  onBarModeChange,
  hasChapterContent,
  agentStage,
  isCurrentlyGenerating,
  isOtherGenerating,
  justFinishedHere,
  instruction,
  targetWords,
  onInstructionChange,
  onTargetWordsChange,
  pov,
  onPovChange,
  povOptions,
  onGenerate,
  onAbortOrGenerate,
  hasChapterOutline,
  draftingOutline,
  onDraftOutline,
  annotations,
  onRemoveAnnotation,
  onClearAnnotations,
  onAddGlobalAnnotation,
  onRewrite,
  rewriteModel,
  onRewriteModelChange,
  writerModel,
  onWriterModelChange,
  modelLibrary,
  entities,
  enableCritic,
  enableDetailReview,
  onToggleCritic,
  onToggleDetailReview,
  writerTemperature,
  writerUseCustomTemperature,
  geminiThinkingLevel,
  deepseekThinkingLevel,
  onQuickParamsChange,
}: GenerationBarProps) {
  const [globalInput, setGlobalInput] = useState('')
  const [showParams, setShowParams] = useState(false)
  const paramsRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 关闭参数浮层：点击外部
  useEffect(() => {
    if (!showParams) return
    const onDown = (e: MouseEvent) => {
      if (paramsRef.current && !paramsRef.current.contains(e.target as Node)) setShowParams(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [showParams])

  // 当前 Writer 模型的调用格式，决定显示 Gemini 还是 DeepSeek 的思考档位
  const currentModel = findModelEntry(modelLibrary, writerModel)
  const modelFormat = currentModel?.api_format || ''
  const isGeminiModel = modelFormat === 'gemini'
  const isDeepseekModel = /deepseek/i.test(currentModel?.model_id || '')
  const [acItems, setAcItems] = useState<EntityItem[]>([])
  const [acIndex, setAcIndex] = useState(0)
  const [acFragment, setAcFragment] = useState({ start: 0, end: 0 })

  const handleAddGlobal = () => {
    if (!globalInput.trim()) return
    onAddGlobalAnnotation(globalInput.trim())
    setGlobalInput('')
  }

  const composingRef = useRef(false)

  const refreshAutocomplete = useCallback((value: string, cursorPos: number) => {
    if (entities.length === 0 || cursorPos === 0) {
      setAcItems([])
      return
    }
    const textBefore = value.slice(0, cursorPos)
    const maxCheck = Math.min(20, textBefore.length)
    for (let len = maxCheck; len >= 1; len--) {
      const suffix = textBefore.slice(-len)
      const matches = entities.filter(e => e.name.startsWith(suffix))
      if (matches.length > 0) {
        setAcItems(matches.slice(0, 8))
        setAcIndex(0)
        setAcFragment({ start: cursorPos - len, end: cursorPos })
        return
      }
    }
    setAcItems([])
  }, [entities])

  const handleInstructionChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.currentTarget.value
    onInstructionChange(value)
    if (!composingRef.current) {
      refreshAutocomplete(value, e.currentTarget.selectionStart)
    }
  }, [onInstructionChange, refreshAutocomplete])

  const handleSelectionRefresh = useCallback((e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    if (composingRef.current) return
    const target = e.currentTarget
    refreshAutocomplete(target.value, target.selectionStart)
  }, [refreshAutocomplete])

  const handleInstructionKeyUp = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (composingRef.current) return
    if (acItems.length > 0 && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(e.key)) return
    refreshAutocomplete(e.currentTarget.value, e.currentTarget.selectionStart)
  }, [acItems.length, refreshAutocomplete])

  const insertEntity = useCallback((item: EntityItem) => {
    const ta = textareaRef.current
    if (!ta) return
    const before = instruction.slice(0, acFragment.start)
    const after = instruction.slice(acFragment.end)
    const newValue = before + item.name + after
    onInstructionChange(newValue)
    setAcItems([])
    requestAnimationFrame(() => {
      const pos = acFragment.start + item.name.length
      ta.selectionStart = pos
      ta.selectionEnd = pos
      ta.focus()
    })
  }, [instruction, acFragment, onInstructionChange])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (composingRef.current || acItems.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setAcIndex(i => (i + 1) % acItems.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setAcIndex(i => (i - 1 + acItems.length) % acItems.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      insertEntity(acItems[acIndex])
    } else if (e.key === 'Escape') {
      setAcItems([])
    }
  }, [acItems, acIndex, insertEntity])

  return (
    <div className="border-t px-4 py-3 shrink-0 space-y-2">
      <AgentStatus stage={agentStage} visible={isCurrentlyGenerating} />

      {/* Mode toggle */}
      {!isCurrentlyGenerating && (
        <div className="flex items-center gap-1 p-0.5 bg-muted rounded-lg w-fit">
          <button
            onClick={() => onBarModeChange('write')}
            className={`flex items-center gap-1 text-xs px-3 py-1 rounded-md transition-colors ${
              barMode === 'write' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <PenLine className="w-3 h-3" /> 续写
          </button>
          <button
            onClick={() => onBarModeChange('rewrite')}
            disabled={!hasChapterContent}
            className={`flex items-center gap-1 text-xs px-3 py-1 rounded-md transition-colors disabled:opacity-40 ${
              barMode === 'rewrite' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <MessageSquareQuote className="w-3 h-3" /> 重写
          </button>
        </div>
      )}

      {barMode === 'write' ? (
        <>
          {/* 没细纲就提醒补一份。不禁用生成按钮，作者想直接冲也拦不住 */}
          {!hasChapterOutline && !isCurrentlyGenerating && (
            <div className="flex items-center gap-2 text-xs rounded-lg px-2.5 py-1.5 bg-amber-500/10 text-amber-700 dark:text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span className="flex-1">这一章还没有细纲，直接生成的话剧情全靠模型临场决定。</span>
              <button
                onClick={onDraftOutline}
                disabled={draftingOutline}
                className="flex items-center gap-1 shrink-0 px-2 py-1 rounded-md border border-amber-500/40 hover:bg-amber-500/15 disabled:opacity-50 transition-colors"
              >
                {draftingOutline && <Loader2 className="w-3 h-3 animate-spin" />}
                {draftingOutline ? '生成中…' : '先补本章细纲'}
              </button>
            </div>
          )}

          {/* Instruction + Generate */}
          <div className="flex flex-col gap-2">
            <div className="relative">
              <AutoTextarea
                ref={textareaRef}
                value={instruction}
                onChange={handleInstructionChange}
                onKeyDown={handleKeyDown}
                onKeyUp={handleInstructionKeyUp}
                onClick={handleSelectionRefresh}
                onSelect={handleSelectionRefresh}
                onCompositionStart={() => { composingRef.current = true; setAcItems([]) }}
                onCompositionEnd={() => { composingRef.current = false }}
                onBlur={() => setTimeout(() => setAcItems([]), 150)}
                placeholder="生成指令（可选）：重点描写心理活动..."
                minRows={3}
                className="w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              {acItems.length > 0 && (
                <div className="absolute bottom-full left-0 right-0 mb-1 bg-background border border-border rounded-lg shadow-2xl overflow-hidden z-50 max-h-48 overflow-y-auto">
                  {acItems.map((item, i) => (
                    <div
                      key={`${item.type}-${item.name}`}
                      onMouseDown={e => { e.preventDefault(); insertEntity(item) }}
                      className={`flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer transition-colors ${
                        i === acIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'
                      }`}
                    >
                      <span className="shrink-0 text-[0.625rem] px-1 py-0.5 rounded bg-muted text-muted-foreground">{item.typeLabel}</span>
                      <span className="font-medium">{item.name}</span>
                      <span className="text-muted-foreground/60 truncate flex-1">{item.description}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={targetWords}
                onChange={e => onTargetWordsChange(Number(e.target.value))}
                className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none"
              >
                <option value={500}>500字</option>
                <option value={1200}>1200字</option>
                <option value={2000}>2000字 · 网文常规</option>
                <option value={2500}>2500字 · 网文常规</option>
                <option value={3000}>3000字 · 网文常规</option>
                <option value={3500}>3500字</option>
                <option value={4000}>4000字</option>
                <option value={5000}>5000字</option>
                <option value={6000}>6000字</option>
                <option value={7000}>7000字</option>
                <option value={8000}>8000字</option>
              </select>
              <select
                value={pov}
                onChange={e => onPovChange(e.target.value)}
                disabled={isCurrentlyGenerating}
                title="本章视角角色（留空＝默认男主，其不知道的秘密将进入上帝视角隔离区）"
                className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none max-w-[140px] truncate disabled:opacity-50"
              >
                <option value="">视角·默认男主</option>
                {povOptions.map(name => (
                  <option key={name} value={name}>视角·{name}</option>
                ))}
              </select>
              <select
                value={modelSelectValue(modelLibrary, writerModel)}
                onChange={e => onWriterModelChange(e.target.value)}
                disabled={isCurrentlyGenerating}
                title="Writer 模型（切换即保存为本小说默认）"
                className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none max-w-[160px] truncate disabled:opacity-50"
              >
                <option value="">跟随全局默认</option>
                {groupModelsByProvider(modelLibrary).map(g => (
                  <optgroup key={g.provider} label={g.provider}>
                    {g.items.map(m => (
                      <option key={m.id} value={String(m.id)}>
                        {m.display_name || m.model_id}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {/* Quick generation params */}
              <div className="relative" ref={paramsRef}>
                <button
                  onClick={() => setShowParams(v => !v)}
                  disabled={isCurrentlyGenerating}
                  title="生成参数（温度 / 思考强度，切换即保存为本小说默认）"
                  className={`flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-xs transition-colors shrink-0 disabled:opacity-50 ${
                    showParams
                      ? 'text-primary bg-primary/10 border border-primary/30'
                      : 'text-muted-foreground hover:bg-muted border border-transparent'
                  }`}
                >
                  <SlidersHorizontal className="w-3.5 h-3.5" />
                  <span className="font-medium">参数</span>
                </button>
                {showParams && (
                  <div className="absolute bottom-full left-0 mb-2 w-64 bg-background border border-border rounded-lg shadow-2xl p-3 z-50 space-y-3">
                    {/* 温度开关 */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium">发送温度参数</span>
                      <button
                        onClick={() => onQuickParamsChange({ writer_use_custom_temperature: !writerUseCustomTemperature })}
                        className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors ${writerUseCustomTemperature ? 'bg-primary' : 'bg-muted'}`}
                      >
                        <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${writerUseCustomTemperature ? 'translate-x-4' : 'translate-x-0'}`} />
                      </button>
                    </div>
                    {/* 温度大小 */}
                    <div className={writerUseCustomTemperature ? '' : 'opacity-40 pointer-events-none'}>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium">生成温度</span>
                        <span className="text-xs font-mono text-muted-foreground">{writerTemperature.toFixed(2)}</span>
                      </div>
                      <input
                        type="range"
                        min={0.1}
                        max={1.5}
                        step={0.05}
                        value={writerTemperature}
                        onChange={e => onQuickParamsChange({ writer_temperature: Number(e.target.value) })}
                        className="w-full accent-primary"
                      />
                      <div className="flex justify-between text-[0.625rem] text-muted-foreground mt-0.5">
                        <span>保守 0.1</span>
                        <span>1.5 发散</span>
                      </div>
                    </div>
                    {/* 思考强度：按当前模型类型显示 */}
                    <div className="border-t pt-2">
                      {isGeminiModel ? (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium">Gemini 思考强度</span>
                          <select
                            value={geminiThinkingLevel}
                            onChange={e => onQuickParamsChange({ gemini_thinking_level: e.target.value })}
                            className="text-xs border rounded-md px-2 py-1 bg-background focus:outline-none"
                          >
                            <option value="off">关闭</option>
                            <option value="low">低</option>
                            <option value="medium">中</option>
                            <option value="high">高</option>
                          </select>
                        </div>
                      ) : isDeepseekModel ? (
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium">DeepSeek 思考</span>
                          <select
                            value={deepseekThinkingLevel}
                            onChange={e => onQuickParamsChange({ deepseek_thinking_level: e.target.value })}
                            className="text-xs border rounded-md px-2 py-1 bg-background focus:outline-none"
                          >
                            <option value="off">关闭</option>
                            <option value="high">高</option>
                            <option value="max">最高</option>
                          </select>
                        </div>
                      ) : (
                        <p className="text-[0.625rem] text-muted-foreground">当前模型无思考强度设置</p>
                      )}
                    </div>
                  </div>
                )}
              </div>
              {/* Review toggles */}
              <button
                onClick={onToggleCritic}
                disabled={isCurrentlyGenerating}
                title={`Critic 审查（${enableCritic ? '已开启' : '已关闭'}）\n\n开启后，章节生成完毕将自动调用审查模型检查以下内容：\n• 角色性格、能力、关系、状态是否与角色卡一致\n• 势力立场、目标、阵营、行动边界是否与势力设定冲突\n• 系统/道具/功法是否前后矛盾或擅自变更\n• 本章是否偏离大纲目标\n• 是否出现逻辑漏洞、人名替换、无根据新增设定\n\n审查不通过将自动进入修订循环（最多重试 2 次）。\n点击切换开关状态。`}
                className={`flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-xs transition-colors shrink-0 disabled:opacity-50 ${
                  enableCritic
                    ? 'text-amber-600 bg-amber-50 hover:bg-amber-100 border border-amber-200'
                    : 'text-muted-foreground hover:bg-muted border border-transparent'
                }`}
              >
                <Shield className="w-3.5 h-3.5" />
                <span className="font-medium">审查{enableCritic ? '开' : '关'}</span>
              </button>
              <button
                onClick={onToggleDetailReview}
                disabled={isCurrentlyGenerating}
                title={`剧情细节审查（${enableDetailReview ? '已开启' : '已关闭'}）\n\n专注章节正文文字层面，检查以下问题：\n• 前后章节之间的连续性断裂\n• 场景、动作、对话的文字重复\n• 人物位置、持有物品的事实矛盾\n• 时间线标注与实际剧情顺序的冲突\n\n基于前 20 章内容进行扫描，发现问题后自动进入修订循环。\n点击切换开关状态。`}
                className={`flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-xs transition-colors shrink-0 disabled:opacity-50 ${
                  enableDetailReview
                    ? 'text-blue-600 bg-blue-50 hover:bg-blue-100 border border-blue-200'
                    : 'text-muted-foreground hover:bg-muted border border-transparent'
                }`}
              >
                <FileSearch className="w-3.5 h-3.5" />
                <span className="font-medium">细节{enableDetailReview ? '开' : '关'}</span>
              </button>
              <div className="flex-1" />
              <button
                onClick={onAbortOrGenerate}
                disabled={isOtherGenerating}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-opacity shrink-0 ${
                  isCurrentlyGenerating
                    ? 'bg-destructive text-destructive-foreground hover:opacity-90'
                    : 'bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50'
                }`}
              >
                {isCurrentlyGenerating
                  ? <><Square className="w-4 h-4" /> 终止</>
                  : isOtherGenerating
                    ? <><Loader2 className="w-4 h-4 animate-spin" /> 其他章节生成中</>
                    : <><Zap className="w-4 h-4" /> 生成章节</>
                }
              </button>
            </div>
          </div>
        </>
      ) : (
        /* ── Rewrite mode ── */
        <div className="space-y-2">
          {/* Annotation list */}
          {annotations.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">批注列表（{annotations.length}）</span>
                <button onClick={onClearAnnotations} className="text-[0.625rem] text-muted-foreground hover:text-destructive">
                  清空全部
                </button>
              </div>
              {annotations.map(a => (
                <div key={a.id} className="flex items-start gap-2 px-2.5 py-1.5 border rounded-lg text-xs group">
                  <span className={`shrink-0 mt-0.5 font-medium ${a.paragraph != null ? 'text-blue-600 dark:text-blue-400' : 'text-amber-600 dark:text-amber-400'}`}>
                    {a.paragraph != null
                      ? (a.paragraph <= CIRCLED_NUMS.length ? `段落${CIRCLED_NUMS[a.paragraph - 1]}` : `段落(${a.paragraph})`)
                      : '全局'}
                  </span>
                  <span className="flex-1 text-foreground">{a.text}</span>
                  <button onClick={() => onRemoveAnnotation(a.id)}
                    className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all shrink-0">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Global annotation input */}
          <div className="flex items-center gap-2">
            <input
              value={globalInput}
              onChange={e => setGlobalInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleAddGlobal() }}
              placeholder="添加全局批注：语气再沉稳些..."
              className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button onClick={handleAddGlobal} disabled={!globalInput.trim()}
              className="text-xs px-3 py-2 border rounded-lg hover:bg-muted disabled:opacity-40 transition-colors">
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Rewrite model selector */}
          {!isCurrentlyGenerating && (
            <div className="flex items-center gap-2">
              <label className="text-xs text-muted-foreground shrink-0">重写模型</label>
              <select
                value={modelSelectValue(modelLibrary, rewriteModel)}
                onChange={e => onRewriteModelChange(e.target.value)}
                className="flex-1 text-xs border rounded-lg px-2 py-1.5 bg-background truncate"
              >
                <option value="">与 Writer 一致{writerModel ? ` (${findModelEntry(modelLibrary, writerModel)?.display_name || writerModel})` : ''}</option>
                {groupModelsByProvider(modelLibrary).map(g => (
                  <optgroup key={g.provider} label={g.provider}>
                    {g.items.map(m => (
                      <option key={m.id} value={String(m.id)}>
                        {m.display_name || m.model_id}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          )}

          {/* Rewrite button */}
          <div className="flex items-center gap-2">
            <div className="flex-1" />
            <button
              onClick={onAbortOrGenerate}
              disabled={isOtherGenerating || (!isCurrentlyGenerating && annotations.length === 0)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-opacity shrink-0 ${
                isCurrentlyGenerating
                  ? 'bg-destructive text-destructive-foreground hover:opacity-90'
                  : 'bg-amber-600 text-white hover:opacity-90 disabled:opacity-50'
              }`}
            >
              {isCurrentlyGenerating
                ? <><Square className="w-4 h-4" /> 终止</>
                : isOtherGenerating
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> 其他章节生成中</>
                  : <><RotateCcw className="w-4 h-4" /> 重写本章（{annotations.length}条批注）</>
              }
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
