import type { RpgStatDef } from '@/api/client'
import { INPUT } from './rpgUi'
import EffectEditor from './EffectEditor'

/** 一个动作除「可用条件」以外的全部内容。
 *  条件留在模组那边：它引用的角色名、道具名、时段都是某个模组特有的，
 *  套装库里没有可选项（见 RpgActionPreset 的注释）。 */
export interface ActionDraft {
  name: string
  prompt_hint: string
  effects: Record<string, number>
  relation_effects: Record<string, number>
  needs_target: boolean
  group: string
  cost_slot: boolean
}

/**
 * 动作表单体。模组编辑页和套装库两边共用。
 *
 * 抽出来主要是为了下面那条联动只存在一份：库里要是漏了它，就能稳定产出
 * 「关系数值填了但没勾选对象」的按钮——点下去关系不变、也不报错，
 * 套进任何模组都是坏的。
 */
export default function ActionFields({
  value, onChange, statDefs, relationDefs, example = '奖励', groups = [], hasClock = false,
}: {
  value: ActionDraft
  onChange: (next: ActionDraft) => void
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  /** 空格子里的示例词，按玩法类别换（见 stylePresets.STYLE_EXAMPLES） */
  example?: string
  /** 已经用过的分栏名，只作为 datalist 备选——分栏是自由文本，不是枚举 */
  groups?: string[]
  /** 模组配了时段吗。没配的话「消耗一格时段」勾了也没有效果，直接不显示 */
  hasClock?: boolean
}) {
  return (
    <>
      <input
        value={value.name}
        onChange={e => onChange({ ...value, name: e.target.value })}
        placeholder={`按钮上的字，如：${example}`}
        className={INPUT}
      />
      <div>
        <input
          value={value.group}
          onChange={e => onChange({ ...value, group: e.target.value })}
          placeholder="分栏，如：经营 / 人事 / 私人"
          list="rpg-action-groups"
          className={INPUT}
        />
        <datalist id="rpg-action-groups">
          {groups.map(g => <option key={g} value={g} />)}
        </datalist>
        <p className="text-xs text-muted-foreground mt-1.5">
          游玩时同一栏的按钮排在一起。留空就归到「其他」。
        </p>
      </div>
      <div>
        <textarea
          value={value.prompt_hint}
          onChange={e => onChange({ ...value, prompt_hint: e.target.value })}
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
        value={value.effects}
        onChange={v => onChange({ ...value, effects: v })}
      />
      <EffectEditor
        label="对方的关系数值变化"
        defs={relationDefs}
        value={value.relation_effects}
        onChange={v => onChange({
          ...value,
          relation_effects: v,
          // 关系变化必须知道改谁，否则这一栏点了也不生效
          needs_target: Object.keys(v).length > 0 ? true : value.needs_target,
        })}
      />
      <label className="flex items-center gap-1.5 cursor-pointer">
        <input
          type="checkbox"
          checked={value.needs_target}
          onChange={e => onChange({ ...value, needs_target: e.target.checked })}
          disabled={Object.keys(value.relation_effects).length > 0}
          className="accent-[hsl(var(--primary))] disabled:opacity-50"
        />
        <span className="text-xs">点之前先选一个在场角色</span>
      </label>
      {hasClock && (
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={value.cost_slot}
            onChange={e => onChange({ ...value, cost_slot: e.target.checked })}
            className="accent-[hsl(var(--primary))]"
          />
          <span className="text-xs">
            点一下花掉一格时段
            <span className="text-muted-foreground">（跨天时会触发每日恢复）</span>
          </span>
        </label>
      )}
    </>
  )
}
