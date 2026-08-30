import { Plus, Loader2, Users, Database, MapPin, Swords, Flag, Search, KeyRound } from 'lucide-react'
import type { NewThreadsData } from '@/api/client'

interface NewCharCandidate { name: string; role: string; description: string }
interface NewEntityCandidate { name: string; type: string; description: string }
interface NewLocationCandidate { name: string; type: string; description: string; parent_name: string }
interface NewTechCandidate { name: string; type: string; description: string }
interface NewFactionCandidate { name: string; type: string; description: string }

interface DiscoveryPanelProps {
  newCharCandidates: NewCharCandidate[]
  selectedCharIndices: Set<number>
  addingChars: boolean
  onToggleChar: (i: number) => void
  onAddChars: () => void
  onDismissChars: () => void

  newEntityCandidates: NewEntityCandidate[]
  selectedEntityIndices: Set<number>
  addingEntities: boolean
  onToggleEntity: (i: number) => void
  onAddEntities: () => void
  onDismissEntities: () => void

  newLocationCandidates: NewLocationCandidate[]
  selectedLocationIndices: Set<number>
  addingLocations: boolean
  onToggleLocation: (i: number) => void
  onAddLocations: () => void
  onDismissLocations: () => void

  newTechCandidates: NewTechCandidate[]
  selectedTechIndices: Set<number>
  addingTechs: boolean
  onToggleTech: (i: number) => void
  onAddTechs: () => void
  onDismissTechs: () => void

  newFactionCandidates: NewFactionCandidate[]
  selectedFactionIndices: Set<number>
  addingFactions: boolean
  onToggleFaction: (i: number) => void
  onAddFactions: () => void
  onDismissFactions: () => void

  newThreads: NewThreadsData['threads']
  selectedThreadIndices: Set<number>
  addingThreads: boolean
  onToggleThread: (i: number) => void
  onAddThreads: () => void
  onDismissThreads: () => void
}

export default function DiscoveryPanel({
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
  newFactionCandidates,
  selectedFactionIndices,
  addingFactions,
  onToggleFaction,
  onAddFactions,
  onDismissFactions,
  newThreads,
  selectedThreadIndices,
  addingThreads,
  onToggleThread,
  onAddThreads,
  onDismissThreads,
}: DiscoveryPanelProps) {
  const isEmpty =
    newCharCandidates.length === 0 &&
    newEntityCandidates.length === 0 &&
    newLocationCandidates.length === 0 &&
    newTechCandidates.length === 0 &&
    newFactionCandidates.length === 0 &&
    newThreads.length === 0

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-2 px-4">
        <Search className="w-6 h-6 opacity-30" />
        <p className="text-xs text-center">暂无待确认的内容。生成章节或点击「重新发现」后，新角色、道具、地点、功法、势力会出现在这里；生成时发现的伏笔/秘密也会留在这里等你确认。</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
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

      {/* New Faction Discovery */}
      {newFactionCandidates.length > 0 && (
        <div className="space-y-1.5 border rounded-lg p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <Flag className="w-3 h-3" /> 发现新势力（本章首次出现）
            </span>
            <button onClick={onDismissFactions} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
          </div>
          <div className="flex flex-wrap gap-2">
            {newFactionCandidates.map((f, i) => (
              <button key={i} onClick={() => onToggleFaction(i)}
                className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border transition-colors ${
                  selectedFactionIndices.has(i) ? 'border-primary bg-primary/10 text-primary' : 'border-transparent bg-muted text-muted-foreground'
                }`}>
                <span className="font-medium">{f.name}</span>
                {f.type && <span className="opacity-60">·{f.type}</span>}
              </button>
            ))}
          </div>
          <button onClick={onAddFactions} disabled={addingFactions || selectedFactionIndices.size === 0}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
            {addingFactions ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            添加选中势力（{selectedFactionIndices.size}/{newFactionCandidates.length}）
          </button>
        </div>
      )}

      {/* 伏笔/秘密：正文可能要读完才好判断，所以留在面板里而不是弹窗 */}
      {newThreads.length > 0 && (
        <div className="space-y-1.5 border rounded-lg p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <KeyRound className="w-3 h-3" /> 发现伏笔/秘密（本章新埋下）
            </span>
            <button onClick={onDismissThreads} className="text-xs text-muted-foreground hover:text-foreground px-1">×</button>
          </div>
          <div className="space-y-1.5">
            {newThreads.map((t, i) => (
              <label key={i} className="flex items-start gap-2 rounded-md bg-muted/50 p-2 cursor-pointer hover:bg-muted">
                <input
                  type="checkbox"
                  checked={selectedThreadIndices.has(i)}
                  onChange={() => onToggleThread(i)}
                  className="mt-0.5 shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded ${
                      t.kind === 'secret'
                        ? 'bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300'
                        : 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                    }`}>
                      {t.kind === 'secret' ? '秘密' : '伏笔'}
                    </span>
                    {t.title && <span className="text-xs font-medium truncate">{t.title}</span>}
                    <span className="text-[10px] text-muted-foreground shrink-0 ml-auto">{'★'.repeat(t.importance)}</span>
                  </div>
                  <div className="text-xs text-muted-foreground whitespace-pre-wrap mt-0.5">{t.content}</div>
                  {(t.related_entities?.length ?? 0) > 0 && (
                    <div className="text-[10px] text-muted-foreground mt-0.5">涉及：{t.related_entities!.join('、')}</div>
                  )}
                </div>
              </label>
            ))}
          </div>
          <button onClick={onAddThreads} disabled={addingThreads || selectedThreadIndices.size === 0}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity">
            {addingThreads ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            添加选中伏笔（{selectedThreadIndices.size}/{newThreads.length}）
          </button>
        </div>
      )}
    </div>
  )
}
