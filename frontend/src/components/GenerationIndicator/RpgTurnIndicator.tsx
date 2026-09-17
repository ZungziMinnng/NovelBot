import { Dices } from 'lucide-react'
import { useRpgTurnStore } from '@/store/rpgTurnStore'
import RunningTurnPills from './RunningTurnPills'

/** 右下角的浮层药丸：某一局在后台生成剧情时显示，点它跳回那一局。 */
export default function RpgTurnIndicator() {
  const running = useRpgTurnStore(state => state.running)

  return (
    <RunningTurnPills
      running={running}
      isHere={(turn, pathname) => (
        pathname === `/game/play/${turn.sessionId}`
        || pathname === `/rpg/play/${turn.sessionId}`
      )}
      icon={<Dices className="w-3.5 h-3.5 shrink-0 opacity-80" />}
      label="剧情生成中"
      title="点击回到这一局查看生成进度"
      stopClassName="ml-1 p-0.5 rounded-full hover:bg-primary-foreground/20 transition-colors"
      onAbort={sessionId => useRpgTurnStore.getState().abort(sessionId)}
    />
  )
}
