import { MessagesSquare } from 'lucide-react'
import { useTavernTurnStore } from '@/store/tavernTurnStore'
import RunningTurnPills from './RunningTurnPills'

/** 右下角的浮层药丸：某条故事线在后台生成时显示，点它跳回那条线。 */
export default function TavernTurnIndicator() {
  const running = useTavernTurnStore(state => state.running)

  return (
    <RunningTurnPills
      running={running}
      isHere={(turn, pathname) => pathname === `/tavern/chat/${turn.sessionId}`}
      icon={<MessagesSquare className="w-3.5 h-3.5 shrink-0 opacity-80" />}
      label="对话生成中"
      title="点击回到这条故事线查看生成进度"
      stopClassName="ml-1 p-0.5 rounded-full bg-transparent hover:bg-primary-foreground/20 transition-colors"
      onAbort={sessionId => useTavernTurnStore.getState().abort(sessionId)}
    />
  )
}
