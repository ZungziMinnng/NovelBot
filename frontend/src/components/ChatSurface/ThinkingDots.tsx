/** 等首个 token 时的三点。Tailwind 只认字面类名，所以延迟写成行内 style */
export default function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1" aria-label="AI 正在回复">
      {[0, 1, 2].map(i => (
        <span
          key={i}
          className="w-1.5 h-1.5 rounded-full bg-current opacity-50 animate-bounce"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </span>
  )
}
