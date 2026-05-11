import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, Users, Globe, X, User, ExternalLink } from 'lucide-react'
import type { Chapter, Novel, Character } from '@/api/client'
import { techniquesApi } from '@/api/client'
import ProjectTab from './sidebar/ProjectTab'
import CharacterTab from './sidebar/CharacterTab'
import WorldTab, {
  WORLD_CATEGORIES,
  WorldSettingView, LocationsView, EntitiesView, NotesView, TimelineView,
} from './sidebar/WorldTab'
import FactionsView from './sidebar/FactionsView'
import TechniquesView, { TechniqueDetail } from './sidebar/TechniquesView'
import RelationshipGraphView from './sidebar/RelationshipGraphView'
import CharacterEditPanel from './sidebar/CharacterEditPanel'
import EntityDetailPanel, { NoteDetailPanel, LocationDetailPanel } from './sidebar/EntityDetailPanel'

type Tab = 'project' | 'characters' | 'world'

type DetailView =
  | { type: 'world'; key: string }
  | { type: 'character'; characterId: number; characterName: string }

type EntitySelection =
  | { kind: 'entity'; id: number }
  | { kind: 'technique'; id: number }
  | { kind: 'note'; id: number }
  | { kind: 'location'; id: number }

const TABS: { key: Tab; label: string; icon: React.ElementType }[] = [
  { key: 'project', label: '项目', icon: FolderOpen },
  { key: 'characters', label: '角色', icon: Users },
  { key: 'world', label: '世界', icon: Globe },
]

interface Props {
  novelId: number
  novel: Novel | undefined
  chapters: Chapter[]
  selectedChapterNum: number
  isGenerating: boolean
  generatingNovelId: number | null
  generatingChapterNum: number | null
  onSelectChapter: (num: number) => void
  onNewChapter: () => void
  onOpenSettings: () => void
}

