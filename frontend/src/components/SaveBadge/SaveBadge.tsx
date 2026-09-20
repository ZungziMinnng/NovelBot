import { AlertCircle, Check, Loader2 } from 'lucide-react'

import type { SaveState } from '../../lib/useFormAutosave'

/** 表单旁边那块状态。以前这里是个「保存」按钮，改成自动保存之后只回话；
 *  「立即保存」由各表单自己摆在原来按钮的位置上（`onRetry` 是同一件事）。 */
export function SaveBadge({ state, blocked, onRetry }: {
  state: SaveState
  /** 「这一份还存不下去」时说什么。各表单的必填栏不一样，由调用方给 */
  blocked: string
  onRetry: () => void
}) {
  if (state === 'saving') {
    return <span className="text-xs text-muted-foreground flex items-center gap-1.5">
      <Loader2 className="w-3.5 h-3.5 animate-spin" />保存中
    </span>
  }
  if (state === 'error') {
    return (
      <button onClick={onRetry} className="text-xs text-red-500 flex items-center gap-1.5 hover:underline">
        <AlertCircle className="w-3.5 h-3.5" />没存上，点这里重试
      </button>
    )
  }
  if (state === 'blocked') {
    return <span className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
      <AlertCircle className="w-3.5 h-3.5" />{blocked}
    </span>
  }
  if (state === 'saved') {
    return <span className="text-xs text-muted-foreground flex items-center gap-1.5">
      <Check className="w-3.5 h-3.5 text-primary" />已保存
    </span>
  }
  return <span className="text-xs text-muted-foreground/70">改动自动保存</span>
}
