import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Zap, X } from 'lucide-react'
import {
  rpgApi, type RpgCondition, type RpgNpc, type RpgSkill, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import { ACCENT, AddRow, Assist, DeleteButton, INPUT, Section } from './rpgUi'
import EffectEditor from './EffectEditor'
import ConditionEditor from './ConditionEditor'
import BatchGenerate from './BatchGenerate'
import { effectChips } from './effectChips'

const CATEGORIES = ['主动', '被动'] as const

interface SkillForm {
  name: string
  description: string
  category: string
  usable: boolean
  effects: Record<string, number>
  requires: RpgCondition
  cooldown: number
  start_with: boolean
}

const EMPTY: SkillForm = {
  name: '', description: '', category: '主动',
  usable: true, effects: {}, requires: {}, cooldown: 0, start_with: false,
}

/** 技能定义。和道具同一条链：玩家「施展」时数值由引擎按 effects 精确增减，
 *  AI 只负责写成画面。比道具多的是冷却——用完要歇几回合，引擎自己算。 */
export default function SkillSection({
  moduleId, statDefs, relationDefs, npcs, slotNames, assistContext,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
}) {
  const qc = useQueryClient()
  const { data: skills = [] } = useQuery({
    queryKey: ['rpg-skills', moduleId],
    queryFn: () => rpgApi.skills.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<SkillForm>(EMPTY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-skills', moduleId] })
  const reset = () => { setForm(EMPTY); setEditingId(null); setShowForm(false) }

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」。被动技能没有「用一次」这回事，
   *  冷却填了也没地方生效，存之前清零 */
  const body = () => ({
    ...form,
    name: form.name.trim(),
    cooldown: form.category === '被动' ? 0 : Math.max(0, form.cooldown),
  })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，存个空名字进去，
   *  列表上就是一行没有名字的东西，而用户只是把它清了准备重打。
   *  新建的技能还没有 id，整份等「添加」一起提交 */
  const autosave = useFormAutosave(
    editingId !== null && form.name.trim() ? { id: editingId, body: body() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.skills.update(id, body)
      refresh()
    },
  )

  const startEdit = (skill: RpgSkill) => {
    // 换一条之前先把上一条欠着的那一次存掉。待存的那一份只有最新一格，
    // 不补发的话它会被下一条的草稿顶掉
    void autosave.flush()
    setEditingId(skill.id)
    setForm({
      name: skill.name, description: skill.description, category: skill.category,
      usable: skill.usable, effects: skill.effects || {},
      requires: (skill.requires || {}) as RpgCondition,
      cooldown: skill.cooldown, start_with: skill.start_with,
    })
    setShowForm(true)
  }

  /** 收起表单。改过的东西已经存进库了，所以这里没得「取消」——但没存成的时候
   *  不能收：收了就等于把改动默默扔掉，而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      await rpgApi.skills.create(moduleId, { ...body(), sort_order: skills.length + 1 })
      refresh()
      reset()
    } catch {
      toast.error('保存技能失败')
    }
  }

  const remove = async (skill: RpgSkill) => {
    if (!await confirmDialog({
      title: `确认删除技能「${skill.name}」？`,
      detail: '已经开的局里，技能栏里的同名技能还在，只是用不出效果了。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.skills.delete(skill.id)
      refresh()
    } catch {
      toast.error('删除技能失败')
    }
  }

  const renderForm = () => (
    <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑技能' : '新增技能'}</span>
        <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input
          value={form.name}
          onChange={e => setForm({ ...form, name: e.target.value })}
          placeholder="技能名，如：听风辨位"
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
      <div>
        <textarea
          value={form.description}
          onChange={e => setForm({ ...form, description: e.target.value })}
          placeholder="怎么施展、使出来什么样子、管什么用、有什么代价……"
          className={`${INPUT} resize-y min-h-[4rem]`}
        />
        <Assist
          moduleId={moduleId}
          field="skill_description"
          context={() => ({ ...assistContext(), 技能名: form.name, 分类: form.category })}
          value={form.description}
          onApply={v => setForm(f => ({ ...f, description: v }))}
        />
      </div>
      <EffectEditor
        label="施展时的数值变化"
        defs={statDefs}
        value={form.effects}
        onChange={v => setForm({ ...form, effects: v })}
      />
      <div>
        <label className="text-xs font-medium mb-1.5 block">施展条件</label>
        <ConditionEditor
          value={form.requires}
          onChange={v => setForm({ ...form, requires: v })}
          statDefs={statDefs}
          relationDefs={relationDefs}
          npcs={npcs}
          slotNames={slotNames}
        />
        <p className="text-xs text-muted-foreground mt-1.5">
          不满足时这一招发不出来，剧情里会写明差在哪，数值不动。
        </p>
      </div>
      {/* 被动技能不出「施展」按钮，冷却也就没有意义，整行藏起来 */}
      {form.category !== '被动' && (
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium">用完歇几回合</label>
          <input
            type="number"
            min={0}
            value={form.cooldown}
            onChange={e => setForm({ ...form, cooldown: Math.max(0, Number(e.target.value) || 0) })}
            className={`${INPUT} w-24`}
          />
          <span className="text-xs text-muted-foreground">0 = 随便用</span>
        </div>
      )}
      <div className="flex gap-4">
        {form.category !== '被动' && (
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={form.usable}
              onChange={e => setForm({ ...form, usable: e.target.checked })}
              className="accent-[hsl(var(--primary))]"
            />
            <span className="text-xs">技能栏里能点「施展」</span>
          </label>
        )}
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={form.start_with}
            onChange={e => setForm({ ...form, start_with: e.target.checked })}
            className="accent-[hsl(var(--primary))]"
          />
          <span className="text-xs">
            开局就会
            <span className="text-muted-foreground">（不勾的话，要在剧情里学到）</span>
          </span>
        </label>
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
      title="技能"
      desc="定义了效果的技能，施展时数字是死的，AI 改不了。勾上「开局就会」的，新开的局一开局就有；没勾的要在剧情里学到。"
      icon={Zap}
      accent={ACCENT.skill}
    >
      <div className="space-y-2">
        {skills.map(skill => (
          <div key={skill.id} className="space-y-2">
          <div className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{skill.name}</span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                  {skill.category}
                </span>
                {Object.entries(skill.effects || {}).map(([k, v]) => (
                  <span key={k} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    {k}{v > 0 ? `+${v}` : v}
                  </span>
                ))}
                {skill.cooldown > 0 && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    冷却 {skill.cooldown} 回合
                  </span>
                )}
                {skill.start_with && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    开局就会
                  </span>
                )}
                {!skill.usable && (
                  <span className="text-[11px] text-muted-foreground">不可施展</span>
                )}
              </div>
              {skill.description && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2">{skill.description}</p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(skill)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(skill)} />
            </div>
          </div>
          {showForm && editingId === skill.id && renderForm()}
          </div>
        ))}

        {showForm && editingId === null && renderForm()}
        {!showForm && (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加技能</AddRow>
            <BatchGenerate<{
              name: string; description: string; category: string
              cooldown: number; start_with: boolean; effects: Record<string, number>
            }>
              moduleId={moduleId}
              kind="skill"
              placeholder="想生成什么技能？比如：生成几招剑修入门功法"
              renderRow={(sk) => (
                <>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{sk.category}</span>
                  {sk.cooldown > 0 && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                      冷却 {sk.cooldown}
                    </span>
                  )}
                  {effectChips(sk.effects)}
                </>
              )}
              onApply={async (sks) => {
                for (const sk of sks) {
                  await rpgApi.skills.create(moduleId, {
                    name: sk.name, description: sk.description, category: sk.category,
                    cooldown: sk.cooldown, start_with: sk.start_with, effects: sk.effects,
                    sort_order: skills.length + 1,
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
