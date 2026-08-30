import { useEffect, useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

export interface ConfirmOptions {
  title: string
  /** 补充说明，换行会原样保留 */
  detail?: string
  confirmText?: string
  cancelText?: string
  /** 危险操作用红色确认键。删除类默认就该是 true */
  danger?: boolean
}

interface PendingRequest extends ConfirmOptions {
  resolve: (ok: boolean) => void
}

let emit: ((req: PendingRequest) => void) | null = null

/**
 * 替代 window.confirm 的 UI 弹窗，返回 Promise<boolean>，调用点写法几乎不变。
 *
 * 做成命令式而不是每处一个受控组件：原生 confirm 的调用点都是
 * `if (!confirm(...)) return` 这种一行守卫，改成受控组件要在每个页面加
 * 状态、加 JSX、把待执行的动作存起来，四十多处会全变形。
 */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  if (!emit) {
    // ConfirmHost 没挂载（理论上不会，它在 App 根上）。退回原生弹窗也比静默放行安全
    return Promise.resolve(window.confirm(options.title))
  }
  return new Promise(resolve => emit!({ ...options, resolve }))
}

/** 挂在 App 根上，和 Toaster 一样全局只有一个 */
export default function ConfirmHost() {
  const [req, setReq] = useState<PendingRequest | null>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    emit = setReq
    return () => { emit = null }
  }, [])

  useEffect(() => {
    if (req) confirmRef.current?.focus()
  }, [req])

  if (!req) return null

  const close = (ok: boolean) => {
    req.resolve(ok)
    setReq(null)
  }

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={() => close(false)}
      // 确认键在打开时已经聚焦，回车由它自己处理，这里只管 Esc
      onKeyDown={e => { if (e.key === 'Escape') close(false) }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
    >
      <div
        className="w-full max-w-sm rounded-xl border bg-card shadow-xl overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        <div className="p-5 flex gap-3.5">
          <div className={`p-2 rounded-lg shrink-0 h-fit ${
            req.danger ? 'bg-red-500/15 text-red-400' : 'bg-primary/10 text-primary'
          }`}>
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p id="confirm-title" className="text-sm font-medium leading-relaxed">{req.title}</p>
            {req.detail && (
              <p className="text-xs text-muted-foreground mt-2 leading-relaxed whitespace-pre-wrap">
                {req.detail}
              </p>
            )}
          </div>
        </div>
        <div className="px-5 py-3 bg-muted/30 border-t flex gap-2 justify-end">
          <button
            onClick={() => close(false)}
            className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors"
          >
            {req.cancelText || '取消'}
          </button>
          <button
            ref={confirmRef}
            onClick={() => close(true)}
            className={`text-sm px-4 py-1.5 rounded-lg transition-colors ${
              req.danger
                ? 'bg-red-500/20 text-red-300 ring-1 ring-red-500/40 hover:bg-red-500/30'
                : 'bg-primary text-primary-foreground hover:opacity-90'
            }`}
          >
            {req.confirmText || '确定'}
          </button>
        </div>
      </div>
    </div>
  )
}
