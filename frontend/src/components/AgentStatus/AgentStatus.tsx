import { motion, AnimatePresence } from 'framer-motion'
import { Brain, Pen, Search, CheckCircle, Loader2 } from 'lucide-react'

interface Props {
  stage: string
  visible: boolean
}

const STAGE_CONFIG: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  building_context: { label: '检索记忆与上下文...', icon: Search },
  writing: { label: 'Writer Agent 创作中...', icon: Pen },
  revising_1: { label: 'Critic 发现问题，修改中（第1次）...', icon: Brain },
  revising_2: { label: 'Critic 发现问题，修改中（第2次）...', icon: Brain },
  reviewing: { label: 'Critic Agent 审查中...', icon: CheckCircle },
  saving: { label: '保存章节...', icon: Loader2 },
  updating_memory: { label: '更新记忆库...', icon: Brain },
}

export default function AgentStatus({ stage, visible }: Props) {
  const config = STAGE_CONFIG[stage]
  if (!config) return null

  const Icon = config.icon

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 8 }}
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />
          <Icon className="w-3.5 h-3.5" />
          <span>{config.label}</span>
        </motion.div>
      )}
    </AnimatePresence>
  )
}