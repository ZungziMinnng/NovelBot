import { useEffect, useState } from 'react'
import { Backpack, ScrollText, Sparkles, Users, Zap } from 'lucide-react'
import type {
  RpgItem, RpgModule, RpgNpc, RpgSession, RpgSkill, RpgStatDef,
} from '@/api/client'
import { following, npcPlace, onstage } from './condition'
import useColumnResize from './useColumnResize'
import CastTab from './sidebar/CastTab'
import NpcDetail from './sidebar/NpcDetail'
import SelfDetail from './sidebar/SelfDetail'
import BagTab from './sidebar/BagTab'
import SkillTab from './sidebar/SkillTab'
import TaskTab from './sidebar/TaskTab'
import FoundTab from './sidebar/FoundTab'
import { PLAYER_SLOT } from './sidebar/SummaryBlock'

// 地图从侧栏搬走了：它现在是主界面（地点总览），而且「过去」变成了
// 纯引擎的瞬移，和这里的其他格子不是一类东西了。
// 存档也搬走了：它去了页头——存/读档是「这一局之外」的事，和角色、道具、
// 新发现这些「局内在看的东西」不是一类，而且腾出来的格子要给技能和任务
export type SidebarTab = 'cast' | 'bag' | 'skill' | 'task' | 'found'

// 每格一个颜色，和 index.css 里 .mode-game 的 --rpg-* 一一对应。
// 固定不跟主题走：换个主题就找不到道具在哪了，那这个设计就白做了
const TABS: { key: SidebarTab; label: string; icon: typeof Users; accent: string }[] = [
  { key: 'cast', label: '角色', icon: Users, accent: 'var(--rpg-cast)' },
  { key: 'bag', label: '道具', icon: Backpack, accent: 'var(--rpg-bag)' },
  { key: 'skill', label: '技能', icon: Zap, accent: 'var(--rpg-skill)' },
  { key: 'task', label: '任务', icon: ScrollText, accent: 'var(--rpg-task)' },
  { key: 'found', label: '新发现', icon: Sparkles, accent: 'var(--rpg-found)' },
]

/** 「隐藏」的一律不画：那是幕后计数器（怀疑度到 60 就有人来敲门），
 *  画出来等于把作者埋的伏笔提前说了。 */
const shown = (defs?: RpgStatDef[]) => (defs || []).filter(d => d.name && d.display !== '隐藏')

interface Props {
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  items: RpgItem[]
  skills: RpgSkill[]
  tab: SidebarTab
  onTab: (t: SidebarTab) => void
  locked: boolean
  /** exact = 模组里有定义、效果是引擎算的。没定义的也能点，只是交给 GM 现写 */
  onUseItem: (name: string, exact: boolean, quantity?: number) => void
  /** 施展一招。exact 的含义同 onUseItem */
  onUseSkill: (name: string, exact: boolean) => void
  /** 玩家自己改一条待办。status 给空串 = 划掉 */
  onSetTask: (name: string, status: '' | 'open' | 'done' | 'failed') => void
  /** 正在看谁的档案。null = 显示名单。状态提到 RpgPlay 上了：地点页也要能开 */
  openNpc: RpgNpc | null
  /** 点名单里某个人 / 传 null 退回名单 */
  onOpenNpc: (npc: RpgNpc | null) => void
  /** 勾中的新发现「加入模组」。这一步会调一次模型补属性和地图连接，所以要等 */
  onApplyDiscoveries: (ids: string[]) => void
  onDismissDiscovery: (id: string) => void
  applyingDiscoveries?: boolean
  /** 认下一件新道具（consumable 决定用不用得完）/ 划掉一条。两个都返回新会话 */
  onConfirmItemClaim: (id: string, consumable: boolean) => void
  onDismissItemClaim: (id: string) => void
  /** openNpc 这一局的近况。存在会话上不在角色卡上，所以由 RpgPlay 取好了传进来 */
  notes: Record<string, string>
  /** openNpc 被这一局改写掉的外貌。同上，也是存档级的 */
  appearance: Record<string, string>
  /** openNpc 那一句「最近在做什么」。同上 */
  activity: string
  onDeleteNote: (key: string) => void
  onDeleteAppearance: (key: string) => void
  onDeleteActivity: () => void
  /** 改写某一格的长期记忆。slot 传 'player' 或角色 id 的字符串，形状同后端
   *  的格子划分——这一层不认识格子，只负责把 slot 递回去 */
  onSaveSummary: (slot: string, text: string) => Promise<void>
  /** 让某人跟着你 / 打发她走。喂给档案页那个既显示状态又当解除入口的小块 */
  onSetFollow: (npcId: number, following: boolean) => void
  /** 档案在侧栏里被改过了。改的是模组那张卡，不是这一局的状态 */
  onSaveNpc: (updated: RpgNpc) => void
}

