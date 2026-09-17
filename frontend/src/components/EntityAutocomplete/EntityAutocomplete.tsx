import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 打字补全：输入框里敲下名字的头几个字，就把匹配的角色 / 地点 / 道具列出来，
 * 选一条直接填进去。行为照小说编辑器那条生成指令栏（Editor/GenerationBar）：
 *
 * - 从光标往前最多回看 20 个字，**先长后短**地找能当某个名字前缀的那一段。
 *   先长后短是关键：光标前是「去铁匠」时，「铁匠」和「匠」都能匹配，
 *   要的是长的那个，否则填完会剩一个孤零零的「铁」。
 * - 中文输入法打字的过程中（composition）不匹配也不弹：拼音的中间态
 *   （「tiej」）匹配不到任何东西，弹一下又消失只会闪。
 * - ↑↓ 选、Enter 填、Esc 关。列表开着的时候 Enter 归补全，不发消息。
 */
export interface EntityItem {
  name: string
  /** 列表左边那个小标签：角色 / 地点 / 道具 */
  typeLabel: string
  description?: string
}

/** 往前回看几个字。名字再长也不至于超过这个数，全扫一遍纯属浪费 */
const MAX_LOOKBACK = 20

export function useEntityAutocomplete(
  entities: EntityItem[],
  value: string,
  onChange: (next: string) => void,
  textareaRef: React.RefObject<HTMLTextAreaElement>,
) {
  const [items, setItems] = useState<EntityItem[]>([])
  const [index, setIndex] = useState(0)
  const [fragment, setFragment] = useState({ start: 0, end: 0 })
  const composing = useRef(false)

  const refresh = useCallback((text: string, cursor: number) => {
    if (entities.length === 0 || cursor === 0) {
      setItems([])
      return
    }
    const before = text.slice(0, cursor)
    for (let len = Math.min(MAX_LOOKBACK, before.length); len >= 1; len--) {
      const suffix = before.slice(-len)
      const matches = entities.filter(e => e.name.startsWith(suffix))
      if (matches.length > 0) {
        // 全部列出来，不截断。多了就在列表里滚——截到前几条的话，想要的那个
        // 偏偏在第九位时，界面上根本看不出它存在
        setItems(matches)
        setIndex(0)
        setFragment({ start: cursor - len, end: cursor })
        return
      }
    }
    setItems([])
  }, [entities])

  const close = useCallback(() => setItems([]), [])

  const insert = useCallback((item: EntityItem) => {
    const next = value.slice(0, fragment.start) + item.name + value.slice(fragment.end)
    onChange(next)
    setItems([])
    // 光标要落在刚填进去的名字后面。等这一帧渲染完再动，不然 React 把 value
    // 写回去的时候会把光标顶到末尾
    requestAnimationFrame(() => {
      const ta = textareaRef.current
      if (!ta) return
      const pos = fragment.start + item.name.length
      ta.selectionStart = pos
      ta.selectionEnd = pos
      ta.focus()
    })
  }, [value, fragment, onChange, textareaRef])

  /** 返回 true 表示这一下被补全吃掉了，调用方不要再当普通按键处理 */
  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (composing.current || items.length === 0) return false
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setIndex(i => (i + 1) % items.length)
      return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setIndex(i => (i - 1 + items.length) % items.length)
      return true
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      insert(items[index])
      return true
    }
    if (e.key === 'Escape') {
      setItems([])
      return true
    }
    return false
  }, [items, index, insert])

  const onInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (!composing.current) refresh(e.currentTarget.value, e.currentTarget.selectionStart)
  }, [refresh])

  const onKeyUp = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (composing.current) return
    // 这四个键刚在 onKeyDown 里处理过，再刷一次会把刚填好的列表又弹出来
    if (items.length > 0 && ['ArrowDown', 'ArrowUp', 'Enter', 'Escape'].includes(e.key)) return
    refresh(e.currentTarget.value, e.currentTarget.selectionStart)
  }, [items.length, refresh])

  /** 鼠标点进正文中间、或拖选之后，光标位置变了，候选也得跟着变 */
  const onSelect = useCallback((e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    if (composing.current) return
    refresh(e.currentTarget.value, e.currentTarget.selectionStart)
  }, [refresh])

  return {
    items,
    index,
    insert,
    close,
    /** 直接摊到 textarea 上的那几个事件。onChange / onKeyDown 要和调用方
     *  自己的合并，所以单独给 */
    handlers: {
      onKeyUp,
      onClick: onSelect,
      onSelect,
      onCompositionStart: () => { composing.current = true; setItems([]) },
      onCompositionEnd: () => { composing.current = false },
      // 延迟关：不延迟的话点候选项时 blur 先跑，列表已经没了
      onBlur: () => setTimeout(() => setItems([]), 150),
    },
    onInput,
    onKeyDown,
  }
}

/** 候选列表。放在 `position: relative` 的容器里，往上弹（输入框都在底部） */
export function EntityAutocompleteList({
  items, index, onPick,
}: {
  items: EntityItem[]
  index: number
  onPick: (item: EntityItem) => void
}) {
  // 列表不截断，长了就滚。↑↓ 选到看不见的那一条时把它带进视野，
  // 否则高亮跑到框外，按键就像没反应
  const active = useRef<HTMLDivElement>(null)
  useEffect(() => { active.current?.scrollIntoView({ block: 'nearest' }) }, [index])

  if (items.length === 0) return null
  return (
    <div className="absolute bottom-full left-0 right-0 mb-1 z-50 max-h-64 overflow-y-auto
      bg-background border border-border rounded-lg shadow-2xl">
      {items.map((item, i) => (
        <div
          key={`${item.typeLabel}-${item.name}`}
          ref={i === index ? active : undefined}
          // mousedown + preventDefault：等到 click 的话输入框已经 blur 了
          onMouseDown={e => { e.preventDefault(); onPick(item) }}
          className={`flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer transition-colors ${
            i === index ? 'bg-accent text-accent-foreground' : 'hover:bg-muted'
          }`}
        >
          <span className="shrink-0 text-[0.625rem] px-1 py-0.5 rounded bg-muted text-muted-foreground">
            {item.typeLabel}
          </span>
          <span className="font-medium shrink-0">{item.name}</span>
          {item.description && (
            <span className="text-muted-foreground/60 truncate flex-1">{item.description}</span>
          )}
        </div>
      ))}
    </div>
  )
}
