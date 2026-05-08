import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, Trash2, User, Pencil, X, Check, Plus,
  RefreshCw, ImagePlus, Sparkles,
} from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import RelationshipGraphView from './RelationshipGraphView'
import toast from 'react-hot-toast'

type Tab = 'basic' | 'inventory' | 'state' | 'relationships'

const TABS: { key: Tab; label: string }[] = [
  { key: 'basic', label: '基本信息' },
  { key: 'inventory', label: '角色背包' },
  { key: 'state', label: '当前状态' },
  { key: 'relationships', label: '关系' },
]

const ROLE_OPTIONS = ['主角', '女主', '反派', '配角', '盟友']
const ROLE_COLORS: Record<string, string> = {
  主角: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  女主: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  反派: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  配角: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  盟友: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
}

const APPEARANCE_KEYS = ['appearance', 'personality', 'speech_style', 'weaknesses']
const BACKGROUND_KEYS = ['background']
const INVENTORY_KEYS = ['skills', 'equipment']
const SPECIAL_KEYS = ['life_experiences', 'core_significance']
const TAB_CLAIMED_KEYS = new Set([...APPEARANCE_KEYS, ...BACKGROUND_KEYS, ...INVENTORY_KEYS, ...SPECIAL_KEYS])

const ENHANCE_SCOPES = [
  { key: 'appearance', label: '外貌' },
  { key: 'personality', label: '性格' },
  { key: 'background', label: '背景' },
  { key: 'skills', label: '技能' },
  { key: 'speech_style', label: '语言风格' },
  { key: 'weaknesses', label: '弱点' },
]

interface Props {
  characterId: number
  novelId: number
  onClose: () => void
}

