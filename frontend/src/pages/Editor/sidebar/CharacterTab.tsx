import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { GripVertical, Plus, Trash2, User, Loader2, ListPlus } from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import toast from 'react-hot-toast'
import AutoTextarea from '@/components/AutoTextarea'
import BulkCharacterStateDrawer from './BulkCharacterStateDrawer'

interface Props {
  novelId: number
  onOpenCharacter: (c: Character) => void
  activeCharacterId?: number | null
  drawerOffsetLeft: number
}

import { ROLE_OPTIONS, getRoleColor } from '@/constants/roles'

export default function CharacterTab({ novelId, onOpenCharacter, activeCharacterId, drawerOffsetLeft }: Props) {
  const qc = useQueryClient()
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })

  const orderStorageKey = `novelbot_character_order_${novelId}`
  const [adding, setAdding] = useState(false)
  const [showBulkState, setShowBulkState] = useState(false)
  const [saving, setSaving] = useState(false)
  const emptyForm = { name: '', role: '配角', age: '', description: '', gender: '', appearance: '', personality: '', background: '' }
  const [form, setForm] = useState(emptyForm)

  const [characterOrder, setCharacterOrder] = useState<number[]>([])
  const [draggingId, setDraggingId] = useState<number | null>(null)

  useEffect(() => {
    try {
      const raw = localStorage.getItem(orderStorageKey)
      setCharacterOrder(raw ? JSON.parse(raw) : [])
    } catch {
      setCharacterOrder([])
    }
  }, [orderStorageKey])

  const orderedCharacters = useMemo(() => {
    if (characterOrder.length === 0) return characters
    const orderIndex = new Map(characterOrder.map((id, index) => [id, index]))
    return [...characters].sort((a, b) => {
      const ai = orderIndex.get(a.id)
      const bi = orderIndex.get(b.id)
      if (ai === undefined && bi === undefined) return 0
      if (ai === undefined) return 1
      if (bi === undefined) return -1
      return ai - bi
    })
  }, [characters, characterOrder])

  const saveCharacterOrder = (next: number[]) => {
    setCharacterOrder(next)
    localStorage.setItem(orderStorageKey, JSON.stringify(next))
  }

  const moveCharacter = (fromId: number, toId: number) => {
    if (fromId === toId) return
    const ids = orderedCharacters.map(c => c.id)
    const from = ids.indexOf(fromId)
    const to = ids.indexOf(toId)
    if (from < 0 || to < 0) return
    const next = [...ids]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    saveCharacterOrder(next)
  }

  const handleAdd = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      const full_sheet: Record<string, string> = {}
      if (form.gender.trim()) full_sheet.gender = form.gender.trim()
      if (form.appearance.trim()) full_sheet.appearance = form.appearance.trim()
      if (form.personality.trim()) full_sheet.personality = form.personality.trim()
      if (form.background.trim()) full_sheet.background = form.background.trim()
      await charactersApi.create({
        novel_id: novelId,
        name: form.name,
        role: form.role,
        age: form.age,
        description: form.description,
        ...(Object.keys(full_sheet).length ? { full_sheet } : {}),
      })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setAdding(false)
      setForm(emptyForm)
    } finally { setSaving(false) }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除该角色？')) return
    await charactersApi.delete(id)
    qc.invalidateQueries({ queryKey: ['characters', novelId] })
    toast.success('已删除')
  }

  return (
    <div className="flex flex-col h-full">
      <div className="p-2">
        <div className="grid grid-cols-2 gap-1.5">
          <button
            onClick={() => setAdding(true)}
            className="flex items-center justify-center gap-1 px-2 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted transition-colors"
          >
            <Plus className="w-3 h-3" /> 新建角色
          </button>
          <button
            onClick={() => setShowBulkState(true)}
            className="flex items-center justify-center gap-1 px-2 py-1.5 text-xs border rounded-lg text-muted-foreground hover:bg-muted transition-colors"
          >
            <ListPlus className="w-3 h-3" /> 状态词条
          </button>
        </div>
      </div>

      <div className="overflow-y-auto flex-1 px-2 pb-2 space-y-1">
        {orderedCharacters.map((c) => (
          <div
            key={c.id}
            draggable
            onDragStart={(e) => {
              setDraggingId(c.id)
              e.dataTransfer.effectAllowed = 'move'
              e.dataTransfer.setData('text/plain', String(c.id))
            }}
            onDragOver={(e) => {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
            }}
            onDrop={(e) => {
              e.preventDefault()
              const fromId = Number(e.dataTransfer.getData('text/plain')) || draggingId
              if (fromId) moveCharacter(fromId, c.id)
              setDraggingId(null)
            }}
            onDragEnd={() => setDraggingId(null)}
            onClick={() => onOpenCharacter(c)}
            className={`group flex items-center gap-2 px-2 py-2 rounded-lg hover:bg-muted cursor-pointer transition-colors ${
              activeCharacterId === c.id ? 'bg-muted ring-1 ring-primary' : ''
            } ${draggingId === c.id ? 'opacity-50 ring-1 ring-primary/40' : ''}`}
          >
            <GripVertical className="w-3.5 h-3.5 text-muted-foreground/50 shrink-0 cursor-grab" />
            {c.avatar_url ? (
              <img src={c.avatar_url} alt={c.name} className="w-8 h-8 rounded-full object-cover shrink-0" />
            ) : (
              <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center shrink-0">
                <User className="w-4 h-4 text-muted-foreground" />
              </div>
            )}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium truncate">{c.name}</span>
                <span className={`text-[0.625rem] px-1.5 py-px rounded-full leading-tight ${getRoleColor(c.role)}`}>
                  {c.role}
                </span>
              </div>
              {c.description && (
                <p className="text-xs text-muted-foreground truncate mt-0.5">{c.description}</p>
              )}
            </div>
            <button
              onClick={(e) => handleDelete(e, c.id)}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-opacity shrink-0"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        ))}
        {characters.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">暂无角色</p>
        )}
      </div>

      {/* Add Modal */}
      {adding && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setAdding(false)}>
          <div className="bg-background rounded-xl p-5 w-[32rem] max-w-[90vw] max-h-[85vh] overflow-y-auto space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建角色</h3>
            <div className="grid grid-cols-3 gap-2">
              <div className="col-span-2">
                <label className="text-xs text-muted-foreground mb-1 block">角色名 *</label>
                <input
                  placeholder="角色名"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">年龄</label>
                <input
                  placeholder="年龄"
                  value={form.age}
                  onChange={(e) => setForm({ ...form, age: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">角色定位</label>
                <select
                  value={ROLE_OPTIONS.includes(form.role) ? form.role : '__custom__'}
                  onChange={(e) => setForm({ ...form, role: e.target.value === '__custom__' ? '' : e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
                >
                  {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                  <option value="__custom__">自定义...</option>
                </select>
                {!ROLE_OPTIONS.includes(form.role) && (
                  <input
                    value={form.role}
                    onChange={(e) => setForm({ ...form, role: e.target.value })}
                    placeholder="输入自定义定位"
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background mt-1"
                    autoFocus
                  />
                )}
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">性别</label>
                <input
                  placeholder="性别"
                  value={form.gender}
                  onChange={(e) => setForm({ ...form, gender: e.target.value })}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">描述</label>
              <AutoTextarea
                placeholder="一句话简介"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                minRows={2}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">外貌</label>
              <AutoTextarea
                placeholder="外貌特征"
                value={form.appearance}
                onChange={(e) => setForm({ ...form, appearance: e.target.value })}
                minRows={3}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">性格（初始底色）</label>
              <AutoTextarea
                placeholder="初始性格倾向"
                value={form.personality}
                onChange={(e) => setForm({ ...form, personality: e.target.value })}
                minRows={3}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">背景故事</label>
              <AutoTextarea
                placeholder="角色来历、经历"
                value={form.background}
                onChange={(e) => setForm({ ...form, background: e.target.value })}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setAdding(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleAdd} disabled={saving} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
      {showBulkState && (
        <BulkCharacterStateDrawer novelId={novelId} offsetLeft={drawerOffsetLeft} onClose={() => setShowBulkState(false)} />
      )}
    </div>
  )
}
