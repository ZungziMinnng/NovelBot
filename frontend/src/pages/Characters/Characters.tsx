import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, User, Loader2, Sun, Moon, Pencil, X, Check, Package, Cog } from 'lucide-react'
import { charactersApi, worldEntitiesApi, novelsApi, type Character, type WorldEntity } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

type Tab = 'character' | 'item' | 'system'

const TAB_CONFIG: Record<Tab, { label: string; icon: React.ElementType; empty: string; createLabel: string }> = {
  character: { label: '角色', icon: User, empty: '暂无角色', createLabel: '新建角色' },
  item: { label: '道具', icon: Package, empty: '暂无道具', createLabel: '新建道具' },
  system: { label: '系统', icon: Cog, empty: '暂无系统', createLabel: '新建系统' },
}

export default function Characters() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme } = useSettingsStore()

  const [activeTab, setActiveTab] = useState<Tab>('character')
  const [selected, setSelected] = useState<Character | null>(null)
  const [selectedEntity, setSelectedEntity] = useState<WorldEntity | null>(null)
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)

  // Character-specific state
  const [newChar, setNewChar] = useState({ name: '', role: '配角', age: '', description: '' })
  const [editing, setEditing] = useState<Character | null>(null)
  const [editForm, setEditForm] = useState({ name: '', role: '配角', age: '', description: '' })

  // Entity-specific state
  const [newEntity, setNewEntity] = useState({ name: '', description: '' })
  const [editingEntity, setEditingEntity] = useState<WorldEntity | null>(null)
  const [entityEditForm, setEntityEditForm] = useState({ name: '', description: '' })

  // Inline key-value editing (shared for character sheet/state and entity props/state)
  const [editingSheet, setEditingSheet] = useState(false)
  const [sheetDraft, setSheetDraft] = useState<Record<string, string>>({})
  const [editingState, setEditingState] = useState(false)
  const [stateDraft, setStateDraft] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState('')
  const [savingSheet, setSavingSheet] = useState(false)

  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: characters = [] } = useQuery({ queryKey: ['characters', novelId], queryFn: () => charactersApi.list(novelId) })
  const { data: items = [] } = useQuery({ queryKey: ['entities', novelId, 'item'], queryFn: () => worldEntitiesApi.list(novelId, 'item') })
  const { data: systems = [] } = useQuery({ queryKey: ['entities', novelId, 'system'], queryFn: () => worldEntitiesApi.list(novelId, 'system') })

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    setSelected(null)
    setSelectedEntity(null)
    setEditingSheet(false)
    setEditingState(false)
  }

  // ── Character handlers ──
  const handleAddChar = async () => {
    if (!newChar.name.trim()) return
    setSaving(true)
    try {
      await charactersApi.create({ ...newChar, novel_id: novelId })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setAdding(false)
      setNewChar({ name: '', role: '配角', age: '', description: '' })
    } finally { setSaving(false) }
  }

  const handleDeleteChar = async (e: React.MouseEvent, charId: number) => {
    e.stopPropagation()
    if (!confirm('确认删除该角色？')) return
    await charactersApi.delete(charId)
    qc.invalidateQueries({ queryKey: ['characters', novelId] })
    if (selected?.id === charId) setSelected(null)
  }

  const handleOpenEdit = (c: Character) => {
    setEditForm({ name: c.name, role: c.role, age: c.age || '', description: c.description || '' })
    setEditing(c)
  }

  const handleSaveEdit = async () => {
    if (!editing) return
    setSaving(true)
    try {
      const updated = await charactersApi.update(editing.id, editForm)
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setSelected(updated)
      setEditing(null)
    } finally { setSaving(false) }
  }

  // ── Entity handlers ──
  const handleAddEntity = async () => {
    if (!newEntity.name.trim()) return
    setSaving(true)
    try {
      await worldEntitiesApi.create({ ...newEntity, novel_id: novelId, type: activeTab as 'item' | 'system' })
      qc.invalidateQueries({ queryKey: ['entities', novelId, activeTab] })
      setAdding(false)
      setNewEntity({ name: '', description: '' })
    } finally { setSaving(false) }
  }

  const handleDeleteEntity = async (e: React.MouseEvent, entityId: number) => {
    e.stopPropagation()
    if (!confirm(`确认删除该${TAB_CONFIG[activeTab].label}？`)) return
    await worldEntitiesApi.delete(entityId)
    qc.invalidateQueries({ queryKey: ['entities', novelId, activeTab] })
    if (selectedEntity?.id === entityId) setSelectedEntity(null)
  }

  const handleOpenEntityEdit = (e: WorldEntity) => {
    setEntityEditForm({ name: e.name, description: e.description || '' })
    setEditingEntity(e)
  }

  const handleSaveEntityEdit = async () => {
    if (!editingEntity) return
    setSaving(true)
    try {
      const updated = await worldEntitiesApi.update(editingEntity.id, entityEditForm)
      qc.invalidateQueries({ queryKey: ['entities', novelId, activeTab] })
      setSelectedEntity(updated)
      setEditingEntity(null)
    } finally { setSaving(false) }
  }

  // ── Shared key-value editing ──
  const openSheetEdit = (data: Record<string, unknown>) => {
    const flat: Record<string, string> = {}
    for (const [k, v] of Object.entries(data)) {
      flat[k] = Array.isArray(v) ? v.join('、') : String(v ?? '')
    }
    setSheetDraft(flat)
    setEditingSheet(true)
    setNewKey('')
  }

  const openStateEdit = (data: Record<string, unknown>) => {
    const flat: Record<string, string> = {}
    for (const [k, v] of Object.entries(data)) {
      flat[k] = Array.isArray(v) ? v.join('、') : String(v ?? '')
    }
    setStateDraft(flat)
    setEditingState(true)
    setNewKey('')
  }

  const saveCharSheet = async (field: 'full_sheet' | 'current_state') => {
    if (!selected) return
    setSavingSheet(true)
    try {
      const draft = field === 'full_sheet' ? sheetDraft : stateDraft
      const updated = await charactersApi.update(selected.id, { [field]: draft })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setSelected(updated)
      if (field === 'full_sheet') setEditingSheet(false)
      else setEditingState(false)
    } finally { setSavingSheet(false) }
  }

  const saveEntityKV = async (field: 'properties' | 'current_state') => {
    if (!selectedEntity) return
    setSavingSheet(true)
    try {
      const draft = field === 'properties' ? sheetDraft : stateDraft
      const updated = await worldEntitiesApi.update(selectedEntity.id, { [field]: draft })
      qc.invalidateQueries({ queryKey: ['entities', novelId, activeTab] })
      setSelectedEntity(updated)
      if (field === 'properties') setEditingSheet(false)
      else setEditingState(false)
    } finally { setSavingSheet(false) }
  }

  const addKeyTo = (target: 'sheet' | 'state') => {
    const key = newKey.trim()
    if (!key) return
    if (target === 'sheet') setSheetDraft(prev => ({ ...prev, [key]: '' }))
    else setStateDraft(prev => ({ ...prev, [key]: '' }))
    setNewKey('')
  }

  const removeKeyFrom = (target: 'sheet' | 'state', key: string) => {
    if (target === 'sheet') setSheetDraft(prev => { const n = { ...prev }; delete n[key]; return n })
    else setStateDraft(prev => { const n = { ...prev }; delete n[key]; return n })
  }

  const roleColor: Record<string, string> = {
    '主角': 'bg-blue-100 text-blue-700',
    '反派': 'bg-red-100 text-red-700',
    '配角': 'bg-gray-100 text-gray-700',
    '盟友': 'bg-green-100 text-green-700',
  }

  const typeColor: Record<string, string> = {
    'item': 'bg-amber-100 text-amber-700',
    'system': 'bg-purple-100 text-purple-700',
  }

  // ── Render helpers ──
  const renderKVEditor = (
    draft: Record<string, string>,
    setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>,
    target: 'sheet' | 'state',
    dashed: boolean = false,
  ) => (
    <>
      {Object.entries(draft).map(([k, v]) => (
        <div key={k} className={`${dashed ? 'border-dashed' : ''} border rounded-lg p-3 group`}>
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-muted-foreground uppercase">{k}</p>
            <button onClick={() => removeKeyFrom(target, k)} className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <textarea
            value={v}
            onChange={e => setDraft(prev => ({ ...prev, [k]: e.target.value }))}
            className="w-full text-sm border rounded-md p-2 bg-background resize-y min-h-[60px] focus:outline-none focus:ring-1 focus:ring-ring"
            rows={Math.max(2, v.split('\n').length)}
          />
        </div>
      ))}
      <div className="flex items-center gap-2">
        <input
          value={newKey}
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addKeyTo(target)}
          placeholder="新字段名..."
          className="flex-1 text-sm border rounded-md px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <button onClick={() => addKeyTo(target)} disabled={!newKey.trim()} className="flex items-center gap-1 text-xs px-2 py-1.5 border rounded hover:bg-muted disabled:opacity-40 transition-colors">
          <Plus className="w-3 h-3" /> 添加
        </button>
      </div>
    </>
  )

  const renderKVDisplay = (data: Record<string, unknown>, dashed: boolean = false) =>
    Object.entries(data).map(([k, v]) => (
      <div key={k} className={`border rounded-lg p-3 ${dashed ? 'border-dashed' : ''}`}>
        <p className="text-xs text-muted-foreground mb-1 uppercase">{k}</p>
        <p className="text-sm whitespace-pre-wrap">{Array.isArray(v) ? v.join('、') : String(v)}</p>
      </div>
    ))

  const renderKVSection = (
    title: string,
    data: Record<string, unknown>,
    isEditing: boolean,
    onEdit: () => void,
    onCancel: () => void,
    onSave: () => void,
    draft: Record<string, string>,
    setDraft: React.Dispatch<React.SetStateAction<Record<string, string>>>,
    target: 'sheet' | 'state',
    dashed: boolean = false,
  ) => (
    (Object.keys(data).length > 0 || isEditing) ? (
      <div className={target === 'state' ? 'mt-4 space-y-3' : 'space-y-3'}>
        <div className="flex items-center gap-2">
          <h3 className="font-semibold">{title}</h3>
          {!isEditing ? (
            <button onClick={onEdit} className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-muted transition-colors">
              <Pencil className="w-3.5 h-3.5" />
            </button>
          ) : (
            <div className="flex items-center gap-1 ml-auto">
              <button onClick={onCancel} className="flex items-center gap-1 text-xs px-2 py-1 border rounded hover:bg-muted transition-colors">取消</button>
              <button onClick={onSave} disabled={savingSheet} className="flex items-center gap-1 text-xs px-2 py-1 bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50 transition-opacity">
                {savingSheet ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />} 保存
              </button>
            </div>
          )}
        </div>
        {isEditing ? renderKVEditor(draft, setDraft, target, dashed) : renderKVDisplay(data, dashed)}
      </div>
    ) : null
  )

  // ── Character detail pane ──
  const renderCharacterDetail = () => {
    if (!selected) return null
    return (
      <div className="max-w-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center">
            <User className="w-7 h-7 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <h2 className="text-xl font-bold">{selected.name}</h2>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span className={`px-2 py-0.5 rounded-full text-xs ${roleColor[selected.role] || ''}`}>{selected.role}</span>
              {selected.age && <span>· {selected.age}岁</span>}
            </div>
          </div>
          <button onClick={() => handleOpenEdit(selected)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors">
            <Pencil className="w-3 h-3" /> 编辑
          </button>
        </div>
        {selected.description && (
          <div className="mb-4 p-4 bg-muted rounded-lg">
            <p className="text-sm">{selected.description}</p>
          </div>
        )}
        {renderKVSection('角色卡', selected.full_sheet, editingSheet,
          () => openSheetEdit(selected.full_sheet), () => setEditingSheet(false), () => saveCharSheet('full_sheet'),
          sheetDraft, setSheetDraft, 'sheet')}
        {renderKVSection('当前状态', selected.current_state, editingState,
          () => openStateEdit(selected.current_state), () => setEditingState(false), () => saveCharSheet('current_state'),
          stateDraft, setStateDraft, 'state', true)}
      </div>
    )
  }

  // ── Entity detail pane ──
  const renderEntityDetail = () => {
    if (!selectedEntity) return null
    const Icon = TAB_CONFIG[activeTab].icon
    return (
      <div className="max-w-2xl">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center">
            <Icon className="w-7 h-7 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <h2 className="text-xl font-bold">{selectedEntity.name}</h2>
            <span className={`px-2 py-0.5 rounded-full text-xs ${typeColor[selectedEntity.type] || ''}`}>
              {TAB_CONFIG[selectedEntity.type]?.label || selectedEntity.type}
            </span>
          </div>
          <button onClick={() => handleOpenEntityEdit(selectedEntity)} className="flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors">
            <Pencil className="w-3 h-3" /> 编辑
          </button>
        </div>
        {selectedEntity.description && (
          <div className="mb-4 p-4 bg-muted rounded-lg">
            <p className="text-sm">{selectedEntity.description}</p>
          </div>
        )}
        {renderKVSection('属性', selectedEntity.properties, editingSheet,
          () => openSheetEdit(selectedEntity.properties), () => setEditingSheet(false), () => saveEntityKV('properties'),
          sheetDraft, setSheetDraft, 'sheet')}
        {renderKVSection('当前状态', selectedEntity.current_state, editingState,
          () => openStateEdit(selectedEntity.current_state), () => setEditingState(false), () => saveEntityKV('current_state'),
          stateDraft, setStateDraft, 'state', true)}
      </div>
    )
  }

  const currentEntities = activeTab === 'item' ? items : systems
  const hasSelection = activeTab === 'character' ? !!selected : !!selectedEntity

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b px-6 py-4 flex items-center gap-3 shrink-0">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 世界设定</h1>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={toggleTheme} className="p-2 rounded-md hover:bg-muted transition-colors" title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}>
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button onClick={() => setAdding(true)} className="flex items-center gap-1 bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-sm hover:opacity-90 transition-opacity">
            <Plus className="w-3.5 h-3.5" /> {TAB_CONFIG[activeTab].createLabel}
          </button>
        </div>
      </header>

      {/* Tab bar */}
      <div className="border-b px-6 flex items-center gap-1">
        {(Object.keys(TAB_CONFIG) as Tab[]).map(tab => {
          const cfg = TAB_CONFIG[tab]
          const Icon = cfg.icon
          const count = tab === 'character' ? characters.length : tab === 'item' ? items.length : systems.length
          return (
            <button
              key={tab}
              onClick={() => handleTabChange(tab)}
              className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {cfg.label}
              {count > 0 && <span className="text-xs opacity-60">({count})</span>}
            </button>
          )
        })}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div className="w-72 border-r overflow-y-auto p-4 space-y-2 shrink-0">
          {activeTab === 'character' ? (
            <>
              {characters.map((c: Character) => (
                <div key={c.id} onClick={() => { setSelected(c); setSelectedEntity(null); setEditingSheet(false); setEditingState(false) }}
                  className={`group p-3 rounded-lg border cursor-pointer transition-colors ${selected?.id === c.id ? 'border-primary bg-primary/5' : 'hover:border-muted-foreground/30'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                        <User className="w-4 h-4 text-muted-foreground" />
                      </div>
                      <div>
                        <p className="font-medium text-sm">{c.name}</p>
                        <span className={`text-xs px-1.5 py-0.5 rounded-full ${roleColor[c.role] || 'bg-gray-100 text-gray-700'}`}>{c.role}</span>
                      </div>
                    </div>
                    <button onClick={e => handleDeleteChar(e, c.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-all">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {c.description && <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{c.description}</p>}
                </div>
              ))}
              {characters.length === 0 && <p className="text-center text-muted-foreground text-sm py-8">{TAB_CONFIG.character.empty}</p>}
            </>
          ) : (
            <>
              {currentEntities.map((e: WorldEntity) => {
                const Icon = TAB_CONFIG[activeTab].icon
                return (
                  <div key={e.id} onClick={() => { setSelectedEntity(e); setSelected(null); setEditingSheet(false); setEditingState(false) }}
                    className={`group p-3 rounded-lg border cursor-pointer transition-colors ${selectedEntity?.id === e.id ? 'border-primary bg-primary/5' : 'hover:border-muted-foreground/30'}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                          <Icon className="w-4 h-4 text-muted-foreground" />
                        </div>
                        <div>
                          <p className="font-medium text-sm">{e.name}</p>
                          <span className={`text-xs px-1.5 py-0.5 rounded-full ${typeColor[e.type] || 'bg-gray-100 text-gray-700'}`}>
                            {TAB_CONFIG[e.type]?.label || e.type}
                          </span>
                        </div>
                      </div>
                      <button onClick={ev => handleDeleteEntity(ev, e.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-all">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    {e.description && <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{e.description}</p>}
                  </div>
                )
              })}
              {currentEntities.length === 0 && <p className="text-center text-muted-foreground text-sm py-8">{TAB_CONFIG[activeTab].empty}</p>}
            </>
          )}
        </div>

        {/* Detail pane */}
        <div className="flex-1 overflow-y-auto p-6">
          {hasSelection ? (
            activeTab === 'character' ? renderCharacterDetail() : renderEntityDetail()
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p>选择左侧{TAB_CONFIG[activeTab].label}查看详情</p>
            </div>
          )}
        </div>
      </div>

      {/* Add character modal */}
      {adding && activeTab === 'character' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl p-6 w-full max-w-md shadow-2xl space-y-4">
            <h3 className="font-bold">新建角色</h3>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="text-xs text-muted-foreground mb-1 block">姓名 *</label>
                <input value={newChar.name} onChange={e => setNewChar({...newChar, name: e.target.value})}
                  className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">年龄</label>
                <input value={newChar.age} onChange={e => setNewChar({...newChar, age: e.target.value})}
                  className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">定位</label>
              <select value={newChar.role} onChange={e => setNewChar({...newChar, role: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background">
                {['主角','反派','配角','盟友'].map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">描述</label>
              <textarea value={newChar.description} onChange={e => setNewChar({...newChar, description: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background resize-none h-16 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setAdding(false)} className="px-4 py-2 text-sm border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleAddChar} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add entity modal */}
      {adding && activeTab !== 'character' && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl p-6 w-full max-w-md shadow-2xl space-y-4">
            <h3 className="font-bold">{TAB_CONFIG[activeTab].createLabel}</h3>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">名称 *</label>
              <input value={newEntity.name} onChange={e => setNewEntity({...newEntity, name: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">描述</label>
              <textarea value={newEntity.description} onChange={e => setNewEntity({...newEntity, description: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background resize-none h-24 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setAdding(false)} className="px-4 py-2 text-sm border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleAddEntity} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit character modal */}
      {editing && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl p-6 w-full max-w-md shadow-2xl space-y-4">
            <h3 className="font-bold">编辑角色</h3>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="text-xs text-muted-foreground mb-1 block">姓名 *</label>
                <input value={editForm.name} onChange={e => setEditForm({...editForm, name: e.target.value})}
                  className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">年龄</label>
                <input value={editForm.age} onChange={e => setEditForm({...editForm, age: e.target.value})}
                  className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">定位</label>
              <select value={editForm.role} onChange={e => setEditForm({...editForm, role: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background">
                {['主角','反派','配角','盟友'].map(r => <option key={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">描述</label>
              <textarea value={editForm.description} onChange={e => setEditForm({...editForm, description: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background resize-none h-24 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setEditing(null)} className="px-4 py-2 text-sm border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSaveEdit} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit entity modal */}
      {editingEntity && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl p-6 w-full max-w-md shadow-2xl space-y-4">
            <h3 className="font-bold">编辑{TAB_CONFIG[activeTab].label}</h3>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">名称 *</label>
              <input value={entityEditForm.name} onChange={e => setEntityEditForm({...entityEditForm, name: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">描述</label>
              <textarea value={entityEditForm.description} onChange={e => setEntityEditForm({...entityEditForm, description: e.target.value})}
                className="w-full border rounded-md p-2 text-sm bg-background resize-none h-24 focus:outline-none focus:ring-1 focus:ring-ring" />
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setEditingEntity(null)} className="px-4 py-2 text-sm border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSaveEntityEdit} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