export default function CharacterEditPanel({ characterId, novelId, onClose }: Props) {
  const qc = useQueryClient()
  const avatarRef = useRef<HTMLInputElement>(null)

  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })
  const character = characters.find((c) => c.id === characterId)

  const [activeTab, setActiveTab] = useState<Tab>('basic')
  const [editingBasic, setEditingBasic] = useState(false)
  const [basicForm, setBasicForm] = useState({ name: '', role: '配角', age: '', description: '' })
  const [saving, setSaving] = useState(false)

  // KV editing state
  const [editingKV, setEditingKV] = useState<string | null>(null) // which section is being edited
  const [kvDraft, setKvDraft] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState('')
  const [savingKV, setSavingKV] = useState(false)

  // Life experiences
  const [addingExp, setAddingExp] = useState(false)
  const [expForm, setExpForm] = useState({ chapter: '', content: '' })

  // AI enhance
  const [showEnhance, setShowEnhance] = useState(false)
  const [enhancePrompt, setEnhancePrompt] = useState('')
  const [enhanceScope, setEnhanceScope] = useState<string[]>(['personality', 'background'])
  const [enhancing, setEnhancing] = useState(false)

  // Avatar
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [refreshingAppearance, setRefreshingAppearance] = useState(false)

  // Relationship editing
  const [addingRel, setAddingRel] = useState(false)
  const [relTarget, setRelTarget] = useState('')
  const [relLabel, setRelLabel] = useState('')
  const [savingRel, setSavingRel] = useState(false)
  const [editingRelName, setEditingRelName] = useState<string | null>(null)
  const [editRelInit, setEditRelInit] = useState('')
  const [editRelCurr, setEditRelCurr] = useState('')

  useEffect(() => {
    if (character) {
      setBasicForm({ name: character.name, role: character.role, age: character.age, description: character.description })
    }
    setEditingKV(null)
    setShowEnhance(false)
  }, [characterId])

  if (!character) return null

  const sheet = character.full_sheet || {}
  const state = character.current_state || {}

  const invalidate = () => qc.invalidateQueries({ queryKey: ['characters', novelId] })

  // ── Basic info ──
  const handleSaveBasic = async () => {
    if (!basicForm.name.trim()) return
    setSaving(true)
    try {
      await charactersApi.update(characterId, basicForm)
      invalidate()
      setEditingBasic(false)
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirm('确认删除该角色？')) return
    await charactersApi.delete(characterId)
    invalidate()
    toast.success('已删除')
    onClose()
  }

  // ── Avatar ──
  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingAvatar(true)
    try {
      await charactersApi.uploadAvatar(characterId, file)
      invalidate()
    } finally {
      setUploadingAvatar(false)
      if (avatarRef.current) avatarRef.current.value = ''
    }
  }

  const handleDeleteAvatar = async () => {
    setUploadingAvatar(true)
    try {
      await charactersApi.deleteAvatar(characterId)
      invalidate()
    } finally { setUploadingAvatar(false) }
  }

  const handleRefreshAppearance = async () => {
    setRefreshingAppearance(true)
    try {
      await charactersApi.refreshAppearance(characterId)
      invalidate()
      toast.success('外貌已刷新')
    } finally { setRefreshingAppearance(false) }
  }

  // ── KV editing ──
  const openKVEdit = (sectionKey: string, data: Record<string, unknown>, keys: string[]) => {
    const flat: Record<string, string> = {}
    for (const k of keys) {
      const v = data[k]
      if (v === undefined) continue
      flat[k] = Array.isArray(v) ? v.join('、') : String(v ?? '')
    }
    setKvDraft(flat)
    setEditingKV(sectionKey)
    setNewKey('')
  }

  const saveKV = async (field: 'full_sheet' | 'current_state') => {
    setSavingKV(true)
    try {
      const existing = field === 'full_sheet' ? { ...sheet } : { ...state }
      Object.assign(existing, kvDraft)
      await charactersApi.update(characterId, { [field]: existing } as Partial<Character>)
      invalidate()
      setEditingKV(null)
      toast.success('已保存')
    } finally { setSavingKV(false) }
  }

  // ── Life experiences ──
  const lifeExps = (sheet.life_experiences || []) as Array<{ chapter: number; content: string }>

  const handleAddExp = async () => {
    if (!expForm.content.trim()) return
    const newExps = [...lifeExps, { chapter: Number(expForm.chapter) || 0, content: expForm.content }]
    setSaving(true)
    try {
      await charactersApi.update(characterId, { full_sheet: { ...sheet, life_experiences: newExps } } as Partial<Character>)
      invalidate()
      setAddingExp(false)
      setExpForm({ chapter: '', content: '' })
    } finally { setSaving(false) }
  }

  const handleDeleteExp = async (idx: number) => {
    const newExps = lifeExps.filter((_, i) => i !== idx)
    await charactersApi.update(characterId, { full_sheet: { ...sheet, life_experiences: newExps } } as Partial<Character>)
    invalidate()
  }

  // ── Core significance ──
  const [editingSignificance, setEditingSignificance] = useState(false)
  const [significanceDraft, setSignificanceDraft] = useState('')

  const handleSaveSignificance = async () => {
    setSaving(true)
    try {
      await charactersApi.update(characterId, { full_sheet: { ...sheet, core_significance: significanceDraft } } as Partial<Character>)
      invalidate()
      setEditingSignificance(false)
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  // ── AI enhance ──
  const handleEnhance = async () => {
    if (!enhancePrompt.trim() || enhanceScope.length === 0) return
    setEnhancing(true)
    try {
      await charactersApi.enhance(characterId, { prompt: enhancePrompt, scope: enhanceScope })
      invalidate()
      setShowEnhance(false)
      setEnhancePrompt('')
      toast.success('角色已完善')
    } catch {
      toast.error('AI 完善失败')
    } finally { setEnhancing(false) }
  }

  const toggleScope = (key: string) => {
    setEnhanceScope(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  // ── Render helpers ──
  const renderKVDisplay = (data: Record<string, unknown>, keys: string[]) => (
    <div className="space-y-2">
      {keys.filter(k => data[k] !== undefined && data[k] !== '').map(k => (
        <div key={k} className="border rounded-lg p-2.5">
          <p className="text-[10px] text-muted-foreground mb-1 uppercase">{k}</p>
          <p className="text-xs whitespace-pre-wrap">{Array.isArray(data[k]) ? (data[k] as string[]).join('、') : String(data[k])}</p>
        </div>
      ))}
    </div>
  )

  const renderKVEditor = () => (
    <div className="space-y-2">
      {Object.entries(kvDraft).map(([k, v]) => (
        <div key={k} className="border rounded-lg p-2.5 group">
          <div className="flex items-center justify-between mb-1">
            <p className="text-[10px] text-muted-foreground uppercase">{k}</p>
            <button onClick={() => setKvDraft(prev => { const n = { ...prev }; delete n[k]; return n })}
              className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all">
              <X className="w-3 h-3" />
            </button>
          </div>
          <textarea
            value={v}
            onChange={e => setKvDraft(prev => ({ ...prev, [k]: e.target.value }))}
            className="w-full text-sm border rounded p-2 bg-background resize-y min-h-[56px] focus:outline-none focus:ring-1 focus:ring-ring"
            rows={Math.max(2, v.split('\n').length)}
          />
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <input
          value={newKey}
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && newKey.trim()) { setKvDraft(prev => ({ ...prev, [newKey.trim()]: '' })); setNewKey('') } }}
          placeholder="新字段名..."
          className="flex-1 text-sm border rounded px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
        />
        <button
          onClick={() => { if (newKey.trim()) { setKvDraft(prev => ({ ...prev, [newKey.trim()]: '' })); setNewKey('') } }}
          disabled={!newKey.trim()}
          className="text-[10px] px-2 py-1 border rounded hover:bg-muted disabled:opacity-40"
        >
          <Plus className="w-3 h-3" />
        </button>
      </div>
    </div>
  )

  const renderKVSection = (
    title: string,
    data: Record<string, unknown>,
    keys: string[],
    sectionId: string,
    field: 'full_sheet' | 'current_state',
  ) => {
    const hasData = keys.some(k => data[k] !== undefined && data[k] !== '')
    const isEditing = editingKV === sectionId
    if (!hasData && !isEditing) return null
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-medium">{title}</h4>
          {!isEditing ? (
            <button onClick={() => openKVEdit(sectionId, data, keys)} className="p-0.5 text-muted-foreground hover:text-foreground">
              <Pencil className="w-3 h-3" />
            </button>
          ) : (
            <div className="flex items-center gap-1 ml-auto">
              <button onClick={() => setEditingKV(null)} className="text-[10px] px-2 py-0.5 border rounded hover:bg-muted">取消</button>
              <button onClick={() => saveKV(field)} disabled={savingKV}
                className="text-[10px] px-2 py-0.5 bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50">
                {savingKV ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              </button>
            </div>
          )}
        </div>
        {isEditing ? renderKVEditor() : renderKVDisplay(data, keys)}
      </div>
    )
  }

  // ── Tab content ──
  const renderBasicTab = () => (
    <div className="space-y-4">
      {/* Name / Role / Age */}
      <div className="border rounded-lg p-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground uppercase">姓名</span>
          <span className="text-xs">{character.name}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground uppercase">定位</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${ROLE_COLORS[character.role] || ''}`}>{character.role}</span>
        </div>
        {character.age && (
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground uppercase">年龄</span>
            <span className="text-xs">{character.age}</span>
          </div>
        )}
      </div>
      {character.description && (
        <div className="border rounded-lg p-3">
          <p className="text-[10px] text-muted-foreground mb-1 uppercase">描述</p>
          <p className="text-xs whitespace-pre-wrap">{character.description}</p>
        </div>
      )}

      {/* Appearance & Personality */}
      {renderKVSection('外貌与性格', sheet, APPEARANCE_KEYS, 'appearance', 'full_sheet')}
      <button onClick={handleRefreshAppearance} disabled={refreshingAppearance}
        className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50">
        {refreshingAppearance ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
        AI 刷新外貌描述
      </button>

      {/* Background */}
      {renderKVSection('背景故事', sheet, BACKGROUND_KEYS, 'background', 'full_sheet')}

      {/* Life experiences */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-medium">人生经历</h4>
          <button onClick={() => setAddingExp(true)} className="p-0.5 text-muted-foreground hover:text-foreground">
            <Plus className="w-3 h-3" />
          </button>
        </div>
        {lifeExps.length === 0 && !addingExp && (
          <p className="text-[10px] text-muted-foreground py-2">暂无经历记录</p>
        )}
        {lifeExps.map((exp, i) => (
          <div key={i} className="border rounded-lg p-2.5 group">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] px-1.5 py-px rounded bg-primary/10 text-primary">
                第 {exp.chapter} 章
              </span>
              <button onClick={() => handleDeleteExp(i)}
                className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all">
                <X className="w-3 h-3" />
              </button>
            </div>
            <p className="text-xs whitespace-pre-wrap">{exp.content}</p>
          </div>
        ))}
        {addingExp && (
          <div className="border border-dashed rounded-lg p-2.5 space-y-2">
            <input
              value={expForm.chapter}
              onChange={e => setExpForm(prev => ({ ...prev, chapter: e.target.value }))}
              placeholder="章节号"
              className="w-20 text-sm border rounded px-2 py-1.5 bg-background"
            />
            <textarea
              value={expForm.content}
              onChange={e => setExpForm(prev => ({ ...prev, content: e.target.value }))}
              placeholder="经历内容..."
              className="w-full text-sm border rounded p-2 bg-background resize-y min-h-[56px]"
              rows={3}
            />
            <div className="flex gap-1.5 justify-end">
              <button onClick={() => setAddingExp(false)} className="text-[10px] px-2 py-0.5 border rounded hover:bg-muted">取消</button>
              <button onClick={handleAddExp} disabled={saving}
                className="text-[10px] px-2 py-0.5 bg-primary text-primary-foreground rounded disabled:opacity-50">
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : '添加'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Core significance */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h4 className="text-xs font-medium">核心意义</h4>
          {!editingSignificance ? (
            <button onClick={() => { setSignificanceDraft(String(sheet.core_significance || '')); setEditingSignificance(true) }}
              className="p-0.5 text-muted-foreground hover:text-foreground">
              <Pencil className="w-3 h-3" />
            </button>
          ) : (
            <div className="flex items-center gap-1 ml-auto">
              <button onClick={() => setEditingSignificance(false)} className="text-[10px] px-2 py-0.5 border rounded hover:bg-muted">取消</button>
              <button onClick={handleSaveSignificance} disabled={saving}
                className="text-[10px] px-2 py-0.5 bg-primary text-primary-foreground rounded disabled:opacity-50">
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              </button>
            </div>
          )}
        </div>
        {editingSignificance ? (
          <textarea
            value={significanceDraft}
            onChange={e => setSignificanceDraft(e.target.value)}
            className="w-full text-sm border rounded p-2 bg-background resize-y min-h-[60px]"
            rows={3}
            placeholder="该角色对故事的核心意义..."
          />
        ) : (
          sheet.core_significance ? (
            <div className="border rounded-lg p-2.5">
              <p className="text-xs whitespace-pre-wrap">{String(sheet.core_significance)}</p>
            </div>
          ) : (
            <p className="text-[10px] text-muted-foreground py-2">未设置</p>
          )
        )}
      </div>
    </div>
  )

  const renderInventoryTab = () => (
    <div className="space-y-4">
      {renderKVSection('技能与装备', sheet, INVENTORY_KEYS, 'inventory', 'full_sheet')}
      {!INVENTORY_KEYS.some(k => sheet[k] !== undefined) && editingKV !== 'inventory' && (
        <button onClick={() => openKVEdit('inventory', {}, INVENTORY_KEYS)}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted">
          <Plus className="w-3 h-3" /> 添加技能/装备
        </button>
      )}
    </div>
  )

  const PRESET_LABELS = ['师徒', '同门', '敌对', '父子', '挚友', '主仆', '恋人', '上下级']

  const handleAddRelationship = async () => {
    if (!relTarget || !relLabel.trim()) return
    setSavingRel(true)
    try {
      const oldRels = (state.relationship_changes || {}) as Record<string, string>
      const newRels = { ...oldRels, [relTarget]: relLabel.trim() }
      await charactersApi.update(characterId, {
        current_state: { ...state, relationship_changes: newRels },
      } as Partial<Character>)
      invalidate()
      qc.invalidateQueries({ queryKey: ['relationship-graph', novelId] })
      setAddingRel(false)
      setRelTarget('')
      setRelLabel('')
      toast.success('关系已添加')
    } catch { toast.error('添加失败') }
    finally { setSavingRel(false) }
  }

  const handleDeleteRelationship = async (name: string) => {
    const oldInitial = { ...(state.initial_relationships || {}) } as Record<string, string>
    const oldCurrent = { ...(state.relationship_changes || {}) } as Record<string, string>
    delete oldInitial[name]
    delete oldCurrent[name]
    await charactersApi.update(characterId, {
      current_state: { ...state, initial_relationships: oldInitial, relationship_changes: oldCurrent },
    } as Partial<Character>)
    invalidate()
    qc.invalidateQueries({ queryKey: ['relationship-graph', novelId] })
    toast.success('关系已删除')
  }

  const handleStartEditRel = (name: string, init: string, curr: string) => {
    setEditingRelName(name)
    setEditRelInit(init)
    setEditRelCurr(curr)
  }

  const handleSaveEditRel = async () => {
    if (!editingRelName) return
    setSavingRel(true)
    try {
      const newInitial = { ...(state.initial_relationships || {}) } as Record<string, string>
      const newCurrent = { ...(state.relationship_changes || {}) } as Record<string, string>
      if (editRelInit.trim()) {
        newInitial[editingRelName] = editRelInit.trim()
      } else {
        delete newInitial[editingRelName]
      }
      if (editRelCurr.trim()) {
        newCurrent[editingRelName] = editRelCurr.trim()
      } else {
        delete newCurrent[editingRelName]
      }
      await charactersApi.update(characterId, {
        current_state: { ...state, initial_relationships: newInitial, relationship_changes: newCurrent },
      } as Partial<Character>)
      invalidate()
      qc.invalidateQueries({ queryKey: ['relationship-graph', novelId] })
      setEditingRelName(null)
      toast.success('关系已更新')
    } catch { toast.error('保存失败') }
    finally { setSavingRel(false) }
  }

  const renderRelationshipsTab = () => {
    const myInitial = (state.initial_relationships || {}) as Record<string, string>
    const myCurrent = (state.relationship_changes || {}) as Record<string, string>
    const charName = character?.name || ''

    const mergedInitial: Record<string, string> = { ...myInitial }
    const mergedCurrent: Record<string, string> = { ...myCurrent }
    for (const c of characters) {
      if (c.id === characterId) continue
      const cs = c.current_state || {}
      const ci = (cs.initial_relationships || {}) as Record<string, string>
      const cc = (cs.relationship_changes || {}) as Record<string, string>
      if (ci[charName] && !mergedInitial[c.name]) mergedInitial[c.name] = ci[charName]
      if (cc[charName] && !mergedCurrent[c.name]) mergedCurrent[c.name] = cc[charName]
    }

    const allTargets = [...new Set([...Object.keys(mergedInitial), ...Object.keys(mergedCurrent)])]
    const availableTargets = characters.filter(
      (c) => c.id !== characterId && !mergedInitial[c.name] && !mergedCurrent[c.name],
    )

    return (
      <>
        {/* Graph */}
        <div className="flex-1 min-h-0">
          <RelationshipGraphView novelId={novelId} focusCharacterId={characterId} />
        </div>

        {/* Bottom panel */}
        <div className="shrink-0 border-t overflow-y-auto max-h-[40%] p-3 space-y-2">
          {allTargets.length > 0 && (
            <div className="space-y-1.5">
              {allTargets.map((name) => {
                const init = mergedInitial[name]
                const curr = mergedCurrent[name]
                const isEditing = editingRelName === name

                if (isEditing) {
                  return (
                    <div key={name} className="border rounded-lg p-2.5 space-y-2 bg-muted/30">
                      <span className="text-sm font-medium">{name}</span>
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground shrink-0 w-16">初始关系</span>
                          <input value={editRelInit} onChange={(e) => setEditRelInit(e.target.value)}
                            placeholder="如：师徒、同门"
                            className="flex-1 text-xs border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground shrink-0 w-16">当前关系</span>
                          <input value={editRelCurr} onChange={(e) => setEditRelCurr(e.target.value)}
                            placeholder="如：反目成仇"
                            className="flex-1 text-xs border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                        </div>
                      </div>
                      <div className="flex justify-end gap-1.5">
                        <button onClick={() => setEditingRelName(null)}
                          className="text-[10px] px-2 py-0.5 border rounded hover:bg-muted">取消</button>
                        <button onClick={handleSaveEditRel} disabled={savingRel || (!editRelInit.trim() && !editRelCurr.trim())}
                          className="text-[10px] px-2 py-0.5 bg-primary text-primary-foreground rounded disabled:opacity-50">
                          {savingRel ? <Loader2 className="w-3 h-3 animate-spin" /> : '保存'}
                        </button>
                      </div>
                    </div>
                  )
                }

                const hasChange = curr && curr !== init
                const text = init && hasChange
                  ? `初始关系：${init} / 当前关系：${curr}`
                  : init
                    ? `初始关系：${init}`
                    : curr
                      ? `当前关系：${curr}`
                      : ''
                return (
                  <div key={name} className="flex items-center gap-2 px-2.5 py-2 border rounded-lg group cursor-pointer hover:bg-muted/30 transition-colors"
                    onClick={() => handleStartEditRel(name, init || '', curr || '')}>
                    <span className="text-sm font-medium shrink-0">{name}</span>
                    <span className="text-xs text-muted-foreground flex-1 truncate">{text}</span>
                    <button onClick={(e) => { e.stopPropagation(); handleDeleteRelationship(name) }}
                      className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-all">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {/* Add relationship */}
          {!addingRel ? (
            <button onClick={() => setAddingRel(true)}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted">
              <Plus className="w-3 h-3" /> 添加关系
            </button>
          ) : (
            <div className="border border-dashed rounded-lg p-2.5 space-y-2">
              <select
                value={relTarget}
                onChange={(e) => setRelTarget(e.target.value)}
                className="w-full text-xs border rounded px-2 py-1.5 bg-background"
              >
                <option value="">选择角色...</option>
                {availableTargets.map((c) => (
                  <option key={c.id} value={c.name}>{c.name} ({c.role})</option>
                ))}
              </select>
              <input
                value={relLabel}
                onChange={(e) => setRelLabel(e.target.value)}
                placeholder="关系标签"
                className="w-full text-xs border rounded px-2 py-1.5 bg-background"
              />
              <div className="flex flex-wrap gap-1">
                {PRESET_LABELS.map((label) => (
                  <button key={label} onClick={() => setRelLabel(label)}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
                      relLabel === label ? 'bg-primary text-primary-foreground border-primary' : 'hover:bg-muted'
                    }`}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex gap-1.5 justify-end">
                <button onClick={() => { setAddingRel(false); setRelTarget(''); setRelLabel('') }}
                  className="text-[10px] px-2 py-0.5 border rounded hover:bg-muted">取消</button>
                <button onClick={handleAddRelationship} disabled={savingRel || !relTarget || !relLabel.trim()}
                  className="text-[10px] px-2 py-0.5 bg-primary text-primary-foreground rounded disabled:opacity-50">
                  {savingRel ? <Loader2 className="w-3 h-3 animate-spin" /> : '添加'}
                </button>
              </div>
            </div>
          )}
        </div>
      </>
    )
  }

  const renderStateTab = () => {
    const stateKeys = Object.keys(state).filter(k => k !== 'relationship_changes' && k !== 'initial_relationships')
    const remainingSheetKeys = Object.keys(sheet).filter(k => !TAB_CLAIMED_KEYS.has(k))
    return (
      <div className="space-y-4">
        {renderKVSection('当前状态', state, stateKeys, 'state', 'current_state')}
        {remainingSheetKeys.length > 0 && (
          renderKVSection('其他属性', sheet, remainingSheetKeys, 'extra', 'full_sheet')
        )}
        {stateKeys.length === 0 && remainingSheetKeys.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">暂无状态信息</p>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Rich header */}
      <div className="p-3 border-b space-y-2.5 shrink-0">
        <div className="flex items-center gap-3">
          <div className="relative group shrink-0">
            <input ref={avatarRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarUpload} />
            {character.avatar_url ? (
              <div className="w-12 h-12 rounded-full overflow-hidden cursor-pointer" onClick={() => avatarRef.current?.click()}>
                <img src={character.avatar_url} alt={character.name} className="w-full h-full object-cover object-top" />
                <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-full flex items-center justify-center">
                  {uploadingAvatar ? <Loader2 className="w-4 h-4 text-white animate-spin" /> : <ImagePlus className="w-4 h-4 text-white" />}
                </div>
              </div>
            ) : (
              <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center cursor-pointer hover:bg-muted/80"
                onClick={() => avatarRef.current?.click()}>
                {uploadingAvatar ? <Loader2 className="w-5 h-5 animate-spin" /> : <User className="w-5 h-5 text-muted-foreground" />}
              </div>
            )}
            {character.avatar_url && (
              <button onClick={handleDeleteAvatar}
                className="absolute -top-1 -right-1 w-4 h-4 bg-destructive text-white rounded-full items-center justify-center text-[8px] hidden group-hover:flex">
                <X className="w-2.5 h-2.5" />
              </button>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold truncate">{character.name}</h3>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-[10px] px-1.5 py-px rounded-full ${ROLE_COLORS[character.role] || ROLE_COLORS['配角']}`}>
                {character.role}
              </span>
              {character.age && <span className="text-[10px] text-muted-foreground">{character.age}岁</span>}
            </div>
          </div>
        </div>
        <div className="flex gap-1.5">
          <button onClick={() => { setBasicForm({ name: character.name, role: character.role, age: character.age, description: character.description }); setEditingBasic(true) }}
            className="flex-1 flex items-center justify-center gap-1 py-1 text-[10px] border rounded-md hover:bg-muted transition-colors">
            <Pencil className="w-3 h-3" /> 编辑
          </button>
          <button onClick={() => setShowEnhance(!showEnhance)}
            className={`flex-1 flex items-center justify-center gap-1 py-1 text-[10px] border rounded-md transition-colors ${showEnhance ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
            <Sparkles className="w-3 h-3" /> AI 完善
          </button>
          <button onClick={handleDelete}
            className="px-2 py-1 text-[10px] border rounded-md text-destructive hover:bg-destructive/10 transition-colors">
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* AI enhance panel */}
      {showEnhance && (
        <div className="p-3 border-b space-y-2 bg-muted/30 shrink-0">
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-3.5 h-3.5 text-primary" />
            <span className="text-xs font-medium">AI 完善角色</span>
          </div>
          <textarea
            value={enhancePrompt}
            onChange={e => setEnhancePrompt(e.target.value)}
            placeholder="输入完善指令，例如：让性格更鲜明，补充童年经历..."
            className="w-full text-sm border rounded-lg p-2 bg-background resize-y min-h-[56px]"
            rows={3}
          />
          <div>
            <p className="text-[10px] text-muted-foreground mb-1">完善范围</p>
            <div className="flex flex-wrap gap-1">
              {ENHANCE_SCOPES.map(({ key, label }) => (
                <button key={key} onClick={() => toggleScope(key)}
                  className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
                    enhanceScope.includes(key) ? 'bg-primary text-primary-foreground border-primary' : 'hover:bg-muted'
                  }`}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <button onClick={handleEnhance} disabled={enhancing || !enhancePrompt.trim() || enhanceScope.length === 0}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
            {enhancing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            {enhancing ? '完善中...' : '开始完善'}
          </button>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b shrink-0 overflow-x-auto">
        {TABS.map(({ key, label }) => (
          <button key={key} onClick={() => setActiveTab(key)}
            className={`shrink-0 px-2.5 py-2 text-[11px] font-medium transition-colors ${
              activeTab === key
                ? 'text-primary border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'relationships' ? (
        <div className="flex-1 flex flex-col overflow-hidden">
          {renderRelationshipsTab()}
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto p-3">
          {activeTab === 'basic' && renderBasicTab()}
          {activeTab === 'inventory' && renderInventoryTab()}
          {activeTab === 'state' && renderStateTab()}
        </div>
      )}

      {/* Edit basic info modal */}
      {editingBasic && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setEditingBasic(false)}>
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={e => e.stopPropagation()}>
            <h3 className="font-medium text-sm">编辑基本信息</h3>
            <input
              value={basicForm.name}
              onChange={e => setBasicForm({ ...basicForm, name: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              placeholder="角色名"
            />
            <select
              value={basicForm.role}
              onChange={e => setBasicForm({ ...basicForm, role: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            >
              {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <input
              value={basicForm.age}
              onChange={e => setBasicForm({ ...basicForm, age: e.target.value })}
              placeholder="年龄"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
            />
            <textarea
              value={basicForm.description}
              onChange={e => setBasicForm({ ...basicForm, description: e.target.value })}
              rows={4}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
              placeholder="描述"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditingBasic(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSaveBasic} disabled={saving}
                className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
