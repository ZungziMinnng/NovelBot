import { AnimatePresence, motion } from 'framer-motion'
import { Calculator, Dices, Loader2, Search, Sparkles } from 'lucide-react'

/**
 * 一轮 AI 正在忙的时候显示的分阶段提示。
 *
 * 存在的理由：玩家按下发送之后，到模型吐出第一个字之前有一段静默期
 * （裁决 → 组织上下文 → 调模型），出完字之后还有一次静默的结算。
 * 这段窗口里界面上原本什么都没有，看不出是在等还是卡了。
 *
 * 用的是后端 stage 事件那套键（见 agents/rpg_turn.py）：
 * adjudicating / building / settling。叙述阶段不发 stage——第一个 token
 * 到达本身就表示「在写」，那时由气泡里的光标接手。
 *
 * 刻意不复用小说侧的 AgentStatus / generationStore：那套带 novelId、章节号等
 * 小说专有字段。这里只要一个本地 stage 字符串，样式也落在 .mode-game 里。
 */
const STAGE_CONFIG: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  adjudicating: { label: '裁决中…', icon: Dices },
  building: { label: '组织线索中…', icon: Search },
  settling: { label: '结算数值中…', icon: Calculator },
}

/** stage 还没到（或后端没发）时的兜底：至少让玩家知道这一轮在跑 */
const FALLBACK = { label: '思考中…', icon: Sparkles }

export default function RpgTurnStatus({
  stage, visible,
}: {
  stage: string
  visible: boolean
}) {
  const config = STAGE_CONFIG[stage] ?? FALLBACK
  const Icon = config.icon

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          className="rounded-2xl border border-primary/15 bg-card/60 backdrop-blur-sm
            px-5 py-3 text-sm text-muted-foreground flex items-center gap-2"
        >
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          <Icon className="w-3.5 h-3.5" />
          <span>{config.label}</span>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
