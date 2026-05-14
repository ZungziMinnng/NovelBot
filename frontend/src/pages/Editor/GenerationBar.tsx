import { useState, useRef, useCallback } from 'react'
import { Plus, Zap, Loader2, Square, Sparkles, Users, Database, MapPin, Swords, RotateCcw, X, MessageSquareQuote, PenLine } from 'lucide-react'
import AgentStatus from '@/components/AgentStatus/AgentStatus'
import type { Annotation } from '@/store/editorStore'
import type { ModelEntry } from '@/api/client'

interface NewCharCandidate { name: string; role: string; description: string }
interface NewEntityCandidate { name: string; type: string; description: string }
interface NewLocationCandidate { name: string; type: string; description: string; parent_name: string }
interface NewTechCandidate { name: string; type: string; description: string }

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
  onGenerate: () => void
  onAbortOrGenerate: () => void

  // Rewrite
  annotations: Annotation[]
  onRemoveAnnotation: (id: string) => void
  onClearAnnotations: () => void
  onAddGlobalAnnotation: (text: string) => void
  onRewrite: () => void
  rewriteModel: string
  onRewriteModelChange: (v: string) => void
  writerModel: string
  modelLibrary: ModelEntry[]

  // Plot suggestions
  plotSuggestions: string[]
  isLoadingSuggestions: boolean
  onFetchSuggestions: () => void

  // New character discovery
  newCharCandidates: NewCharCandidate[]
  selectedCharIndices: Set<number>
  addingChars: boolean
  onToggleChar: (i: number) => void
  onAddChars: () => void
  onDismissChars: () => void

  // New entity discovery
  newEntityCandidates: NewEntityCandidate[]
  selectedEntityIndices: Set<number>
  addingEntities: boolean
  onToggleEntity: (i: number) => void
  onAddEntities: () => void
  onDismissEntities: () => void

  // New location discovery
  newLocationCandidates: NewLocationCandidate[]
  selectedLocationIndices: Set<number>
  addingLocations: boolean
  onToggleLocation: (i: number) => void
  onAddLocations: () => void
  onDismissLocations: () => void

  // New technique discovery
  newTechCandidates: NewTechCandidate[]
  selectedTechIndices: Set<number>
  addingTechs: boolean
  onToggleTech: (i: number) => void
  onAddTechs: () => void
  onDismissTechs: () => void

  // Entity autocomplete
  entities: EntityItem[]
}

