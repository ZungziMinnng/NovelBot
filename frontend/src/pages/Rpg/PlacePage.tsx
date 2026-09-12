import { Info, MapPin, MessagesSquare, Users } from 'lucide-react'
import type { RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { knownNpcs, norm, onstage } from './condition'
import RpgAvatar from './RpgAvatar'
import { PANEL } from './rpgUi'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
  npcs: RpgNpc[]
  /** 进这个人的线，之后说的话只进他这条历史 */
  onTalk: (npc: RpgNpc) => void
  onDetail: (npc: RpgNpc) => void
  /** 公共场面：群戏、环境描写、一个人待着都落这里 */
  onScene: () => void
}

/**
 * 地点页：这里有哪些人，点谁就跟谁说话。
 *
 * 这一页上的按钮全是导航（换一条线看），不是动作，所以不看 `locked`：
 * 一局结束之后历史照样该能翻。
 *
 * 「场面线」的文案特意不叫「独处」——它会膨胀成**公共场面**，三人同桌吃饭、
 * 群戏、没人在场的环境描写都只能落这里。写成「独处」玩家就不知道该往哪放了。
 */
export default function PlacePage({
  sess, locations, npcs, onTalk, onDetail, onScene,
}: Props) {
  const loc = locations.find(l => norm(l.name) === norm(sess.location || ''))
  // 只列见过面的人：列出来等于把还没登场的人抖出来
  const here = knownNpcs(npcs, sess).filter(n => onstage(n, sess))

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className={`${PANEL} p-4`}>
        <p className="font-semibold flex items-center gap-1.5">
          <MapPin className="w-4 h-4 text-primary shrink-0" />
          {sess.location || '不知身在何处'}
        </p>
        {loc?.description && (
          <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">{loc.description}</p>
        )}
      </div>

      <button
        onClick={onScene}
        className="w-full text-left rounded-xl border border-primary/25 bg-primary/[0.06] p-4
          hover:bg-primary/[0.12] transition-colors"
      >
        <p className="text-sm font-medium flex items-center gap-1.5">
          <Users className="w-4 h-4 text-primary shrink-0" />
          大家在一起
        </p>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          没有特定的说话对象，在场的人都在。群戏、环境描写、一个人待着，都写到这条线上。
        </p>
      </button>

      {here.length === 0 ? (
        <p className="text-xs text-muted-foreground px-1 leading-relaxed">
          这里没有别人。回总览换个地方看看。
        </p>
      ) : here.map(npc => (
        <div key={npc.id} className={`${PANEL} p-3.5 flex items-center gap-3`}>
          <RpgAvatar name={npc.name} url={npc.avatar_url} size="md" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{npc.name}</p>
            {npc.description && (
              <p className="text-xs text-muted-foreground truncate">{npc.description}</p>
            )}
          </div>
          <button
            onClick={() => onDetail(npc)}
            title="看他的档案"
            className="p-2 rounded-lg text-muted-foreground hover:bg-muted shrink-0"
          >
            <Info className="w-4 h-4" />
          </button>
          <button
            onClick={() => onTalk(npc)}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-primary
              text-primary-foreground hover:opacity-90 shrink-0"
          >
            <MessagesSquare className="w-3.5 h-3.5" />说话
          </button>
        </div>
      ))}
    </div>
  )
}
