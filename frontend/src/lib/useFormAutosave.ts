import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * 表单类编辑的自动保存。原来长在 RPG 模组编辑页（RpgModule.tsx）里，现在给
 * 模组编辑器所有「点开某一条、改完收起」的分栏共用。
 *
 * 在此之前是「填完点保存」。可这些面板越写越长，保存按钮却孤零零挂在某一头：
 * 改最上面那一格的人（勾完了要往下滚好几屏才看得见保存）根本想不到还得去点它
 * ——「我明明点了，退出来又没了」就是这么来的。现在改哪一格都自己存，
 * 旁边那块只负责回话。
 */

export type SaveState = 'idle' | 'saving' | 'saved' | 'error' | 'blocked'

/**
 * 改了就直接存进库，不等按钮。
 *
 * 三件事必须守住，少一件都会退化成「改了没存上，界面上还显示存上了」：
 *
 * 1. **数据到位之前一个字都不发。** 表单是 null 起步的，早发一步就是拿空表单
 *    把整行盖掉。第一次看到真实值只记基准，不保存。
 * 2. **同一时刻只放一个请求出去。** 打字会连着排好几次，而两个请求谁先落地并
 *    不由发出的顺序决定；后发的先到，库里留下的是上一秒的旧值，界面上却看不出
 *    任何异常。所以有请求在路上时不另发，等它一趟跑完再按**最新那一份**补一次。
 * 3. **存不上要说。** 状态条会一直红着，点它重试；表单收起之前也拦一道。
 *
 * `draft` 就是现在要存的那一份实体，判据和发给后端的内容是同一个东西，不必再
 * 给每一栏单独列依赖。传 null = 这一份**还存不下去**（必填栏空着）：不动基准、
 * 不发请求，只把状态条挂黄，因为「存一半的空名字」比「没存」更糟。
 *
 * 有多行可编辑时，**这份 draft 必须自带它属于哪一行**（`{id, body}`）：收尾那次
 * 保存是在表单已经换人、甚至已经关掉之后才跑的，`save` 闭包里的 `editingId`
 * 那一刻早就不对了，而 draft 一直跟着数据走。
 */
export function useFormAutosave<T>(
  draft: T | null, ready: boolean, save: (data: T) => Promise<void>, delay = 700,
) {
  const [state, setState] = useState<SaveState>('idle')
  const key = draft === null ? null : JSON.stringify(draft)
  // 最后一份「存得下去」的形态。表单收起时它就是收尾那一次要发的内容，
  // 所以**只在 draft 非空时更新**，绝不清成 null
  const latest = useRef<{ key: string; data: T } | null>(null)
  const sent = useRef<string | null>(null)      // 已经存进去的那一份
  const writer = useRef(save)
  const running = useRef(false)
  const ok = useRef(true)
  const waiters = useRef<Array<() => void>>([])
  writer.current = save
  if (draft !== null && key !== null) latest.current = { key, data: draft }

  /** 立刻把欠的那一次存掉。返回是否存成了——存不成的时候调用方不该关表单，
   *  关了就等于默默把改动扔了，而用户看到的只是一闪而过的红字。 */
  const flush = useCallback(async (): Promise<boolean> => {
    if (running.current) {
      // 已经有一个在路上。等它跑完就行：它收尾前会自己把最新那份带出去
      await new Promise<void>(resolve => { waiters.current.push(resolve) })
      return ok.current
    }
    running.current = true
    try {
      while (latest.current && latest.current.key !== sent.current) {
        const shot = latest.current
        setState('saving')
        await writer.current(shot.data)
        sent.current = shot.key
      }
      setState('saved')
      ok.current = true
      return true
    } catch {
      // 基准停在原地：下次再改还会重试，用户也能点状态条自己重试
      setState('error')
      ok.current = false
      return false
    } finally {
      running.current = false
      const waiting = waiters.current
      waiters.current = []
      waiting.forEach(resolve => resolve())
    }
  }, [])

  useEffect(() => {
    if (!ready) {
      // 表单收起了 / 换了一条。先把欠的那一次补掉再清基准——少了这一段，
      // 「改完立刻点收起」就是丢改动，而 debounce 那几百毫秒里用户根本不会
      // 觉得自己是在抢时间
      if (sent.current !== null && sent.current !== latest.current?.key) void flush()
      sent.current = null
      setState('idle')
      return
    }
    if (key === null) { setState('blocked'); return }
    if (sent.current === null) { sent.current = key; return }  // 刚加载出来的，只记基准
    if (sent.current === key) return
    const timer = setTimeout(flush, delay)
    return () => clearTimeout(timer)
  }, [key, ready, delay, flush])

  // 卸载（点了返回、换页）时把欠的那一次送出去。这里没有 setState 的顾虑，
  // 请求也不跟着组件走——但少了它，「改完立刻返回」就是丢改动
  useEffect(() => () => {
    if (sent.current !== null && sent.current !== latest.current?.key) void flush()
  }, [flush])

  return { state, flush }
}
