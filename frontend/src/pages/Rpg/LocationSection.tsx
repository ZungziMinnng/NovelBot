import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MapPin, X } from 'lucide-react'
import {
  rpgApi, type RpgCondition, type RpgLocation, type RpgNpc, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { AddRow, DeleteButton, INPUT, Section } from './rpgUi'
import ConditionEditor from './ConditionEditor'

interface LocForm {
  name: string
  description: string
  connections: string[]
  enter_requires: RpgCondition
}

const EMPTY: LocForm = { name: '', description: '', connections: [], enter_requires: {} }

/** 地点。connections 存名字不存 id——NPC 的常驻地点本来就是字符串，
 *  用 id 会凭空多一套映射，改个地点名就对不上了。 */
export default function LocationSection({
  moduleId, statDefs, relationDefs, npcs,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
}) {
  const qc = useQueryClient()
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<LocForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-locations', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  const startEdit = (loc: RpgLocation) => {
    setEditingId(loc.id)
    setForm({
      name: loc.name, description: loc.description,
      connections: loc.connections || [], enter_requires: loc.enter_requires || {},
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      if (editingId) {
        await rpgApi.locations.update(editingId, { ...form, name: form.name.trim() })
      } else {
        await rpgApi.locations.create(moduleId, {
          ...form, name: form.name.trim(), sort_order: locations.length + 1,
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存地点失败')
    }
  }

  const remove = async (loc: RpgLocation) => {
    if (!await confirmDialog({
      title: `确认删除地点「${loc.name}」？`,
      detail: '别的地点连到它的那条路也会断掉。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.locations.delete(loc.id)
      refresh()
    } catch {
      toast.error('删除地点失败')
    }
  }

  const others = locations.filter(l => l.id !== editingId).map(l => l.name)
  const toggleLink = (name: string) => setForm(prev => ({
    ...prev,
    connections: prev.connections.includes(name)
      ? prev.connections.filter(n => n !== name)
      : [...prev.connections, name],
  }))

  return (
    <Section
      title="地点"
      desc="连起来才走得通。一个地点都不定义时移动不受限制，定义了就按图走。"
      icon={MapPin}
    >
      <div className="space-y-2">
        {locations.map(loc => (
          <div key={loc.id} className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{loc.name}</span>
                {(loc.connections || []).map(c => (
                  <span key={c} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    → {c}
                  </span>
                ))}
                {Object.keys(loc.enter_requires || {}).length > 0 && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">
                    有进入条件
                  </span>
                )}
              </div>
              {loc.description && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{loc.description}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(loc)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(loc)} />
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑地点' : '新增地点'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="地点名，如：地窖"
              className={INPUT}
            />
            <textarea
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="走进来看到什么、闻到什么、有什么不对劲……"
              className={`${INPUT} resize-y min-h-[4rem]`}
            />
            <div>
              <label className="text-xs font-medium mb-1.5 block">能走到哪</label>
              {others.length === 0 ? (
                <p className="text-xs text-muted-foreground">先多加几个地点，才能连起来。</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {others.map(name => (
                    <button
                      key={name}
                      onClick={() => toggleLink(name)}
                      className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                        form.connections.includes(name)
                          ? 'bg-primary/15 text-primary border-primary/40'
                          : 'hover:bg-muted text-muted-foreground'
                      }`}
                    >
                      {name}
                    </button>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground mt-1.5">
                两边只要有一边连上就走得通，不用两头都点一遍。
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1.5 block">进入条件</label>
              <ConditionEditor
                value={form.enter_requires}
                onChange={v => setForm({ ...form, enter_requires: v })}
                statDefs={statDefs}
                relationDefs={relationDefs}
                npcs={npcs}
              />
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
          <AddRow onClick={() => setShowForm(true)}>添加地点</AddRow>
        )}
      </div>
    </Section>
  )
}
