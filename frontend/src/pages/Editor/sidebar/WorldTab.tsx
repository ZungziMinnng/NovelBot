import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Globe, MapPin, Sword, Cog, FileText, Clock, Shield, Zap, Network, History, BookOpen,
  Plus, Trash2, Loader2, RefreshCw, ChevronRight, ChevronDown, Sparkles, Save, Check, X,
  ScrollText, Gem,
  Eye, Flag,
} from 'lucide-react'
import {
  novelsApi, locationsApi, worldEntitiesApi, novelNotesApi, chaptersApi, worldviewChangesApi, glossaryApi, worldRulesApi, storyThreadsApi,
  type Novel, type Location, type Chapter, type GlossaryEntry, type WorldRule, type StoryThread, type StoryThreadKind, type StoryThreadStatus,
  type StaleThreadReport,
} from '@/api/client'
import ImportanceSelect from '@/components/ImportanceSelect'
import AutoTextarea from '@/components/AutoTextarea'
import toast from 'react-hot-toast'

// group: 按内容性质分组；badge: 生成时的注入行为（每章注入/检索注入/按需选取/视图）
export const WORLD_CATEGORIES: { key: string; label: string; icon: React.ElementType; color: string; group: string; badge: string }[] = [
  { key: 'world_setting', label: '世界观', icon: Globe, color: 'text-blue-500', group: 'foundation', badge: '检索注入' },
  { key: 'core_rules', label: '核心规则', icon: ScrollText, color: 'text-red-500', group: 'foundation', badge: '每章注入' },
  { key: 'glossary', label: '用词库', icon: BookOpen, color: 'text-indigo-500', group: 'foundation', badge: '每章注入' },
  { key: 'special_elements', label: '特殊元素', icon: Gem, color: 'text-fuchsia-500', group: 'library', badge: '按需选取' },
  { key: 'locations', label: '地点', icon: MapPin, color: 'text-green-500', group: 'library', badge: '按需选取' },
  { key: 'items', label: '道具', icon: Sword, color: 'text-amber-500', group: 'library', badge: '按需选取' },
  { key: 'systems', label: '系统', icon: Cog, color: 'text-purple-500', group: 'library', badge: '按需选取' },
  { key: 'factions', label: '势力', icon: Shield, color: 'text-violet-500', group: 'library', badge: '按需选取' },
  { key: 'techniques', label: '功法', icon: Zap, color: 'text-orange-500', group: 'library', badge: '按需选取' },
  { key: 'notes', label: '补充设定', icon: FileText, color: 'text-cyan-500', group: 'library', badge: '按需选取' },
  { key: 'story_threads', label: '伏笔/秘密', icon: Eye, color: 'text-yellow-600', group: 'memory', badge: '每章注入' },
  { key: 'worldview_changes', label: '世界观变更', icon: History, color: 'text-teal-500', group: 'memory', badge: '每章注入' },
  { key: 'timeline', label: '时间线', icon: Clock, color: 'text-rose-500', group: 'memory', badge: '视图' },
  { key: 'relationships', label: '关系网', icon: Network, color: 'text-pink-500', group: 'view', badge: '视图' },
]

const WORLD_GROUPS: { key: string; title: string }[] = [
  { key: 'foundation', title: '世界基石' },
  { key: 'library', title: '设定库' },
  { key: 'memory', title: '剧情记忆' },
  { key: 'view', title: '关系视图' },
]

interface Props {
  novelId: number
  novel: Novel | undefined
  onOpenSettings: () => void
  onOpenDetail: (key: string) => void
  activeDetailKey?: string | null
}

