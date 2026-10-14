import { useState, useRef, useEffect } from 'react'
import { MoreHorizontal } from 'lucide-react'

export interface HeaderMenuItem {
  key: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  onClick: () => void
  title?: string
  /** 开关类条目（如 Dev 视图）处于打开状态 */
  active?: boolean
}

/**
 * 顶栏的「更多」。不常用的入口收进来，顶栏只留高频的几个。
 * 浮层用 absolute 留在组件树里，不 portal：放进 .mode-game 页面时还能拿到那套颜色变量
 */
export default function HeaderMenu({ items, label = '更多' }: { items: HeaderMenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const anyActive = items.some(i => i.active)

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={label}
        className={`relative flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-full transition-colors ${
          open ? 'bg-foreground/[0.08] text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06]'
        }`}
      >
        <MoreHorizontal className="w-3.5 h-3.5" />
        <span className="hidden sm:inline">{label}</span>
        {/* 收起来的开关有开着的，给个小点提示，不然打开 Dev 后就找不到它了 */}
        {anyActive && <span aria-hidden className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-primary" />}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1.5 min-w-[11rem] rounded-xl border border-foreground/10 bg-card p-1.5 shadow-xl"
        >
          {items.map(({ key, label: text, icon: Icon, onClick, title, active }) => (
            <button
              key={key}
              role="menuitem"
              title={title}
              onClick={() => { setOpen(false); onClick() }}
              className={`w-full flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${
                active ? 'text-primary bg-primary/10' : 'hover:bg-foreground/[0.06]'
              }`}
            >
              <Icon className="w-4 h-4 shrink-0 opacity-80" />
              <span className="flex-1">{text}</span>
              {active && <span className="text-[11px] font-medium">已开</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
