import { useCallback, useRef } from 'react'

/**
 * 拖边框改一列的宽度。
 *
 * 和 pages/Editor/EditorSidebar.tsx 里的 createResizeHandler 是同一套做法，
 * 但那一份是组件内私有的、而且写死了「手柄在右缘」——RPG 的侧栏在**右边**，
 * 往左拖才是变宽，位移得反过来算。没去抽公共件是因为那属于顺手重构编辑器，
 * 这次不碰它。
 *
 * 宽度不落盘：编辑器那边也没存，玩家每次进来都是默认宽度。
 */
export default function useColumnResize(
  setWidth: (next: number) => void,
  min: number,
  max: number,
  /** 手柄在被调整的那一列的哪一边。右侧栏的手柄在左缘 */
  edge: 'left' | 'right' = 'left',
) {
  const start = useRef({ x: 0, width: 0 })

  return useCallback((event: React.MouseEvent) => {
    event.preventDefault()
    const column = event.currentTarget.parentElement
    if (!column) return
    start.current = { x: event.clientX, width: column.offsetWidth }

    const onMove = (moved: MouseEvent) => {
      const delta = edge === 'left'
        ? start.current.x - moved.clientX
        : moved.clientX - start.current.x
      setWidth(Math.max(min, Math.min(max, start.current.width + delta)))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    // 拖的时候整页都得是 col-resize，不然滑出手柄光标就变回去了；
    // userSelect 关掉是为了别把剧情正文一路选蓝
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [setWidth, min, max, edge])
}
