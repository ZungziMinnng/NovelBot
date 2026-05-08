import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Loader2, Search } from 'lucide-react'
import { factionsApi, locationsApi, type Faction, type Location } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  novelId: number
}

const ALIGNMENTS = ['全部', '正派', '邪派', '中立'] as const
const POWER_LEVELS = ['', '顶尖', '一流', '二流', '三流'] as const

const ALIGNMENT_COLORS: Record<string, string> = {
  正派: 'bg-green-500/20 text-green-400',
  邪派: 'bg-red-500/20 text-red-400',
  中立: 'bg-gray-500/20 text-gray-400',
}

export default function FactionsView({ novelId }: Props) {
  const qc = useQueryClient()
  const { data: factions = [] } = useQuery({
    queryKey: ['factions', novelId],
    queryFn: () => factionsApi.list(novelId),
  })
  const { data: locations = [] } = useQuery({
    queryKey: ['locations', novelId],
    queryFn: () => locationsApi.list(novelId),
  })

  const [search, setSearch] = useState('')
  const [filterAlignment, setFilterAlignment] = useState('全部')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [saving, setSaving] = useState(false)
  const [listRatio, setListRatio] = useState(0.4)
  const containerRef = useRef<HTMLDivElement>(null)

  const filtered = factions.filter((f) => {
    if (filterAlignment !== '全部' && f.alignment !== filterAlignment) return false
    if (search && !f.name.includes(search) && !f.type.includes(search)) return false
    return true
  })

  const selected = factions.find((f) => f.id === selectedId) || null

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const container = containerRef.current
    if (!container) return
    const startY = e.clientY
    const startRatio = listRatio
    const containerH = container.clientHeight
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientY - startY
      const newRatio = Math.max(0.2, Math.min(0.75, startRatio + delta / containerH))
      setListRatio(newRatio)
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [listRatio])

  return (
    <div ref={containerRef} className="flex flex-col h-full">
      {/* List section */}
      <div className="flex flex-col shrink-0 overflow-hidden" style={selected ? { height: `${listRatio * 100}%` } : { flex: 1 }}>
        {/* Header */}
        <div className="flex items-center justify-between px-3 pt-3 pb-1 shrink-0">
          <span className="text-xs text-muted-foreground font-medium">势力列表 ({factions.length})</span>
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1 text-xs px-2 py-1 text-primary hover:bg-muted rounded transition-colors"
          >
            <Plus className="w-3 h-3" /> 新建
          </button>
        </div>

        {/* Search + Filter */}
        <div className="flex gap-1.5 px-3 pb-2 shrink-0">
          <div className="flex-1 relative">
            <Search className="w-3 h-3 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索势力..."
              className="w-full border rounded-lg pl-7 pr-2 py-1.5 text-xs bg-background"
            />
          </div>
          <select
            value={filterAlignment}
            onChange={(e) => setFilterAlignment(e.target.value)}
            className="border rounded-lg px-2 py-1.5 text-xs bg-background"
          >
            {ALIGNMENTS.map((a) => <option key={a} value={a}>{a === '全部' ? '全部立场' : a}</option>)}
          </select>
        </div>

        {/* List */}
        <div className="overflow-y-auto flex-1 px-2">
          {filtered.map((f) => (
            <div
              key={f.id}
              onClick={() => setSelectedId(selectedId === f.id ? null : f.id)}
              className={`group flex items-center gap-2 px-2 py-2 rounded-lg cursor-pointer transition-colors mb-0.5 ${
                selectedId === f.id ? 'bg-muted ring-1 ring-primary' : 'hover:bg-muted'
              }`}
            >
              <div
                className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-[10px] font-bold text-white"
                style={{ backgroundColor: f.color || '#6b7280' }}
              >
                {f.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium truncate">{f.name}</span>
                  {f.alignment && (
                    <span className={`text-[10px] px-1.5 py-px rounded ${ALIGNMENT_COLORS[f.alignment] || ALIGNMENT_COLORS['中立']}`}>
                      {f.alignment}
                    </span>
                  )}
                </div>
                {f.type && (
                  <p className="text-xs text-muted-foreground truncate">{f.type}</p>
                )}
              </div>
              {f.power_level && (
                <span className="text-[10px] text-muted-foreground shrink-0">{f.power_level}</span>
              )}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-6">
              {factions.length === 0 ? '暂无势力' : '无匹配结果'}
            </p>
          )}
        </div>
      </div>

      {/* Resize handle + Detail */}
      {selected && (
        <>
          <div
            onMouseDown={handleDragStart}
            className="h-1.5 shrink-0 cursor-row-resize hover:bg-primary/30 active:bg-primary/50 transition-colors border-y"
          />
          <FactionDetail
            faction={selected}
            locations={locations}
            novelId={novelId}
            onClose={() => setSelectedId(null)}
          />
        </>
      )}

      {/* Add Modal */}
      {adding && (
        <AddFactionModal
          novelId={novelId}
          saving={saving}
          onSave={async (data) => {
            setSaving(true)
            try {
              await factionsApi.create({ ...data, novel_id: novelId })
              qc.invalidateQueries({ queryKey: ['factions', novelId] })
              setAdding(false)
            } finally { setSaving(false) }
          }}
          onCancel={() => setAdding(false)}
        />
      )}
    </div>
  )
}

// ── Faction Detail (inline edit form) ────────────────────────────────────────

const DETAIL_TABS: { key: 'description' | 'goals' | 'traits' | 'history'; label: string }[] = [
  { key: 'description', label: '描述' },
  { key: 'goals', label: '目标' },
  { key: 'traits', label: '特点' },
  { key: 'history', label: '历史' },
]

function FactionDetail({ faction, locations, novelId, onClose }: {
  faction: Faction
  locations: Location[]
  novelId: number
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState(toForm(faction))
  const [saving, setSaving] = useState(false)
  const [detailTab, setDetailTab] = useState<'description' | 'goals' | 'traits' | 'history'>('description')

  useEffect(() => { setForm(toForm(faction)) }, [faction.id])

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      await factionsApi.update(faction.id, form)
      qc.invalidateQueries({ queryKey: ['factions', novelId] })
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!confirm('确认删除该势力？')) return
    await factionsApi.delete(faction.id)
    qc.invalidateQueries({ queryKey: ['factions', novelId] })
    toast.success('已删除')
    onClose()
  }

  const set = (key: string, val: string | number | null) => setForm({ ...form, [key]: val })

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="px-3 pt-2 pb-1 flex items-center justify-between shrink-0">
        <span className="text-xs font-medium text-muted-foreground">势力详情</span>
        <button onClick={handleDelete} className="p-1 hover:text-destructive transition-colors">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-2 space-y-2">
        {/* Two-column fields */}
        <div className="grid grid-cols-2 gap-2">
          <Field label="势力名称" value={form.name} onChange={(v) => set('name', v)} />
          <Field label="势力类型" value={form.type} onChange={(v) => set('type', v)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <SelectField label="实力等级" value={form.power_level} onChange={(v) => set('power_level', v)} options={POWER_LEVELS as unknown as string[]} />
          <SelectField label="立场" value={form.alignment} onChange={(v) => set('alignment', v)} options={['正派', '邪派', '中立']} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Field label="领袖" value={form.leader} onChange={(v) => set('leader', v)} />
          <Field label="总部位置" value={form.headquarters} onChange={(v) => set('headquarters', v)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-[10px] text-muted-foreground">关联地图</label>
            <select
              value={form.location_id ?? ''}
              onChange={(e) => set('location_id', e.target.value ? Number(e.target.value) : null)}
              className="w-full border rounded px-2 py-2 text-sm bg-background"
            >
              <option value="">无</option>
              {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </div>
          <Field label="成员数量" value={form.member_count} onChange={(v) => set('member_count', v)} placeholder="如：数百人、上万人等" />
        </div>

        {/* Color */}
        <div>
          <label className="text-[10px] text-muted-foreground">代表颜色</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={form.color || '#6b7280'}
              onChange={(e) => set('color', e.target.value)}
              className="w-8 h-8 rounded border cursor-pointer"
            />
            <input
              value={form.color}
              onChange={(e) => set('color', e.target.value)}
              placeholder="#8b5cf6"
              className="flex-1 border rounded px-2 py-2 text-sm bg-background font-mono"
            />
          </div>
        </div>

        {/* Tabbed textareas */}
        <div>
          <div className="flex border-b mb-1.5">
            {DETAIL_TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setDetailTab(key)}
                className={`px-2.5 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                  detailTab === key ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea
            value={form[detailTab]}
            onChange={(e) => set(detailTab, e.target.value)}
            rows={5}
            className="w-full border rounded px-2 py-2 text-sm bg-background resize-y"
          />
        </div>
      </div>

      <div className="px-3 py-2 shrink-0">
        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin mx-auto" /> : '保存'}
        </button>
      </div>
    </div>
  )
}

// ── Add Modal ────────────────────────────────────────────────────────────────

function AddFactionModal({ novelId, saving, onSave, onCancel }: {
  novelId: number
  saving: boolean
  onSave: (data: { name: string; type: string; alignment: string }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [alignment, setAlignment] = useState('中立')

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onCancel}>
      <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-medium">新建势力</h3>
        <input
          placeholder="势力名称"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
          autoFocus
        />
        <input
          placeholder="势力类型"
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
        />
        <select
          value={alignment}
          onChange={(e) => setAlignment(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
        >
          {['正派', '邪派', '中立'].map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
          <button
            onClick={() => name.trim() && onSave({ name, type, alignment })}
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

// ── Helpers ──────────────────────────────────────────────────────────────────

function toForm(f: Faction) {
  return {
    name: f.name, type: f.type, power_level: f.power_level, alignment: f.alignment,
    leader: f.leader, headquarters: f.headquarters, location_id: f.location_id,
    member_count: f.member_count, color: f.color, description: f.description,
    goals: f.goals, traits: f.traits, history: f.history,
  }
}

function Field({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string
}) {
  return (
    <div>
      <label className="text-[10px] text-muted-foreground">{label}</label>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
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
        rows={3}
        className="w-full border rounded px-2 py-2 text-sm bg-background resize-y"
      />
    </div>
  )
}
