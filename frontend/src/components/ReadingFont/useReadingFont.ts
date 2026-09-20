import { useState, useCallback, useMemo, type CSSProperties } from 'react'

export type ReadingFontScope = 'rpg' | 'tavern'

/** 键按 scope 分开，没跟小说侧的 `novel_*` 共用：小说是一整页正文，这两处是气泡里的
 *  几行短文本，舒适基准不是一回事。共用一个字号，小说调到 20px，气泡立刻被挤歪。
 *
 *  默认值也不是拍脑袋定的，照抄这两个页面现在写死的排版：RPG 正文是 text-base（16px）
 *  配 `.novel-content` 那套行高 2，酒馆是 text-sm leading-relaxed。谁都没调过的时候，
 *  观感和加这个控件之前逐字一致 */
const DEFAULTS: Record<ReadingFontScope, { fontSize: number; lineHeight: number }> = {
  rpg: { fontSize: 16, lineHeight: 2.0 },
  tavern: { fontSize: 14, lineHeight: 1.75 },
}

export function useReadingFont(scope: ReadingFontScope): {
  fontSize: number
  lineHeight: number
  fontWeight: string
  setFontSize: (v: number) => void
  setLineHeight: (v: number) => void
  setFontWeight: (v: string) => void
  style: CSSProperties
} {
  const [fontSize, setFontSizeState] = useState(
    () => Number(localStorage.getItem(`${scope}_font_size`) || DEFAULTS[scope].fontSize),
  )
  const [lineHeight, setLineHeightState] = useState(
    () => Number(localStorage.getItem(`${scope}_line_height`) || DEFAULTS[scope].lineHeight),
  )
  const [fontWeight, setFontWeightState] = useState(
    () => localStorage.getItem(`${scope}_font_weight`) || '',
  )

  // setter 里顺手写盘，同小说侧的姿势，不用 useEffect 盯着 state 同步：
  // 那样 scope 变化重挂时会把上一个 scope 的值误写进新键
  const setFontSize = useCallback((v: number) => {
    setFontSizeState(v)
    localStorage.setItem(`${scope}_font_size`, String(v))
  }, [scope])

  const setLineHeight = useCallback((v: number) => {
    setLineHeightState(v)
    localStorage.setItem(`${scope}_line_height`, String(v))
  }, [scope])

  const setFontWeight = useCallback((v: string) => {
    setFontWeightState(v)
    // 空串是「常规」，等于没表态，删键而不是存空串——同小说侧。存了空串以后想改默认值，
    // 会被一堆残留的空串挡着读不到新的那个
    if (v) localStorage.setItem(`${scope}_font_weight`, v)
    else localStorage.removeItem(`${scope}_font_weight`)
  }, [scope])

  const style = useMemo<CSSProperties>(() => ({
    fontSize: `${fontSize}px`,
    lineHeight,
    // 粗细为空时干脆不输出这个键，不然会盖掉元素自己 class 上的 font-weight
    ...(fontWeight ? { fontWeight } : {}),
  }), [fontSize, lineHeight, fontWeight])

  return { fontSize, lineHeight, fontWeight, setFontSize, setLineHeight, setFontWeight, style }
}
