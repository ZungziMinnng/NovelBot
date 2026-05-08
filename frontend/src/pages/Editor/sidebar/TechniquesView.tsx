import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Loader2, Search, ArrowRightLeft } from 'lucide-react'
import { techniquesApi, type Technique } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  novelId: number
  onSelectTechnique?: (id: number) => void
  selectedTechniqueId?: number | null
}

const TYPES = ['全部', '功法', '武技', '身法', '秘术', '阵法'] as const
const POWER_LEVELS = ['', '顶尖', '一流', '二流', '三流'] as const

const TYPE_COLORS: Record<string, string> = {
  功法: 'bg-amber-500/20 text-amber-400',
  武技: 'bg-red-500/20 text-red-400',
  身法: 'bg-sky-500/20 text-sky-400',
  秘术: 'bg-purple-500/20 text-purple-400',
  阵法: 'bg-green-500/20 text-green-400',
}

export default function TechniquesView({ novelId, onSelectTechnique, selectedTechniqueId }: Props) {
  const qc = useQueryClient()
  const { data: techniques = [] } = useQuery({
    queryKey: ['techniques', novelId],
    queryFn: () => techniquesApi.list(novelId),
  })

  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('全部')
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [transferMenuId, setTransferMenuId] = useState<number | null>(null)

  const handleTransferToEntity = async (t: Technique, targetType: 'item' | 'system') => {
    setTransferMenuId(null)
    try {
      await techniquesApi.convertToEntity(t.id, targetType)
      qc.invalidateQueries({ queryKey: ['techniques', novelId] })
      qc.invalidateQueries({ queryKey: ['entities', novelId, targetType] })
      toast.success(`已将「${t.name}」移至${targetType === 'item' ? '道具' : '系统'}`)
    } catch { toast.error('移动失败') }
  }

  const filtered = techniques.filter((t) => {
    if (filterType !== '全部' && t.type !== filterType) return false
    if (search && !t.name.includes(search) && !t.type.includes(search)) return false
    return true
  })

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 pt-3 pb-1">
        <span className="text-xs text-muted-foreground font-medium">功法列表 ({techniques.length})</span>
        <button
          onClick={() => setAdding(true)}
          className="flex items-center gap-1 text-xs px-2 py-1 text-primary hover:bg-muted rounded transition-colors"
        >
          <Plus className="w-3 h-3" /> 新建
        </button>
      </div>

      <div className="flex gap-1.5 px-3 pb-2">
        <div className="flex-1 relative">
          <Search className="w-3 h-3 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索功法..."
            className="w-full border rounded-lg pl-7 pr-2 py-1.5 text-xs bg-background"
          />
        </div>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          className="border rounded-lg px-2 py-1.5 text-xs bg-background"
        >
          {TYPES.map((t) => <option key={t} value={t}>{t === '全部' ? '全部类型' : t}</option>)}
        </select>
      </div>

      <div className="overflow-y-auto flex-1 px-2">
        {filtered.map((t) => (
          <div
            key={t.id}
            onClick={() => onSelectTechnique?.(t.id)}
            className={`group flex items-center gap-2 px-2 py-2 rounded-lg cursor-pointer transition-colors mb-0.5 relative ${
              selectedTechniqueId === t.id ? 'bg-muted ring-1 ring-primary' : 'hover:bg-muted'
            }`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium truncate">{t.name}</span>
                {t.type && (
                  <span className={`text-[10px] px-1.5 py-px rounded ${TYPE_COLORS[t.type] || 'bg-gray-500/20 text-gray-400'}`}>
                    {t.type}
                  </span>
                )}
              </div>
              {t.practitioners && (
                <p className="text-xs text-muted-foreground truncate">使用者：{t.practitioners}</p>
              )}
            </div>
            <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
              <button
                onClick={(e) => { e.stopPropagation(); setTransferMenuId(transferMenuId === t.id ? null : t.id) }}
                className="p-1 hover:text-primary"
                title="转移"
              >
                <ArrowRightLeft className="w-3 h-3" />
              </button>
              {t.power_level && (
                <span className="text-[10px] text-muted-foreground">{t.power_level}</span>
              )}
            </div>
            {transferMenuId === t.id && (
              <div
                className="absolute right-0 top-full z-20 bg-popover border rounded-lg shadow-md py-1 min-w-[100px]"
                onClick={(e) => e.stopPropagation()}
              >
                <p className="text-[10px] text-muted-foreground px-3 py-1">移至</p>
                <button
                  onClick={() => handleTransferToEntity(t, 'item')}
                  className="w-full text-left text-xs px-3 py-1.5 hover:bg-muted transition-colors"
                >
                  道具
                </button>
                <button
                  onClick={() => handleTransferToEntity(t, 'system')}
                  className="w-full text-left text-xs px-3 py-1.5 hover:bg-muted transition-colors"
                >
                  系统
                </button>
              </div>
            )}
          </div>
        ))}
        {filtered.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-6">
            {techniques.length === 0 ? '暂无功法' : '无匹配结果'}
          </p>
        )}
      </div>

      {adding && (
        <AddTechniqueModal
          saving={saving}
          onSave={async (data) => {
            setSaving(true)
            try {
              await techniquesApi.create({ ...data, novel_id: novelId })
              qc.invalidateQueries({ queryKey: ['techniques', novelId] })
              setAdding(false)
            } finally { setSaving(false) }
          }}
          onCancel={() => setAdding(false)}
        />
      )}
    </div>
  )
}

