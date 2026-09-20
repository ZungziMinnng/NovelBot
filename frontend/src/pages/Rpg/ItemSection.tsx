import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Package, X } from 'lucide-react'
import { rpgApi, type RpgItem, type RpgStatDef } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import { ACCENT, AddRow, Assist, DeleteButton, INPUT, Section } from './rpgUi'
import EffectEditor from './EffectEditor'
import BatchGenerate from './BatchGenerate'
import { effectChips } from './effectChips'

const CATEGORIES = ['消耗品', '装备', '关键道具'] as const

interface ItemForm {
  name: string
  description: string
  category: string
  usable: boolean
  consumable: boolean
  start_with: boolean
  effects: Record<string, number>
}

const EMPTY: ItemForm = {
  name: '', description: '', category: '消耗品',
  usable: true, consumable: true, start_with: false, effects: {},
}

/** 换分类时「用一次就少一个」跟不跟着变。消耗品一件一件地少，装备和关键道具
 *  不该用一次就没了——钥匙用完消失是 bug 不是设计。只给个对的默认值，勾还是
 *  能手动改回来，所以这条不会把「一瓶反复喝的药水」这种写法堵死 */
const consumableByCategory = (category: string) => category === '消耗品'

/** 道具定义。玩家「使用」时数值由引擎按 effects 精确增减，AI 只负责写成画面。 */
export default function ItemSection({
  moduleId, statDefs, assistContext,
}: {
  moduleId: number
  statDefs: RpgStatDef[]
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
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

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」 */
  const body = () => ({ ...form, name: form.name.trim() })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，存个空名字进去，
   *  列表上就是一行没有名字的东西，而用户只是把它清了准备重打。
   *  新建的道具还没有 id，整份等「添加」一起提交 */
  const autosave = useFormAutosave(
    editingId !== null && form.name.trim() ? { id: editingId, body: body() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.items.update(id, body)
      refresh()
    },
  )

  const startEdit = (item: RpgItem) => {
    // 换一条之前先把上一条欠着的那一次存掉。待存的那一份只有最新一格，
    // 不补发的话它会被下一条的草稿顶掉
    void autosave.flush()
    setEditingId(item.id)
    setForm({
      name: item.name, description: item.description, category: item.category,
      usable: item.usable, consumable: item.consumable, start_with: item.start_with,
      effects: item.effects || {},
    })
    setShowForm(true)
  }

  /** 收起表单。改过的东西已经存进库了，所以这里没得「取消」——但没存成的时候
   *  不能收：收了就等于把改动默默扔掉，而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      await rpgApi.items.create(moduleId, { ...body(), sort_order: items.length + 1 })
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

  const renderForm = () => (
    <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑道具' : '新增道具'}</span>
        <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
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
          onChange={e => {
            const category = e.target.value
            setForm({ ...form, category, consumable: consumableByCategory(category) })
          }}
          className={INPUT}
        >
          {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      <div>
        <textarea
          value={form.description}
          onChange={e => setForm({ ...form, description: e.target.value })}
          placeholder="它长什么样、哪来的、用起来是什么感觉……"
          className={`${INPUT} resize-y min-h-[4rem]`}
        />
        <Assist
          moduleId={moduleId}
          field="item_description"
          context={() => ({ ...assistContext(), 道具名: form.name, 分类: form.category })}
          value={form.description}
          onApply={v => setForm(f => ({ ...f, description: v }))}
        />
      </div>
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
      {/* 单独一行，因为这一条的后果和前两条不在一处：前两条管「怎么用」，
          这条管「有没有」。没勾的话，这件道具只是个定义，开局身上不会有 */}
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={form.start_with}
          onChange={e => setForm({ ...form, start_with: e.target.checked })}
          className="accent-[hsl(var(--primary))]"
        />
        <span className="text-xs">
          开局就带在身上
          <span className="text-muted-foreground">（不勾的话，新开的局里不会有这件）</span>
        </span>
      </label>
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
      title="道具"
      desc="定义了效果的道具，用起来数字是死的，AI 改不了。勾上「开局就带在身上」的，新开的局一开局就有一件；没勾的要在剧情里拿到。"
      icon={Package}
      accent={ACCENT.bag}
    >
      <div className="space-y-2">
        {items.map(item => (
          <div key={item.id} className="space-y-2">
          <div className="border rounded-lg px-3 py-2 flex items-start gap-3">
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
                {item.start_with && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                    开局就带
                  </span>
                )}
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
          {showForm && editingId === item.id && renderForm()}
          </div>
        ))}

        {showForm && editingId === null && renderForm()}
        {!showForm && (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加道具</AddRow>
            <BatchGenerate<{
              name: string; description: string; category: string
              consumable: boolean; start_with: boolean; effects: Record<string, number>
            }>
              moduleId={moduleId}
              kind="item"
              placeholder="想生成什么道具？比如：生成几件魔法学院里常见的消耗品"
              renderRow={(it) => (
                <>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{it.category}</span>
                  {effectChips(it.effects)}
                </>
              )}
              onApply={async (its) => {
                for (const it of its) {
                  await rpgApi.items.create(moduleId, {
                    name: it.name, description: it.description, category: it.category,
                    consumable: it.consumable, start_with: it.start_with, effects: it.effects,
                    sort_order: items.length + 1,
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
