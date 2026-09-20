import { useState, useRef, useEffect } from 'react'
import { Type } from 'lucide-react'

/**
 * 正文字体的那个「Aa」按钮。**受控**：不自己调 `useReadingFont`。
 *
 * 调用页面本来就得拿 hook 的 `style` 铺到气泡上，hook 在页面那一层调一次就够。
 * 按钮再调一份就是两套 state，调完这边的 select，那边的气泡不会跟着变。
 * 写盘也归 hook 管，这里不碰 localStorage。
 */
export default function ReadingFontButton({
  size = 'md',
  fontSize,
  lineHeight,
  fontWeight,
  setFontSize,
  setLineHeight,
  setFontWeight,
}: {
  size?: 'sm' | 'md'
  fontSize: number
  lineHeight: number
  fontWeight: string
  setFontSize: (v: number) => void
  setLineHeight: (v: number) => void
  setFontWeight: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'
  const btnPad = size === 'sm' ? 'p-1.5' : 'p-2'

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`${btnPad} rounded-md hover:bg-muted transition-colors`}
        title="正文字体"
      >
        <Type className={iconSize} />
      </button>
      {open && (
        // 选完不关：这三项经常要连着来回调，关一次再点开一次太烦
        <div className="absolute right-0 top-full mt-1 z-50 bg-card border rounded-xl shadow-lg p-3 w-[200px] space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">字号</span>
            <select
              value={fontSize}
              onChange={e => setFontSize(Number(e.target.value))}
              className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              title="字体大小"
            >
              <option value={12}>12px</option>
              <option value={13}>13px</option>
              <option value={14}>14px</option>
              <option value={15}>15px</option>
              <option value={16}>16px</option>
              <option value={17}>17px</option>
              <option value={18}>18px</option>
              <option value={19}>19px</option>
              <option value={20}>20px</option>
              <option value={22}>22px</option>
              <option value={24}>24px</option>
              <option value={26}>26px</option>
              <option value={28}>28px</option>
              <option value={32}>32px</option>
            </select>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">行间距</span>
            <select
              value={lineHeight}
              onChange={e => setLineHeight(Number(e.target.value))}
              className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              title="行间距"
            >
              <option value={1.2}>1.2&#215;</option>
              <option value={1.5}>1.5&#215;</option>
              <option value={1.8}>1.8&#215;</option>
              <option value={2.0}>2.0&#215;</option>
              <option value={2.5}>2.5&#215;</option>
              <option value={3.0}>3.0&#215;</option>
            </select>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">粗细</span>
            <select
              value={fontWeight}
              onChange={e => setFontWeight(e.target.value)}
              className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
              title="字体粗细"
            >
              <option value="">常规</option>
              <option value="300">细体</option>
              <option value="500">中等</option>
              <option value="600">半粗</option>
              <option value="700">加粗</option>
            </select>
          </div>
        </div>
      )}
    </div>
  )
}
