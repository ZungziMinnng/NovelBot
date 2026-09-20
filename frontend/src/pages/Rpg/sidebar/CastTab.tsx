import { ChevronRight, Clock, MapPin } from 'lucide-react'
import type { RpgModule, RpgNpc, RpgSession, RpgStatDef } from '@/api/client'
import { following, knownNpcs, npcPlace, onstage } from '../condition'
import RpgAvatar from '../RpgAvatar'
import StatBar from '../StatBar'
import { PANEL } from '../rpgUi'
import SummaryBlock from './SummaryBlock'

export default function CastTab({
  sess, module, npcs, statDefs, relDefs, onOpenNpc, onSaveSummary,
}: {
  sess: RpgSession
  module?: RpgModule
  npcs: RpgNpc[]
  statDefs: RpgStatDef[]
  relDefs: RpgStatDef[]
  onOpenNpc: (npc: RpgNpc) => void
  /** 改写你自己那格的长期记忆。每个角色那格在她们各自的档案页里改 */
  onSaveSummary: (text: string) => Promise<void>
}) {
  // 没见过也不在场的不列：列出来等于把还没登场的人抖出来。
  // 模拟器例外，那边开局就全员在册（见 knownNpcs）
  const known = knownNpcs(npcs, sess, module)

  return (
    <>
      <div className={`${PANEL} p-3`}>
        <div className="flex items-center gap-2.5">
          <RpgAvatar name={sess.char_name || '你'} size="md" />
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{sess.char_name || '无名者'}</p>
            <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
              <MapPin className="w-3 h-3 shrink-0" />
              {sess.location || '不知身在何处'}
            </p>
            {/* 和顶栏同一条判据：有时段表就有时钟，不看 slot 有没有落格 */}
            {(sess.time_slots?.length || module?.time_slots?.length || 0) > 0 && (
              <p className="text-xs text-muted-foreground truncate flex items-center gap-1">
                <Clock className="w-3 h-3 shrink-0" />
                第 {sess.day} 天{sess.slot ? ` · ${sess.slot}` : ''}
              </p>
            )}
          </div>
        </div>
        {statDefs.length > 0 ? (
          <div className="mt-3 space-y-2">
            {statDefs.map(def => (
              <StatBar key={def.name} def={def} value={Number(sess.stats?.[def.name] ?? def.initial)} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground mt-3 leading-relaxed">
            这个模组还没定义数值。回模组页的「玩家数值」里加几项，这里就会显示。
          </p>
        )}
        {/* 你自己那格的长期记忆，挂在你自己这张卡上——每个角色那格挂在她们
            各自的档案页里，位置对得上「谁记得这件事」。它和她们那几格是**并列**
            的：这一份是你亲身经历过的全部（含单独赶路那些），每轮都注入 */}
        <div className="mt-3">
          <SummaryBlock
            title="你记得的"
            hint="旧剧情压成的一段话，每轮都喂给模型。改它等于改这一局的前情"
            empty="还没压过：这一局的经过都还在窗口里，原样记着。"
            text={sess.summary || ''}
            onSave={onSaveSummary}
          />
        </div>
      </div>

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
