import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Package, X } from 'lucide-react'
import { rpgApi, type RpgItem, type RpgStatDef } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { AddRow, DeleteButton, INPUT, Section } from './rpgUi'
import EffectEditor from './EffectEditor'

const CATEGORIES = ['消耗品', '装备', '关键道具'] as const

interface ItemForm {
  name: string
  description: string
  category: string
  usable: boolean
  consumable: boolean
  effects: Record<string, number>
}

const EMPTY: ItemForm = {
  name: '', description: '', category: '消耗品', usable: true, consumable: true, effects: {},
}

/** 道具定义。玩家「使用」时数值由引擎按 effects 精确增减，AI 只负责写成画面。 */
export default function ItemSection({
  moduleId, statDefs,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
}) {
  const qc = useQueryClient()
  const { data: items = [] } = useQuery({
    queryKey: ['rpg-items', moduleId],
    queryFn: () => rpgApi.items.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ItemForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-items', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  const startEdit = (item: RpgItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name, description: item.description, category: item.category,
      usable: item.usable, consumable: item.consumable, effects: item.effects || {},
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      if (editingId) {
        await rpgApi.items.update(editingId, { ...form, name: form.name.trim() })
      } else {
        await rpgApi.items.create(moduleId, { ...form, name: form.name.trim(), sort_order: items.length + 1 })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存道具失败')
    }
  }

  const remove = async (item: RpgItem) => {
    if (!await confirmDialog({
      title: `确认删除道具「${item.name}」？`,
      detail: '已经开的局里，背包里的同名物品还在，只是用不出效果了。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.items.delete(item.id)
      refresh()
    } catch {
      toast.error('删除道具失败')
    }
  }

  return (
    <Section
      title="道具"
      desc="定义了效果的道具，用起来数字是死的，AI 改不了。没定义的东西也能进背包，只是没有精确效果。"
      icon={Package}
    >
      <div className="space-y-2">
        {items.map(item => (
          <div key={item.id} className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{item.name}</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  {item.category}
                </span>
                {Object.entries(item.effects || {}).map(([k, v]) => (
                  <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    {k}{v > 0 ? `+${v}` : v}
                  </span>
                ))}
                {!item.usable && (
                  <span className="text-[11px] text-muted-foreground">不可使用</span>
                )}
              </div>
              {item.description && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{item.description}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(item)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(item)} />
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑道具' : '新增道具'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="道具名，如：治伤药水"
                className={INPUT}
              />
              <select
                value={form.category}
                onChange={e => setForm({ ...form, category: e.target.value })}
                className={INPUT}
              >
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
            <textarea
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="它长什么样、哪来的、用起来是什么感觉……"
              className={`${INPUT} resize-y min-h-[4rem]`}
            />
            <EffectEditor
              label="使用时的数值变化"
              defs={statDefs}
              value={form.effects}
              onChange={v => setForm({ ...form, effects: v })}
            />
            <div className="flex gap-4">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.usable}
                  onChange={e => setForm({ ...form, usable: e.target.checked })}
                  className="accent-[hsl(var(--primary))]"
                />
                <span className="text-xs">背包里能点「使用」</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.consumable}
                  onChange={e => setForm({ ...form, consumable: e.target.checked })}
                  className="accent-[hsl(var(--primary))]"
                />
                <span className="text-xs">用一次就少一个</span>
              </label>
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button
                onClick={submit}
                disabled={!form.name.trim()}
                className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {editingId ? '保存' : '添加'}
              </button>
            </div>
          </div>
        ) : (
          <AddRow onClick={() => setShowForm(true)}>添加道具</AddRow>
        )}
      </div>
    </Section>
  )
}
