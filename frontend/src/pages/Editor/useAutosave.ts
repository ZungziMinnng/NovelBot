import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 正文编辑的自动保存。
 *
 * 在此之前编辑器只有手动「保存」按钮，而切换章节的 effect 会直接用新章节内容覆盖
 * editContent——改了没保存又误点别的章节，改动就没了。这里补三层保护：
 * 空闲防抖自动保存、切章/卸载前强制落盘、关页面前浏览器拦截。
 */
const IDLE_DELAY_MS = 2000

interface Options {
  enabled: boolean
  chapterId: number | undefined
  /** content 实际属于哪一章。切章那一帧 chapterId 已是新章、content 还是旧章的，
   *  不带这个判断会把上一章的正文存进新章节。 */
  contentChapterId: number | undefined
  content: string
  baseline: string | undefined
  onSave: (chapterId: number, content: string) => Promise<void>
}

export type SaveState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

export function useAutosave({ enabled, chapterId, contentChapterId, content, baseline, onSave }: Options) {
  const dirty =
    enabled &&
    chapterId !== undefined &&
    contentChapterId === chapterId &&
    baseline !== undefined &&
    content !== baseline
  const [state, setState] = useState<SaveState>('idle')

  // 待存快照。只在有改动时写入、保存成功后清除——切章那一帧 dirty 已经是 false，
  // 若在渲染期清空，effect 清理阶段就拿不到上一章待存的内容了。
  const pending = useRef<{ chapterId: number; content: string } | null>(null)
  if (dirty) {
    pending.current = { chapterId: chapterId!, content }
  } else if (pending.current && pending.current.content === baseline) {
    // 已经由手动保存写进去了，别留着快照在切章时再回写一次
    pending.current = null
  }
  const inFlight = useRef(false)

  const save = useCallback(async () => {
    const snapshot = pending.current
    if (!snapshot || inFlight.current) return
    inFlight.current = true
    setState('saving')
    try {
      await onSave(snapshot.chapterId, snapshot.content)
      // 保存期间用户可能又改了，那份新内容要留着，别连同已存的一起清掉
      if (pending.current?.content === snapshot.content) {
        pending.current = null
        setState('saved')
      } else {
        setState('dirty')
      }
    } catch {
      setState('error')
    } finally {
      inFlight.current = false
    }
  }, [onSave])

  // 空闲防抖：停手 2 秒落盘。依赖 content 而非 dirty，连续输入会不断重排计时器。
  useEffect(() => {
    if (!dirty) return
    setState('dirty')
    const timer = setTimeout(save, IDLE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [content, dirty, save])

  // 切章节或离开编辑器：立刻落盘，不等防抖
  useEffect(() => {
    if (chapterId === undefined) return
    return () => { void save() }
  }, [chapterId, save])

  // 退出编辑态后复位，免得下次进来还挂着上一轮的「已自动保存」
  useEffect(() => {
    if (!enabled) setState('idle')
  }, [enabled])

  // 落盘是异步的，关页面来不及等——交给浏览器原生拦截
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  return { state: dirty && state === 'saved' ? 'dirty' : state, dirty, saveNow: save }
}
