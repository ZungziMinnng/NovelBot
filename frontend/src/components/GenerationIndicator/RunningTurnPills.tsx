import type { ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Loader2, X } from 'lucide-react'

/**
 * 后台生成中的浮层药丸列表。RPG 和酒馆共用这一份，两边只差图标、文案和
 * 「什么算已经在那一页了」的路径规则。
 *
 * **用 `useLocation` 比 pathname，不用 `useParams`**：调用方挂在 `<Routes>`
 * 外面（App.tsx），那儿没有路由上下文，`useParams` 只会返回空对象，拿它判
 * 「已经在那一页了」永远判不中（GenerationIndicator 就踩了这个坑，药丸在
 * 自己页面上也一直挂着）。
 *
 * 允许多局并行，所以是好几个药丸纵着排——外层容器负责堆叠和间距。
 */
export interface RunningTurn {
  sessionId: number
  title: string
  path: string
}

interface Props {
  running: RunningTurn[]
  /** 这一条是不是就是当前所在的页面，真则不显示药丸 */
  isHere: (turn: RunningTurn, pathname: string) => boolean
  icon: ReactNode
  /** 接在书名号后面，如「剧情生成中」 */
  label: string
  title: string
  /** 两侧停止按钮的 class 有细微差别，原样传进来别统一 */
  stopClassName: string
  onAbort: (sessionId: number) => void
}

export default function RunningTurnPills({
  running, isHere, icon, label, title, stopClassName, onAbort,
}: Props) {
  const navigate = useNavigate()
  const location = useLocation()

  const here = running.filter(turn => !isHere(turn, location.pathname))
  if (here.length === 0) return null

  return (
    <>
      {here.map(turn => (
        <div
          key={turn.sessionId}
          onClick={() => navigate(turn.path)}
          className="flex items-center gap-2.5 bg-primary text-primary-foreground px-4 py-2.5 rounded-full shadow-lg cursor-pointer hover:opacity-90 transition-opacity select-none"
          title={title}
        >
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          {icon}
          <span className="text-sm font-medium whitespace-nowrap">
            {turn.title ? `《${turn.title}》` : ''}{label}
          </span>
          <button
            onClick={e => {
              e.stopPropagation()
              onAbort(turn.sessionId)
            }}
            className={stopClassName}
            title="停止生成"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </>
  )
}
