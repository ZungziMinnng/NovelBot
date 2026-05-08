import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, Trash2, User, Pencil, X, Check, Plus,
  RefreshCw, ImagePlus, Sparkles, ScrollText,
} from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import RelationshipGraphView from './RelationshipGraphView'
import toast from 'react-hot-toast'

type Tab = 'basic' | 'skills' | 'state' | 'relationships'

const TABS: { key: Tab; label: string }[] = [
  { key: 'basic', label: '基本信息' },
  { key: 'skills', label: '技能道具' },
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
const BODY_KEYS = ['body_traits']
const SKILLS_KEYS = ['skills', 'equipment']
const TAB_CLAIMED_KEYS = new Set([...APPEARANCE_KEYS, ...BODY_KEYS, ...SKILLS_KEYS])

const ENHANCE_SCOPES = [
  { key: 'appearance', label: '外貌' },
  { key: 'personality', label: '性格' },
  { key: 'skills', label: '技能' },
  { key: 'speech_style', label: '语言风格' },
  { key: 'weaknesses', label: '弱点' },
  { key: 'body_traits', label: '身体特质' },
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


  // AI enhance
  const [showEnhance, setShowEnhance] = useState(false)
  const [enhancePrompt, setEnhancePrompt] = useState('')
  const [enhanceScope, setEnhanceScope] = useState<string[]>(['personality', 'background'])
  const [enhancing, setEnhancing] = useState(false)

  // Avatar
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [refreshingAppearance, setRefreshingAppearance] = useState(false)
  const [generatingHistory, setGeneratingHistory] = useState(false)

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

  const handleGenerateHistory = async () => {
    setGeneratingHistory(true)
    try {
      await charactersApi.generateHistory(characterId)
      invalidate()
      toast.success('角色经历已生成')
    } catch {
      toast.error('生成失败')
    } finally { setGeneratingHistory(false) }
  }

  // ── KV editing ──
  const [editingKeys, setEditingKeys] = useState<string[]>([])

  const openKVEdit = (sectionKey: string, data: Record<string, unknown>, keys: string[]) => {
    const flat: Record<string, string> = {}
    for (const k of keys) {
      const v = data[k]
      if (v === undefined) continue
      flat[k] = Array.isArray(v) ? v.join('、') : String(v ?? '')
    }
    setKvDraft(flat)
    setEditingKeys(keys)
    setEditingKV(sectionKey)
    setNewKey('')
  }

  const saveKV = async (field: 'full_sheet' | 'current_state') => {
    setSavingKV(true)
    try {
      const base = field === 'full_sheet' ? { ...sheet } : { ...state }
      for (const k of editingKeys) {
        if (!(k in kvDraft)) delete base[k]
      }
      Object.assign(base, kvDraft)
      await charactersApi.update(characterId, { [field]: base } as Partial<Character>)
      invalidate()
      setEditingKV(null)
      toast.success('已保存')
    } finally { setSavingKV(false) }
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
  const renderBasicTab = () => {
    const allBodyKeys = BODY_KEYS
    return (
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

        {/* Body traits */}
        {renderKVSection('身体特质', sheet, allBodyKeys, 'body', 'full_sheet')}
        {!allBodyKeys.some(k => sheet[k] !== undefined) && editingKV !== 'body' && (
          <button onClick={() => openKVEdit('body', {}, allBodyKeys)}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted">
            <Plus className="w-3 h-3" /> 添加身体特质
          </button>
        )}

        {/* Character history */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <ScrollText className="w-3.5 h-3.5 text-muted-foreground" />
            <h4 className="text-xs font-medium">角色经历</h4>
          </div>
          {Array.isArray(sheet.character_history) && sheet.character_history.length > 0 ? (
            <>
              <div className="relative">
                <div className="absolute left-2.5 top-0 bottom-0 w-0.5 bg-border" />
                {(sheet.character_history as { chapter: number; content: string }[]).map((entry, i) => (
                  <div key={i} className="relative pl-7 py-1.5">
                    <div className="absolute left-1 top-2.5 w-3 h-3 rounded-full bg-primary/80 border-2 border-background" />
                    <span className="text-[10px] font-mono text-muted-foreground">第{entry.chapter}章</span>
                    <p className="text-xs text-muted-foreground leading-relaxed">{entry.content}</p>
                  </div>
                ))}
              </div>
              <button onClick={handleGenerateHistory} disabled={generatingHistory}
                className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50">
                {generatingHistory ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                {generatingHistory ? '生成中...' : '重新生成'}
              </button>
            </>
          ) : (
            <button onClick={handleGenerateHistory} disabled={generatingHistory}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted disabled:opacity-50">
              {generatingHistory ? <Loader2 className="w-3 h-3 animate-spin" /> : <ScrollText className="w-3 h-3" />}
              {generatingHistory ? '生成中...' : '生成角色经历'}
            </button>
          )}
        </div>
      </div>
    )
  }

  const renderSkillsTab = () => {
    const extraKeys = Object.keys(sheet).filter(k => !TAB_CLAIMED_KEYS.has(k) && !SKILLS_KEYS.includes(k) && k !== 'character_history')
    const allKeys = [...SKILLS_KEYS, ...extraKeys]
    return (
      <div className="space-y-4">
        {renderKVSection('技能道具', sheet, allKeys, 'skills', 'full_sheet')}
        {!allKeys.some(k => sheet[k] !== undefined) && editingKV !== 'skills' && (
          <button onClick={() => openKVEdit('skills', {}, allKeys)}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted">
            <Plus className="w-3 h-3" /> 添加技能/道具
          </button>
        )}
      </div>
    )
  }

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
    return (
      <div className="space-y-4">
        {renderKVSection('当前状态', state, stateKeys, 'state', 'current_state')}
        {stateKeys.length === 0 && (
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
          {activeTab === 'skills' && renderSkillsTab()}
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
