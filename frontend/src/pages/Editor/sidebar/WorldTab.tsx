import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Globe, MapPin, Sword, Cog, FileText, Clock, Shield, Zap, Network,
  Plus, Trash2, Loader2, RefreshCw, ChevronRight,
} from 'lucide-react'
import {
  novelsApi, locationsApi, worldEntitiesApi, novelNotesApi, chaptersApi,
  type Novel, type Location, type Chapter,
} from '@/api/client'
import toast from 'react-hot-toast'

export const WORLD_CATEGORIES: { key: string; label: string; icon: React.ElementType; color: string }[] = [
  { key: 'world_setting', label: '世界观', icon: Globe, color: 'text-blue-500' },
  { key: 'locations', label: '地点', icon: MapPin, color: 'text-green-500' },
  { key: 'items', label: '道具', icon: Sword, color: 'text-amber-500' },
  { key: 'systems', label: '系统', icon: Cog, color: 'text-purple-500' },
  { key: 'factions', label: '势力', icon: Shield, color: 'text-violet-500' },
  { key: 'techniques', label: '功法', icon: Zap, color: 'text-orange-500' },
  { key: 'notes', label: '补充设定', icon: FileText, color: 'text-cyan-500' },
  { key: 'timeline', label: '时间线', icon: Clock, color: 'text-rose-500' },
  { key: 'relationships', label: '关系网', icon: Network, color: 'text-pink-500' },
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
      <div className="grid grid-cols-2 gap-2">
        {WORLD_CATEGORIES.map(({ key, label, icon: Icon, color }) => (
          <button
            key={key}
            onClick={() => onOpenDetail(key)}
            className={`flex flex-col items-center gap-1.5 p-3 rounded-lg border hover:bg-muted transition-colors ${
              activeDetailKey === key ? 'bg-muted border-primary' : ''
            }`}
          >
            <Icon className={`w-5 h-5 ${color}`} />
            <span className="text-xs font-medium">{label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Sub-views (rendered in detail panel) ──────────────────────────────────

export function WorldSettingView({ novel, onEdit }: { novel: Novel | undefined; onEdit: () => void }) {
  const text = novel?.core_setting || ''
  return (
    <div className="p-3 space-y-3">
      <button onClick={onEdit} className="w-full text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors">
        编辑世界观设定
      </button>
      {text ? (
        <pre className="text-xs whitespace-pre-wrap font-sans leading-relaxed text-muted-foreground max-h-[60vh] overflow-y-auto">
          {text}
        </pre>
      ) : (
        <p className="text-xs text-muted-foreground text-center py-6">暂无世界观设定</p>
      )}
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
        <span className={`text-[10px] px-1.5 py-px rounded shrink-0 ${LOC_TYPE_COLORS[node.type] || LOC_TYPE_COLORS.other}`}>
          {LOC_TYPE_LABELS[node.type] || node.type}
        </span>
        {hasChildren && (
          <span className="text-[10px] text-muted-foreground shrink-0">({node.children.length})</span>
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
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setAdding(false)}>
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
            <textarea
              placeholder="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
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
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setAdding(false)}>
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建{label}</h3>
            <input
              placeholder="名称"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <textarea
              placeholder="描述"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              rows={3}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
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

export function NotesView({ novelId, onSelectNote, selectedNoteId }: {
  novelId: number
  onSelectNote?: (id: number) => void
  selectedNoteId?: number | null
}) {
  const qc = useQueryClient()
  const { data: notes = [] } = useQuery({
    queryKey: ['notes', novelId],
    queryFn: () => novelNotesApi.list(novelId),
  })
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ title: '', content: '' })

  const handleSave = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await novelNotesApi.create({ ...form, novel_id: novelId })
      qc.invalidateQueries({ queryKey: ['notes', novelId] })
      setAdding(false)
      setForm({ title: '', content: '' })
    } finally { setSaving(false) }
  }

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
          onClick={() => { setAdding(true); setForm({ title: '', content: '' }) }}
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
      {notes.length === 0 && !adding && (
        <p className="text-xs text-muted-foreground text-center py-6">暂无补充设定</p>
      )}

      {adding && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setAdding(false)}>
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建设定</h3>
            <input
              placeholder="标题"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <textarea
              placeholder="内容"
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={6}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
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
                <span className="text-[10px] font-mono text-muted-foreground">第{entry.chapter}章</span>
                {entry.time ? (
                  <span className="text-[10px] font-medium bg-primary/10 text-primary px-1.5 py-px rounded-full">{entry.time}</span>
                ) : (
                  <span className="text-[10px] text-muted-foreground/50 italic">无标注</span>
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
