import { useState } from 'react'
import { Loader2, X } from 'lucide-react'
import type { RpgTaskProposal } from '@/api/client'
import { WaitBar } from './rpgUi'

/** 「这几桩事看着办完了？」——照抄小说侧伏笔回收的规矩：模型只有提名权，
 *  改不改状态由玩家逐条点头。默认全勾上，因为提议已经过了一遍复核
 *  （名字必须在清单上、理由必须是正文原话），多数时候是对的。
 *
 *  没勾的那几条也会一并提交（accept=false）：「我看过了，这条不算完」和
 *  「还没看」必须是两回事，否则同一条提议下一回合又会弹出来。 */
export default function TaskResolutionsModal({
  proposals, saving, onConfirm, onClose,
}: {
  proposals: RpgTaskProposal[]
  saving: boolean
  onConfirm: (accepts: Array<{ id: string; accept: boolean }>) => void
  onClose: () => void
}) {
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(proposals.map(p => p.id)),
  )

  const toggle = (id: string) => setPicked(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  return (
    // 不能 createPortal：--rpg-* 那套颜色变量定在外面的 .mode-game 上
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={saving ? undefined : onClose}
    >
      <div
        className="bg-background rounded-xl shadow-xl max-h-[80vh] overflow-y-auto w-[560px]"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-background border-b px-5 py-3 flex items-center gap-3 z-10 rounded-t-xl">
          <h2 className="font-bold text-base flex-1">这几桩事，算办完了吗</h2>
          <button onClick={onClose} disabled={saving} className="p-1.5 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-3">
          {proposals.map(p => (
            <label
              key={p.id}
              className="flex items-start gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40"
            >
              <input
                type="checkbox"
                checked={picked.has(p.id)}
                onChange={() => toggle(p.id)}
                className="mt-1 shrink-0"
              />
              <span
                className={`shrink-0 text-xs px-2 py-0.5 rounded ${
                  p.action === 'done'
                    ? 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300'
                    : 'bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300'
                }`}
              >
                {p.action === 'done' ? '办成了' : '办砸了'}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium">{p.name}</div>
                {/* 依据必须是正文原话，摆出来玩家才好判断 */}
                <div className="text-sm text-muted-foreground mt-0.5">「{p.reason}」</div>
              </div>
            </label>
          ))}
          <p className="text-xs text-muted-foreground">
            勾中的会标成对应状态，模组里写了奖励的会一并到账；没勾的仍然进行中，
            但也不会再问第二遍。直接关掉则什么都不改，下一回合可能再问。
          </p>
        </div>

        <div className="sticky bottom-0 bg-background border-t px-5 py-3 flex items-center justify-end gap-2 rounded-b-xl">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-3 py-1.5 text-sm rounded hover:bg-muted"
          >
            先放着
          </button>
          <button
            onClick={() => onConfirm(
              proposals.map(p => ({ id: p.id, accept: picked.has(p.id) })),
            )}
            disabled={saving}
            className="px-3 py-1.5 text-sm rounded bg-primary text-primary-foreground
              hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            确认{picked.size > 0 ? `（${picked.size}）` : ''}
          </button>
        </div>
        {/* 这一下要写库并重拉会话。弹窗期间整个界面被遮住，不画条子的话
            玩家只能看着一个按钮里的小转圈猜还要等多久 */}
        {saving && <WaitBar className="px-5 pb-4" />}
      </div>
    </div>
  )
}
