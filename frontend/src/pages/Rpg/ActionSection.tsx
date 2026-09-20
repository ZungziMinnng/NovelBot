import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { MousePointerClick, X } from 'lucide-react'
import {
  rpgApi, type RpgAction, type RpgCondition, type RpgNpc, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import { AddRow, DeleteButton, INPUT, Section } from './rpgUi'
import ConditionEditor from './ConditionEditor'
import ActionFields, { type ActionDraft } from './ActionFields'
import { ActionPresetBar } from './PresetTools'
import BatchGenerate from './BatchGenerate'
import { effectChips } from './effectChips'

/** 表单体在 ActionFields 里，这儿多两样只属于本模组的：可用条件和地点限定。
 *  两者引用的角色名、道具名、时段、地点名都是这个模组特有的，搬到别的模组
 *  一条都对不上，所以都不跟着动作套装走 */
type ActionForm = ActionDraft & { requires: RpgCondition; at_location: string }

const EMPTY: ActionForm = {
  name: '', prompt_hint: '', effects: {}, relation_effects: {}, requires: {}, needs_target: false,
  target_anywhere: false, summons_target: false, group: '', cost_slot: false, at_location: '',
}

/** 动作按钮。点一次数值由引擎算死，AI 完全碰不到，只拿到「已经发生的事实」去写文字。 */
export default function ActionSection({
  moduleId, statDefs, relationDefs, npcs, slotNames, example = '奖励', onAddStats,
  title = '动作按钮', desc,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
  /** 空格子里的示例词，按玩法类别换（见 stylePresets.STYLE_EXAMPLES） */
  example?: string
  /** 套动作套装时一键补建缺的数值。数值表不在这一层，得让模组页去写 */
  onAddStats: (stats: RpgStatDef[], relations: RpgStatDef[]) => void
  /** 模拟器里这些按钮就是主界面本身，不是「额外给的快捷路」，所以标题和说明可换 */
  title?: string
  desc?: string
}) {
  const qc = useQueryClient()
  const { data: actions = [] } = useQuery({
    queryKey: ['rpg-actions', moduleId],
    queryFn: () => rpgApi.actions.list(moduleId),
  })
  // 地点只用来填 at_location 那个下拉。列表本身在 LocationSection 里管，
  // 这里跟着同一个 queryKey 走，那边增删地点这边的下拉自动跟上
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId),
  })
  const groups = [...new Set(actions.map(a => (a.group || '').trim()).filter(Boolean))]

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<ActionForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-actions', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」 */
  const body = () => ({ ...form, name: form.name.trim() })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，存个空名字进去，
   *  按钮上就是一行没有名字的东西，而用户只是把它清了准备重打。
   *  新建的动作还没有 id，整份等「添加」一起提交 */
  const autosave = useFormAutosave(
    editingId !== null && form.name.trim() ? { id: editingId, body: body() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.actions.update(id, body)
      refresh()
    },
  )

  const startEdit = (action: RpgAction) => {
    // 换一条之前先把上一条欠着的那一次存掉。待存的那一份只有最新一格，
    // 不补发的话它会被下一条的草稿顶掉
    void autosave.flush()
    setEditingId(action.id)
    setForm({
      name: action.name, prompt_hint: action.prompt_hint,
      effects: action.effects || {}, relation_effects: action.relation_effects || {},
      requires: action.requires || {}, needs_target: action.needs_target,
      target_anywhere: !!action.target_anywhere, summons_target: !!action.summons_target,
      group: action.group || '', cost_slot: !!action.cost_slot,
      at_location: action.at_location || '',
    })
    setShowForm(true)
  }

  /** 收起表单。改过的东西已经存进库了，所以这里没得「取消」——但没存成的时候
   *  不能收：收了就等于把改动默默扔掉，而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      await rpgApi.actions.create(moduleId, { ...body(), sort_order: actions.length + 1 })
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

  const renderForm = () => (
    <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑动作' : '新增动作'}</span>
        <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
      </div>
      <ActionFields
        value={form}
        onChange={next => setForm({ ...form, ...next })}
        statDefs={statDefs}
        relationDefs={relationDefs}
        example={example}
        groups={groups}
        hasClock={slotNames.length > 0}
      />
      {locations.length > 0 && (
        <div>
          <label className="text-xs font-medium mb-1.5 block">只在这个地点可用</label>
          <select
            value={form.at_location}
            onChange={e => setForm({ ...form, at_location: e.target.value })}
            className={INPUT}
          >
            <option value="">随处可用</option>
            {locations.map(l => <option key={l.id} value={l.name}>{l.name}</option>)}
          </select>
          <p className="text-xs text-muted-foreground mt-1.5">
            人不在那儿时按钮置灰。改了地点名记得回来重选一次——这里存的是名字。
          </p>
        </div>
      )}
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
      <div className="flex items-center gap-2">
        {editingId !== null && (
          <span className="mr-auto">
            <SaveBadge
              state={autosave.state}
              blocked="名字还空着，先不存"
              onRetry={autosave.flush}
            />
          </span>
        )}
        <button onClick={editingId ? close : reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
          {editingId ? '收起' : '取消'}
        </button>
        <button
          onClick={editingId ? autosave.flush : submit}
          disabled={!form.name.trim()}
          className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
        >
          {editingId ? '立即保存' : '添加'}
        </button>
      </div>
    </div>
  )

  return (
    <Section
      title={title}
      desc={desc ?? '玩家一直能自由打字，这些按钮是额外给的快捷路：点一次数字精确变化，不经过 AI。'}
      icon={MousePointerClick}
    >
      <div className="space-y-2">
        <ActionPresetBar
          moduleId={moduleId}
          actions={actions}
          statDefs={statDefs}
          relationDefs={relationDefs}
          onAddStats={onAddStats}
        />
        {actions.map(action => (
          <div key={action.id} className="space-y-2">
          <div className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                {action.group && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {action.group}
                  </span>
                )}
                <span className="text-sm font-medium">{action.name}</span>
                {action.needs_target && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    {action.target_anywhere ? '要选对象·可远程' : '要选对象'}
                  </span>
                )}
                {action.summons_target && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    叫到身边
                  </span>
                )}
                {action.cost_slot && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    费一格时段
                  </span>
                )}
                {action.at_location && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    限{action.at_location}
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
          {showForm && editingId === action.id && renderForm()}
          </div>
        ))}

        {showForm && editingId === null && renderForm()}
        {!showForm && (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加动作</AddRow>
            <BatchGenerate<{
              name: string; prompt_hint: string; needs_target: boolean
              effects: Record<string, number>; relation_effects: Record<string, number>
              group?: string
            }>
              moduleId={moduleId}
              kind="action"
              placeholder="想生成什么动作按钮？比如：几个和 NPC 拉近关系的社交动作"
              renderRow={(a) => (
                <>
                  {a.group && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                      {a.group}
                    </span>
                  )}
                  {effectChips(a.effects)}
                  {effectChips(a.relation_effects, true)}
                </>
              )}
              onApply={async (acts) => {
                for (const a of acts) {
                  await rpgApi.actions.create(moduleId, {
                    name: a.name, prompt_hint: a.prompt_hint, needs_target: a.needs_target,
                    effects: a.effects, relation_effects: a.relation_effects,
                    group: a.group || '',
                    sort_order: actions.length + 1,
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
