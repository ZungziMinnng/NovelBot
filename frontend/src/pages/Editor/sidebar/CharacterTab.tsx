import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, User, Loader2 } from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  novelId: number
  onOpenCharacter: (c: Character) => void
  activeCharacterId?: number | null
}

const ROLE_OPTIONS = ['男主', '女主', '主角', '配角', '反派', '朋友']
const ROLE_COLORS: Record<string, string> = {
  男主: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  女主: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  主角: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  反派: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  配角: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  朋友: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
}

export default function CharacterTab({ novelId, onOpenCharacter, activeCharacterId }: Props) {
  const qc = useQueryClient()
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })

  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ name: '', role: '配角', age: '', description: '' })

  const handleAdd = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await charactersApi.create({ ...form, novel_id: novelId })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setAdding(false)
      setForm({ name: '', role: '配角', age: '', description: '' })
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
        <button
          onClick={() => setAdding(true)}
          className="w-full flex items-center justify-center gap-1 px-3 py-1.5 text-xs border border-dashed rounded-lg text-muted-foreground hover:bg-muted transition-colors"
        >
          <Plus className="w-3 h-3" /> 新建角色
        </button>
      </div>

      <div className="overflow-y-auto flex-1 px-2 pb-2 space-y-1">
        {characters.map((c) => (
          <div
            key={c.id}
            onClick={() => onOpenCharacter(c)}
            className={`group flex items-center gap-2 px-2 py-2 rounded-lg hover:bg-muted cursor-pointer transition-colors ${
              activeCharacterId === c.id ? 'bg-muted ring-1 ring-primary' : ''
            }`}
          >
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
                <span className={`text-[10px] px-1.5 py-px rounded-full leading-tight ${ROLE_COLORS[c.role] || ROLE_COLORS['配角']}`}>
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
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <h3 className="font-medium">新建角色</h3>
            <input
              placeholder="角色名"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <input
              list="role-options-new"
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              placeholder="角色定位"
            />
            <datalist id="role-options-new">
              {ROLE_OPTIONS.map(r => <option key={r} value={r} />)}
            </datalist>
            <input
              placeholder="年龄"
              value={form.age}
              onChange={(e) => setForm({ ...form, age: e.target.value })}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
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
              <button onClick={handleAdd} disabled={saving} className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
