import { useState, useRef, useEffect } from 'react'
import { Type } from 'lucide-react'

const SELECT = 'border rounded-lg px-1.5 py-1 bg-background text-xs'

/**
 * 正文字体的那个「Aa」按钮。**受控**：不自己调 `useReadingFont`。
 *
 * 调用页面本来就得拿 hook 的 `style` 铺到气泡上，hook 在页面那一层调一次就够。
 * 按钮再调一份就是两套 state，调完这边的 select，那边的气泡不会跟着变。
 * 写盘也归调用方管，这里不碰 localStorage。
 *
 * 字体、颜色、首行缩进三项是可选的：只有小说编辑器传，酒馆/游戏不传就不显示。
 */
export default function ReadingFontButton({
  size = 'md',
  fontSize,
  lineHeight,
  fontWeight,
  setFontSize,
  setLineHeight,
  setFontWeight,
  fontFamily,
  setFontFamily,
  fontColor,
  setFontColor,
  indent,
  setIndent,
}: {
  size?: 'sm' | 'md'
  fontSize: number
  lineHeight: number
  fontWeight: string
  setFontSize: (v: number) => void
  setLineHeight: (v: number) => void
  setFontWeight: (v: string) => void
  fontFamily?: string
  setFontFamily?: (v: string) => void
  fontColor?: string
  setFontColor?: (v: string) => void
  indent?: boolean
  setIndent?: (v: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', handler)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', handler)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'
  const btnPad = size === 'sm' ? 'p-1.5' : 'p-2'

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`${btnPad} rounded-full transition-colors ${open ? 'bg-foreground/[0.08] text-foreground' : 'hover:bg-muted'}`}
        title="正文字体"
        aria-label="正文字体"
        aria-expanded={open}
      >
        <Type className={iconSize} />
      </button>
      {open && (
        // 选完不关：这几项经常要连着来回调，关一次再点开一次太烦
        <div className="absolute right-0 top-full mt-1.5 z-50 bg-card border border-foreground/10 rounded-xl shadow-xl p-3 w-[220px] space-y-2.5">
          <p className="text-xs font-medium">正文排版</p>
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">字号</span>
            <select
              value={fontSize}
              onChange={e => setFontSize(Number(e.target.value))}
              className={SELECT}
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
              className={SELECT}
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
          {setFontFamily && (
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">字体</span>
              <select
                value={fontFamily ?? ''}
                onChange={e => setFontFamily(e.target.value)}
                className={`${SELECT} max-w-[110px]`}
                title="字体"
              >
                <option value="">默认</option>
                <option value="SimSun, serif">宋体</option>
                <option value="KaiTi, serif">楷体</option>
                <option value="FangSong, serif">仿宋</option>
                <option value="Microsoft YaHei, sans-serif">微软雅黑</option>
                <option value="SimHei, sans-serif">黑体</option>
                <option value="Source Han Serif SC, serif">思源宋体</option>
                <option value="Noto Sans SC, sans-serif">Noto Sans</option>
              </select>
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground">粗细</span>
            <select
              value={fontWeight}
              onChange={e => setFontWeight(e.target.value)}
              className={SELECT}
              title="字体粗细"
            >
              <option value="">常规</option>
              <option value="300">细体</option>
              <option value="500">中等</option>
              <option value="600">半粗</option>
              <option value="700">加粗</option>
            </select>
          </div>
          {setIndent && (
            <label className="flex items-center justify-between gap-3 cursor-pointer">
              <span className="text-xs text-muted-foreground" title="只影响显示，不往正文里加空格">首行缩进</span>
              <input
                type="checkbox"
                checked={!!indent}
                onChange={e => setIndent(e.target.checked)}
                className="accent-primary"
              />
            </label>
          )}
          {setFontColor && (
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-muted-foreground">颜色</span>
              <div className="flex items-center gap-1.5">
                {fontColor && (
                  <button
                    onClick={() => setFontColor('')}
                    className="text-xs text-muted-foreground hover:text-foreground"
                    title="恢复跟随主题的默认颜色"
                  >
                    恢复默认
                  </button>
                )}
                <input
                  type="color"
                  value={fontColor || '#000000'}
                  onChange={e => setFontColor(e.target.value)}
                  className="w-7 h-7 border rounded-lg cursor-pointer bg-transparent p-0.5"
                  title="字体颜色"
                  aria-label="字体颜色"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
