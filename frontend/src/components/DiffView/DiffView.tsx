import { useMemo } from 'react'
import { X } from 'lucide-react'

interface DiffViewProps {
  originalText: string
  revisedText: string
  onClose: () => void
}

/**
 * 段落级对比视图：左栏显示初稿，右栏显示修改稿。
 * 不在两版本中都存在的段落分别用红/绿色块标注。
 */
export default function DiffView({ originalText, revisedText, onClose }: DiffViewProps) {
  const { originalLines, revisedLines } = useMemo(() => {
    // 按段落分割（空行作为分隔符）
    const splitLines = (text: string) =>
      text.split('\n').filter((l) => l.trim() !== '' || l === '')

    const orig = splitLines(originalText)
    const rev = splitLines(revisedText)

    // 用 Set 做简单段落差集判断
    const origSet = new Set(orig)
    const revSet = new Set(rev)

    return {
      originalLines: orig.map((line) => ({
        text: line,
        // 空行不标注；只有内容行且不在修改稿中才标红
        changed: line.trim() !== '' && !revSet.has(line),
      })),
      revisedLines: rev.map((line) => ({
        text: line,
        changed: line.trim() !== '' && !origSet.has(line),
      })),
    }
  }, [originalText, revisedText])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/30 shrink-0">
        <div className="flex items-center gap-4 text-xs font-medium">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-red-500/40 border border-red-500/60 inline-block" />
            修订前版本
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-sm bg-green-500/40 border border-green-500/60 inline-block" />
            修订后版本
          </span>
        </div>
        <button
          onClick={onClose}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded-md hover:bg-muted"
        >
          <X className="w-3.5 h-3.5" />
          关闭对比
        </button>
      </div>

      {/* Two-column diff */}
      <div className="flex flex-1 overflow-hidden divide-x">
        {/* Left: Original */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 text-sm leading-loose novel-content font-serif space-y-0">
            {originalLines.map((line, i) =>
              line.text.trim() === '' ? (
                <div key={i} className="h-4" />
              ) : (
                <p
                  key={i}
                  className={`py-0.5 px-1 rounded transition-colors ${
                    line.changed
                      ? 'bg-red-500/15 dark:bg-red-500/20 border-l-2 border-red-500/70'
                      : ''
                  }`}
                >
                  {line.text}
                </p>
              )
            )}
          </div>
        </div>

        {/* Right: Revised */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 text-sm leading-loose novel-content font-serif space-y-0">
            {revisedLines.map((line, i) =>
              line.text.trim() === '' ? (
                <div key={i} className="h-4" />
              ) : (
                <p
                  key={i}
                  className={`py-0.5 px-1 rounded transition-colors ${
                    line.changed
                      ? 'bg-green-500/15 dark:bg-green-500/20 border-l-2 border-green-500/70'
                      : ''
                  }`}
                >
                  {line.text}
                </p>
              )
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
