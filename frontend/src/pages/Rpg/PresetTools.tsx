import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Library, Loader2, Save } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgApi, type RpgAction, type RpgActionSeed, type RpgStatDef, type RpgStatPreset } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { INPUT } from './rpgUi'
import { BUILTIN_STAT_PACKS, type StatPack } from './presetLib'
import { newPlayerStat, newRelationStat, type StatDraft } from './StatDefsSection'
import PresetApplyDialog from './PresetApplyDialog'

/**
 * 模组编辑页上的两个套装入口：数值区一条、动作区一条。
 *
 * 不合成一个统一入口放在题材预设旁边——那等于把刚拆开的两个库又绑回一次操作。
 * 题材预设那三个按钮的语义是「整套模板，一次填四样」，和这里不是一回事。
 */

/** 工具条按钮。和页面顶部那排导航按钮同一档尺寸，不是新的一套 */
const BTN = 'flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-50'

/**
 * 存进库的命名条。就地展开一行，不另开模态：起名只要一个输入框，
 * 为它弹一个居中蒙层比在原地展开更打断手上的活。
 */
function SaveBar({ hint, onSave, onCancel }: {
  /** 这次要存什么、有什么不跟着走，一句话 */
  hint: string
  onSave: (name: string) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await onSave(name.trim())
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border rounded-lg p-3 bg-muted/30 space-y-2">
      <p className="text-xs text-muted-foreground">{hint}</p>
      <div className="flex items-center gap-2">
        <input
          className={INPUT}
          placeholder="给这套起个名字"
          value={name}
          onChange={e => setName(e.target.value)}
          autoFocus
          // 回车等于点保存：这一行只为输入一次名字而存在，让手离开键盘去够按钮不划算
          onKeyDown={e => { if (e.key === 'Enter' && name.trim() && !busy) void save() }}
        />
        <button onClick={save} disabled={!name.trim() || busy} className={`${BTN} shrink-0`}>
          {busy && <Loader2 className="w-3 h-3 animate-spin" />} 保存
        </button>
        <button onClick={onCancel} disabled={busy} className={`${BTN} shrink-0`}>取消</button>
      </div>
    </div>
  )
}

// ── 数值区 ────────────────────────────────────────────────────────────────

