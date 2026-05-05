import { Check } from 'lucide-react'
import type { Chapter } from '@/api/client'

interface ChapterSidebarProps {
  chapters: Chapter[]
  selectedChapterNum: number
  isGenerating: boolean
  generatingNovelId: number | null
  generatingChapterNum: number | null
  onSelectChapter: (num: number) => void
  onNewChapter: () => void
}

export default function ChapterSidebar({
  chapters,
  selectedChapterNum,
  isGenerating,
  generatingNovelId,
  generatingChapterNum,
  onSelectChapter,
  onNewChapter,
}: ChapterSidebarProps) {
  return (
    <div className="w-52 border-r flex flex-col shrink-0">
      <div className="p-3 border-b">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">章节</p>
      </div>
      <div className="overflow-y-auto flex-1 p-2 space-y-0.5">
        {chapters.map((c: Chapter) => (
          <button
            key={c.id}
            onClick={() => onSelectChapter(c.number)}
            className={`w-full text-left px-2.5 py-2 rounded-md text-sm transition-colors ${
              c.number === selectedChapterNum
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="truncate">第{c.number}章</span>
              {isGenerating && generatingNovelId === c.novel_id && generatingChapterNum === c.number
                ? <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />
                : c.status === 'confirmed'
                  ? <Check className="w-3 h-3 shrink-0 opacity-70" />
                  : null}
            </div>
            {c.title && c.title !== `第${c.number}章` && (
              <p className={`text-xs truncate mt-0.5 ${c.number === selectedChapterNum ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                {c.title}
              </p>
            )}
          </button>
        ))}
        <button
          onClick={onNewChapter}
          className="w-full text-left px-2.5 py-2 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors border border-dashed mt-2"
        >
          + 新章节
        </button>
      </div>
    </div>
  )
}