export default function WorldTab({ onOpenDetail, activeDetailKey }: Props) {
  return (
    <div className="p-3">
      <p className="text-xs font-medium text-muted-foreground mb-3 uppercase tracking-wide">世界素材</p>
      <div className="space-y-4">
        {WORLD_GROUPS.map(({ key: groupKey, title }) => (
          <div key={groupKey}>
            <p className="text-[0.6875rem] text-muted-foreground mb-1.5">{title}</p>
            <div className="grid grid-cols-2 gap-2">
              {WORLD_CATEGORIES.filter((c) => c.group === groupKey).map(({ key, label, icon: Icon, color, badge }) => (
                <button
                  key={key}
                  onClick={() => onOpenDetail(key)}
                  className={`flex flex-col items-center gap-1 p-3 rounded-lg border hover:bg-muted transition-colors ${
                    activeDetailKey === key ? 'bg-muted border-primary' : ''
                  }`}
                >
                  <Icon className={`w-5 h-5 ${color}`} />
                  <span className="text-xs font-medium">{label}</span>
                  <span className="text-[0.625rem] text-muted-foreground">{badge}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Sub-views (rendered in detail panel) ──────────────────────────────────

interface WorldSections {
  background: string
  rules: string
  elements: string
  notes: string
}

function parseWorldSections(text: string): WorldSections {
  const sections: WorldSections = { background: '', rules: '', elements: '', notes: '' }
  if (!text) return sections

  const sectionMap: Record<string, keyof WorldSections> = {
    '时代背景': 'background',
    '核心规则': 'rules',
    '特殊元素': 'elements',
    '补充备注': 'notes',
  }

  const regex = /^##\s+(.+)$/gm
  const matches = [...text.matchAll(regex)]

  if (matches.length === 0) {
    sections.background = text.trim()
    return sections
  }

  for (let i = 0; i < matches.length; i++) {
    const heading = matches[i][1].trim()
    const start = matches[i].index! + matches[i][0].length
    const end = i + 1 < matches.length ? matches[i + 1].index! : text.length
    const content = text.slice(start, end).trim()
    const key = sectionMap[heading]
    if (key) sections[key] = content
  }

  return sections
}

function mergeWorldSections(s: WorldSections): string {
  const parts: string[] = []
  if (s.background.trim()) parts.push(`## 时代背景\n${s.background.trim()}`)
  if (s.rules.trim()) parts.push(`## 核心规则\n${s.rules.trim()}`)
  if (s.elements.trim()) parts.push(`## 特殊元素\n${s.elements.trim()}`)
  if (s.notes.trim()) parts.push(`## 补充备注\n${s.notes.trim()}`)
  return parts.join('\n\n')
}

export function WorldSettingView({ novel, onEdit }: { novel: Novel | undefined; onEdit: () => void }) {
  const qc = useQueryClient()
  const [sections, setSections] = useState<WorldSections>({ background: '', rules: '', elements: '', notes: '' })
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [optimizing, setOptimizing] = useState<string | null>(null)
  const [notesExpanded, setNotesExpanded] = useState(false)

  useEffect(() => {
    if (novel?.core_setting != null) {
      setSections(parseWorldSections(novel.core_setting))
      setDirty(false)
    }
  }, [novel?.core_setting])

  const updateSection = useCallback((key: keyof WorldSections, value: string) => {
    setSections(prev => ({ ...prev, [key]: value }))
    setDirty(true)
  }, [])

  const handleSave = async () => {
    if (!novel) return
    setSaving(true)
    try {
      await novelsApi.update(novel.id, { core_setting: mergeWorldSections(sections) })
      qc.invalidateQueries({ queryKey: ['novel', novel.id] })
      setDirty(false)
      toast.success('世界观已保存')
    } catch { toast.error('保存失败') }
    finally { setSaving(false) }
  }

  const sectionLabels: Record<keyof WorldSections, string> = {
    background: '时代背景',
    rules: '核心规则',
    elements: '特殊元素',
    notes: '补充备注',
  }

  const handleOptimize = async (sectionKey: keyof WorldSections) => {
    if (!novel) return
    const sectionText = sections[sectionKey]
    const isGenerate = !sectionText.trim()
    setOptimizing(sectionKey)
    try {
      const result = await novelsApi.optimizeWorld(novel.id, sectionText, sectionLabels[sectionKey])
      updateSection(sectionKey, result.core_setting)
      toast.success(isGenerate ? 'AI 生成完成' : 'AI 优化完成')
    } catch { toast.error(isGenerate ? 'AI 生成失败' : 'AI 优化失败') }
    finally { setOptimizing(null) }
  }

  if (!novel) return <p className="text-xs text-muted-foreground text-center py-6">加载中...</p>

  const cardClass = "border rounded-lg p-3 space-y-2"

  return (
    <div className="p-3 space-y-4 max-h-[70vh] overflow-y-auto">
      {/* 时代背景 */}
      <div className={cardClass}>
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-medium">时代背景</h4>
          <button
            onClick={() => handleOptimize('background')}
            disabled={optimizing === 'background'}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-md text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
          >
            {optimizing === 'background' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
            {sections.background.trim() ? 'AI 优化' : 'AI 生成'}
          </button>
        </div>
        <AutoTextarea
          value={sections.background}
          onChange={e => updateSection('background', e.target.value)}
          placeholder="描述时代与地理、政治格局、社会阶层..."
          className="w-full border rounded-md p-2 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
      </div>

      {/* 核心规则 / 特殊元素已迁至独立结构化列表（左侧「核心规则」「特殊元素」类目管理） */}
      <p className="text-[0.6875rem] text-muted-foreground px-1">
        核心规则、特殊元素现由左侧「核心规则」「特殊元素」类目以条目形式管理。
      </p>

      {/* 补充备注 */}
      <div className="border rounded-lg">
        <button
          onClick={() => setNotesExpanded(!notesExpanded)}
          className="w-full flex items-center justify-between px-3 py-2 text-sm hover:bg-muted/50 transition-colors"
        >
          <span className="font-medium text-sm">补充备注</span>
          <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${notesExpanded ? 'rotate-180' : ''}`} />
        </button>
        {notesExpanded && (
          <div className="px-3 pb-3">
            <AutoTextarea
              value={sections.notes}
              onChange={e => updateSection('notes', e.target.value)}
              placeholder="其他需要补充的设定信息..."
              className="w-full border rounded-md p-2 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        )}
      </div>

      {/* 保存按钮 */}
      <div className="flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={!dirty || saving}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium"
        >
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          保存世界观
        </button>
        <button
          onClick={onEdit}
          className="px-3 py-2 text-sm border rounded-lg hover:bg-muted transition-colors"
        >
          源文本
        </button>
      </div>
    </div>
  )
}

// ── Location tree helpers ─────────────────────────────────────────────────

type LocationNode = Location & { children: LocationNode[] }

function buildLocationTree(locations: Location[]): LocationNode[] {
  const map = new Map<number, LocationNode>()
  const roots: LocationNode[] = []
  for (const loc of locations) map.set(loc.id, { ...loc, children: [] })
  for (const loc of locations) {
    const node = map.get(loc.id)!
    if (loc.parent_id && map.has(loc.parent_id)) {
      map.get(loc.parent_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }
  return roots
}

const LOC_TYPE_LABELS: Record<string, string> = {
  world: '世界', continent: '大陆', region: '地区', city: '城市',
  building: '建筑', landmark: '地标', other: '其他',
}

const LOC_TYPE_COLORS: Record<string, string> = {
  world: 'bg-blue-500/20 text-blue-400',
  continent: 'bg-amber-500/20 text-amber-400',
  region: 'bg-purple-500/20 text-purple-400',
  city: 'bg-sky-500/20 text-sky-400',
  building: 'bg-green-500/20 text-green-400',
  landmark: 'bg-rose-500/20 text-rose-400',
  other: 'bg-gray-500/20 text-gray-400',
}

const LOC_TYPES = ['world', 'continent', 'region', 'city', 'building', 'landmark', 'other']

function LocationTreeNode({ node, depth, onSelect, selectedId, onDelete }: {
  node: LocationNode
  depth: number
  onSelect: (id: number) => void
  selectedId?: number | null
  onDelete: (e: React.MouseEvent, id: number) => void
}) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = node.children.length > 0

  return (
    <>
      <div
        className={`group flex items-center gap-1 py-1.5 pr-2 rounded cursor-pointer transition-colors ${
          selectedId === node.id ? 'bg-muted ring-1 ring-primary' : 'hover:bg-muted'
        }`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => onSelect(node.id)}
      >
        {hasChildren ? (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
            className="p-0.5 rounded hover:bg-muted-foreground/10 shrink-0"
          >
            <ChevronRight className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <MapPin className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        <span className="text-sm truncate flex-1 min-w-0">{node.name}</span>
        <span className={`text-[0.625rem] px-1.5 py-px rounded shrink-0 ${LOC_TYPE_COLORS[node.type] || LOC_TYPE_COLORS.other}`}>
          {LOC_TYPE_LABELS[node.type] || node.type}
        </span>
        {hasChildren && (
          <span className="text-[0.625rem] text-muted-foreground shrink-0">({node.children.length})</span>
        )}
        <button
          onClick={(e) => onDelete(e, node.id)}
          className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-opacity shrink-0"
        >
          <Trash2 className="w-3 h-3" />
        </button>
      </div>
      {expanded && node.children.map((child) => (
        <LocationTreeNode key={child.id} node={child} depth={depth + 1} onSelect={onSelect} selectedId={selectedId} onDelete={onDelete} />
      ))}
    </>
  )
}

export function LocationsView({ novelId, onSelectLocation, selectedLocationId }: {
  novelId: number
  onSelectLocation?: (id: number) => void
  selectedLocationId?: number | null
}) {
  const qc = useQueryClient()
  const { data: locations = [] } = useQuery({
    queryKey: ['locations', novelId],
    queryFn: () => locationsApi.list(novelId),
  })
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ name: '', type: 'city', description: '', parent_id: null as number | null })

  const tree = buildLocationTree(locations)

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await locationsApi.create({ ...form, novel_id: novelId })
      qc.invalidateQueries({ queryKey: ['locations', novelId] })
      setAdding(false)
      setForm({ name: '', type: 'city', description: '', parent_id: null })
    } finally { setSaving(false) }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除？')) return
    await locationsApi.delete(id)
    qc.invalidateQueries({ queryKey: ['locations', novelId] })
  }

  return (
    <div className="p-2">
      <div className="flex items-center justify-between px-1 pb-2">
        <span className="text-xs text-muted-foreground">地图层级 · {locations.length}</span>
        <button
          onClick={() => { setAdding(true); setForm({ name: '', type: 'city', description: '', parent_id: null }) }}
          className="flex items-center gap-1 text-xs px-2 py-1 text-primary hover:bg-muted rounded transition-colors"
        >
          <Plus className="w-3 h-3" /> 新建
        </button>
      </div>

      {tree.map((node) => (
        <LocationTreeNode key={node.id} node={node} depth={0} onSelect={(id) => onSelectLocation?.(id)} selectedId={selectedLocationId} onDelete={handleDelete} />
      ))}

      {locations.length === 0 && !adding && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无地点</p>
      )}

      {adding && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建地点</h3>
            <input
              placeholder="地点名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <select
              value={form.type}
              onChange={(e) => setForm({ ...form, type: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            >
              {LOC_TYPES.map((t) => <option key={t} value={t}>{LOC_TYPE_LABELS[t]}</option>)}
            </select>
            <select
              value={form.parent_id ?? ''}
              onChange={(e) => setForm({ ...form, parent_id: e.target.value ? Number(e.target.value) : null })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            >
              <option value="">无上级地点</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>{l.name}</option>
              ))}
            </select>
            <AutoTextarea
              placeholder="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setAdding(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function EntitiesView({ novelId, type, onSelectEntity, selectedEntityId }: {
  novelId: number; type: 'item' | 'system'
  onSelectEntity?: (id: number) => void
  selectedEntityId?: number | null
}) {
  const qc = useQueryClient()
  const queryKey = ['entities', novelId, type]
  const { data: entities = [] } = useQuery({
    queryKey,
    queryFn: () => worldEntitiesApi.list(novelId, type),
  })
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ name: '', description: '' })

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await worldEntitiesApi.create({ ...form, type, novel_id: novelId })
      qc.invalidateQueries({ queryKey })
      setAdding(false)
      setForm({ name: '', description: '' })
    } finally { setSaving(false) }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除？')) return
    await worldEntitiesApi.delete(id)
    qc.invalidateQueries({ queryKey })
  }

  const Icon = type === 'item' ? Sword : Cog
  const label = type === 'item' ? '道具' : '系统'

  return (
    <div className="p-2 space-y-1">
      <div className="px-1 pb-1">
        <button
          onClick={() => { setAdding(true); setForm({ name: '', description: '' }) }}
          className="w-full flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted"
        >
          <Plus className="w-3 h-3" /> 新建{label}
        </button>
      </div>
      {entities.map((ent) => (
        <div
          key={ent.id}
          onClick={() => onSelectEntity?.(ent.id)}
          className={`group flex items-start gap-2 px-2 py-2 rounded-lg cursor-pointer transition-colors relative ${
            selectedEntityId === ent.id ? 'bg-muted ring-1 ring-primary' : 'hover:bg-muted'
          }`}
        >
          <Icon className="w-3.5 h-3.5 mt-0.5 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium truncate block">{ent.name}</span>
            {ent.description && (
              <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">{ent.description}</p>
            )}
          </div>
          <button onClick={(e) => handleDelete(e, ent.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
      {entities.length === 0 && !adding && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无{label}</p>
      )}

      {adding && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建{label}</h3>
            <input
              placeholder="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <AutoTextarea
              placeholder="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setAdding(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function NotesView({ novelId, onSelectNote, selectedNoteId, onNewNote }: {
  novelId: number
  onSelectNote?: (id: number) => void
  selectedNoteId?: number | null
  onNewNote?: () => void
}) {
  const qc = useQueryClient()
  const { data: notes = [] } = useQuery({
    queryKey: ['notes', novelId],
    queryFn: () => novelNotesApi.list(novelId),
  })

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除？')) return
    await novelNotesApi.delete(id)
    qc.invalidateQueries({ queryKey: ['notes', novelId] })
  }

  return (
    <div className="p-2 space-y-1">
      <div className="px-1 pb-1">
        <button
          onClick={() => onNewNote?.()}
          className="w-full flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted"
        >
          <Plus className="w-3 h-3" /> 新建设定
        </button>
      </div>
      {notes.map((note) => (
        <div
          key={note.id}
          onClick={() => onSelectNote?.(note.id)}
          className={`group flex items-start gap-2 px-2 py-2 rounded-lg cursor-pointer transition-colors ${
            selectedNoteId === note.id ? 'bg-muted ring-1 ring-primary' : 'hover:bg-muted'
          }`}
        >
          <FileText className="w-3.5 h-3.5 mt-0.5 text-muted-foreground shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium truncate block">{note.title}</span>
            {note.content && (
              <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{note.content}</p>
            )}
          </div>
          <button onClick={(e) => handleDelete(e, note.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
      {notes.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无补充设定</p>
      )}
    </div>
  )
}

interface GlossaryForm { term: string; category: string; forbidden_variants: string; notes: string; importance: number }

export function GlossaryView({ novelId }: { novelId: number }) {
  const qc = useQueryClient()
  const { data: entries = [] } = useQuery({
    queryKey: ['glossary', novelId],
    queryFn: () => glossaryApi.list(novelId),
  })
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<GlossaryForm>({ term: '', category: '自定义', forbidden_variants: '', notes: '', importance: 3 })
  const GLOSSARY_CATEGORIES = ['描写用词', '人名', '地名', '功法', '丹药', '武器', '常用词', '禁忌词', '自定义']

  const resetForm = () => {
    setForm({ term: '', category: '自定义', forbidden_variants: '', notes: '', importance: 3 })
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (entry: GlossaryEntry) => {
    setEditingId(entry.id)
    setForm({ term: entry.term, category: entry.category, forbidden_variants: entry.forbidden_variants, notes: entry.notes, importance: entry.importance })
    setShowForm(true)
  }

  const handleSubmit = async () => {
    if (!form.term.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await glossaryApi.update(editingId, {
          term: form.term.trim(), category: form.category,
          forbidden_variants: form.forbidden_variants, notes: form.notes,
        })
      } else {
        await glossaryApi.create({
          novel_id: novelId, term: form.term.trim(), category: form.category,
          forbidden_variants: form.forbidden_variants, notes: form.notes,
        })
      }
      qc.invalidateQueries({ queryKey: ['glossary', novelId] })
      resetForm()
    } finally { setSaving(false) }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除？')) return
    await glossaryApi.delete(id)
    qc.invalidateQueries({ queryKey: ['glossary', novelId] })
  }

  return (
    <div className="p-2 space-y-1">
      {!showForm && (
        <div className="px-1 pb-1">
          <button
            onClick={() => setShowForm(true)}
            className="w-full flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted"
          >
            <Plus className="w-3 h-3" /> 添加词条
          </button>
        </div>
      )}

      {showForm && (
        <div className="border rounded-lg p-3 bg-muted/20 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">{editingId ? '编辑词条' : '添加词条'}</span>
            <button onClick={resetForm} className="p-0.5 rounded hover:bg-muted"><X className="w-3.5 h-3.5" /></button>
          </div>
          <div className="flex gap-2">
            <input value={form.term} onChange={e => setForm({ ...form, term: e.target.value })}
              placeholder="指定用词 *"
              className="flex-1 border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
            <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}
              className="w-20 border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring">
              {GLOSSARY_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <input value={form.forbidden_variants} onChange={e => setForm({ ...form, forbidden_variants: e.target.value })}
            placeholder="禁用词汇（逗号分隔，如：消炎、萧言）"
            className="w-full border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
          <input value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })}
            placeholder="说明（可选），如：描绘灵魂时使用"
            className="w-full border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
          <div className="flex justify-end gap-2">
            <button onClick={resetForm} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
            <button onClick={handleSubmit} disabled={!form.term.trim() || saving}
              className="text-xs px-3 py-1 bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50">
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : editingId ? '保存' : '添加'}
            </button>
          </div>
        </div>
      )}

      {entries.map((entry) => (
        <div key={entry.id} onClick={() => startEdit(entry)}
          className="group flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-muted cursor-pointer">
          <BookOpen className="w-3.5 h-3.5 mt-0.5 text-indigo-500 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium truncate">{entry.term}</span>
              <span className="text-[0.625rem] px-1 py-0.5 rounded bg-muted text-muted-foreground shrink-0">{entry.category}</span>
            </div>
            {entry.forbidden_variants && (
              <p className="text-[0.6875rem] text-red-600 dark:text-red-400 mt-0.5">
                禁止：{entry.forbidden_variants}
              </p>
            )}
            {entry.notes && (
              <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{entry.notes}</p>
            )}
          </div>
          <button onClick={(e) => handleDelete(e, entry.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
      {entries.length === 0 && !showForm && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无用词规范</p>
      )}
    </div>
  )
}

interface WorldRuleForm { title: string; content: string; importance: number; enabled: boolean }

export function WorldRulesView({ novelId, kind }: { novelId: number; kind: 'rule' | 'element' }) {
  const qc = useQueryClient()
  const queryKey = ['world-rules', novelId, kind]
  const { data: rules = [] } = useQuery({
    queryKey,
    queryFn: () => worldRulesApi.list(novelId, kind),
  })
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<WorldRuleForm>({ title: '', content: '', importance: 3, enabled: true })

  const label = kind === 'rule' ? '核心规则' : '特殊元素'
  const placeholder = kind === 'rule'
    ? '规则内容，如：修士无法在灵气枯竭之地飞行'
    : '特殊元素，如：血月之夜妖物力量翻倍'

  const invalidate = () => {
    qc.invalidateQueries({ queryKey })
    qc.invalidateQueries({ queryKey: ['novel', novelId] })
  }

  const resetForm = () => {
    setForm({ title: '', content: '', importance: 3, enabled: true })
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (rule: WorldRule) => {
    setEditingId(rule.id)
    setForm({ title: rule.title, content: rule.content, importance: rule.importance, enabled: rule.enabled })
    setShowForm(true)
  }

  const handleSubmit = async () => {
    if (!form.content.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await worldRulesApi.update(editingId, form)
      } else {
        await worldRulesApi.create({ novel_id: novelId, kind, ...form })
      }
      invalidate()
      resetForm()
    } finally { setSaving(false) }
  }

  const toggleEnabled = async (rule: WorldRule) => {
    await worldRulesApi.update(rule.id, { enabled: !rule.enabled })
    invalidate()
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除？')) return
    await worldRulesApi.delete(id)
    invalidate()
  }

  const Icon = kind === 'rule' ? ScrollText : Gem

  return (
    <div className="p-2 space-y-1">
      {!showForm && (
        <div className="px-1 pb-1">
          <button
            onClick={() => setShowForm(true)}
            className="w-full flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted"
          >
            <Plus className="w-3 h-3" /> 添加{label}
          </button>
        </div>
      )}

      {showForm && (
        <div className="border rounded-lg p-3 bg-muted/20 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium">{editingId ? `编辑${label}` : `添加${label}`}</span>
            <button onClick={resetForm} className="p-0.5 rounded hover:bg-muted"><X className="w-3.5 h-3.5" /></button>
          </div>
          <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })}
            placeholder="标题（可选，如：飞行禁制）"
            className="w-full border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
          <AutoTextarea value={form.content} onChange={e => setForm({ ...form, content: e.target.value })}
            placeholder={placeholder}
            className="w-full border rounded px-2 py-1.5 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
          <div className="flex items-center gap-2">
            <ImportanceSelect value={form.importance} onChange={v => setForm({ ...form, importance: v })} className="flex-1" />
            <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer">
              <input type="checkbox" checked={form.enabled} onChange={e => setForm({ ...form, enabled: e.target.checked })} />
              启用
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={resetForm} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
            <button onClick={handleSubmit} disabled={!form.content.trim() || saving}
              className="text-xs px-3 py-1 bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50">
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : editingId ? '保存' : '添加'}
            </button>
          </div>
        </div>
      )}

      {rules.map((rule) => (
        <div key={rule.id} onClick={() => startEdit(rule)}
          className={`group flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-muted cursor-pointer ${rule.enabled ? '' : 'opacity-50'}`}>
          <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${kind === 'rule' ? 'text-red-500' : 'text-fuchsia-500'}`} />
          <div className="flex-1 min-w-0">
            {rule.title && <span className="text-sm font-medium truncate block">{rule.title}</span>}
            {rule.content && <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{rule.content}</p>}
          </div>
          <button onClick={(e) => { e.stopPropagation(); toggleEnabled(rule) }}
            className="opacity-0 group-hover:opacity-100 p-1 transition-opacity shrink-0"
            title={rule.enabled ? '点击停用' : '点击启用'}>
            {rule.enabled ? <Check className="w-3 h-3 text-green-500" /> : <X className="w-3 h-3 text-muted-foreground" />}
          </button>
          <button onClick={(e) => handleDelete(e, rule.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      ))}
      {rules.length === 0 && !showForm && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无{label}</p>
      )}
    </div>
  )
}

interface StoryThreadForm {
  kind: StoryThreadKind
  title: string
  content: string
  status: StoryThreadStatus
  source_chapter: number
  due_chapter: number
  resolved_chapter: number
  resolution: string
  known_by: string
  related_entities: string
  importance: number
}

const emptyStoryThreadForm = (kind: StoryThreadKind): StoryThreadForm => ({
  kind,
  title: '',
  content: '',
  status: 'active',
  source_chapter: 0,
  due_chapter: 0,
  resolved_chapter: 0,
  resolution: '',
  known_by: '',
  related_entities: '',
  importance: 3,
})

const splitNames = (value: string) => value
  .split(/[,，、\n]/)
  .map((item) => item.trim())
  .filter(Boolean)

function StaleThreadAlert({ report, onExpire }: {
  report: StaleThreadReport | undefined
  onExpire: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  if (!report || (!report.stale.length && !report.density_hint)) return null
  return (
    <div className="border border-amber-500/40 bg-amber-500/5 rounded-md p-2 space-y-1.5">
      {report.density_hint && (
        <p className="text-[0.625rem] text-amber-700 dark:text-amber-400">{report.density_hint}</p>
      )}
      {report.stale.length > 0 && (
        <>
          <button onClick={() => setOpen((v) => !v)}
            className="text-xs text-amber-700 dark:text-amber-400 hover:underline">
            {report.stale.length} 条埋了很久还没回收（已写到第{report.current_chapter}章）
          </button>
          {open && report.stale.map((thread) => (
            <div key={thread.id} className="flex items-start gap-2 text-[0.625rem] pl-1">
              <div className="flex-1 min-w-0">
                <div className="truncate">{thread.title || thread.content.slice(0, 20)}</div>
                <div className="text-muted-foreground">{thread.reason}</div>
              </div>
              <button onClick={() => onExpire(thread.id)}
                className="shrink-0 px-1.5 py-0.5 border rounded hover:bg-muted">
                标为已过期
              </button>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

const THREAD_STATUS_LABEL: Record<StoryThreadStatus, string> = {
  active: '活跃',
  resolved: '已回收',
  abandoned: '已废弃',
  expired: '已过期',
}

export function StoryThreadsView({ novelId }: { novelId: number }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState<StoryThreadKind>('foreshadowing')
  const [statusFilter, setStatusFilter] = useState<'all' | StoryThreadStatus>('all')
  const [charFilter, setCharFilter] = useState<string>('all')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<StoryThreadForm>(() => emptyStoryThreadForm('foreshadowing'))
  const queryKey = ['story-threads', novelId]

  const { data: threads = [], isLoading } = useQuery({
    queryKey,
    queryFn: () => storyThreadsApi.list(novelId),
  })

  // 长期没回收的伏笔只提醒，标不标记为已过期由作者定
  const { data: staleReport } = useQuery({
    queryKey: ['story-threads-stale', novelId],
    queryFn: () => storyThreadsApi.stale(novelId),
  })

  // 一条伏笔/秘密的关联人物 = 知情者 + 涉及实体；两者都空则归入"未分类"
  const threadNames = (thread: StoryThread) =>
    [...new Set([...thread.known_by, ...thread.related_entities])]
  const allNames = [...new Set(threads.flatMap(threadNames))].sort((a, b) => a.localeCompare(b, 'zh'))

  const visible = threads.filter((thread) =>
    thread.kind === kind &&
    (statusFilter === 'all' || thread.status === statusFilter) &&
    (charFilter === 'all' ||
      (charFilter === 'unassigned' ? threadNames(thread).length === 0 : threadNames(thread).includes(charFilter)))
  )
  const counts = {
    foreshadowing: threads.filter((thread) => thread.kind === 'foreshadowing' && thread.status === 'active').length,
    secret: threads.filter((thread) => thread.kind === 'secret' && thread.status === 'active').length,
  }

  const invalidate = () => qc.invalidateQueries({ queryKey })

  const changeKind = (nextKind: StoryThreadKind) => {
    setKind(nextKind)
    setStatusFilter('all')
    setEditingId(null)
    setShowForm(false)
    setForm(emptyStoryThreadForm(nextKind))
  }

  const startCreate = () => {
    setEditingId(null)
    setForm(emptyStoryThreadForm(kind))
    setShowForm(true)
  }

  const startEdit = (thread: StoryThread) => {
    setEditingId(thread.id)
    setForm({
      kind: thread.kind,
      title: thread.title,
      content: thread.content,
      status: thread.status,
      source_chapter: thread.source_chapter,
      due_chapter: thread.due_chapter,
      resolved_chapter: thread.resolved_chapter,
      resolution: thread.resolution,
      known_by: thread.known_by.join('、'),
      related_entities: thread.related_entities.join('、'),
      importance: thread.importance,
    })
    setShowForm(true)
  }

  const closeForm = () => {
    setShowForm(false)
    setEditingId(null)
    setForm(emptyStoryThreadForm(kind))
  }

  const handleSave = async () => {
    if (!form.content.trim()) return
    setSaving(true)
    const payload = {
      kind: form.kind,
      title: form.title.trim(),
      content: form.content.trim(),
      status: form.status,
      source_chapter: Number(form.source_chapter) || 0,
      due_chapter: form.kind === 'foreshadowing' ? Number(form.due_chapter) || 0 : 0,
      resolved_chapter: Number(form.resolved_chapter) || 0,
      resolution: form.resolution.trim(),
      known_by: form.kind === 'secret' ? splitNames(form.known_by) : [],
      related_entities: splitNames(form.related_entities),
      importance: form.importance,
    }
    try {
      if (editingId) await storyThreadsApi.update(editingId, payload)
      else await storyThreadsApi.create({ novel_id: novelId, ...payload })
      invalidate()
      closeForm()
      toast.success(editingId ? '条目已更新' : '条目已创建')
    } catch {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (event: React.MouseEvent, id: number) => {
    event.stopPropagation()
    if (!confirm('确认删除这条长期记忆？')) return
    await storyThreadsApi.delete(id)
    invalidate()
  }

  const toggleResolved = async (event: React.MouseEvent, thread: StoryThread) => {
    event.stopPropagation()
    await storyThreadsApi.update(thread.id, {
      status: thread.status === 'active' ? 'resolved' : 'active',
    })
    invalidate()
  }

  return (
    <div className="p-2 space-y-2">
      <div className="grid grid-cols-2 border rounded-md p-0.5 bg-muted/40">
        {([
          ['foreshadowing', `伏笔 ${counts.foreshadowing}`],
          ['secret', `秘密 ${counts.secret}`],
        ] as const).map(([value, label]) => (
          <button key={value} onClick={() => changeKind(value)}
            className={`h-8 text-xs rounded transition-colors ${kind === value ? 'bg-background shadow-sm font-medium' : 'text-muted-foreground hover:text-foreground'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex gap-1.5">
        <button onClick={startCreate}
          className="flex-1 h-8 flex items-center justify-center gap-1 text-xs border border-dashed rounded-md text-muted-foreground hover:bg-muted">
          <Plus className="w-3.5 h-3.5" /> 新建{kind === 'foreshadowing' ? '伏笔' : '秘密'}
        </button>
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
          className="h-8 border rounded-md px-2 text-xs bg-background">
          <option value="all">全部状态</option>
          <option value="active">活跃</option>
          <option value="resolved">已回收</option>
          <option value="abandoned">已废弃</option>
          <option value="expired">已过期</option>
        </select>
        <select value={charFilter} onChange={(event) => setCharFilter(event.target.value)}
          className="h-8 border rounded-md px-2 text-xs bg-background max-w-[7.5rem]">
          <option value="all">全部人物</option>
          <option value="unassigned">未分类</option>
          {allNames.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
      </div>

      <StaleThreadAlert
        report={staleReport}
        onExpire={async (id) => {
          await storyThreadsApi.update(id, { status: 'expired' })
          invalidate()
          qc.invalidateQueries({ queryKey: ['story-threads-stale', novelId] })
        }}
      />

      {isLoading && <div className="flex justify-center py-6"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>}
      {!isLoading && visible.map((thread) => {
        const ThreadIcon = thread.kind === 'foreshadowing' ? Flag : Eye
        return (
          <div key={thread.id} onClick={() => startEdit(thread)}
            className={`group flex items-start gap-2 p-2 rounded-md border cursor-pointer hover:bg-muted/50 ${thread.status !== 'active' ? 'opacity-60' : ''}`}>
            <ThreadIcon className={`w-4 h-4 mt-0.5 shrink-0 ${thread.kind === 'foreshadowing' ? 'text-amber-600' : 'text-violet-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium truncate">{thread.title || (thread.kind === 'foreshadowing' ? '未命名伏笔' : '未命名秘密')}</span>
                <span className={`text-[0.625rem] px-1 py-0.5 rounded shrink-0 ${thread.status === 'active' ? 'bg-green-500/10 text-green-600' : 'bg-muted text-muted-foreground'}`}>
                  {THREAD_STATUS_LABEL[thread.status]}
                </span>
              </div>
              <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{thread.content}</p>
              <div className="flex flex-wrap gap-x-2 mt-1 text-[0.625rem] text-muted-foreground">
                {thread.source_chapter > 0 && <span>来源 第{thread.source_chapter}章</span>}
                {thread.kind === 'foreshadowing' && thread.due_chapter > 0 && <span>预计 第{thread.due_chapter}章</span>}
                {thread.kind === 'secret' && thread.known_by.length > 0 && <span>知情者 {thread.known_by.join('、')}</span>}
                {thread.related_entities.length > 0 && <span>涉及 {thread.related_entities.join('、')}</span>}
                <span>重要度 {thread.importance}</span>
              </div>
            </div>
            <button onClick={(event) => toggleResolved(event, thread)} title={thread.status === 'active' ? '标记已回收' : '恢复为活跃'}
              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-muted shrink-0">
              <Check className="w-3.5 h-3.5" />
            </button>
            <button onClick={(event) => handleDelete(event, thread.id)} title="删除"
              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-muted hover:text-destructive shrink-0">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        )
      })}
      {!isLoading && visible.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无{kind === 'foreshadowing' ? '伏笔' : '秘密'}</p>
      )}

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onMouseDown={closeForm}>
          <div className="bg-background rounded-md p-5 w-[420px] max-h-[85vh] overflow-y-auto space-y-3 shadow-lg"
            onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="font-medium">{editingId ? '编辑' : '新建'}{form.kind === 'foreshadowing' ? '伏笔' : '秘密'}</h3>
              <button onClick={closeForm} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })}
              placeholder="标题（便于识别）" className="w-full border rounded px-3 py-2 text-sm bg-background" />
            <AutoTextarea value={form.content} onChange={(event) => setForm({ ...form, content: event.target.value })}
              placeholder={form.kind === 'foreshadowing' ? '伏笔的事实内容、已经出现的迹象及不可遗忘的约束' : '秘密的真实内容'}
              autoFocus className="w-full border rounded px-3 py-2 text-sm bg-background" />
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[0.625rem] text-muted-foreground">来源章节
                <input type="number" min={0} value={form.source_chapter}
                  onChange={(event) => setForm({ ...form, source_chapter: Number(event.target.value) })}
                  className="mt-1 w-full border rounded px-2 py-2 text-sm bg-background" />
              </label>
              {form.kind === 'foreshadowing' ? (
                <label className="text-[0.625rem] text-muted-foreground">预计回收章节
                  <input type="number" min={0} value={form.due_chapter}
                    onChange={(event) => setForm({ ...form, due_chapter: Number(event.target.value) })}
                    className="mt-1 w-full border rounded px-2 py-2 text-sm bg-background" />
                </label>
              ) : (
                <ImportanceSelect value={form.importance} onChange={(importance) => setForm({ ...form, importance })} />
              )}
            </div>
            {form.kind === 'foreshadowing' && (
              <ImportanceSelect value={form.importance} onChange={(importance) => setForm({ ...form, importance })} />
            )}
            {form.kind === 'secret' && (
              <input value={form.known_by} onChange={(event) => setForm({ ...form, known_by: event.target.value })}
                placeholder="知情者（用逗号或顿号分隔；留空表示无人明确知晓）"
                className="w-full border rounded px-3 py-2 text-sm bg-background" />
            )}
            <input value={form.related_entities} onChange={(event) => setForm({ ...form, related_entities: event.target.value })}
              placeholder="关联角色/地点/道具（用逗号或顿号分隔）"
              className="w-full border rounded px-3 py-2 text-sm bg-background" />
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[0.625rem] text-muted-foreground">状态
                <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as StoryThreadStatus })}
                  className="mt-1 w-full border rounded px-2 py-2 text-sm bg-background">
                  <option value="active">活跃</option>
                  <option value="resolved">已回收</option>
                  <option value="abandoned">已废弃</option>
                  <option value="expired">已过期</option>
                </select>
              </label>
              <label className="text-[0.625rem] text-muted-foreground">回收章节
                <input type="number" min={0} value={form.resolved_chapter}
                  onChange={(event) => setForm({ ...form, resolved_chapter: Number(event.target.value) })}
                  className="mt-1 w-full border rounded px-2 py-2 text-sm bg-background" />
              </label>
            </div>
            {form.status === 'resolved' && (
              <AutoTextarea value={form.resolution} onChange={(event) => setForm({ ...form, resolution: event.target.value })}
                placeholder="如何回收或揭晓" minRows={3} className="w-full border rounded px-3 py-2 text-sm bg-background" />
            )}
            <div className="flex justify-end gap-2">
              <button onClick={closeForm} className="px-3 py-1.5 text-sm border rounded hover:bg-muted">取消</button>
              <button onClick={handleSave} disabled={saving || !form.content.trim()}
                className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function WorldviewChangesView({ novelId }: { novelId: number }) {
  const qc = useQueryClient()
  const { data: changes = [] } = useQuery({
    queryKey: ['worldview-changes', novelId],
    queryFn: () => worldviewChangesApi.list(novelId),
  })
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [form, setForm] = useState({ fact: '', effective_chapter: 0 })

  const confirmed = changes.filter((c) => c.status === 'confirmed')
  const pending = changes.filter((c) => c.status === 'pending')

  const invalidate = () => qc.invalidateQueries({ queryKey: ['worldview-changes', novelId] })

  const handleSave = async () => {
    if (!form.fact.trim()) return
    setSaving(true)
    try {
      await worldviewChangesApi.create({
        novel_id: novelId,
        fact: form.fact.trim(),
        effective_chapter: Number(form.effective_chapter) || 0,
      })
      invalidate()
      setAdding(false)
      setForm({ fact: '', effective_chapter: 0 })
    } finally { setSaving(false) }
  }

  const handleScan = async () => {
    setScanning(true)
    try {
      const res = await worldviewChangesApi.scan(novelId)
      invalidate()
      if (res.added > 0) toast.success(`AI 发现 ${res.added} 条疑似变更，请确认`)
      else toast(`未发现新的世界观变更`)
    } catch { toast.error('AI 扫描失败') }
    finally { setScanning(false) }
  }

  const handleConfirm = async (id: number) => {
    await worldviewChangesApi.update(id, { status: 'confirmed' })
    invalidate()
  }

  const handleDelete = async (id: number) => {
    await worldviewChangesApi.delete(id)
    invalidate()
  }

  return (
    <div className="p-2 space-y-2">
      <div className="flex items-center gap-1.5 px-1 pb-1">
        <button
          onClick={() => { setAdding(true); setForm({ fact: '', effective_chapter: 0 }) }}
          className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted"
        >
          <Plus className="w-3 h-3" /> 新建变更
        </button>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="flex items-center gap-1 px-3 py-1.5 text-xs border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
        >
          {scanning ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
          AI 扫描
        </button>
      </div>

      {/* AI 待确认 */}
      {pending.length > 0 && (
        <div className="space-y-1">
          <p className="text-[0.625rem] font-medium text-amber-500 px-1 uppercase tracking-wide">AI 待确认 · {pending.length}</p>
          {pending.map((c) => (
            <div key={c.id} className="border border-amber-500/40 bg-amber-500/5 rounded-lg p-2 space-y-1.5">
              <p className="text-xs">{c.fact}</p>
              {c.supersedes && <p className="text-[0.6875rem] text-muted-foreground">原设定：{c.supersedes}</p>}
              <div className="flex items-center gap-2">
                {c.effective_chapter > 0 && (
                  <span className="text-[0.625rem] text-muted-foreground">第{c.effective_chapter}章起</span>
                )}
                <div className="flex-1" />
                <button onClick={() => handleConfirm(c.id)} className="flex items-center gap-1 text-[0.6875rem] px-2 py-0.5 rounded bg-primary text-primary-foreground hover:opacity-90">
                  <Check className="w-3 h-3" /> 确认
                </button>
                <button onClick={() => handleDelete(c.id)} className="text-[0.6875rem] px-2 py-0.5 rounded border hover:bg-muted">忽略</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 已生效 */}
      {confirmed.length > 0 && (
        <div className="space-y-1">
          <p className="text-[0.625rem] font-medium text-muted-foreground px-1 uppercase tracking-wide">已生效 · {confirmed.length}</p>
          {confirmed.map((c) => (
            <div key={c.id} className="group flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-muted">
              <History className="w-3.5 h-3.5 mt-0.5 text-teal-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs">{c.fact}</p>
                <span className="text-[0.625rem] text-muted-foreground">
                  {c.effective_chapter > 0 ? `第${c.effective_chapter}章起` : '全程生效'}
                </span>
              </div>
              <button onClick={() => handleDelete(c.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {changes.length === 0 && !adding && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无世界观变更</p>
      )}

      {adding && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建世界观变更</h3>
            <textarea
              placeholder="变更后的事实，如：王朝已由大雍更替为昭明仙朝"
              value={form.fact}
              onChange={(e) => setForm({ ...form, fact: e.target.value })}
              rows={4}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
              autoFocus
            />
            <div className="flex items-center gap-2">
              <label className="text-sm text-muted-foreground shrink-0">第几章起生效</label>
              <input
                type="number"
                min={0}
                value={form.effective_chapter}
                onChange={(e) => setForm({ ...form, effective_chapter: Number(e.target.value) })}
                className="w-20 border rounded-lg px-2 py-1.5 text-sm bg-background"
              />
            </div>
            <p className="text-[0.6875rem] text-muted-foreground">0 = 全程生效；填 N 则仅第 N 章及之后注入。</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setAdding(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSave} disabled={saving} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function extractTime(chapter: Chapter): string | null {
  const m = (chapter.summary || '').match(/【(.+?)】/)
  return m ? m[1] : null
}

export function TimelineView({ novelId }: { novelId: number }) {
  const qc = useQueryClient()
  const { data: chapters = [] } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })
  const [reindexing, setReindexing] = useState(false)

  const entries = [...chapters]
    .sort((a, b) => a.number - b.number)
    .filter((c) => c.summary)
    .map((c) => ({ chapter: c.number, volume: c.volume, time: extractTime(c), summary: c.summary! }))

  return (
    <div className="p-2">
      {entries.length > 0 && (
        <div className="flex justify-end mb-3 px-1">
          <button
            onClick={async () => {
              setReindexing(true)
              try {
                const res = await novelsApi.reindexTimeline(novelId)
                qc.invalidateQueries({ queryKey: ['chapters', novelId] })
                toast.success(`已更新 ${res.updated} 章时间标记`)
              } catch (err: any) {
                const detail = err?.response?.data?.detail || err?.message || '未知错误'
                toast.error(`重标注失败：${detail}`, { duration: 8000 })
              } finally { setReindexing(false) }
            }}
            disabled={reindexing}
            className="flex items-center gap-1 text-xs px-2.5 py-1 border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
          >
            {reindexing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            {reindexing ? '标注中...' : '重标注'}
          </button>
        </div>
      )}
      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-6">暂无时间线数据</p>
      ) : (
        <div className="relative">
          <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-border" />
          {entries.map((entry) => (
            <div key={entry.chapter} className="relative pl-8 py-2">
              <div className="absolute left-1.5 top-3.5 w-3 h-3 rounded-full bg-primary border-2 border-background" />
              <div className="flex items-baseline gap-1.5 mb-0.5">
                <span className="text-[0.625rem] font-mono text-muted-foreground">第{entry.chapter}章</span>
                {entry.time ? (
                  <span className="text-[0.625rem] font-medium bg-primary/10 text-primary px-1.5 py-px rounded-full">{entry.time}</span>
                ) : (
                  <span className="text-[0.625rem] text-muted-foreground/50 italic">无标注</span>
                )}
              </div>
              <p className="text-xs text-muted-foreground leading-relaxed line-clamp-3">{entry.summary}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
