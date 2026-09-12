import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MousePointerClick, X } from 'lucide-react'
import {
  rpgApi, type RpgAction, type RpgCondition, type RpgNpc, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { AddRow, DeleteButton, INPUT, Section } from './rpgUi'
import ConditionEditor from './ConditionEditor'
import EffectEditor from './EffectEditor'

interface ActionForm {
  name: string
  prompt_hint: string
  effects: Record<string, number>
  relation_effects: Record<string, number>
  requires: RpgCondition
  needs_target: boolean
}

const EMPTY: ActionForm = {
  name: '', prompt_hint: '', effects: {}, relation_effects: {}, requires: {}, needs_target: false,
}

/** 动作按钮。点一次数值由引擎算死，AI 完全碰不到，只拿到「已经发生的事实」去写文字。 */
export default function ActionSection({
  moduleId, statDefs, relationDefs, npcs, slotNames,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
}) {
  const qc = useQueryClient()
  const { data: actions = [] } = useQuery({
    queryKey: ['rpg-actions', moduleId],
    queryFn: () => rpgApi.actions.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ActionForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-actions', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  const startEdit = (action: RpgAction) => {
    setEditingId(action.id)
    setForm({
      name: action.name, prompt_hint: action.prompt_hint,
      effects: action.effects || {}, relation_effects: action.relation_effects || {},
      requires: action.requires || {}, needs_target: action.needs_target,
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      if (editingId) {
        await rpgApi.actions.update(editingId, { ...form, name: form.name.trim() })
      } else {
        await rpgApi.actions.create(moduleId, {
          ...form, name: form.name.trim(), sort_order: actions.length + 1,
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存动作失败')
    }
  }

  const remove = async (action: RpgAction) => {
    if (!await confirmDialog({
      title: `确认删除动作「${action.name}」？`, confirmText: '删除', danger: true,
    })) return
    try {
      await rpgApi.actions.delete(action.id)
      refresh()
    } catch {
      toast.error('删除动作失败')
    }
  }

  return (
    <Section
      title="动作按钮"
      desc="玩家一直能自由打字，这些按钮是额外给的快捷路：点一次数字精确变化，不经过 AI。"
      icon={MousePointerClick}
    >
      <div className="space-y-2">
        {actions.map(action => (
          <div key={action.id} className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{action.name}</span>
                {action.needs_target && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    要选对象
                  </span>
                )}
                {Object.entries(action.effects || {}).map(([k, v]) => (
                  <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    {k}{v > 0 ? `+${v}` : v}
                  </span>
                ))}
                {Object.entries(action.relation_effects || {}).map(([k, v]) => (
                  <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-pink-500/10 text-pink-700 dark:text-pink-300">
                    对方{k}{v > 0 ? `+${v}` : v}
                  </span>
                ))}
              </div>
              {action.prompt_hint && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{action.prompt_hint}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(action)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(action)} />
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑动作' : '新增动作'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <input
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="按钮上的字，如：奖励"
              className={INPUT}
            />
            <div>
              <textarea
                value={form.prompt_hint}
                onChange={e => setForm({ ...form, prompt_hint: e.target.value })}
                placeholder="你摸了摸她的头，夸了她一句。"
                className={`${INPUT} resize-y min-h-[4rem]`}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                点了按钮等于玩家说了这句话。用第二人称写，写得具体一点，GM 就照着这个往下展开。
              </p>
            </div>
            <EffectEditor
              label="玩家数值变化"
              defs={statDefs}
              value={form.effects}
              onChange={v => setForm({ ...form, effects: v })}
            />
            <EffectEditor
              label="对方的关系数值变化"
              defs={relationDefs}
              value={form.relation_effects}
              onChange={v => setForm({
                ...form,
                relation_effects: v,
                // 关系变化必须知道改谁，否则这一栏点了也不生效
                needs_target: Object.keys(v).length > 0 ? true : form.needs_target,
              })}
            />
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={form.needs_target}
                onChange={e => setForm({ ...form, needs_target: e.target.checked })}
                disabled={Object.keys(form.relation_effects).length > 0}
                className="accent-[hsl(var(--primary))] disabled:opacity-50"
              />
              <span className="text-xs">点之前先选一个在场角色</span>
            </label>
            <div>
              <label className="text-xs font-medium mb-1.5 block">可用条件</label>
              <ConditionEditor
                value={form.requires}
                onChange={v => setForm({ ...form, requires: v })}
                statDefs={statDefs}
                relationDefs={relationDefs}
                npcs={npcs}
                slotNames={slotNames}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                不满足时按钮置灰，鼠标移上去会写明差在哪。
              </p>
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
          <AddRow onClick={() => setShowForm(true)}>添加动作</AddRow>
        )}
      </div>
    </Section>
  )
}
