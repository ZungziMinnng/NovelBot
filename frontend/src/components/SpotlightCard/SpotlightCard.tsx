import { useRef, useState } from 'react'

interface SpotlightCardProps extends React.PropsWithChildren {
  className?: string
  spotlightColor?: string
  style?: React.CSSProperties
}

// 小说 / 酒馆 / 游戏三张列表页的卡共用这一套。颜色全走 --primary，
// 进了 .mode-tavern / .mode-game 自动变粉 / 变紫，不再写死 pink/violet
export const LIST_CARD =
  'reveal group rounded-2xl border border-foreground/10 bg-card shadow-sm transition-[transform,box-shadow,border-color] duration-500 ease-out-expo hover:-translate-y-1 hover:border-primary/40 hover:shadow-xl'
// 顶边一条主色，悬停从左展开（和首页模式卡同一个动作）
export const LIST_CARD_BAR =
  'pointer-events-none absolute inset-x-0 top-0 z-10 h-[3px] origin-left scale-x-[0.18] bg-primary transition-transform duration-700 ease-out-expo group-hover:scale-x-100 group-focus-within:scale-x-100'
// 卡里的整块可点区域：键盘聚焦画内描边（外描边会被卡的 overflow-hidden 裁掉）
export const LIST_CARD_HIT =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/60'
export const CARD_ICON_BTN =
  'grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors'
export const CARD_ICON_BTN_DANGER =
  'grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/10 transition-colors'
export const HEADER_PILL =
  'flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border border-foreground/10 text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground transition-colors'

export default function SpotlightCard({
  children,
  className = '',
  spotlightColor = 'rgba(255, 255, 255, 0.06)',
  style,
}: SpotlightCardProps) {
  const divRef = useRef<HTMLDivElement>(null)
  const [isFocused, setIsFocused] = useState(false)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [opacity, setOpacity] = useState(0)

  const handleMouseMove: React.MouseEventHandler<HTMLDivElement> = (e) => {
    if (!divRef.current || isFocused) return
    const rect = divRef.current.getBoundingClientRect()
    setPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top })
  }

  return (
    <div
      ref={divRef}
      onMouseMove={handleMouseMove}
      onFocus={() => { setIsFocused(true); setOpacity(1) }}
      onBlur={() => { setIsFocused(false); setOpacity(0) }}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      className={`relative overflow-hidden ${className}`}
      style={style}
    >
      <div
        className="pointer-events-none absolute inset-0 transition-opacity duration-500 ease-in-out"
        style={{
          opacity,
          background: `radial-gradient(circle at ${position.x}px ${position.y}px, ${spotlightColor}, transparent 80%)`,
        }}
      />
      {children}
    </div>
  )
}
