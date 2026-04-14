import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2, User, Loader2, Sun, Moon } from 'lucide-react'
import { charactersApi, novelsApi, type Character } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

export default function Characters() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Character | null>(null)
  const [adding, setAdding] = useState(false)
  const [newChar, setNewChar] = useState({ name: '', role: '配角', age: '', description: '' })
  const [saving, setSaving] = useState(false)

  const { theme, toggleTheme } = useSettingsStore()
  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: characters = [] } = useQuery({ queryKey: ['characters', novelId], queryFn: () => charactersApi.list(novelId) })

  const handleAdd = async () => {
    if (!newChar.name.trim()) return
    setSaving(true)
    try {
      await charactersApi.create({ ...newChar, novel_id: novelId })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setAdding(false)
      setNewChar({ name: '', role: '配角', age: '', description: '' })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, charId: number) => {
    e.stopPropagation()
    if (!confirm('确认删除该角色？')) return
    await charactersApi.delete(charId)
    qc.invalidateQueries({ queryKey: ['characters', novelId] })
    if (selected?.id === charId) setSelected(null)
  }

  const roleColor: Record<string, string> = {
    '主角': 'bg-blue-100 text-blue-700',
    '反派': 'bg-red-100 text-red-700',
    '配角': 'bg-gray-100 text-gray-700',
    '盟友': 'bg-green-100 text-green-700',
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b px-6 py-4 flex items-center gap-3 shrink-0">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 角色管理</h1>
        <div className="ml-auto flex items-center gap-1">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md hover:bg-muted transition-colors"
            title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button onClick={() => setAdding(true)} className="flex items-center gap-1 bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-sm hover:opacity-90 transition-opacity">
            <Plus className="w-3.5 h-3.5" /> 新建角色
          </button>
        </div>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div className="w-72 border-r overflow-y-auto p-4 space-y-2 shrink-0">
          {characters.map((c: Character) => (
            <div key={c.id} onClick={() => setSelected(c)} className={`group p-3 rounded-lg border cursor-pointer transition-colors ${selected?.id === c.id ? 'border-primary bg-primary/5' : 'hover:border-muted-foreground/30'}`}>
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
                <button onClick={e => handleDelete(e, c.id)} className="opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-all">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              {c.description && <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{c.description}</p>}
            </div>
          ))}
          {characters.length === 0 && <p className="text-center text-muted-foreground text-sm py-8">暂无角色</p>}
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {selected ? (
            <div className="max-w-2xl">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center">
                  <User className="w-7 h-7 text-muted-foreground" />
                </div>
                <div>
                  <h2 className="text-xl font-bold">{selected.name}</h2>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span className={`px-2 py-0.5 rounded-full text-xs ${roleColor[selected.role] || ''}`}>{selected.role}</span>
                    {selected.age && <span>· {selected.age}岁</span>}
                  </div>
                </div>
              </div>
              {selected.description && (
                <div className="mb-4 p-4 bg-muted rounded-lg">
                  <p className="text-sm">{selected.description}</p>
                </div>
              )}
              {Object.keys(selected.full_sheet).length > 0 && (
                <div className="space-y-3">
                  <h3 className="font-semibold">角色卡</h3>
                  {Object.entries(selected.full_sheet).map(([k, v]) => (
                    <div key={k} className="border rounded-lg p-3">
                      <p className="text-xs text-muted-foreground mb-1 uppercase">{k}</p>
                      <p className="text-sm">{Array.isArray(v) ? v.join('、') : String(v)}</p>
                    </div>
                  ))}
                </div>
              )}
              {Object.keys(selected.current_state).length > 0 && (
                <div className="mt-4 space-y-3">
                  <h3 className="font-semibold">当前状态</h3>
                  {Object.entries(selected.current_state).map(([k, v]) => (
                    <div key={k} className="border rounded-lg p-3 border-dashed">
                      <p className="text-xs text-muted-foreground mb-1">{k}</p>
                      <p className="text-sm">{Array.isArray(v) ? v.join('、') : String(v)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-muted-foreground">
              <p>选择左侧角色查看详情</p>
            </div>
          )}
        </div>
      </div>
      {adding && (
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
              <button onClick={handleAdd} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                创建
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}