export function TechniqueDetail({ technique, novelId, onClose }: {
  technique: Technique
  novelId: number
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState(toForm(technique))
  const [saving, setSaving] = useState(false)

  useEffect(() => { setForm(toForm(technique)) }, [technique.id])

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await techniquesApi.update(technique.id, form)
      qc.invalidateQueries({ queryKey: ['techniques', novelId] })
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirm('确认删除该功法？')) return
    await techniquesApi.delete(technique.id)
    qc.invalidateQueries({ queryKey: ['techniques', novelId] })
    toast.success('已删除')
    onClose()
  }

  const set = (key: string, val: string) => setForm({ ...form, [key]: val })

  return (
    <div className="px-3 py-3 space-y-2.5 overflow-y-auto">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">功法详情</span>
        <button onClick={handleDelete} className="p-1 hover:text-destructive transition-colors">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="名称" value={form.name} onChange={(v) => set('name', v)} />
        <SelectField label="类型" value={form.type} onChange={(v) => set('type', v)} options={['功法', '武技', '身法', '秘术', '阵法']} />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SelectField label="威力等级" value={form.power_level} onChange={(v) => set('power_level', v)} options={POWER_LEVELS as unknown as string[]} />
        <Field label="使用者" value={form.practitioners} onChange={(v) => set('practitioners', v)} />
      </div>

      <TextareaField label="描述" value={form.description} onChange={(v) => set('description', v)} />

      <button
        onClick={handleSave}
        disabled={saving}
        className="w-full px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50"
      >
        {saving ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : '保存'}
      </button>
    </div>
  )
}

function AddTechniqueModal({ saving, onSave, onCancel }: {
  saving: boolean
  onSave: (data: { name: string; type: string }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [type, setType] = useState('功法')

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-medium">新建功法</h3>
        <input
          placeholder="功法名称"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
          autoFocus
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
        >
          {['功法', '武技', '身法', '秘术', '阵法'].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
          <button
            onClick={() => name.trim() && onSave({ name, type })}
            disabled={saving}
            className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

function toForm(t: Technique) {
  return {
    name: t.name, type: t.type, description: t.description,
    practitioners: t.practitioners, power_level: t.power_level,
  }
}

function Field({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-[10px] text-muted-foreground">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded px-2 py-2 text-sm bg-background"
      />
    </div>
  )
}

function SelectField({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: string[]
}) {
  return (
    <div>
      <label className="text-[10px] text-muted-foreground">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full border rounded px-2 py-2 text-sm bg-background"
      >
        {options.map((o) => <option key={o} value={o}>{o || '—'}</option>)}
      </select>
    </div>
  )
}

function TextareaField({ label, value, onChange }: {
  label: string; value: string; onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-[10px] text-muted-foreground">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className="w-full border rounded px-2 py-2 text-sm bg-background resize-y"
      />
    </div>
  )
}
