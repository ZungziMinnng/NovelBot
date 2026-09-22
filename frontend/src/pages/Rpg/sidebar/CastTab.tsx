import { ChevronRight } from 'lucide-react'
import type { RpgModule, RpgNpc, RpgSession, RpgStatDef } from '@/api/client'
import { following, knownNpcs, npcPlace, onstage } from '../condition'
import RpgAvatar from '../RpgAvatar'
import StatBar from '../StatBar'
import { PANEL } from '../rpgUi'

export default function CastTab({
  sess, module, npcs, relDefs, onOpenNpc, onOpenSelf,
}: {
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  relDefs: RpgStatDef[]
  onOpenNpc: (npc: RpgNpc) => void
  /** 点自己那一行，去看自己的档案（数值和「你记得的」都在那儿） */
  onOpenSelf: () => void
}) {
  // 没见过也不在场的不列：列出来等于把还没登场的人抖出来。
  // 模拟器例外，那边开局就全员在册（见 knownNpcs）
  const known = knownNpcs(npcs, sess, module)

  return (
    <>
      {/* 你自己也只是名单里的一行，和下面那些人同一个形状——数值、天数时段、
          「你记得的」全在点进去那一页里。从前这儿是一张永远摊开的大卡，
          一进这一格先被自己占掉大半屏，名单反而看不见。地点和前几条数值
          GameHud 上一直挂着，不靠这儿常驻 */}
      <button
        onClick={onOpenSelf}
        className={`${PANEL} w-full text-left p-3 hover:bg-muted/40 transition-colors`}
      >
        <div className="flex items-center gap-2.5">
          <RpgAvatar name={sess.char_name || '你'} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium flex items-center gap-1.5">
              <span className="truncate">{sess.char_name || '无名者'}</span>
              <span className="text-[10px] px-1 py-0.5 rounded shrink-0
                bg-amber-500/15 text-amber-700 dark:text-amber-300">
                主角
              </span>
            </p>
            <p className="text-xs text-muted-foreground truncate">
              {sess.location || '不知身在何处'}
            </p>
          </div>
          <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        </div>
      </button>

      {/* 「登记在册」写出人数，因为这一格的内容是会长的：玩家得看得出
          名单在变。被提到一句不算登记——那只是让模型拿到了他的设定，
          人还没在你眼前出现过，所以下面这句提示只说「走到他所在的地点」 */}
      <p className="text-[11px] text-muted-foreground px-1 pt-1">
        登记在册 {known.length} 人
      </p>

      {known.length === 0 ? (
        <p className="text-xs text-muted-foreground px-1 leading-relaxed">
          {module?.play_style === 'sim'
            ? '这个模组还没有角色。回模组页的「角色」里加几个人，这里就会有了。'
            : '还没遇到什么人。走到他们所在的地点，见过面才会记到这里。'}
        </p>
      ) : known.map(npc => {
        const state = sess.npc_states?.[String(npc.id)] || {}
        const isHere = onstage(npc, sess)
        const isFollowing = following(npc, sess)
        // AI 调度记下的那句。从前只在点进去那一页里露面，于是按完「结束时段」
        // 界面上什么都不变，玩家以为调度根本没跑
        const activity = sess.npc_activities?.[String(npc.id)] || ''
        return (
          <button
            key={npc.id}
            onClick={() => onOpenNpc(npc)}
            className={`${PANEL} w-full text-left p-3 hover:bg-muted/40 transition-colors`}
          >
            <div className="flex items-center gap-2.5">
              <RpgAvatar name={npc.name} url={npc.avatar_url} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium flex items-center gap-1.5">
                  <span className="truncate">{npc.name}</span>
                  {/* 名单这一格只标状态，叉在档案页里：这里整行是个 button，
                      里面再套一个 button 是无效 HTML，点了也未必触发 */}
                  {isFollowing && (
                    <span className="text-[10px] px-1 py-0.5 rounded shrink-0
                      bg-cyan-500/15 text-cyan-700 dark:text-cyan-300">
                      跟着你
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground truncate">
                  {isHere ? '就在你面前' : npcPlace(
                    npc, sess.slot, sess.npc_places, sess.npc_followers, sess.location,
                  ) || '不知在哪'}
                </p>
                {/* 一行封顶、超了截断：这句最长 40 字，摊开会把名单顶散 */}
                {activity && (
                  <p className="text-[11px] text-muted-foreground/70 truncate">
                    最近：{activity}
                  </p>
                )}
              </div>
              <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            </div>
            {npc.relation_enabled !== false && (
              <div className="mt-2.5 space-y-1.5">
                {(npc.relation_stat_names?.length
                  ? relDefs.filter(def => npc.relation_stat_names.includes(def.name))
                  : relDefs
                ).map(def => (
                  <StatBar
                    key={def.name}
                    def={def}
                    value={Number(state[def.name] ?? npc.initial_state?.[def.name] ?? def.initial)}
                  />
                ))}
              </div>
            )}
          </button>
        )
      })}
    </>
  )
}
