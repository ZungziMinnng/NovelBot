/** 预览里把 {数值名: 增减} 画成一串 chip。道具、动作的一键生成预览都用它。 */
export function effectChips(effects?: Record<string, number>, relation = false) {
  const entries = Object.entries(effects || {})
  if (!entries.length) return null
  return entries.map(([k, v]) => (
    <span
      key={k}
      className={`text-[11px] px-2 py-0.5 rounded-full ${
        relation
          ? 'bg-pink-500/10 text-pink-700 dark:text-pink-300'
          : 'bg-primary/10 text-primary'
      }`}
    >
      {relation ? '对方' : ''}{k}{v > 0 ? `+${v}` : v}
    </span>
  ))
}
