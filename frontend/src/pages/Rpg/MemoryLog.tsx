import { useMemo, useState } from 'react'
import type { RpgNpc, RpgSession } from '../../api/client'
import { PLAYER_SLOT } from './sidebar/SummaryBlock'

/**
 * 顶栏那个记忆历史查看器：下拉框选一格，列出这一格的记忆是怎么长成现在这样的。
 *
 * 和小说侧的章节摘要对应，区别在切分单位——小说按章，这里按**游戏内的格**
 * （第几天 · 哪个时段）。攒历史的地方是后端 `_log_summary`，一格一条。
 *
 * **只读**。改记忆的口子在右侧栏那张角色卡上（SummaryBlock），那儿改的是「此刻
 * 这一份」，也就是真的会注入模型的那段话。这里列的是已经被顶掉的旧版本，改它
 * 没有任何意义，给个输入框只会让人以为动了模型的记忆。
 *
 * 老局是空的：这一列上线之前被覆盖掉的版本库里没有，找不回来。
 */
export default function MemoryLog({ sess, npcs }: { sess: RpgSession; npcs: RpgNpc[] }) {
  // 有历史的格子才进下拉框。玩家那格排最前（它是唯一一格装全部剧情的），
  // 剩下的按模组里的角色顺序，不按 id——作者排的顺序就是他心里的主次
  const slots = useMemo(() => {
    const log = sess.summary_log || {}
    const rows: { slot: string; label: string }[] = []
    if (log[PLAYER_SLOT]?.length) rows.push({ slot: PLAYER_SLOT, label: '你的经历' })
    for (const npc of npcs) {
      if (log[String(npc.id)]?.length) rows.push({ slot: String(npc.id), label: npc.name })
    }
    return rows
  }, [sess.summary_log, npcs])

  const [picked, setPicked] = useState('')
  // 选中的那格可能因为读档而整个消失（读档会把 summary_log 一起回滚），
  // 所以每次渲染都回落到第一格，而不是把失效的选择留在 state 里
  const slot = slots.some(s => s.slot === picked) ? picked : slots[0]?.slot || ''
  // 新的排前面：玩家要核对的几乎总是最近那几格
  const rows = [...(sess.summary_log?.[slot] || [])].reverse()

  if (!slots.length) {
    return (
      <p className="text-xs text-muted-foreground leading-relaxed">
        还没有攒下记忆。剧情长到窗口装不下时，溢出的那一段会被压成一段话记在这儿——
        每一格一条。
      </p>
    )
  }

  return (
    <div className="space-y-2.5">
      <select
        value={slot}
        onChange={e => setPicked(e.target.value)}
        className="w-full text-xs rounded-md border bg-background px-2 py-1.5
          focus:outline-none focus:ring-1 focus:ring-primary/40"
      >
        {slots.map(s => (
          <option key={s.slot} value={s.slot}>
            {s.label}（{sess.summary_log[s.slot].length} 格）
          </option>
        ))}
      </select>
      <p className="text-[11px] text-muted-foreground/70 leading-relaxed">
        每一格压出来的那版长期记忆，新的在上面。只能看：要改这个人此刻的记忆，
        去右边那张角色卡。
      </p>
      {rows.map(row => (
        <div
          key={`${row.day}-${row.slot}-${row.upto}`}
          className="border-l-2 border-primary/40 pl-3"
        >
          <p className="text-[11px] text-muted-foreground">
            第 {row.day} 天{row.slot ? ` · ${row.slot}` : ''}
            <span className="text-muted-foreground/60"> · 盖到第 {row.upto} 条</span>
          </p>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{row.text}</p>
        </div>
      ))}
    </div>
  )
}
