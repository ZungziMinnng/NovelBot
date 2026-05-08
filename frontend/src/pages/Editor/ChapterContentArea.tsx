import { useRef, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import DiffView from '@/components/DiffView/DiffView'
import type { Chapter } from '@/api/client'

interface ChapterContentAreaProps {
  displayText: string
  isEditing: boolean
  editContent: string
  warningMessage: string
  errorMessage: string
  isCurrentlyGenerating: boolean
  isStreaming: boolean
  streamingMode: boolean
  showDiff: boolean
  originalDraft: string
  currentChapter: Chapter | null
  fontSize: number
  lineHeight: number
  fontFamily: string
  fontWeight: string
  plotSuggestions: string[]
  instruction: string
  onEditContentChange: (v: string) => void
  onCloseDiff: () => void
  onSelectSuggestion: (s: string) => void
}

export default function ChapterContentArea({
  displayText,
  isEditing,
  editContent,
  warningMessage,
  errorMessage,
  isCurrentlyGenerating,
  isStreaming,
  streamingMode,
  showDiff,
  originalDraft,
  currentChapter,
  fontSize,
  lineHeight,
  fontFamily,
  fontWeight,
  plotSuggestions,
  instruction,
  onEditContentChange,
  onCloseDiff,
  onSelectSuggestion,
}: ChapterContentAreaProps) {
  const contentEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isCurrentlyGenerating && streamingMode) {
      contentEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [isCurrentlyGenerating, streamingMode])

  return (
    <div className={`flex-1 ${showDiff && !isCurrentlyGenerating && originalDraft ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      {showDiff && !isCurrentlyGenerating && originalDraft ? (
        <DiffView
          originalText={originalDraft}
          revisedText={currentChapter?.content || ''}
          onClose={onCloseDiff}
        />
      ) : isEditing ? (
        <textarea
          value={editContent}
          onChange={e => onEditContentChange(e.target.value)}
          className="w-full h-full p-8 resize-none bg-background focus:outline-none novel-content font-serif"
          style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any }}
          placeholder="在此输入内容..."
        />
      ) : warningMessage && !isCurrentlyGenerating ? (
        <div className="flex flex-col h-full overflow-y-auto">
          <div className="mx-8 mt-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-lg px-4 py-2.5 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300 shrink-0">
            <span className="shrink-0 mt-0.5">⚠</span>
            <span>{warningMessage}</span>
          </div>
          <div className="p-8 novel-content whitespace-pre-wrap" style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any }}>
            {displayText}
          </div>
        </div>
      ) : errorMessage ? (
        <div className="p-8 flex flex-col items-center justify-center h-full gap-3">
          <div className="max-w-lg w-full bg-destructive/10 border border-destructive/30 rounded-lg p-4">
            <p className="text-sm font-medium text-destructive mb-1">生成失败</p>
            <p className="text-xs text-destructive/80 whitespace-pre-wrap break-words">{errorMessage}</p>
          </div>
        </div>
      ) : isCurrentlyGenerating && !streamingMode ? (
        <div className="p-8 flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
          <Loader2 className="w-8 h-8 animate-spin" />
          <p className="text-sm">AI 正在创作中，完成后自动显示...</p>
          <p className="text-xs opacity-60">切换页面不会中断生成</p>
        </div>
      ) : (
        <div className="h-full flex flex-col overflow-y-auto">
          {currentChapter?.instruction && (
            <div className="px-8 pt-6 pb-1 shrink-0">
              <details>
                <summary className="text-xs text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">
                  📝 本章构思
                </summary>
                <p className="mt-2 text-sm text-muted-foreground border-l-2 border-muted pl-3 whitespace-pre-wrap">
                  {currentChapter.instruction}
                </p>
              </details>
            </div>
          )}
          <div className={`p-8 novel-content whitespace-pre-wrap flex-1 ${isStreaming ? 'streaming-cursor' : ''}`} style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any }}>
            {displayText || (
              <span className="text-muted-foreground/50">
                {isCurrentlyGenerating ? '' : '点击下方「生成章节」开始创作...'}
              </span>
            )}
            <div ref={contentEndRef} />
          </div>
          {plotSuggestions.length > 0 && (
            <div className="px-8 pt-1 pb-6 shrink-0">
              <details open>
                <summary className="text-xs text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">
                  ✨ 下章剧情建议（点击填入指令）
                </summary>
                <div className="mt-2 flex flex-col gap-1">
                  {plotSuggestions.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => onSelectSuggestion(s)}
                      className={`text-left text-xs px-3 py-1.5 rounded-lg border transition-colors hover:bg-muted ${
                        instruction === s ? 'border-primary bg-primary/5 text-primary' : 'border-border'
                      }`}
                    >
                      <span className="text-muted-foreground mr-1.5">{i + 1}.</span>{s}
                    </button>
                  ))}
                </div>
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
