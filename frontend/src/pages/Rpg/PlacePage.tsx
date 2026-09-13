import { Info, MapPin, MessagesSquare, Users } from 'lucide-react'
import type { RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { knownNpcs, norm, onstage } from './condition'
import RpgAvatar from './RpgAvatar'
import { PANEL } from './rpgUi'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
  npcs: RpgNpc[]
  /** 只看这个人参与过的部分。不改变接下来的话进哪儿——那只有一个地方可进 */
  onTalk: (npc: RpgNpc) => void
  onDetail: (npc: RpgNpc) => void
  /** 公共场面：群戏、环境描写、一个人待着都落这里 */
  onScene: () => void
}

/**
 * 地点页：这里有哪些人，点谁就看谁的视角。
 *
 * 这一页上的按钮全是导航（换个视角看），不是动作，所以不看 `locked`：
 * 一局结束之后历史照样该能翻。
 *
 * 措辞是「看谁」而不是「进谁的线」：所有消息都在同一条时间线上，点一个人
 * 只是把时间线**筛**成他参与过的那些，不会让接下来写的话落到别处去。
 * 从前这一页写的「在其中点名提到某个人，就会进他单独的那条线」是界面的
 * 老规矩——正是它让同一句话看着像是存错了地方。
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
          看全部
        </p>
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
          整条时间线，从开场白到现在。群戏、环境描写、一个人待着、跟谁说了句话，
          都在这上面。
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
            title="只看他参与过的部分"
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-primary
              text-primary-foreground hover:opacity-90 shrink-0"
          >
            <MessagesSquare className="w-3.5 h-3.5" />查看
          </button>
        </div>
      ))}
    </div>
  )
}