export function StatPresetBar({ form, set }: {
  form: StatDraft
  set: <K extends keyof StatDraft>(key: K, value: StatDraft[K]) => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const qc = useQueryClient()
  const { data: presets } = useQuery({ queryKey: ['rpg-stat-presets'], queryFn: rpgApi.statPresets.list })

  /** 整表覆盖，不是合并：两套「精力」并排存在时后端按名字取、后一行赢，
   *  界面上根本看不出哪一行在生效 */
  const applyStats = async (pack: StatPack) => {
    const has = (form.stat_defs || []).length > 0 || (form.relation_stat_defs || []).length > 0
    // 空表时不弹：没有东西会被换掉，多一次确认只是噪音（照 GenreField 的 hasStats）
    if (has && !(await confirmDialog({
      title: `用「${pack.name}」替换现在的数值表？`,
      detail: '现有的数值定义会被换掉。已经开的局不受影响——那一局的数值在建局时就拷走了。',
      confirmText: '套用',
    }))) return
    // structuredClone：内置套装是模块级常量，直接把引用塞进表单，作者在数值表里
    // 改一个字就改到了常量本身，这次会话里所有模组套出来的都跟着变
    set('stat_defs', structuredClone(pack.stat_defs))
    set('relation_stat_defs', structuredClone(pack.relation_stat_defs))
    setOpen(false)
    toast.success('已套用')
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className={BTN} onClick={() => { setOpen(o => !o); setSaving(false) }}>
          <Library className="w-3.5 h-3.5" /> 从库套用
        </button>
        <button className={BTN} onClick={() => { setSaving(s => !s); setOpen(false) }}>
          <Save className="w-3.5 h-3.5" /> 存进库
        </button>
      </div>

      {open && (
        // 就地展开而不是浮层：这是「选一个就走」的短列表，浮层还得管定位和点外关闭
        <div className="border rounded-lg p-2 space-y-1 bg-muted/30">
          <p className="text-xs font-medium text-muted-foreground px-2 pt-1">内置套装</p>
          {BUILTIN_STAT_PACKS.map(p => (
            <button
              key={p.key ?? p.name}
              onClick={() => applyStats(p)}
              className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted"
            >
              {p.name}
              <span className="text-muted-foreground ml-2">
                {p.stat_defs.length} 项 · {p.relation_stat_defs.length} 项关系
              </span>
            </button>
          ))}

          <p className="text-xs font-medium text-muted-foreground px-2 pt-2">我的套装</p>
          {(presets ?? []).length === 0 ? (
            <p className="text-xs text-muted-foreground px-2 py-1.5">还没有自己的数值套装。</p>
          ) : (
            (presets ?? []).map((p: RpgStatPreset) => (
              <button
                key={p.id}
                onClick={() => applyStats({
                  id: p.id, name: p.name, note: p.note,
                  stat_defs: p.stat_defs || [], relation_stat_defs: p.relation_stat_defs || [],
                })}
                className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted"
              >
                {p.name}
                <span className="text-muted-foreground ml-2">
                  {(p.stat_defs || []).length} 项 · {(p.relation_stat_defs || []).length} 项关系
                </span>
              </button>
            ))
          )}
        </div>
      )}

      {saving && (
        <SaveBar
          hint="存进库的是现在这两张表的副本。以后改库不会动这个模组，改这个模组也不会写回库。"
          onCancel={() => setSaving(false)}
          onSave={async name => {
            try {
              await rpgApi.statPresets.create({
                name,
                stat_defs: form.stat_defs || [],
                relation_stat_defs: form.relation_stat_defs || [],
              })
              qc.invalidateQueries({ queryKey: ['rpg-stat-presets'] })
              toast.success('已存进库')
              setSaving(false)
            } catch {
              // 失败时不收起：名字还在框里，改一下就能重试，不用重新打一遍
              toast.error('存进库失败')
            }
          }}
        />
      )}
    </div>
  )
}

// ── 动作区 ────────────────────────────────────────────────────────────────

export function ActionPresetBar({ moduleId, actions, statDefs, relationDefs, onAddStats }: {
  moduleId: number
  actions: RpgAction[]
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  /** 补建缺的数值。数值表不在这个组件手里，得让模组页去 set */
  onAddStats: (stats: RpgStatDef[], relations: RpgStatDef[]) => void
}) {
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const qc = useQueryClient()

  const apply = async (picked: RpgActionSeed[], fill: { stats: string[]; relations: string[] }) => {
    try {
      // 1) 补建的数值是「追加」，绝不是覆盖——这里在修补，不是在套数值套装。
      //    默认值就是作者手点「添加一项」那一份：从 effects 的数字反推是错的，
      //    资金 +200 会推出 max:200，而钱恰恰该是无上限，猜错比不猜难查十倍
      onAddStats(
        fill.stats.map(n => ({ ...newPlayerStat(), name: n })),
        fill.relations.map(n => ({ ...newRelationStat(), name: n })),
      )
      // 2) 动作当场落库（和 GenreField 套模板走的是同一条路，不引入第二种落库方式）
      await Promise.all(picked.map((a, i) => rpgApi.actions.create(moduleId, {
        ...a,
        // 库里的数据可能是手工编辑出来的。relation_effects 非空却 needs_target=false
        // 的按钮点下去关系数值不变、也不报错，和动作表单里那条联动是同一条规则
        needs_target: a.needs_target || Object.keys(a.relation_effects || {}).length > 0,
        // 可用条件不跟着套装走：它引用的角色名、道具名、时段都是别的模组特有的
        requires: {},
        sort_order: actions.length + i + 1,
      })))
      qc.invalidateQueries({ queryKey: ['rpg-actions', moduleId] })
      setShow(false)
      toast.success(`已套用 ${picked.length} 个动作`)
    } catch {
      toast.error('套用动作套装失败')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 flex-wrap">
        <button className={BTN} onClick={() => { setShow(true); setSaving(false) }}>
          <Library className="w-3.5 h-3.5" /> 从库套用
        </button>
        {/* 一个动作都没有时存进库没有意义：空套装在库里只会占一行、永远没人用 */}
        <button className={BTN} disabled={actions.length === 0} onClick={() => { setSaving(s => !s); setShow(false) }}>
          <Save className="w-3.5 h-3.5" /> 存进库
        </button>
      </div>

      {saving && (
        <SaveBar
          hint={`存的是这 ${actions.length} 个动作的副本，可用条件不会跟着进库——它引用的角色名、道具名和时段换个模组就对不上了。`}
          onCancel={() => setSaving(false)}
          onSave={async name => {
            try {
              await rpgApi.actionPresets.create({
                name,
                // at_location 和 requires 一样刻意不进库：存的是地点名，
                // 换个模组就是永远灰着的死按钮
                actions: actions.map(a => ({
                  name: a.name, prompt_hint: a.prompt_hint,
                  effects: a.effects || {}, relation_effects: a.relation_effects || {},
                  needs_target: a.needs_target,
                  // 这两个和 cost_slot 同类：纯布尔，不引用模组里的任何名字，
                  // 搬到别的模组照样成立（远程/召见靠的是「见过面」和玩家当前
                  // 位置，两者每个模组都有）
                  target_anywhere: !!a.target_anywhere, summons_target: !!a.summons_target,
                  group: a.group || '', cost_slot: !!a.cost_slot,
                })),
              })
              qc.invalidateQueries({ queryKey: ['rpg-action-presets'] })
              toast.success('已存进库')
              setSaving(false)
            } catch {
              toast.error('存进库失败')
            }
          }}
        />
      )}

      {show && (
        <PresetApplyDialog
          existingNames={actions.map(a => a.name)}
          statDefs={statDefs}
          relationDefs={relationDefs}
          onCancel={() => setShow(false)}
          onApply={apply}
        />
      )}
    </div>
  )
}
