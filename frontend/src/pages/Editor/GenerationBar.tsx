import { Plus, Zap, Loader2, Square, Sparkles, Users, Database } from 'lucide-react'
import AgentStatus from '@/components/AgentStatus/AgentStatus'

interface NewCharCandidate { name: string; role: string; description: string }
interface NewEntityCandidate { name: string; type: string; description: string }

interface GenerationBarProps {
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
}

export default function GenerationBar({
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
}: GenerationBarProps) {
  return (
    <div className="border-t px-4 py-3 shrink-0 space-y-2">
      <AgentStatus stage={agentStage} visible={isCurrentlyGenerating} />

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
            <button
              onClick={onDismissChars}
              className="text-xs text-muted-foreground hover:text-foreground px-1"
            >
              ×
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {newCharCandidates.map((c, i) => (
              <button
                key={i}
                onClick={() => onToggleChar(i)}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                  selectedCharIndices.has(i)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-transparent bg-muted text-muted-foreground'
                }`}
              >
                <span className="font-medium">{c.name}</span>
                <span className="opacity-60">·{c.role}</span>
              </button>
            ))}
          </div>
          <button
            onClick={onAddChars}
            disabled={addingChars || selectedCharIndices.size === 0}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
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
            <button
              onClick={onDismissEntities}
              className="text-xs text-muted-foreground hover:text-foreground px-1"
            >
              ×
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {newEntityCandidates.map((e, i) => (
              <button
                key={i}
                onClick={() => onToggleEntity(i)}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                  selectedEntityIndices.has(i)
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-transparent bg-muted text-muted-foreground'
                }`}
              >
                <span className="font-medium">{e.name}</span>
                <span className="opacity-60">·{e.type === 'system' ? '系统' : '道具'}</span>
              </button>
            ))}
          </div>
          <button
            onClick={onAddEntities}
            disabled={addingEntities || selectedEntityIndices.size === 0}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {addingEntities ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            添加选中实体（{selectedEntityIndices.size}/{newEntityCandidates.length}）
          </button>
        </div>
      )}

      {/* Instruction + Generate */}
      <div className="flex flex-col gap-2">
        <textarea
          value={instruction}
          onChange={e => onInstructionChange(e.target.value)}
          placeholder="生成指令（可选）：重点描写心理活动..."
          rows={3}
          className="w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y min-h-[38px]"
        />
        <div className="flex items-center gap-2">
          <select
            value={targetWords}
            onChange={e => onTargetWordsChange(Number(e.target.value))}
            className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none"
          >
            <option value={500}>500字</option>
            <option value={800}>800字</option>
            <option value={1200}>1200字</option>
            <option value={2000}>2000字</option>
            <option value={3000}>3000字</option>
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
    </div>
  )
}
