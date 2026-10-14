import { useState } from 'react'
import { Loader2, X } from 'lucide-react'

const MAX_DAYS = 30

/** 时间跳转：N 天后的哪个时段。纯引擎，不写过渡叙事；只能往后。
 *  今天（0 天后）只能选比现在更晚的时段，天数大于 0 时任何时段都行。 */
export default function TimeJumpModal({
  slots, day, slot, saving, onConfirm, onClose,
}: {
  slots: string[]
  day: number
  slot: string
  saving: boolean
  onConfirm: (days: number, slot: string) => void
  onClose: () => void
}) {
  const current = Math.max(0, slots.indexOf(slot))
  const [days, setDays] = useState(1)
  const [picked, setPicked] = useState(slots[0] || '')

  // 今天只能选更晚的时段
  const allowed = (name: string) => days > 0 || slots.indexOf(name) > current
  const pick = allowed(picked) ? picked : (slots.find(allowed) || '')
  const ok = !!pick && days >= 0 && days <= MAX_DAYS

  const setDaysClamped = (value: number) => {
    const n = Number.isFinite(value) ? Math.min(MAX_DAYS, Math.max(0, Math.trunc(value))) : 0
    setDays(n)
  }

  return (
    // 不能 createPortal：--rpg-* 那套颜色变量定在外面的 .mode-game 上
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={saving ? undefined : onClose}
    >
      <div
        className="bg-background rounded-xl shadow-xl w-[420px] max-w-full"
        onClick={e => e.stopPropagation()}
      >
        <div className="border-b px-5 py-3 flex items-center gap-3 rounded-t-xl">
          <h2 className="font-bold text-base flex-1">时间跳转</h2>
          <button onClick={onClose} disabled={saving} className="p-1.5 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="text-sm text-muted-foreground">
            现在是第 {day} 天{slot ? ` · ${slot}` : ''}
          </div>

          <div className="flex items-center gap-2 text-sm">
            <input
              type="number"
              min={0}
              max={MAX_DAYS}
              value={days}
              onChange={e => setDaysClamped(Number(e.target.value))}
              className="w-20 border rounded-md px-2 py-1 bg-background"
            />
            <span>天后</span>
            <span className="text-xs text-muted-foreground">（0 = 今天，最多 {MAX_DAYS}）</span>
          </div>

          <div className="flex flex-wrap gap-2">
            {slots.map(name => (
              <button
                key={name}
                disabled={!allowed(name)}
                onClick={() => setPicked(name)}
                className={`text-sm px-3 py-1 rounded-md border disabled:opacity-30 disabled:cursor-not-allowed ${
                  pick === name ? 'bg-primary text-primary-foreground border-transparent' : 'hover:bg-muted'
                }`}
              >
                {name}
              </button>
            ))}
          </div>

          {ok && (
            <div className="text-sm">
              跳到：<b>第 {day + days} 天 · {pick}</b>
            </div>
          )}
          {!ok && (
            <div className="text-xs text-amber-600">今天已经没有更晚的时段了，请把天数改成 1 天以上。</div>
          )}

          <p className="text-xs text-muted-foreground">
            不会生成剧情，中间这段时间直接略过；下一次发言时 GM 会知道时间跳过去了。
            跨天恢复和每日任务只结算一次。跳之前会自动存档，可以读档反悔。
          </p>
        </div>

        <div className="border-t px-5 py-3 flex justify-end gap-2">
          <button onClick={onClose} disabled={saving} className="text-sm px-3 py-1.5 rounded-md border hover:bg-muted">
            取消
          </button>
          <button
            onClick={() => onConfirm(days, pick)}
            disabled={!ok || saving}
            className="text-sm px-3 py-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-40 flex items-center gap-1"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}跳转
          </button>
        </div>
      </div>
    </div>
  )
}
