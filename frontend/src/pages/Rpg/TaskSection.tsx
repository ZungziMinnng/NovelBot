import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ScrollText, X } from 'lucide-react'
import { rpgApi, type RpgStatDef, type RpgTask } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { ACCENT, AddRow, Assist, DeleteButton, INPUT, Section } from './rpgUi'
import EffectEditor from './EffectEditor'
import BatchGenerate from './BatchGenerate'
import { effectChips } from './effectChips'

const CATEGORIES = ['主线', '支线', '日常'] as const

interface TaskForm {
  name: string
  description: string
  objective: string
  category: string
  effects: Record<string, number>
  auto_start: boolean
}

const EMPTY: TaskForm = {
  name: '', description: '', objective: '', category: '支线',
  effects: {}, auto_start: false,
}

/** 任务定义。和技能、道具不同的是：它不由玩家「使用」，而是挂在任务栏上提醒，
 *  等剧情里办成了，模型提名、玩家点头才算完——所以 `objective` 那一栏格外要紧，
 *  它是判定完成与否的**唯一**依据，写虚了模型就会乱认。 */
export default function TaskSection({
  moduleId, statDefs, assistContext,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
}) {
  const qc = useQueryClient()
  const { data: tasks = [] } = useQuery({
    queryKey: ['rpg-tasks', moduleId],
    queryFn: () => rpgApi.tasks.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<TaskForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-tasks', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  const startEdit = (task: RpgTask) => {
    setEditingId(task.id)
    setForm({
      name: task.name, description: task.description, objective: task.objective,
      category: task.category, effects: task.effects || {}, auto_start: task.auto_start,
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    const payload = { ...form, name: form.name.trim(), objective: form.objective.trim() }
    try {
      if (editingId) {
        await rpgApi.tasks.update(editingId, payload)
      } else {
        await rpgApi.tasks.create(moduleId, { ...payload, sort_order: tasks.length + 1 })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存任务失败')
    }
  }

  const remove = async (task: RpgTask) => {
    if (!await confirmDialog({
      title: `确认删除任务「${task.name}」？`,
      detail: '已经开的局里，任务栏上的同名待办还在，只是办完了不再发奖励。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.tasks.delete(task.id)
      refresh()
    } catch {
      toast.error('删除任务失败')
    }
  }

  const renderForm = () => (
    <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑任务' : '新增任务'}</span>
        <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input
          value={form.name}
          onChange={e => setForm({ ...form, name: e.target.value })}
          placeholder="任务名，如：送信给老周"
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
      {/* 这一栏单独占一行、单独给说明：AI 判定「算不算办完」只看它 */}
      <div>
        <label className="text-xs font-medium mb-1.5 block">怎样才算办完</label>
        <input
          value={form.objective}
          onChange={e => setForm({ ...form, objective: e.target.value })}
          placeholder="写一件看得见的事，如：把信交到老周手上"
          className={INPUT}
        />
        <p className="text-xs text-muted-foreground mt-1.5">
          AI 判断这桩事办没办完，只看这一句。写成能在正文里读出来的动作，
          别写「让老周信任你」这种看不见的心情。
        </p>
      </div>
      <div>
        <textarea
          value={form.description}
          onChange={e => setForm({ ...form, description: e.target.value })}
          placeholder="谁托付的、为什么要办、办不成会怎样……"
          className={`${INPUT} resize-y min-h-[4rem]`}
        />
        <Assist
          moduleId={moduleId}
          field="task_description"
          context={() => ({
            ...assistContext(), 任务名: form.name, 分类: form.category, 完成标准: form.objective,
          })}
          value={form.description}
          onApply={v => setForm(f => ({ ...f, description: v }))}
        />
      </div>
      <EffectEditor
        label="办成之后的奖励"
        defs={statDefs}
        value={form.effects}
        onChange={v => setForm({ ...form, effects: v })}
      />
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={form.auto_start}
          onChange={e => setForm({ ...form, auto_start: e.target.checked })}
          className="accent-[hsl(var(--primary))]"
        />
        <span className="text-xs">
          开局就接下
          <span className="text-muted-foreground">（不勾的话，要在剧情里被托付）</span>
        </span>
      </label>
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
  )

  return (
    <Section
      title="任务"
      desc="玩家手上欠着的事。剧情里办成了，由 AI 提名、玩家确认才算完，奖励那时才到账。勾上「开局就接下」的，新开的局一上来就在任务栏里。"
      icon={ScrollText}
      accent={ACCENT.task}
    >
      <div className="space-y-2">
        {tasks.map(task => (
          <div key={task.id} className="space-y-2">
          <div className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{task.name}</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  {task.category}
                </span>
                {Object.entries(task.effects || {}).map(([k, v]) => (
                  <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    {k}{v > 0 ? `+${v}` : v}
                  </span>
                ))}
                {task.auto_start && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    开局就接下
                  </span>
                )}
              </div>
              {task.objective && (
                <p className="text-xs mt-1.5" style={{ color: `hsl(${ACCENT.task})` }}>
                  办完的标准：{task.objective}
                </p>
              )}
              {task.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{task.description}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(task)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(task)} />
            </div>
          </div>
          {showForm && editingId === task.id && renderForm()}
          </div>
        ))}

        {showForm && editingId === null && renderForm()}
        {!showForm && (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加任务</AddRow>
            <BatchGenerate<{
              name: string; description: string; objective: string
              category: string; auto_start: boolean; effects: Record<string, number>
            }>
              moduleId={moduleId}
              kind="task"
              placeholder="想生成什么任务？比如：生成几桩镖局里接得到的差事"
              renderRow={(task) => (
                <>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{task.category}</span>
                  {task.objective && (
                    <span className="text-[11px] text-muted-foreground">办完的标准：{task.objective}</span>
                  )}
                  {effectChips(task.effects)}
                </>
              )}
              onApply={async (list) => {
                for (const task of list) {
                  await rpgApi.tasks.create(moduleId, {
                    name: task.name, description: task.description, objective: task.objective,
                    category: task.category, auto_start: task.auto_start, effects: task.effects,
                    sort_order: tasks.length + 1,
                  })
                }
                await refresh()
              }}
            />
          </div>
        )}
      </div>
    </Section>
  )
}
