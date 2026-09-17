import { DoorOpen, MapPin, MessageSquare, Sparkles } from 'lucide-react'
import type { RpgAction, RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { actionBlocked, checkCondition, norm, visibleLocations } from './condition'
import RpgAvatar from './RpgAvatar'
import { PANEL } from './rpgUi'

interface Props {
  sess: RpgSession
  actions: RpgAction[]
  locations: RpgLocation[]
  /** 此刻在你跟前的人。名单由 RpgPlay 算，这里不重算——它那份还兼顾了没有地点的模组 */
  hereNpcs: RpgNpc[]
  /** 判条件用的全量角色表。关系数值条件要按名字找人，只给在场的会误判 */
  npcs: RpgNpc[]
  locked: boolean
  /** 有一次瞬移正在路上 */
  busy: boolean
  onRunAction: (action: RpgAction) => void
  onGo: (name: string) => void
  onTalk: (npc: RpgNpc) => void
  /** 切到时间线看剧情 */
  onOpenLine: () => void
  /** 需要选对象的动作作用在谁身上。和底部输入区那个下拉是同一份状态 */
  target: string
  onTarget: (name: string) => void
}

const OTHER = '其他'

/**
 * 模拟器的主页：一屏功能按钮。
 *
 * 探索冒险那一档进来先看地图，因为那边玩的是「去看看那边有什么」。模拟器玩的是
 * 「今天安排什么」，所以这里把动作按钮摆到主位、按作者填的 group 分栏，地点退成
 * 其中一栏的几个入口。两边共用同一套数据，差别只在这一层怎么摆。
 *
 * 置灰的判据和底部输入区那排 chip 逐条相同（checkCondition + needs_target），
 * 多一条 at_location——它是 RpgAction 自己的列，不在 RpgCondition 里，所以只能
 * 在这里单独判。判定权始终在后端，这里放行了 _run_action 照样会拦。
 */
export default function SimHome({
  sess, actions, locations, hereNpcs, npcs, locked, busy,
  onRunAction, onGo, onTalk, onOpenLine, target, onTarget,
}: Props) {
  // 分栏顺序按作者在模组里排的 sort_order 走：第一次出现的组排前面。
  // 不排序、也不按字典序——作者把「经营」放在最上面就是想让它在最上面
  const groups: Array<{ name: string; rows: RpgAction[] }> = []
  for (const action of actions) {
    const key = (action.group || '').trim() || OTHER
    const found = groups.find(g => g.name === key)
    if (found) found.rows.push(action)
    else groups.push({ name: key, rows: [action] })
  }

  const needTargetAnywhere = actions.some(a => a.needs_target)
  // 迷雾同总览：没去过、也不挨着去过的地方不列出来
  const visible = visibleLocations(locations, sess)
  const places = locations.filter(l => visible.has(l.id))
  const hereName = norm(sess.location || '')

  const blockedWhy = (action: RpgAction): string =>
    actionBlocked(action, sess, npcs, target)

  return (
    <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-4 space-y-4">
      {needTargetAnywhere && hereNpcs.length > 0 && (
        <div className={`${PANEL} px-3 py-2.5 flex flex-wrap items-center gap-2`}>
          <span className="text-xs text-muted-foreground">这些安排作用在</span>
          <select
            value={target}
            onChange={e => onTarget(e.target.value)}
            className="text-xs border rounded-lg px-2 py-1 bg-background/60 focus:outline-none"
          >
            <option value="">谁也不选</option>
            {hereNpcs.map(n => <option key={n.id} value={n.name}>{n.name}</option>)}
          </select>
          <span className="text-xs text-muted-foreground">
            只决定关系数值加给谁，不会把你带到别处去。
          </span>
        </div>
      )}

      {groups.length === 0 ? (
        <div className={`${PANEL} px-4 py-16 text-center space-y-2`}>
          <p className="text-sm text-muted-foreground">
            这个模拟器还没有功能按钮。回模组页的「功能」里加几个，这里就会有了。
          </p>
          <button
            onClick={onOpenLine}
            className="text-xs px-3 py-1.5 rounded-lg border hover:bg-muted"
          >
            先去自由输入
          </button>
        </div>
      ) : (
        groups.map(group => (
          <section key={group.name} className={`${PANEL} px-4 py-3.5`}>
            <div className="flex items-center gap-2 text-xs font-medium text-primary mb-3">
              <Sparkles className="w-3.5 h-3.5" />{group.name}
            </div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {group.rows.map(action => {
                const why = blockedWhy(action)
                return (
                  <button
                    key={action.id}
                    onClick={() => onRunAction(action)}
                    disabled={locked || !!why}
                    title={why || action.prompt_hint || action.name}
                    className="text-left rounded-xl border border-primary/25 bg-primary/[0.04] px-3 py-2.5
                      hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    <div className="text-sm font-medium truncate">{action.name}</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {action.cost_slot && (
                        <span className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                          费一格时段
                        </span>
                      )}
                      {Object.entries(action.effects || {}).map(([k, v]) => (
                        <span key={k} className="text-[11px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                          {k}{v > 0 ? `+${v}` : v}
                        </span>
                      ))}
                      {Object.entries(action.relation_effects || {}).map(([k, v]) => (
                        <span key={k} className="text-[11px] px-1.5 py-0.5 rounded bg-pink-500/10 text-pink-700 dark:text-pink-300">
                          对方{k}{v > 0 ? `+${v}` : v}
                        </span>
                      ))}
                    </div>
                    {why && <div className="mt-1 text-[11px] text-muted-foreground truncate">{why}</div>}
                  </button>
                )
              })}
            </div>
          </section>
        ))
      )}

      {hereNpcs.length > 0 && (
        <section className={`${PANEL} px-4 py-3.5`}>
          <div className="flex items-center gap-2 text-xs font-medium text-primary mb-3">
            <MessageSquare className="w-3.5 h-3.5" />找人说话
          </div>
          <div className="flex flex-wrap gap-2">
            {hereNpcs.map(npc => (
              <button
                key={npc.id}
                onClick={() => onTalk(npc)}
                disabled={locked}
                title={`单独和${npc.name}说话`}
                className="flex items-center gap-2 rounded-xl border px-2.5 py-2 hover:bg-muted
                  disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <RpgAvatar name={npc.name} url={npc.avatar_url} size="sm" />
                <span className="text-sm">{npc.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* 地点在这一档只是几个入口。点了直接瞬移（零模型调用），不打开地图——
          那张图是探索冒险的东西，这边的场所之间没有「路」的概念 */}
      {places.length > 0 && (
        <section className={`${PANEL} px-4 py-3.5`}>
          <div className="flex items-center gap-2 text-xs font-medium text-primary mb-3">
            <MapPin className="w-3.5 h-3.5" />去别处
          </div>
          <div className="flex flex-wrap gap-2">
            {places.map(loc => {
              const isHere = norm(loc.name) === hereName
              const [ok, why] = checkCondition(loc.enter_requires, sess, npcs)
              return (
                <button
                  key={loc.id}
                  onClick={() => onGo(loc.name)}
                  disabled={isHere || locked || busy || !ok}
                  title={isHere ? '你已经在这儿了' : ok ? loc.description || loc.name : why}
                  className="text-sm px-3 py-2 rounded-xl border hover:bg-muted
                    disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {isHere ? `${loc.name}（在这儿）` : loc.name}
                </button>
              )
            })}
          </div>
        </section>
      )}

      <button
        onClick={onOpenLine}
        className="w-full rounded-xl border border-dashed px-4 py-3 text-sm text-muted-foreground
          hover:bg-muted hover:text-foreground transition-colors inline-flex items-center justify-center gap-2"
      >
        <DoorOpen className="w-4 h-4" />看剧情 / 自由输入
      </button>
    </div>
  )
}
