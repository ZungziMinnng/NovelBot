import { Gauge, X } from 'lucide-react'

/** 一次操作的真实用量。
 *
 *  叙事 = 写正文那次调用；辅助 = 判定 + 结算 + 建议，后端把它们累加进同一对
 *  `aux_*` 字段，拆不开，所以这里也不假装拆得开。 */
export interface TurnCost {
  /** assistant 那行消息的 id，同时当 key */
  id: number
  label: string
  narrIn: number
  narrOut: number
  auxIn: number
  auxOut: number
}

interface Props {
  /** 从新到旧，第一条就是最近这次操作 */
  entries: TurnCost[]
  totalIn: number
  totalOut: number
  onClose: () => void
}

/** 上万就压成 k：这一列只有 200px 宽，五位数会把行挤断 */
const fmt = (n: number) => (n >= 10000 ? `${(n / 1000).toFixed(1)}k` : n.toLocaleString())

const sum = (cost: TurnCost) => cost.narrIn + cost.narrOut + cost.auxIn + cost.auxOut

function Line({ name, tin, tout }: { name: string; tin: number; tout: number }) {
  return (
    <div className="flex items-baseline gap-1 text-muted-foreground">
      <span className="shrink-0">{name}</span>
      <span className="ml-auto shrink-0 tabular-nums">↑{fmt(tin)} ↓{fmt(tout)}</span>
    </div>
  )
}

/** 本次行动花了多少 token。挂在立绘列右边，页头的「用量」开关管它的生死。
 *
 *  数字全部来自已经在手的数据——消息列表每行都带四个 token 字段，回合结束时
 *  那条 done 也带同样四个，所以这一列不需要任何新接口。 */
export default function TurnCostPanel({ entries, totalIn, totalOut, onClose }: Props) {
  const [now, ...past] = entries

  return (
    <div className="flex flex-col gap-3 border-t border-border/50 px-3 py-4 text-xs">
      <div className="flex items-center gap-1 font-semibold text-foreground/80">
        <Gauge className="w-3.5 h-3.5 shrink-0" />
        本次用量
        <button onClick={onClose} title="收起这一列" className="ml-auto p-0.5 rounded hover:bg-muted">
          <X className="w-3 h-3" />
        </button>
      </div>

      {!now ? (
        /* 地点总览里点【移动到这里】、按「结束这个时段」都是纯引擎的，一个字
           都不发给模型，所以它们不会在这里留下条目——说清楚，免得看着像坏了 */
        <p className="text-muted-foreground leading-relaxed">
          这一局还没有调用过模型。瞬移、结束时段这类纯引擎操作不花 token，也不会出现在这里。
        </p>
      ) : (
        <div className="space-y-1">
          <p className="font-medium truncate" title={now.label}>{now.label}</p>
          <Line name="叙事" tin={now.narrIn} tout={now.narrOut} />
          <Line name="判定结算" tin={now.auxIn} tout={now.auxOut} />
          <div className="flex items-baseline gap-1 pt-1 border-t border-border/50 font-medium">
            <span>合计</span>
            <span className="ml-auto tabular-nums">{fmt(sum(now))}</span>
          </div>
        </div>
      )}

      {past.length > 0 && (
        <div className="space-y-0.5">
          <p className="text-muted-foreground/70">再往前</p>
          {past.map(entry => (
            <div key={entry.id} className="flex items-baseline gap-1 text-muted-foreground">
              <span className="truncate" title={entry.label}>{entry.label}</span>
              <span className="ml-auto shrink-0 tabular-nums">{fmt(sum(entry))}</span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-auto pt-2 border-t border-border/50">
        <p className="text-muted-foreground/70">本局累计</p>
        <p className="text-foreground/80 tabular-nums">↑{fmt(totalIn)} ↓{fmt(totalOut)}</p>
      </div>
    </div>
  )
}
