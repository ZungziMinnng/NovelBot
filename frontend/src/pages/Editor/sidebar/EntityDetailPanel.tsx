import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, X, Check, Loader2, Trash2, ArrowRightLeft } from 'lucide-react'
import { worldEntitiesApi, novelNotesApi, locationsApi, type WorldEntity } from '@/api/client'
import toast from 'react-hot-toast'

// ── KV helpers (adapted from Characters.tsx pattern) ────────────────────────

function flattenKV(data: Record<string, unknown>): Record<string, string> {
  const flat: Record<string, string> = {}
  for (const [k, v] of Object.entries(data)) {
    flat[k] = Array.isArray(v) ? v.join('、') : String(v ?? '')
  }
  return flat
}

function KVDisplay({ data, dashed }: { data: Record<string, unknown>; dashed?: boolean }) {
  return (
    <>
      {Object.entries(data).map(([k, v]) => (
        <div key={k} className={`border rounded-lg p-3 ${dashed ? 'border-dashed' : ''}`}>
          <p className="text-xs text-muted-foreground mb-1 uppercase">{k}</p>
          <p className="text-sm whitespace-pre-wrap">{Array.isArray(v) ? v.join('、') : String(v)}</p>
        </div>
      ))}
    </>
  )
}

function KVEditor({ draft, setDraft, onRemove, newKey, setNewKey, onAddKey, dashed }: {
  draft: Record<string, string>
  setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>
  onRemove: (key: string) => void
  newKey: string
  setNewKey: (v: string) => void
  onAddKey: () => void
  dashed?: boolean
}) {
  return (
    <>
      {Object.entries(draft).map(([k, v]) => (
        <div key={k} className={`${dashed ? 'border-dashed' : ''} border rounded-lg p-3 group`}>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-muted-foreground uppercase">{k}</p>
            <button onClick={() => onRemove(k)} className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <textarea
            value={v}
            onChange={e => setDraft(prev => ({ ...prev, [k]: e.target.value }))}
            className="w-full text-sm border rounded-md p-2 bg-background resize-y min-h-[48px] focus:outline-none focus:ring-1 focus:ring-ring"
            rows={Math.max(2, v.split('\n').length)}
          />
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          value={newKey}
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onAddKey()}
          placeholder="新字段名..."
          className="flex-1 text-sm border rounded-md px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <button onClick={onAddKey} disabled={!newKey.trim()} className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded hover:bg-muted disabled:opacity-40 transition-colors">
          <Plus className="w-3 h-3" /> 添加
        </button>
      </div>
    </>
  )
}

function KVSection({ title, data, field, entityId, novelId, entityType, dashed }: {
  title: string
  data: Record<string, unknown>
  field: 'properties' | 'current_state'
  entityId: number
  novelId: number
  entityType: 'item' | 'system'
  dashed?: boolean
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState('')
  const [saving, setSaving] = useState(false)

  const startEdit = () => {
    setDraft(flattenKV(data))
    setNewKey('')
    setEditing(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await worldEntitiesApi.update(entityId, { [field]: draft })
      qc.invalidateQueries({ queryKey: ['entities', novelId, entityType] })
      setEditing(false)
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const addKey = () => {
    const k = newKey.trim()
    if (!k) return
    setDraft(prev => ({ ...prev, [k]: '' }))
    setNewKey('')
  }

  if (Object.keys(data).length === 0 && !editing) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-muted-foreground uppercase">{title}</h3>
          <button onClick={startEdit} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted transition-colors">
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
        {editing && (
          <KVEditor draft={draft} setDraft={setDraft} onRemove={(k) => setDraft(prev => { const n = { ...prev }; delete n[k]; return n })}
            newKey={newKey} setNewKey={setNewKey} onAddKey={addKey} dashed={dashed} />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-medium text-muted-foreground uppercase">{title}</h3>
        {!editing ? (
          <button onClick={startEdit} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted transition-colors">
            <Pencil className="w-3.5 h-3.5" />
          </button>
        ) : (
          <div className="flex items-center gap-1 ml-auto">
            <button onClick={() => setEditing(false)} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
            <button onClick={handleSave} disabled={saving} className="flex items-center gap-1 text-xs px-2 py-1 bg-primary text-primary-foreground rounded disabled:opacity-50">
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
            </button>
          </div>
        )}
      </div>
      {editing
        ? <KVEditor draft={draft} setDraft={setDraft} onRemove={(k) => setDraft(prev => { const n = { ...prev }; delete n[k]; return n })}
            newKey={newKey} setNewKey={setNewKey} onAddKey={addKey} dashed={dashed} />
        : <KVDisplay data={data} dashed={dashed} />
      }
    </div>
  )
}

// ── EntityDetailPanel ───────────────────────────────────────────────────────

interface EntityDetailProps {
  entityId: number
  novelId: number
  entityType: 'item' | 'system'
  onClose: () => void
}

export default function EntityDetailPanel({ entityId, novelId, entityType, onClose }: EntityDetailProps) {
  const qc = useQueryClient()
  const queryKey = ['entities', novelId, entityType]
  const { data: entities = [] } = useQuery({
    queryKey,
    queryFn: () => worldEntitiesApi.list(novelId, entityType),
  })
  const entity = entities.find(e => e.id === entityId)

  const [editingBasic, setEditingBasic] = useState(false)
  const [basicForm, setBasicForm] = useState({ name: '', description: '' })
  const [savingBasic, setSavingBasic] = useState(false)
  const [transferOpen, setTransferOpen] = useState(false)

  useEffect(() => {
    if (entity) {
      setBasicForm({ name: entity.name, description: entity.description })
      setEditingBasic(false)
    }
  }, [entityId])

  if (!entity) {
    return <div className="p-4 text-sm text-muted-foreground text-center">实体不存在或已删除</div>
  }

  const label = entityType === 'item' ? '道具' : '系统'
  const transferTargets = entityType === 'item'
    ? [{ key: 'system' as const, label: '系统' }, { key: 'technique' as const, label: '功法' }]
    : [{ key: 'item' as const, label: '道具' }, { key: 'technique' as const, label: '功法' }]

  const handleSaveBasic = async () => {
    if (!basicForm.name.trim()) return
    setSavingBasic(true)
    try {
      await worldEntitiesApi.update(entityId, basicForm)
      qc.invalidateQueries({ queryKey })
      setEditingBasic(false)
      toast.success('已保存')
    } finally { setSavingBasic(false) }
  }

  const handleDelete = async () => {
    if (!confirm(`确认删除该${label}？`)) return
    await worldEntitiesApi.delete(entityId)
    qc.invalidateQueries({ queryKey })
    toast.success('已删除')
    onClose()
  }

  const handleTransfer = async (target: 'item' | 'system' | 'technique') => {
    setTransferOpen(false)
    try {
      if (target === 'technique') {
        await worldEntitiesApi.convertToTechnique(entityId)
        qc.invalidateQueries({ queryKey: ['techniques', novelId] })
      } else {
        await worldEntitiesApi.update(entityId, { type: target })
        qc.invalidateQueries({ queryKey: ['entities', novelId, target] })
      }
      qc.invalidateQueries({ queryKey })
      toast.success(`已移至${target === 'item' ? '道具' : target === 'system' ? '系统' : '功法'}`)
      onClose()
    } catch { toast.error('移动失败') }
  }

  return (
    <div className="p-3 space-y-4">
      {/* Basic info */}
      <div className="space-y-2">
        {editingBasic ? (
          <>
            <input
              value={basicForm.name}
              onChange={e => setBasicForm(prev => ({ ...prev, name: e.target.value }))}
              className="w-full text-sm font-medium border rounded-lg px-3 py-2 bg-background"
            />
            <textarea
              value={basicForm.description}
              onChange={e => setBasicForm(prev => ({ ...prev, description: e.target.value }))}
              rows={4}
              className="w-full text-sm border rounded-lg px-3 py-2 bg-background resize-y"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditingBasic(false)} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
              <button onClick={handleSaveBasic} disabled={savingBasic} className="flex items-center gap-1 text-xs px-2 py-1 bg-primary text-primary-foreground rounded disabled:opacity-50">
                {savingBasic ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold flex-1 truncate">{entity.name}</h2>
              <button onClick={() => setEditingBasic(true)} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground">
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </div>
            {entity.description && (
              <p className="text-xs text-muted-foreground whitespace-pre-wrap">{entity.description}</p>
            )}
          </>
        )}
      </div>

      {/* Properties */}
      <KVSection
        title="属性"
        data={entity.properties}
        field="properties"
        entityId={entityId}
        novelId={novelId}
        entityType={entityType}
      />

      {/* Current state */}
      <KVSection
        title="当前状态"
        data={entity.current_state}
        field="current_state"
        entityId={entityId}
        novelId={novelId}
        entityType={entityType}
        dashed
      />

      {/* Actions */}
      <div className="flex items-center gap-2 pt-2 border-t">
        <div className="relative">
          <button
            onClick={() => setTransferOpen(!transferOpen)}
            className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded hover:bg-muted transition-colors"
          >
            <ArrowRightLeft className="w-3 h-3" /> 转移
          </button>
          {transferOpen && (
            <div className="absolute left-0 top-full z-20 mt-1 bg-popover border rounded-lg shadow-md py-1 min-w-[100px]">
              <p className="text-[10px] text-muted-foreground px-3 py-1">移至</p>
              {transferTargets.map(t => (
                <button key={t.key} onClick={() => handleTransfer(t.key)}
                  className="w-full text-left text-xs px-3 py-1.5 hover:bg-muted transition-colors">
                  {t.label}
                </button>
              ))}
            </div>
          )}
        </div>
        <button onClick={handleDelete} className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded text-destructive hover:bg-destructive/10 transition-colors ml-auto">
          <Trash2 className="w-3 h-3" /> 删除
        </button>
      </div>
    </div>
  )
}

// ── NoteDetailPanel ─────────────────────────────────────────────────────────

interface NoteDetailProps {
  noteId: number
  novelId: number
  onClose: () => void
}

export function NoteDetailPanel({ noteId, novelId, onClose }: NoteDetailProps) {
  const qc = useQueryClient()
  const { data: notes = [] } = useQuery({
    queryKey: ['notes', novelId],
    queryFn: () => novelNotesApi.list(novelId),
  })
  const note = notes.find(n => n.id === noteId)

  const [form, setForm] = useState({ title: '', content: '' })
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (note) {
      setForm({ title: note.title, content: note.content })
      setDirty(false)
    }
  }, [noteId])

  if (!note) {
    return <div className="p-4 text-sm text-muted-foreground text-center">笔记不存在或已删除</div>
  }

  const handleSave = async () => {
    if (!form.title.trim()) return
    setSaving(true)
    try {
      await novelNotesApi.update(noteId, form)
      qc.invalidateQueries({ queryKey: ['notes', novelId] })
      setDirty(false)
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirm('确认删除该设定？')) return
    await novelNotesApi.delete(noteId)
    qc.invalidateQueries({ queryKey: ['notes', novelId] })
    toast.success('已删除')
    onClose()
  }

  const update = (key: string, val: string) => {
    setForm(prev => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  return (
    <div className="p-3 flex flex-col h-full gap-3">
      <input
        value={form.title}
        onChange={e => update('title', e.target.value)}
        placeholder="标题"
        className="text-sm font-medium border rounded-lg px-3 py-2 bg-background shrink-0"
      />
      <textarea
        value={form.content}
        onChange={e => update('content', e.target.value)}
        placeholder="内容..."
        className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background resize-none min-h-[200px]"
      />
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleSave}
          disabled={saving || !dirty}
          className="flex items-center gap-1 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-lg disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
        </button>
        <button onClick={handleDelete} className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded text-destructive hover:bg-destructive/10 transition-colors ml-auto">
          <Trash2 className="w-3 h-3" /> 删除
        </button>
      </div>
    </div>
  )
}

// ── LocationDetailPanel ─────────────────────────────────────────────────────

const LOC_TYPE_OPTIONS = ['continent', 'region', 'city', 'building', 'landmark', 'other'] as const
const LOC_TYPE_LABELS: Record<string, string> = {
  continent: '大陆', region: '区域', city: '城市', building: '建筑', landmark: '地标', other: '其他',
}

interface LocationDetailProps {
  locationId: number
  novelId: number
  onClose: () => void
}

export function LocationDetailPanel({ locationId, novelId, onClose }: LocationDetailProps) {
  const qc = useQueryClient()
  const { data: locations = [] } = useQuery({
    queryKey: ['locations', novelId],
    queryFn: () => locationsApi.list(novelId),
  })
  const location = locations.find(l => l.id === locationId)

  const [editingBasic, setEditingBasic] = useState(false)
  const [basicForm, setBasicForm] = useState({ name: '', type: 'city', description: '', parent_id: null as number | null })
  const [savingBasic, setSavingBasic] = useState(false)

  const [editingProps, setEditingProps] = useState(false)
  const [propsDraft, setPropsDraft] = useState<Record<string, string>>({})
  const [propsNewKey, setPropsNewKey] = useState('')
  const [savingProps, setSavingProps] = useState(false)

  const [editingLocState, setEditingLocState] = useState(false)
  const [locStateDraft, setLocStateDraft] = useState<Record<string, string>>({})
  const [locStateNewKey, setLocStateNewKey] = useState('')
  const [savingLocState, setSavingLocState] = useState(false)

  useEffect(() => {
    if (location) {
      setBasicForm({ name: location.name, type: location.type, description: location.description, parent_id: location.parent_id })
      setEditingBasic(false)
      setEditingProps(false)
      setEditingLocState(false)
    }
  }, [locationId])

  if (!location) {
    return <div className="p-4 text-sm text-muted-foreground text-center">地点不存在或已删除</div>
  }

  const parentName = location.parent_id ? locations.find(l => l.id === location.parent_id)?.name : null

  const handleSaveBasic = async () => {
    if (!basicForm.name.trim()) return
    setSavingBasic(true)
    try {
      await locationsApi.update(locationId, basicForm)
      qc.invalidateQueries({ queryKey: ['locations', novelId] })
      setEditingBasic(false)
      toast.success('已保存')
    } finally { setSavingBasic(false) }
  }

  const handleDeleteLoc = async () => {
    if (!confirm('确认删除该地点？')) return
    await locationsApi.delete(locationId)
    qc.invalidateQueries({ queryKey: ['locations', novelId] })
    toast.success('已删除')
    onClose()
  }

  const saveLocKV = async (field: 'properties' | 'current_state', draft: Record<string, string>, setEditing: (v: boolean) => void, setSavingFn: (v: boolean) => void) => {
    setSavingFn(true)
    try {
      await locationsApi.update(locationId, { [field]: draft })
      qc.invalidateQueries({ queryKey: ['locations', novelId] })
      setEditing(false)
      toast.success('已保存')
    } finally { setSavingFn(false) }
  }

  const removeLocKey = (setter: React.Dispatch<React.SetStateAction<Record<string, string>>>, key: string) => {
    setter(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  const renderLocKV = (
    title: string, data: Record<string, unknown>,
    editing: boolean, draft: Record<string, string>,
    setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>,
    newKey: string, setNewKey: (v: string) => void,
    kvSaving: boolean, setEditing: (v: boolean) => void, setSavingFn: (v: boolean) => void,
    field: 'properties' | 'current_state', dashed?: boolean,
  ) => {
    const startEdit = () => { setDraft(flattenKV(data)); setNewKey(''); setEditing(true) }
    const addKey = () => { const k = newKey.trim(); if (!k) return; setDraft(prev => ({ ...prev, [k]: '' })); setNewKey('') }

    if (Object.keys(data).length === 0 && !editing) {
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-medium text-muted-foreground uppercase">{title}</h3>
            <button onClick={startEdit} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted"><Plus className="w-3.5 h-3.5" /></button>
          </div>
        </div>
      )
    }

    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-medium text-muted-foreground uppercase">{title}</h3>
          {!editing ? (
            <button onClick={startEdit} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted"><Pencil className="w-3.5 h-3.5" /></button>
          ) : (
            <div className="flex items-center gap-1 ml-auto">
              <button onClick={() => setEditing(false)} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
              <button onClick={() => saveLocKV(field, draft, setEditing, setSavingFn)} disabled={kvSaving} className="flex items-center gap-1 text-xs px-2 py-1 bg-primary text-primary-foreground rounded disabled:opacity-50">
                {kvSaving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
              </button>
            </div>
          )}
        </div>
        {editing
          ? <KVEditor draft={draft} setDraft={setDraft} onRemove={(k) => removeLocKey(setDraft, k)} newKey={newKey} setNewKey={setNewKey} onAddKey={addKey} dashed={dashed} />
          : <KVDisplay data={data} dashed={dashed} />
        }
      </div>
    )
  }

  return (
    <div className="p-3 space-y-4">
      <div className="space-y-2">
        {editingBasic ? (
          <>
            <input value={basicForm.name} onChange={e => setBasicForm(prev => ({ ...prev, name: e.target.value }))}
              placeholder="地点名称" className="w-full text-sm font-medium border rounded-lg px-3 py-2 bg-background" />
            <div className="grid grid-cols-2 gap-2">
              <select value={basicForm.type} onChange={e => setBasicForm(prev => ({ ...prev, type: e.target.value }))}
                className="border rounded-lg px-3 py-2 text-sm bg-background">
                {LOC_TYPE_OPTIONS.map(t => <option key={t} value={t}>{LOC_TYPE_LABELS[t]}</option>)}
              </select>
              <select value={basicForm.parent_id ?? ''} onChange={e => setBasicForm(prev => ({ ...prev, parent_id: e.target.value ? Number(e.target.value) : null }))}
                className="border rounded-lg px-3 py-2 text-sm bg-background">
                <option value="">无上级地点</option>
                {locations.filter(l => l.id !== locationId).map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
            </div>
            <textarea value={basicForm.description} onChange={e => setBasicForm(prev => ({ ...prev, description: e.target.value }))}
              placeholder="描述" rows={4} className="w-full text-sm border rounded-lg px-3 py-2 bg-background resize-y" />
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditingBasic(false)} className="text-xs px-2 py-1 border rounded hover:bg-muted">取消</button>
              <button onClick={handleSaveBasic} disabled={savingBasic} className="flex items-center gap-1 text-xs px-2 py-1 bg-primary text-primary-foreground rounded disabled:opacity-50">
                {savingBasic ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold flex-1 truncate">{location.name}</h2>
              <span className="text-[10px] px-1.5 py-px rounded bg-muted text-muted-foreground shrink-0">
                {LOC_TYPE_LABELS[location.type] || location.type}
              </span>
              <button onClick={() => setEditingBasic(true)} className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground">
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </div>
            {parentName && <p className="text-xs text-muted-foreground">上级：{parentName}</p>}
            {location.description && <p className="text-xs text-muted-foreground whitespace-pre-wrap">{location.description}</p>}
          </>
        )}
      </div>

      {renderLocKV('属性', location.properties, editingProps, propsDraft, setPropsDraft,
        propsNewKey, setPropsNewKey, savingProps, setEditingProps, setSavingProps, 'properties')}

      {renderLocKV('当前状态', location.current_state, editingLocState, locStateDraft, setLocStateDraft,
        locStateNewKey, setLocStateNewKey, savingLocState, setEditingLocState, setSavingLocState, 'current_state', true)}

      <div className="pt-2 border-t">
        <button onClick={handleDeleteLoc} className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded text-destructive hover:bg-destructive/10 transition-colors">
          <Trash2 className="w-3 h-3" /> 删除
        </button>
      </div>
    </div>
  )
}
