import { Footprints, Info, MapPin, MessagesSquare, Users, X } from 'lucide-react'
import type { RpgLocation, RpgNpc, RpgSession } from '@/api/client'
import { knownNpcs, norm, onstage } from './condition'
import LocationOverview from './LocationOverview'
import RpgAvatar from './RpgAvatar'
import { PANEL } from './rpgUi'

interface Props {
  sess: RpgSession
  locations: RpgLocation[]
  npcs: RpgNpc[]
  /** 把他叫到一边单独说话：时间线筛成他参与过的部分，同时切成私聊模式 */
  onTalk: (npc: RpgNpc) => void
  onDetail: (npc: RpgNpc) => void
  /** 不冲着某一个人去的那两种开场：一起聊（群聊）、独自行动。
   *  两个都回整条时间线，区别只在这一轮的话记进谁的记忆 */
  onScene: (mode: 'group' | 'solo') => void
  /** 点内部地图上的一个地点，直接过去。同总览那张图 */
  onGo: (name: string) => void
  /** 划掉 GM 给这个地方记错的那一句近况。参数是 place_notes 里的那个键 */
  onDropPlaceNote: (place: string) => void
  locked: boolean
  busy: boolean
}

/**
 * 地点页：这里有哪些人，以及这一轮你打算怎么开口。
 *
 * 三个开场，一个都不藏：**一起聊**（在场的人都参与）、**独自行动**（你做你自己的
 * 事）、每个人身上的**单独说话**（只跟她说，旁人听不见）。它们决定的是这段话
 * 记进谁的记忆——这是明牌的，因为从前它由「你正在看谁」偷偷决定，于是同一句话
 * 看着像是存错了地方。
 *
 * 点进来的按钮全是导航加一个开场姿势，不往世界里写东西，所以不看 `locked`：
 * 一局结束之后历史照样该能翻。选错了也不要紧，输入框上方还能改。
 *
 * 时间线只有一条：点一个人只是把它**筛**成他参与过的那些，不会分叉。
 */
export default function PlacePage({
  sess, locations, npcs, onTalk, onDetail, onScene, onGo, onDropPlaceNote, locked, busy,
}: Props) {
  const loc = locations.find(l => norm(l.name) === norm(sess.location || ''))
  const children = loc ? locations.filter(child => child.parent_id === loc.id) : []
  // 只列见过面的人：列出来等于把还没登场的人抖出来
  const here = knownNpcs(npcs, sess).filter(n => onstage(n, sess))
  // GM 记下的「这地方现在什么样」。按 norm 找键：模型写进去的地名可能
  // 多个空格，删的时候要把原来那个键原样传回去
  const noteKey = Object.keys(sess.place_notes || {})
    .find(key => norm(key) === norm(sess.location || ''))
  const note = noteKey ? String(sess.place_notes[noteKey] || '').trim() : ''

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
        {/* 模组里写死的描述之下、这一局被你弄成的样子。它每次你站在这儿都会
            进提示词，所以记错了得有个不读档的补救 */}
        {note && (
          <div className="group flex items-start gap-2 text-sm mt-2 pt-2 border-t leading-relaxed">
            <p className="flex-1">
              <span className="text-muted-foreground">现在</span>
              <span className="mx-1.5 text-muted-foreground/50">·</span>
              {note}
            </p>
            <button
              onClick={() => onDropPlaceNote(noteKey!)}
              title="划掉这一句"
              className="p-0.5 mt-0.5 rounded text-muted-foreground/50 opacity-0 group-hover:opacity-100 hover:bg-muted hover:text-foreground shrink-0"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>

      {/* 内部地图直接摊开。以前这里是一个「进入内部地图」的按钮，可里面有什么
          按钮上根本看不出来，等于多点一下才看得见——地方就在脚下，没有「进入」
          这一说 */}
      {children.length > 0 && (
        <div className={`${PANEL} p-4 space-y-2`}>
          <p className="text-sm font-medium flex items-center gap-1.5">
            <MapPin className="w-4 h-4 text-primary shrink-0" />
            这里面
          </p>
          <LocationOverview
            sess={sess}
            locations={locations}
            npcs={npcs}
            parentId={loc!.id}
            locked={locked}
            busy={busy}
            onGo={onGo}
            // 玩家站在外层这一格上，里面没有哪个点是「你在这里」，点不到
            onPick={() => {}}
          />
        </div>
      )}

      {/* 三个开场在这一页上摊平：这两个，加下面每个人身上的「单独说话」。
          从前这儿只有一个「看全部」，它同时是「看整条时间线」和「群聊」两件事
          ——独自行动根本没有入口，群聊也看不出来自己选过。
          两个都回整条时间线（看不丢东西），进去之后输入框上方还能改主意 */}
      <div className={`grid gap-3 ${here.length > 0 ? 'sm:grid-cols-2' : ''}`}>
        {here.length > 0 && (
          <button
            onClick={() => onScene('group')}
            className="text-left rounded-xl border border-primary/25 bg-primary/[0.06] p-4
              hover:bg-primary/[0.12] transition-colors"
          >
            <p className="text-sm font-medium flex items-center gap-1.5">
              <Users className="w-4 h-4 text-primary shrink-0" />
              一起聊
            </p>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              {here.map(npc => npc.name).join('、')}都在场，这段话记进他们每个人的记忆。
            </p>
          </button>
        )}
        <button
          onClick={() => onScene('solo')}
          className="text-left rounded-xl border p-4 hover:bg-muted/50 transition-colors"
        >
          <p className="text-sm font-medium flex items-center gap-1.5">
            <Footprints className="w-4 h-4 text-primary shrink-0" />
            独自行动
          </p>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
            {here.length > 0
              ? '你做你自己的事，不主动找谁搭话。旁边的人看着——他们记得，也可能开口。'
              : '翻箱子、赶路、琢磨事情。这里没有别人，写什么都算你一个人的。'}
          </p>
        </button>
      </div>

      {here.length === 0 ? (
        <p className="text-xs text-muted-foreground px-1 leading-relaxed">
          想找人说话，回总览换个地方。
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
            title="把他叫到一边单独说话，旁人听不见这一段"
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg bg-primary
              text-primary-foreground hover:opacity-90 shrink-0"
          >
            <MessagesSquare className="w-3.5 h-3.5" />单独说话
          </button>
        </div>
      ))}
    </div>
  )
}
