import { useState } from 'react'
import { Check, RotateCcw, X } from 'lucide-react'
import type { RpgSession, RpgSessionTask } from '@/api/client'
import { PANEL } from '../rpgUi'
import Empty from './Empty'

const LABEL: Record<string, string> = { done: '已完成', failed: '没办成' }

/** 手上挂着的事。进行中的在上，了结了的折在下面——玩下去清单只会变长，
 *  已经翻篇的事不该一直占着眼睛。 */
export default function TaskTab({
  sess, locked, onSetTask,
}: {
  sess: RpgSession
  locked: boolean
  /** status 给空串 = 划掉这一条 */
  onSetTask: (name: string, status: '' | 'open' | 'done' | 'failed') => void
}) {
  const [showClosed, setShowClosed] = useState(false)
  const all = sess.tasks || []
  const open = all.filter(t => t.status === 'open')
  // 日常任务完成后当天不再占据任务栏；跨天由引擎重新打开。
  const closed = all.filter(t => t.status !== 'open' && !(t.category === '日常' && t.status === 'done'))

  const card = (task: RpgSessionTask, done: boolean) => (
    <div key={task.name} className={`${PANEL} p-3`}>
      <div className="flex items-baseline gap-2">
        <p className={`text-sm font-medium flex-1 truncate ${done ? 'line-through opacity-60' : ''}`}>
          {task.name}
        </p>
        {done && (
          <span className="text-xs text-muted-foreground">{LABEL[task.status] || ''}</span>
        )}
      </div>
      {task.desc && (
        <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{task.desc}</p>
      )}
      {!done && task.goal && (
        // 「怎样才算办完」要显示出来：AI 判定收线只看这一句，玩家看得见
        // 才知道为什么那桩事还没算完
        <p className="text-xs mt-1.5" style={{ color: 'hsl(var(--rpg-task))' }}>
          办完的标准：{task.goal}
        </p>
      )}
      <div className="flex gap-1.5 mt-2.5">
        {done ? (
          <button
            onClick={() => onSetTask(task.name, 'open')}
            disabled={locked}
            className="flex-1 text-xs py-1.5 rounded-lg border text-muted-foreground
              hover:bg-muted disabled:opacity-40 flex items-center justify-center gap-1"
          >
            <RotateCcw className="w-3 h-3" />重新进行
          </button>
        ) : (
          <>
            <button
              onClick={() => onSetTask(task.name, 'done')}
              disabled={locked}
              title="不等 AI 判断，自己标完成"
              className="flex-1 text-xs py-1.5 rounded-lg bg-primary text-primary-foreground
                hover:opacity-90 disabled:opacity-40 flex items-center justify-center gap-1"
            >
              <Check className="w-3 h-3" />办完了
            </button>
            <button
              onClick={() => onSetTask(task.name, 'failed')}
              disabled={locked}
              title="这桩事再也办不成了"
              className="flex-1 text-xs py-1.5 rounded-lg border text-muted-foreground
                hover:bg-muted disabled:opacity-40"
            >
              办砸了
            </button>
          </>
        )}
        <button
          onClick={() => onSetTask(task.name, '')}
          disabled={locked}
          title="从清单上划掉"
          className="px-2 rounded-lg border text-muted-foreground hover:bg-muted disabled:opacity-40"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
    </div>
  )

  return (
    <>
      {all.length === 0 && <Empty>手上没什么要办的事。</Empty>}
      {open.map(task => card(task, false))}
      {closed.length > 0 && (
        <button
          onClick={() => setShowClosed(v => !v)}
          className="w-full text-xs py-1.5 text-muted-foreground hover:text-foreground"
        >
          {showClosed ? '收起' : `已经了结的 ${closed.length} 桩`}
        </button>
      )}
      {showClosed && closed.map(task => card(task, true))}
    </>
  )
}
