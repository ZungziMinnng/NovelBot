import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Sun, Moon, Plus, Pencil, Trash2, X, Loader2, Map as MapIcon, Globe, Building, Landmark } from 'lucide-react'
import { novelsApi, locationsApi, type Location } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

const LOCATION_TYPES = ['continent', 'region', 'city', 'building', 'landmark', 'other'] as const
const TYPE_LABELS: Record<string, string> = {
  continent: '大陆', region: '区域', city: '城市', building: '建筑', landmark: '地标', other: '其他',
}
const TYPE_ICONS: Record<string, typeof Globe> = {
  continent: Globe, region: MapIcon, city: Building, building: Building, landmark: Landmark, other: MapIcon,
}

export default function Locations() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme } = useSettingsStore()

  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: locations = [], isLoading } = useQuery({
    queryKey: ['locations', novelId],
    queryFn: () => locationsApi.list(novelId),
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formName, setFormName] = useState('')
  const [formType, setFormType] = useState<string>('city')
  const [formDesc, setFormDesc] = useState('')
  const [formParentId, setFormParentId] = useState<string>('')
  const [saving, setSaving] = useState(false)

  const parentMap = new Map(locations.map(l => [l.id, l.name]))

  const resetForm = () => {
    setFormName('')
    setFormType('city')
    setFormDesc('')
    setFormParentId('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (loc: Location) => {
    setEditingId(loc.id)
    setFormName(loc.name)
    setFormType(loc.type)
    setFormDesc(loc.description || '')
    setFormParentId(loc.parent_id ? String(loc.parent_id) : '')
    setShowForm(true)
  }

  const handleSubmit = async () => {
    if (!formName.trim()) return
    setSaving(true)
    try {
      const data = {
        novel_id: novelId,
        name: formName.trim(),
        type: formType,
        description: formDesc,
        parent_id: formParentId ? Number(formParentId) : undefined,
      }
      if (editingId) {
        await locationsApi.update(editingId, data)
      } else {
        await locationsApi.create(data)
      }
      qc.invalidateQueries({ queryKey: ['locations', novelId] })
      resetForm()
    } finally { setSaving(false) }
  }

  const handleDelete = async (locId: number) => {
    if (!confirm('确认删除该地点？子地点将保留但失去父级关联。')) return
    await locationsApi.delete(locId)
    qc.invalidateQueries({ queryKey: ['locations', novelId] })
  }

  const getIcon = (type: string) => {
    const Icon = TYPE_ICONS[type] || Map
    return <Icon className="w-3.5 h-3.5" />
  }

  // Group by type for display
  const grouped: Record<string, Location[]> = {}
  for (const loc of locations) {
    (grouped[loc.type] ??= []).push(loc)
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 地点</h1>
        <button onClick={toggleTheme} className="ml-auto p-2 rounded-md hover:bg-muted" title="切换主题">
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {/* Add button */}
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted-foreground">
            {locations.length} 个地点 · 记录小说中的大陆、国家、城市、建筑等区域信息
          </p>
          {!showForm && (
            <button onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted transition-colors">
              <Plus className="w-3.5 h-3.5" /> 添加地点
            </button>
          )}
        </div>

        {/* Add / Edit form */}
        {showForm && (
          <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑地点' : '添加新地点'}</span>
              <button onClick={resetForm} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block">名称 *</label>
                <input value={formName} onChange={e => setFormName(e.target.value)}
                  placeholder="例：天渊城"
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block">类型</label>
                <select value={formType} onChange={e => setFormType(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring">
                  {LOCATION_TYPES.map(t => (
                    <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block">描述</label>
              <textarea value={formDesc} onChange={e => setFormDesc(e.target.value)} rows={2}
                placeholder="地理位置、气候、政治归属、重要性等"
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium mb-1 block">父级地点</label>
                <select value={formParentId} onChange={e => setFormParentId(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring">
                  <option value="">无（顶级区域）</option>
                  {locations.filter(l => l.id !== editingId).map(l => (
                    <option key={l.id} value={l.id}>
                      [{TYPE_LABELS[l.type] ?? l.type}] {l.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={resetForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSubmit} disabled={!formName.trim() || saving}
                className="text-sm px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingId ? '保存修改' : '添加'}
              </button>
            </div>
          </div>
        )}

        {/* Location list grouped by type */}
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : locations.length === 0 ? (
          <div className="text-center py-20 text-muted-foreground">
            <p>暂无地点数据，点击「添加地点」开始</p>
          </div>
        ) : (
          <div className="space-y-6">
            {Object.entries(grouped).map(([type, items]) => (
              <div key={type}>
                <div className="flex items-center gap-1.5 mb-2 text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  {getIcon(type)}
                  {TYPE_LABELS[type] || type}
                  <span className="opacity-50">({items.length})</span>
                </div>
                <div className="space-y-1.5">
                  {items.map(loc => (
                    <div key={loc.id} className="flex items-center gap-3 border rounded-lg px-4 py-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{loc.name}</span>
                          {loc.parent_id && parentMap.has(loc.parent_id) && (
                            <span className="text-xs text-muted-foreground">
                              ← {parentMap.get(loc.parent_id)}
                            </span>
                          )}
                        </div>
                        {loc.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{loc.description}</p>
                        )}
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button onClick={() => startEdit(loc)} className="p-1.5 rounded hover:bg-muted" title="编辑">
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => handleDelete(loc.id)} className="p-1.5 rounded hover:bg-red-50 hover:text-red-500" title="删除">
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
