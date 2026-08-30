import { useQuery } from '@tanstack/react-query'
import { Loader2, ChevronRight, BookOpen, Users } from 'lucide-react'
import { novelsApi, type Novel } from '@/api/client'

function formatWordCount(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return String(n)
}

interface Props {
  novel: Novel
  onClose: () => void
  onEnter: () => void
}

export default function NovelPreviewModal({ novel, onClose, onEnter }: Props) {
  const { data: overview, isLoading } = useQuery({
    queryKey: ['novel-overview', novel.id],
    queryFn: () => novelsApi.overview(novel.id),
  })

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-background rounded-xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="p-5 border-b">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-lg truncate">{novel.title}</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground shrink-0">
              {novel.genre || '未分类'}
            </span>
          </div>
          {novel.premise && (
            <p className="text-sm text-muted-foreground mt-2 line-clamp-3 whitespace-pre-wrap">{novel.premise}</p>
          )}
        </div>

        <div className="p-5 overflow-y-auto flex-1">
          {isLoading || !overview ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />加载中...
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm">
                <BookOpen className="w-4 h-4 text-primary shrink-0" />
                <span className="font-medium">
                  {overview.volume_count}卷 · {overview.chapter_count}章 · {formatWordCount(overview.total_words)}字
                </span>
              </div>
              <div>
                <div className="flex items-center gap-2 text-sm mb-2">
                  <Users className="w-4 h-4 text-primary shrink-0" />
                  <span className="font-medium">角色（{overview.characters.length}）</span>
                </div>
                {overview.characters.length === 0 ? (
                  <p className="text-xs text-muted-foreground">暂无角色</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {overview.characters.map((c) => (
                      <span
                        key={c.name}
                        className={`text-xs px-2 py-1 rounded-full border ${
                          c.role === '主角'
                            ? 'bg-primary/10 border-primary/40 text-primary font-medium'
                            : 'bg-muted border-border text-muted-foreground'
                        }`}
                      >
                        {c.name}
                        <span className="opacity-70 ml-1">{c.role}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 text-sm rounded-lg hover:bg-muted">
            关闭
          </button>
          <button
            onClick={onEnter}
            className="flex items-center gap-1 bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:opacity-90 text-sm font-medium"
          >
            进入创作
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
