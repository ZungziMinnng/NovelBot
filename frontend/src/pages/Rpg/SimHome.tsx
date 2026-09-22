import { DoorOpen, Lightbulb, Loader2, MapPin, MessageSquare, Sparkles } from 'lucide-react'
import type {
  RpgAction, RpgLocation, RpgModule, RpgNpc, RpgSession, RpgSuggestion,
} from '@/api/client'
import { actionBlocked, checkCondition, norm, visibleLocations } from './condition'
import { actionTimeHint, effectPreview } from './actionFeedback'
import { kindMeta, splitSuggestions, suggestionLabel } from './suggestion'
import RpgAvatar from './RpgAvatar'
import { PANEL, WaitBar } from './rpgUi'

interface Props {
  module?: RpgModule
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
  /** 「帮我想想」的两条建议。和底部输入区那块显示区共用同一份 store 状态 */
  tips: RpgSuggestion[]
  /** 「帮我想想」在跑。住在 store 里，所以在两套界面之间切换不会丢 */
  suggesting: boolean
  onSuggest: () => void
  /** 点一条建议。走哪个入口由 kind 决定，这里只发意图，不碰 API */
  onSuggestion: (tip: RpgSuggestion) => void
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
  sess, actions, locations, hereNpcs, npcs, locked, busy, module,
  onRunAction, onGo, onTalk, onOpenLine, target, onTarget,
  tips, suggesting, onSuggest, onSuggestion,
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

  // 只为「必须人在跟前」那些动作而存在。可远程指定的动作点了自己会弹名单
  // （见 RpgPlay 的 runAction），不读这个下拉——算进来的话，一个只有手机功能的
  // 模组会白挂一个选不出所以然的选择器
  const needTargetAnywhere = actions.some(a => a.needs_target && !a.target_anywhere)
  // 迷雾同总览：没去过、也不挨着去过的地方不列出来
  const visible = visibleLocations(locations, sess)
  const places = locations.filter(l => visible.has(l.id))
  const hereName = norm(sess.location || '')

  const blockedWhy = (action: RpgAction): string =>
    actionBlocked(action, sess, npcs, action.target_anywhere ? '' : target, module)

  // 建议条分两行渲染，同底部输入区那一块（见 suggestion.ts）。
  // 这一档进门问的就是「今天安排什么」，所以这一节摆在页面最上面
  const { structured, plain } = splitSuggestions(tips)

  return (
    <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-4 space-y-4">
      {(tips.length > 0 || suggesting) && (
        <section className={`${PANEL} px-4 py-3.5`}>
          <div className="flex items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2 text-xs font-medium text-primary">
              <Lightbulb className="w-3.5 h-3.5" />今天安排什么
            </div>
            <button
              onClick={onSuggest}
              disabled={locked || suggesting}
              className="text-xs px-2.5 py-1 rounded-lg border hover:bg-muted
                disabled:opacity-40 disabled:cursor-not-allowed
                inline-flex items-center gap-1.5"
            >
              {suggesting
                ? <Loader2 className="w-3 h-3 animate-spin" />
                : <Lightbulb className="w-3 h-3" />}
              {suggesting ? '在想…' : '帮我想想'}
            </button>
          </div>

          {/* 一次模型调用。按钮里那个转圈太小，主页这一屏功能按钮又多 */}
          {suggesting && <WaitBar className="mb-3" />}

          {/* 结构化那几件：逐字复用下面动作卡片的样子，点了直接走引擎 */}
          {structured.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {structured.map((tip, i) => {
                const Icon = kindMeta(tip.kind).icon
                // 动作的 name 是空的（后端只给 action_id），名字从动作表里查。
                // 已被作者删掉时查不到，只显示「动作」两个字，点了静默收场
                const actionName = actions.find(a => a.id === tip.action_id)?.name || ''
                return (
                  <button
                    key={i}
                    onClick={() => onSuggestion(tip)}
                    disabled={locked}
                    title={tip.text}
                    className="text-left rounded-xl border border-primary/25 bg-primary/[0.04] px-3 py-2.5
                      hover:bg-primary/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    <div className="flex items-center gap-1.5 text-[11px] text-primary">
                      <Icon className="w-3 h-3 shrink-0" />
                      {suggestionLabel(tip, actionName)}
                    </div>
                    <div className="mt-1 text-sm">{tip.text}</div>
                  </button>
                )
              })}
            </div>
          )}

          {/* 自由文本那几件：虚线卡，沿用「看剧情 / 自由输入」那颗的样式 */}
          {plain.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {plain.map((tip, i) => (
                <button
                  key={i}
                  onClick={() => onSuggestion(tip)}
                  disabled={locked}
                  className="text-sm px-3 py-2 rounded-xl border border-dashed text-muted-foreground
                    hover:bg-muted hover:text-foreground disabled:opacity-40
                    disabled:cursor-not-allowed transition-colors"
                >
                  {tip.text}
                </button>
              ))}
            </div>
          )}

          {tips.length === 0 && (
            <p className="text-xs text-muted-foreground">想想接下来能做点什么…</p>
          )}
        </section>
      )}

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
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                        {actionTimeHint(action, sess, module)}
                      </span>
                      {Object.entries(action.effects || {}).map(([k, v]) => (
                        <span key={k} className="text-[11px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                          {effectPreview(k, v, module?.stat_defs, sess.stats)}
                        </span>
                      ))}
                      {Object.entries(action.relation_effects || {}).map(([k, v]) => (
                        <span key={k} className="text-[11px] px-1.5 py-0.5 rounded bg-pink-500/10 text-pink-700 dark:text-pink-300">
                          对方{effectPreview(k, v, module?.relation_stat_defs)}
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
