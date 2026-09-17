import type { RpgSession, RpgSkill } from '@/api/client'
import { norm } from '../condition'
import { PANEL } from '../rpgUi'
import Empty from './Empty'

export default function SkillTab({
  sess, skills, locked, onUseSkill,
}: {
  sess: RpgSession
  skills: RpgSkill[]
  locked: boolean
  onUseSkill: (name: string, exact: boolean) => void
}) {
  const learned = sess.skills || []
  const skillByName = (name: string) => skills.find(s => norm(s.name) === norm(name))

  return (
    <>
      {learned.length === 0 ? (
        <Empty>还没学会什么本事。</Empty>
      ) : learned.map((row, i) => {
        const def = skillByName(row.name)
        // 有定义、作者勾了「能用」、而且不是被动 = 引擎精确结算
        const exact = !!def?.usable && def?.category !== '被动'
        // 没定义的照样能点（剧情里现学的一招），只是效果交给 GM 现写。同背包
        const passive = def?.category === '被动'
        const canUse = !passive && (exact || !def)
        const cooling = Math.max(0, row.cooldown_left || 0)
        return (
          <div key={`${row.name}-${i}`} className={`${PANEL} p-3`}>
            <div className="flex items-baseline gap-2">
              <p className="text-sm font-medium flex-1 truncate">{row.name}</p>
              {passive && <span className="text-xs text-muted-foreground">被动</span>}
            </div>
            {def?.description && (
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {def.description}
              </p>
            )}
            {def && Object.keys(def.effects || {}).length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {Object.entries(def.effects).map(([name, delta]) => (
                  <span
                    key={name}
                    className={`text-[11px] px-1.5 py-0.5 rounded ${
                      delta >= 0
                        ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                        : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                    }`}
                  >
                    {name} {delta >= 0 ? `+${delta}` : delta}
                  </span>
                ))}
              </div>
            )}
            {canUse && (
              <button
                onClick={() => onUseSkill(row.name, exact)}
                disabled={locked || cooling > 0}
                title={cooling > 0
                  ? `还要歇 ${cooling} 回合`
                  : exact
                    ? '效果是模组里写死的，AI 改不了'
                    : '模组里没有这个技能的定义：使出来什么效果由 GM 现写，数值不精确'}
                // 描边 = 效果不精确，同背包那两种按钮的区分
                className={`mt-2.5 w-full text-xs py-1.5 rounded-lg disabled:opacity-40 ${
                  exact
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'border text-muted-foreground hover:bg-muted'
                }`}
              >
                {cooling > 0 ? `冷却中 · 还剩 ${cooling} 回合` : '施展'}
              </button>
            )}
          </div>
        )
      })}
    </>
  )
}
