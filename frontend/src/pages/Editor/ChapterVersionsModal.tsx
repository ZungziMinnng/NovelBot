import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { History, Loader2, RotateCcw, X } from 'lucide-react'
import DiffView from '@/components/DiffView/DiffView'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { chaptersApi, type Chapter } from '@/api/client'

// 后端在覆盖正文之前存的快照，reason 说明是被什么覆盖掉的
const REASON_LABEL: Record<string, string> = {
  regenerate: '重新生成前',
  rewrite: '批注重写前',
  restore: '恢复旧版前',
  edit: '手动编辑',
}

interface Props {
  chapter: Chapter
  /** 编辑框里的正文可能还没保存，对比时以它为准 */
  currentText: string
  onRestored: (updated: Chapter) => void
  onClose: () => void
}

export default function ChapterVersionsModal({ chapter, currentText, onRestored, onClose }: Props) {
  const [pickedId, setPickedId] = useState<number | null>(null)
  const [restoring, setRestoring] = useState(false)

  const { data: versions = [], isLoading } = useQuery({
    queryKey: ['chapter-versions', chapter.id],
    queryFn: () => chaptersApi.versions(chapter.id),
    staleTime: 0,
  })
  const { data: picked, isFetching: loadingPicked } = useQuery({
    queryKey: ['chapter-version', chapter.id, pickedId],
    queryFn: () => chaptersApi.version(chapter.id, pickedId!),
    enabled: pickedId != null,
  })

  const handleRestore = async () => {
    if (!picked) return
    const ok = await confirmDialog({
      title: '恢复到这个版本？',
      detail: '现在的正文会先存成一个历史版本，恢复后还能再换回来。',
      confirmText: '恢复',
    })
    if (!ok) return
    setRestoring(true)
    try {
      const updated = await chaptersApi.restoreVersion(chapter.id, picked.id)
      onRestored(updated)
      toast.success('已恢复')
      onClose()
    } catch {
      toast.error('恢复失败')
    } finally { setRestoring(false) }
  }

  const fmt = (s: string) => new Date(s).toLocaleString('zh-CN', { hour12: false })

  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-background rounded-xl shadow-xl w-full max-w-6xl h-[85vh] flex flex-col overflow-hidden"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-label="历史版本"
      >
        <div className="flex items-center gap-2 px-4 py-2.5 border-b shrink-0">
          <History className="w-4 h-4 text-muted-foreground" />
          <span className="text-sm font-medium">第{chapter.number}章 · 历史版本</span>
          <span className="text-xs text-muted-foreground">每章保留最近 30 个；手动编辑最多 10 分钟存一份</span>
          <button onClick={onClose} className="ml-auto p-1 rounded hover:bg-muted" aria-label="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex flex-1 min-h-0">
          <div className="w-56 border-r overflow-y-auto p-2 space-y-0.5 shrink-0">
            {isLoading ? (
              <div className="flex justify-center py-6"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>
            ) : versions.length === 0 ? (
              <p className="text-xs text-muted-foreground px-2 py-4">
                还没有历史版本。重新生成、批注重写、手动编辑之前会自动存一份。
              </p>
            ) : versions.map(v => (
              <button
                key={v.id}
                onClick={() => setPickedId(v.id)}
                className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs transition-colors ${
                  pickedId === v.id ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                }`}
              >
                <div className="flex justify-between gap-2">
                  <span>{REASON_LABEL[v.reason] || v.reason}</span>
                  <span className="opacity-70 tabular-nums">{v.word_count}字</span>
                </div>
                <div className="opacity-70 tabular-nums mt-0.5">{fmt(v.created_at)}</div>
              </button>
            ))}
          </div>
          <div className="flex-1 min-w-0 flex flex-col">
            {pickedId == null ? (
              <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground">
                选左边一个版本，和现在的正文对比
              </div>
            ) : loadingPicked || !picked ? (
              <div className="flex-1 flex items-center justify-center"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
            ) : (
              <>
                <div className="flex-1 min-h-0">
                  <DiffView
                    originalText={picked.content}
                    revisedText={currentText}
                    leftLabel="这个旧版本"
                    rightLabel="现在的正文"
                    onClose={() => setPickedId(null)}
                  />
                </div>
                <div className="border-t px-4 py-2 flex justify-end shrink-0">
                  <button
                    onClick={handleRestore}
                    disabled={restoring}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 bg-primary text-primary-foreground rounded-full hover:opacity-95 disabled:opacity-50"
                  >
                    {restoring ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                    恢复到这个版本
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
