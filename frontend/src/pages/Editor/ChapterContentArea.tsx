import { useRef, useEffect } from 'react'
import { Loader2, Plus } from 'lucide-react'
import DiffView from '@/components/DiffView/DiffView'
import type { Chapter } from '@/api/client'

const CIRCLED_NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

// LLM 输出的段落分隔不统一（单换行/空行/多空行混用），阅读视图统一为段间一个空行；不改动存库原文
const normalizeSpacing = (text: string) =>
  text.split(/\n+/).filter(p => p.trim()).join('\n\n')

// 正文栏宽：em 跟着阅读字号走，max-w 含左右内边距，实际每行约 46 字
const MEASURE = 'w-full max-w-[52em] mx-auto px-6 sm:px-10 py-10'
// 带段号的批注视图左边多一列序号，放宽一点让正文那列和上面对齐
const MEASURE_NUMBERED = 'w-full max-w-[54em] mx-auto px-6 sm:px-10 py-10'
// 构思、警告这类正文外的条子，跟正文同一条中线
const COLUMN = 'w-full max-w-[52rem] mx-auto px-6 sm:px-10'

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
  fontColor: string
  instruction: string
  rewriteMode: boolean
  /** 阅读视图每段首行缩进两字；编辑框是原生 textarea，做不到逐段缩进 */
  indent: boolean
  textareaRef?: React.RefObject<HTMLTextAreaElement>
  onSelectionChange?: (range: { start: number; end: number }) => void
  onEditContentChange: (v: string) => void
  onCloseDiff: () => void
  onAddParagraphAnnotation: (paragraph: number) => void
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
  fontColor,
  instruction,
  rewriteMode,
  indent,
  textareaRef,
  onSelectionChange,
  onEditContentChange,
  onCloseDiff,
  onAddParagraphAnnotation,
}: ChapterContentAreaProps) {
  const contentEndRef = useRef<HTMLDivElement>(null)

  // 缩进要逐段加，只能拆成一段一个块；段间留一行空白，和不缩进时的观感一致
  const renderBody = (text: string) => indent
    ? text.split(/\n+/).filter(p => p.trim()).map((p, i) => (
        <p key={i} style={{ textIndent: '2em', marginBottom: `${lineHeight}em` }}>{p.trim()}</p>
      ))
    : normalizeSpacing(text)

  useEffect(() => {
    if (isCurrentlyGenerating && streamingMode) {
      contentEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [isCurrentlyGenerating, streamingMode])

  const renderParagraphs = (text: string) => {
    const paragraphs = text.split('\n').filter(p => p.trim())
    return (
      <div className={`space-y-0 ${MEASURE_NUMBERED}`} style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any, color: fontColor || undefined }}>
        {paragraphs.map((p, i) => {
          const num = i < CIRCLED_NUMS.length ? CIRCLED_NUMS[i] : `(${i + 1})`
          return (
            <div key={i} className="group flex gap-0 py-1 hover:bg-muted/30 rounded transition-colors -mx-2 px-2">
              <span className="shrink-0 w-6 text-muted-foreground/50 text-xs font-mono select-none pt-0.5">
                {num}
              </span>
              <span className="flex-1 novel-content whitespace-pre-wrap" style={indent ? { textIndent: '2em' } : undefined}>{indent ? p.trim() : p}</span>
              <button
                onClick={() => onAddParagraphAnnotation(i + 1)}
                className="shrink-0 ml-2 mt-0.5 flex items-center gap-0.5 rounded-full px-1.5 text-xs text-muted-foreground hover:text-primary hover:bg-primary/10 transition-all [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 focus-visible:opacity-100"
                title={`给第 ${i + 1} 段加批注`}
              >
                <Plus className="w-3 h-3" />批注
              </button>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className={`flex-1 ${showDiff && !isCurrentlyGenerating && originalDraft ? 'overflow-hidden' : 'overflow-y-auto'}`}>
      {showDiff && !isCurrentlyGenerating && originalDraft ? (
        <DiffView
          originalText={originalDraft}
          revisedText={displayText}
          onClose={onCloseDiff}
        />
      ) : isEditing ? (
        <textarea
          ref={textareaRef}
          value={editContent}
          onChange={e => onEditContentChange(e.target.value)}
          onSelect={e => onSelectionChange?.({ start: e.currentTarget.selectionStart, end: e.currentTarget.selectionEnd })}
          className={`block h-full resize-none bg-background focus:outline-none novel-content font-serif ${MEASURE}`}
          style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any, color: fontColor || undefined }}
          placeholder="在此输入内容..."
        />
      ) : warningMessage && !isCurrentlyGenerating ? (
        <div className="flex flex-col h-full overflow-y-auto">
          <div className={`${COLUMN} mt-6 shrink-0`}>
          <div className="bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-xl px-4 py-2.5 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300">
            <span className="shrink-0 mt-0.5">⚠</span>
            <span>{warningMessage}</span>
          </div>
          </div>
          {rewriteMode && displayText ? (
            <div className="flex-1">
              {renderParagraphs(displayText)}
            </div>
          ) : (
            <div className={`novel-content whitespace-pre-wrap ${MEASURE}`} style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any, color: fontColor || undefined }}>
              {renderBody(displayText)}
            </div>
          )}
        </div>
      ) : errorMessage ? (
        <div className="p-8 flex flex-col items-center justify-center h-full gap-3">
          <div className="max-w-lg w-full bg-destructive/10 border border-destructive/30 rounded-xl p-4">
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
            <div className={`${COLUMN} pt-8 shrink-0`}>
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
          {rewriteMode && displayText && !isCurrentlyGenerating ? (
            <div className="flex-1">
              {renderParagraphs(displayText)}
            </div>
          ) : (
            <div className={`novel-content whitespace-pre-wrap flex-1 ${MEASURE} ${isStreaming ? 'streaming-cursor' : ''}`} style={{ fontSize: `${fontSize}px`, lineHeight, fontFamily: fontFamily || undefined, fontWeight: fontWeight as any, color: fontColor || undefined }}>
              {displayText ? renderBody(displayText) : (
                <span className="text-muted-foreground/50">
                  {isCurrentlyGenerating ? '' : '点击下方「生成章节」开始创作...'}
                </span>
              )}
              <div ref={contentEndRef} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
