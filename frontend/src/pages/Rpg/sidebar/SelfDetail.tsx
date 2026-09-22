import { useEffect } from 'react'
import { ChevronLeft, MapPin } from 'lucide-react'
import type { RpgModule, RpgSession, RpgStatDef } from '@/api/client'
import RpgAvatar from '../RpgAvatar'
import StatBar from '../StatBar'
import { playSfx } from '../useSfx'
import SummaryBlock from './SummaryBlock'

/**
 * 你自己的档案。和 NpcDetail 一样住在侧栏那一列里，顶掉名单。
 *
 * 从前这些内容是名单最上面一张永远摊开的卡，一进「角色」这一格先被自己占掉
 * 大半屏。现在主角在名单里也只是一行，点开才进这儿——和小说侧角色、和下面
 * 那些 NPC 同一个规矩。
 *
 * **没有 tab、没有编辑态**：NpcDetail 那两样是给「模组作者写死的资料」用的，
 * 而这一页上没有那种东西，只有这一局长出来的状态和记忆。
 */
export default function SelfDetail({
  sess, module, statDefs, onBack, onSaveSummary,
}: {
  sess: RpgSession
  module?: RpgModule
  statDefs: RpgStatDef[]
  /** 回名单 */
  onBack: () => void
  /** 改写你自己那格的长期记忆。空串 = 丢掉它 */
  onSaveSummary: (text: string) => Promise<void>
}) {
  // 同 NpcDetail：一次挂载 = 一次打开
  useEffect(() => { playSfx('npc') }, [])

  // 和顶栏同一条判据：有时段表就有时钟，不看 slot 有没有落格
  const hasClock = (sess.time_slots?.length || module?.time_slots?.length || 0) > 0

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="shrink-0 border-b border-border/60 px-3 py-2.5 flex items-center gap-2">
        <button
          onClick={onBack}
          title="回名单"
          className="p-1 rounded hover:bg-muted shrink-0"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        <RpgAvatar name={sess.char_name || '你'} size="md" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold truncate">{sess.char_name || '无名者'}</p>
          {/* 天数时段接在地点后面当后缀，不另起一行：这一列最窄只有 280，
              页眉再长一行就把下面的数值挤下去了 */}
          <p className="text-xs text-muted-foreground flex items-center gap-1 truncate">
            <MapPin className="w-3 h-3 shrink-0" />
            {sess.location || '不知身在何处'}
            {hasClock && (
              <span className="shrink-0">
                · 第 {sess.day} 天{sess.slot ? ` · ${sess.slot}` : ''}
              </span>
            )}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {statDefs.length > 0 ? (
          <div className="space-y-2">
            {statDefs.map(def => (
              <StatBar key={def.name} def={def} value={Number(sess.stats?.[def.name] ?? def.initial)} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground leading-relaxed">
            这个模组还没定义数值。回模组页的「玩家数值」里加几项，这里就会显示。
          </p>
        )}

        {/* 你自己那格的长期记忆，挂在你自己这一页上——每个角色那格挂在她们
            各自的档案页里，位置对得上「谁记得这件事」。它和她们那几格是**并列**
            的：这一份是你亲身经历过的全部（含单独赶路那些），每轮都注入 */}
        <SummaryBlock
          title="你记得的"
          hint="旧剧情压成的一段话，每轮都喂给模型。改它等于改这一局的前情"
          empty="还没压过：这一局的经过都还在窗口里，原样记着。"
          text={sess.summary || ''}
          onSave={onSaveSummary}
        />
      </div>
    </div>
  )
}