export default function EditorSidebar({
  novelId,
  novel,
  chapters,
  selectedChapterNum,
  isGenerating,
  generatingNovelId,
  generatingChapterNum,
  onSelectChapter,
  onNewChapter,
  onOpenSettings,
}: Props) {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<Tab>('project')
  const [detailView, setDetailView] = useState<DetailView | null>(null)
  const [entitySelection, setEntitySelection] = useState<EntitySelection | null>(null)
  const [sidebarWidth, setSidebarWidth] = useState(256)
  const [panelWidth, setPanelWidth] = useState(420)
  const [entityPanelWidth, setEntityPanelWidth] = useState(420)
  const dragRef = useRef({ startX: 0, startW: 0 })

  const createResizeHandler = useCallback((setter: React.Dispatch<React.SetStateAction<number>>, min: number, max: number) => {
    return (e: React.MouseEvent) => {
      e.preventDefault()
      const el = e.currentTarget.parentElement!
      dragRef.current = { startX: e.clientX, startW: el.offsetWidth }
      const onMove = (ev: MouseEvent) => {
        setter(Math.max(min, Math.min(max, dragRef.current.startW + ev.clientX - dragRef.current.startX)))
      }
      const onUp = () => {
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    }
  }, [])

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    setDetailView(null)
    setEntitySelection(null)
  }

  const handleOpenWorldDetail = (key: string) => {
    if (detailView?.type === 'world' && detailView.key === key) {
      setDetailView(null)
    } else {
      setDetailView({ type: 'world', key })
    }
    setEntitySelection(null)
  }

  const handleOpenCharacter = (c: Character) => {
    if (detailView?.type === 'character' && detailView.characterId === c.id) {
      setDetailView(null)
    } else {
      setDetailView({ type: 'character', characterId: c.id, characterName: c.name })
    }
    setEntitySelection(null)
  }

  const entityType: 'item' | 'system' | null =
    detailView?.type === 'world' && detailView.key === 'items' ? 'item'
    : detailView?.type === 'world' && detailView.key === 'systems' ? 'system'
    : null

  const { data: techniques = [] } = useQuery({
    queryKey: ['techniques', novelId],
    queryFn: () => techniquesApi.list(novelId),
    enabled: entitySelection?.kind === 'technique',
  })
  const selectedTechnique = entitySelection?.kind === 'technique'
    ? techniques.find(t => t.id === entitySelection.id) ?? null
    : null

  let DetailIcon: React.ElementType = Globe
  let detailTitle = ''
  let detailColor = ''
  if (detailView?.type === 'world') {
    const cat = WORLD_CATEGORIES.find((c) => c.key === detailView.key)
    if (cat) {
      DetailIcon = cat.icon
      detailTitle = cat.label
      detailColor = cat.color
    }
  } else if (detailView?.type === 'character') {
    DetailIcon = User
    detailTitle = detailView.characterName
  }

  const detailLink =
    detailView?.type === 'world' && detailView.key === 'locations' ? `/novel/${novelId}/locations`
    : detailView?.type === 'world' && detailView.key === 'notes' ? `/novel/${novelId}/notes`
    : detailView?.type === 'world' && detailView.key === 'items' ? `/novel/${novelId}/characters?tab=item`
    : detailView?.type === 'world' && detailView.key === 'systems' ? `/novel/${novelId}/characters?tab=system`
    : detailView?.type === 'character' ? `/novel/${novelId}/characters`
    : null

  return (
    <div className="flex shrink-0 h-full">
      {/* Sidebar */}
      <div className="border-r flex flex-col relative" style={{ width: sidebarWidth }}>
        {/* Tab bar */}
        <div className="flex border-b shrink-0">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => handleTabChange(key)}
              className={`flex-1 flex items-center justify-center gap-1 py-2.5 text-xs font-medium transition-colors ${
                activeTab === key
                  ? 'text-primary border-b-2 border-primary'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden">
          {activeTab === 'project' && (
            <ProjectTab
              novelId={novelId}
              novel={novel}
              chapters={chapters}
              selectedChapterNum={selectedChapterNum}
              isGenerating={isGenerating}
              generatingNovelId={generatingNovelId}
              generatingChapterNum={generatingChapterNum}
              onSelectChapter={onSelectChapter}
              onNewChapter={onNewChapter}
            />
          )}
          {activeTab === 'characters' && (
            <CharacterTab
              novelId={novelId}
              onOpenCharacter={handleOpenCharacter}
              activeCharacterId={detailView?.type === 'character' ? detailView.characterId : null}
              drawerOffsetLeft={sidebarWidth}
            />
          )}
          {activeTab === 'world' && (
            <WorldTab
              novelId={novelId}
              novel={novel}
              onOpenSettings={onOpenSettings}
              onOpenDetail={handleOpenWorldDetail}
              activeDetailKey={detailView?.type === 'world' ? detailView.key : null}
            />
          )}
        </div>
        {/* Resize handle */}
        <div
          onMouseDown={createResizeHandler(setSidebarWidth, 200, 400)}
          className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
        />
      </div>

      {/* Detail Panel */}
      {detailView && (
        <div className="border-r flex flex-col bg-background relative" style={{ width: panelWidth }}>
          <div className="flex items-center gap-2 px-3 py-2.5 border-b shrink-0">
            <DetailIcon className={`w-4 h-4 ${detailColor}`} />
            <span className="text-sm font-medium flex-1 truncate">{detailTitle}</span>
            {detailLink && (
              <button onClick={() => navigate(detailLink)} className="p-1 rounded hover:bg-muted" title="打开详情页">
                <ExternalLink className="w-3.5 h-3.5" />
              </button>
            )}
            <button onClick={() => { setDetailView(null); setEntitySelection(null) }} className="p-1 rounded hover:bg-muted">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {detailView.type === 'world' && (
              <>
                {detailView.key === 'world_setting' && <WorldSettingView novel={novel} onEdit={onOpenSettings} />}
                {detailView.key === 'locations' && (
                  <LocationsView novelId={novelId}
                    onSelectLocation={(id) => setEntitySelection({ kind: 'location', id })}
                    selectedLocationId={entitySelection?.kind === 'location' ? entitySelection.id : null}
                  />
                )}
                {detailView.key === 'items' && (
                  <EntitiesView novelId={novelId} type="item"
                    onSelectEntity={(id) => setEntitySelection({ kind: 'entity', id })}
                    selectedEntityId={entitySelection?.kind === 'entity' ? entitySelection.id : null}
                  />
                )}
                {detailView.key === 'systems' && (
                  <EntitiesView novelId={novelId} type="system"
                    onSelectEntity={(id) => setEntitySelection({ kind: 'entity', id })}
                    selectedEntityId={entitySelection?.kind === 'entity' ? entitySelection.id : null}
                  />
                )}
                {detailView.key === 'factions' && <FactionsView novelId={novelId} />}
                {detailView.key === 'techniques' && (
                  <TechniquesView novelId={novelId}
                    onSelectTechnique={(id) => setEntitySelection({ kind: 'technique', id })}
                    selectedTechniqueId={entitySelection?.kind === 'technique' ? entitySelection.id : null}
                  />
                )}
                {detailView.key === 'notes' && (
                  <NotesView novelId={novelId}
                    onSelectNote={(id) => setEntitySelection({ kind: 'note', id })}
                    selectedNoteId={entitySelection?.kind === 'note' ? entitySelection.id : null}
                  />
                )}
                {detailView.key === 'timeline' && <TimelineView novelId={novelId} />}
                {detailView.key === 'relationships' && (
                  <RelationshipGraphView
                    novelId={novelId}
                    onSelectCharacter={(id, name) =>
                      setDetailView({ type: 'character', characterId: id, characterName: name })
                    }
                  />
                )}
              </>
            )}
            {detailView.type === 'character' && (
              <CharacterEditPanel
                characterId={detailView.characterId}
                novelId={novelId}
                onClose={() => setDetailView(null)}
              />
            )}
          </div>
          {/* Resize handle */}
          <div
            onMouseDown={createResizeHandler(setPanelWidth, 320, 640)}
            className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
          />
        </div>
      )}

      {/* Entity Detail Panel (third column) */}
      {entitySelection && (
        <div className="border-r flex flex-col bg-background relative" style={{ width: entityPanelWidth }}>
          <div className="flex items-center gap-2 px-3 py-2.5 border-b shrink-0">
            <span className="text-sm font-medium flex-1 truncate">
              {entitySelection.kind === 'entity' ? (entityType === 'item' ? '道具详情' : '系统详情')
                : entitySelection.kind === 'technique' ? '功法详情'
                : entitySelection.kind === 'location' ? '地点详情'
                : '设定详情'}
            </span>
            <button onClick={() => setEntitySelection(null)} className="p-1 rounded hover:bg-muted">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {entitySelection.kind === 'entity' && entityType && (
              <EntityDetailPanel
                entityId={entitySelection.id}
                novelId={novelId}
                entityType={entityType}
                onClose={() => setEntitySelection(null)}
              />
            )}
            {entitySelection.kind === 'technique' && selectedTechnique && (
              <TechniqueDetail
                technique={selectedTechnique}
                novelId={novelId}
                onClose={() => setEntitySelection(null)}
              />
            )}
            {entitySelection.kind === 'note' && (
              <NoteDetailPanel
                noteId={entitySelection.id}
                novelId={novelId}
                onClose={() => setEntitySelection(null)}
              />
            )}
            {entitySelection.kind === 'location' && (
              <LocationDetailPanel
                locationId={entitySelection.id}
                novelId={novelId}
                onClose={() => setEntitySelection(null)}
              />
            )}
          </div>
          <div
            onMouseDown={createResizeHandler(setEntityPanelWidth, 320, 640)}
            className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
          />
        </div>
      )}
    </div>
  )
}