const CIRCLED_NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

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
  onGenerate,
  onAbortOrGenerate,
  annotations,
  onRemoveAnnotation,
  onClearAnnotations,
  onAddGlobalAnnotation,
  onRewrite,
  rewriteModel,
  onRewriteModelChange,
  writerModel,
  modelLibrary,
  plotSuggestions,
  isLoadingSuggestions,
  onFetchSuggestions,
  newCharCandidates,
  selectedCharIndices,
  addingChars,
  onToggleChar,
  onAddChars,
  onDismissChars,
  newEntityCandidates,
  selectedEntityIndices,
  addingEntities,
  onToggleEntity,
  onAddEntities,
  onDismissEntities,
  newLocationCandidates,
  selectedLocationIndices,
  addingLocations,
  onToggleLocation,
  onAddLocations,
  onDismissLocations,
  newTechCandidates,
  selectedTechIndices,
  addingTechs,
  onToggleTech,
  onAddTechs,
  onDismissTechs,
  entities,
}: GenerationBarProps) {
  const [globalInput, setGlobalInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
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
          {/* Plot Suggestions — fetch button only */}
          {justFinishedHere && plotSuggestions.length === 0 && (
            <div className="flex items-center gap-2">
              <button
                onClick={onFetchSuggestions}
                disabled={isLoadingSuggestions}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
              >
                {isLoadingSuggestions
                  ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> 生成建议中...</>
                  : <><Sparkles className="w-3.5 h-3.5" /> 获取下章剧情建议</>
                }
              </button>
            </div>
          )}

          {/* New Character Discovery */}
          {newCharCandidates.length > 0 && (
            <div className="space-y-1.5 border rounded-lg p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Users className="w-3 h-3" /> 发现新角色（本章首次出现）
                </span>
                <button onClick={onDismissChars} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {newCharCandidates.map((c, i) => (
                  <button key={i} onClick={() => onToggleChar(i)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                      selectedCharIndices.has(i) ? 'border-primary bg-primary/10 text-primary' : 'border-transparent bg-muted text-muted-foreground'
                    }`}>
                    <span className="font-medium">{c.name}</span>
                    <span className="opacity-60">·{c.role}</span>
                  </button>
                ))}
              </div>
              <button onClick={onAddChars} disabled={addingChars || selectedCharIndices.size === 0}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
                {addingChars ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                添加选中角色（{selectedCharIndices.size}/{newCharCandidates.length}）
              </button>
            </div>
          )}

          {/* New Entity Discovery */}
          {newEntityCandidates.length > 0 && (
            <div className="space-y-1.5 border rounded-lg p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Database className="w-3 h-3" /> 发现新道具/系统（本章首次出现）
                </span>
                <button onClick={onDismissEntities} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {newEntityCandidates.map((e, i) => (
                  <button key={i} onClick={() => onToggleEntity(i)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                      selectedEntityIndices.has(i) ? 'border-primary bg-primary/10 text-primary' : 'border-transparent bg-muted text-muted-foreground'
                    }`}>
                    <span className="font-medium">{e.name}</span>
                    <span className="opacity-60">·{e.type === 'system' ? '系统' : '道具'}</span>
                  </button>
                ))}
              </div>
              <button onClick={onAddEntities} disabled={addingEntities || selectedEntityIndices.size === 0}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
                {addingEntities ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                添加选中实体（{selectedEntityIndices.size}/{newEntityCandidates.length}）
              </button>
            </div>
          )}

          {/* New Location Discovery */}
          {newLocationCandidates.length > 0 && (
            <div className="space-y-1.5 border rounded-lg p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <MapPin className="w-3 h-3" /> 发现新地点（本章首次出现）
                </span>
                <button onClick={onDismissLocations} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {newLocationCandidates.map((loc, i) => (
                  <button key={i} onClick={() => onToggleLocation(i)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                      selectedLocationIndices.has(i) ? 'border-primary bg-primary/10 text-primary' : 'border-transparent bg-muted text-muted-foreground'
                    }`}>
                    <span className="font-medium">{loc.name}</span>
                    {loc.parent_name && <span className="opacity-60">← {loc.parent_name}</span>}
                  </button>
                ))}
              </div>
              <button onClick={onAddLocations} disabled={addingLocations || selectedLocationIndices.size === 0}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
                {addingLocations ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                添加选中地点（{selectedLocationIndices.size}/{newLocationCandidates.length}）
              </button>
            </div>
          )}

          {/* New Technique Discovery */}
          {newTechCandidates.length > 0 && (
            <div className="space-y-1.5 border rounded-lg p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground flex items-center gap-1">
                  <Swords className="w-3 h-3" /> 发现新功法/武技（本章首次出现）
                </span>
                <button onClick={onDismissTechs} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {newTechCandidates.map((t, i) => (
                  <button key={i} onClick={() => onToggleTech(i)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                      selectedTechIndices.has(i) ? 'border-primary bg-primary/10 text-primary' : 'border-transparent bg-muted text-muted-foreground'
                    }`}>
                    <span className="font-medium">{t.name}</span>
                    <span className="opacity-60">·{t.type}</span>
                  </button>
                ))}
              </div>
              <button onClick={onAddTechs} disabled={addingTechs || selectedTechIndices.size === 0}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
                {addingTechs ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                添加选中功法（{selectedTechIndices.size}/{newTechCandidates.length}）
              </button>
            </div>
          )}

          {/* Instruction + Generate */}
          <div className="flex flex-col gap-2">
            <div className="relative">
              <textarea
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
                rows={3}
                className="w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y min-h-[38px]"
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
                      <span className="shrink-0 text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground">{item.typeLabel}</span>
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
                <option value={2000}>2000字</option>
                <option value={3000}>3000字</option>
                <option value={4000}>4000字</option>
                <option value={5000}>5000字</option>
              </select>
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
                <button onClick={onClearAnnotations} className="text-[10px] text-muted-foreground hover:text-destructive">
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
                value={rewriteModel}
                onChange={e => onRewriteModelChange(e.target.value)}
                className="flex-1 text-xs border rounded-lg px-2 py-1.5 bg-background truncate"
              >
                <option value="">与 Writer 一致{writerModel ? ` (${writerModel})` : ''}</option>
                {modelLibrary.filter(m => m.model_type !== 'embedding').map(m => (
                  <option key={m.model_id} value={m.model_id}>{m.display_name || m.model_id}</option>
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