/** 常驻菜单。角色/道具/新发现三格，和日式游戏的菜单一个意思：
 *  始终在屏幕上，不用先想起来「我能看这个」。
 *
 *  第一格是「角色」：你自己那一行，加上已经登记在册的人。数值没有单独的一格——
 *  它跟着「你」走，在你自己那一页里，不然玩家要在两格之间来回翻才能看完一件事。
 *
 *  点开一个人看档案是**在这一列里主从切换**，不另开一列也不弹窗：这一列
 *  最宽 520，剧情区是 max-w-3xl 居中，再分一列出去正文就被挤扁了；而弹窗
 *  会把剧情整个盖住，想边看正文边对照档案做不到。 */
export default function StatusSidebar({
  sess, module, npcs, items, skills,
  tab, onTab, locked,
  onUseItem, onUseSkill, onSetTask, openNpc, onOpenNpc,
  onApplyDiscoveries, onDismissDiscovery, applyingDiscoveries = false,
  onConfirmItemClaim, onDismissItemClaim,
  notes, appearance, activity, onDeleteNote, onDeleteAppearance, onDeleteActivity,
  onSaveSummary, onSetFollow, onSaveNpc,
}: Props) {
  // 不落盘。编辑器那边也没存，玩家每次进来都是默认宽度
  const [width, setWidth] = useState(320)
  /** 在不在看自己那一页。不提到 RpgPlay 上：它只从这一格的名单点得开，
   *  不像 NPC 档案还要被地点页调起 */
  const [openSelf, setOpenSelf] = useState(false)
  // 地点页点一张脸时自己这一页得让位；不清掉的话从那个人的档案返回会退回自己
  // 这一页，而玩家按那个箭头是想回名单
  useEffect(() => { if (openNpc) setOpenSelf(false) }, [openNpc])
  // 侧栏在**左边**，手柄在它的右缘：往右拖才是变宽
  const onResizeDown = useColumnResize(setWidth, 280, 520, 'right')
  const found = sess.discoveries || []
  const todo = (sess.tasks || []).filter(t => t.status === 'open').length
  // 待认领的新道具也数进道具这一格：它就挂在这一格最上面，不数的话玩家不知道
  // 有件东西等着他认——而没认下来的东西是不在背包里的
  const claims = (sess.item_claims || []).length
  const badge = (key: SidebarTab) =>
    key === 'found' ? found.length : key === 'task' ? todo : key === 'bag' ? claims : 0
  const statDefs = shown(module?.stat_defs)
  const relDefs = shown(module?.relation_stat_defs)

  return (
    // rpg-side 而不是 bg-card：默认主题下 --card 和 --background 同色，
    // 铺 bg-card 等于没铺。见 index.css 里那条规则
    <div
      // max-w-full 是给窄屏抽屉兜底的：那边的壳子是 min(20rem,85vw)，
      // 小屏上比 320 窄，不封顶就会横着溢出去
      className="rpg-side relative flex flex-col h-full min-h-0 max-w-full border-r border-border/60"
      style={{ width }}
    >
      {/* 手柄必须是这一列的直接子元素：hook 量的是 parentElement 的宽 */}
      <div
        onMouseDown={onResizeDown}
        title="拖动改宽度"
        className="absolute right-0 top-0 h-full w-1 cursor-col-resize hover:bg-primary/40 z-10"
      />
      <div className="flex shrink-0 border-b border-border/60">
        {TABS.map(({ key, label, icon: Icon, accent }) => (
          <button
            key={key}
            // 切走再切回来时档案应该已经收起：留着的话玩家点「角色」是想看名单，
            // 结果还停在上一个人的档案上
            onClick={() => { onTab(key); onOpenNpc(null); setOpenSelf(false) }}
            style={tab === key ? { color: `hsl(${accent})`, borderColor: `hsl(${accent})` } : undefined}
            className={`relative flex-1 flex flex-col items-center gap-1 py-2.5 text-[11px] border-b-2 transition-colors
              ${tab === key ? 'bg-foreground/[0.04] font-medium' : 'border-transparent text-muted-foreground hover:bg-muted/50'}`}
          >
            <Icon className="w-4 h-4" />
            {label}
            {/* 角标是这一格唯一的出场方式：不弹窗、不打断，玩到想起来了再点进来。
                任务那格数的是**手上还没办完的事**，不是待确认的提议——收线要不要认
                已经当场弹过窗了，角标该回答的是「我还欠着几桩事」 */}
            {badge(key) > 0 && (
              <span
                style={{ background: `hsl(${accent})` }}
                className="absolute top-1.5 right-1/2 translate-x-4 min-w-[15px] h-[15px] px-1
                  rounded-full text-[10px] leading-[15px] text-white font-medium"
              >
                {badge(key)}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* 档案自带页眉和自己的滚动区，所以它是**顶掉**下面这个滚动容器，
          不是塞在里面——塞进去会套两层滚动条，页眉也就跟着滚走了 */}
      {tab === 'cast' && openNpc ? (
        <NpcDetail
          // 换一个人看要重新挂载：档案打开的提示音挂在挂载上
          key={openNpc.id}
          npc={openNpc}
          relationDefs={relDefs}
          state={sess.npc_states?.[String(openNpc.id)] || {}}
          notes={notes}
          appearance={appearance}
          onDeleteAppearance={onDeleteAppearance}
          activity={activity}
          history={sess.npc_history?.[String(openNpc.id)] || []}
          activityLog={sess.npc_activity_log?.[String(openNpc.id)] || []}
          milestones={sess.npc_milestones || []}
          here={onstage(openNpc, sess)}
          place={npcPlace(
            openNpc, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
          ) || ''}
          following={following(openNpc, sess)}
          summary={sess.thread_summaries?.[String(openNpc.id)] || ''}
          onSaveSummary={text => onSaveSummary(String(openNpc.id), text)}
          onUnfollow={() => onSetFollow(openNpc.id, false)}
          onBack={() => onOpenNpc(null)}
          onDeleteNote={onDeleteNote}
          onDeleteActivity={onDeleteActivity}
          onSaved={onSaveNpc}
        />
      ) : tab === 'cast' && openSelf ? (
        <SelfDetail
          sess={sess}
          module={module}
          statDefs={statDefs}
          onBack={() => setOpenSelf(false)}
          onSaveSummary={text => onSaveSummary(PLAYER_SLOT, text)}
        />
      ) : (
        <div className="flex-1 overflow-y-auto p-3 space-y-3">
          {tab === 'cast' && (
            <CastTab
              sess={sess}
              module={module}
              npcs={npcs}
              relDefs={relDefs}
              onOpenNpc={onOpenNpc}
              onOpenSelf={() => setOpenSelf(true)}
            />
          )}

          {tab === 'bag' && (
            <BagTab
              module={module}
              sess={sess}
              items={items}
              locked={locked}
              onUseItem={onUseItem}
              onConfirmClaim={onConfirmItemClaim}
              onDismissClaim={onDismissItemClaim}
            />
          )}

          {tab === 'skill' && (
            <SkillTab sess={sess} skills={skills} module={module} npcs={npcs} locked={locked} onUseSkill={onUseSkill} />
          )}

          {tab === 'task' && (
            <TaskTab sess={sess} locked={locked} onSetTask={onSetTask} />
          )}

          {tab === 'found' && (
            <FoundTab
              found={found}
              onApplyDiscoveries={onApplyDiscoveries}
              onDismissDiscovery={onDismissDiscovery}
              applyingDiscoveries={applyingDiscoveries}
            />
          )}
        </div>
      )}
    </div>
  )
}
