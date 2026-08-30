import { useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'
import { storyThreadsApi, type ThreadResolution } from '@/api/client'

interface ThreadResolutionsModalProps {
  novelId: number
  resolutions: ThreadResolution[]
  currentChapter: number
  onClose: () => void
}

export function ThreadResolutionsModal({ novelId, resolutions, currentChapter, onClose }: ThreadResolutionsModalProps) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(() => new Set(resolutions.map((_, i) => i)))
  const [saving, setSaving] = useState(false)

  const toggle = (i: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  const handleConfirm = async () => {
    const picked = resolutions.filter((_, i) => selected.has(i))
    if (picked.length === 0) {
      onClose()
      return
    }
    setSaving(true)
    try {
      for (const r of picked) {
        if (r.action === 'resolve') {
          await storyThreadsApi.update(r.thread_id, {
            status: 'resolved',
            resolved_chapter: currentChapter,
            resolution: r.resolution || '',
          })
        } else {
          await storyThreadsApi.update(r.thread_id, {
            known_by: r.known_by ?? [],
          })
        }
      }
      qc.invalidateQueries({ queryKey: ['story-threads', novelId] })
      toast.success(`已更新 ${picked.length} 条`)
      onClose()
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '更新失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-background rounded-xl shadow-xl max-h-[80vh] overflow-y-auto w-[560px] mx-4"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-background border-b px-5 py-3 flex items-center gap-3 z-10 rounded-t-xl">
          <h2 className="font-bold text-base flex-1">本章检测到的伏笔回收 / 秘密公开</h2>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
        </div>

        <div className="p-5 space-y-3">
          {resolutions.map((r, i) => (
            <label key={i} className="flex items-start gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/40">
              <input
                type="checkbox"
                checked={selected.has(i)}
                onChange={() => toggle(i)}
                className="mt-1 shrink-0"
              />
              <span
                className={`shrink-0 text-xs px-2 py-0.5 rounded ${
                  r.action === 'resolve'
                    ? 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300'
                    : 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300'
                }`}
              >
                {r.action === 'resolve' ? (r.kind === 'secret' ? '秘密揭晓' : '伏笔回收') : '秘密新知情'}
              </span>
              <div className="flex-1 min-w-0">
                {r.title && <div className="text-sm font-medium">{r.title}</div>}
                <div className="text-sm text-muted-foreground whitespace-pre-wrap">{r.content}</div>
                {r.action === 'resolve' ? (
                  r.resolution && <div className="text-xs text-green-700 dark:text-green-400 mt-1">结局：{r.resolution}</div>
                ) : (
                  (r.newly_known_by?.length ?? 0) > 0 && (
                    <div className="text-xs text-blue-700 dark:text-blue-400 mt-1">新知情者：{r.newly_known_by!.join('、')}</div>
                  )
                )}
              </div>
            </label>
          ))}
          <p className="text-xs text-muted-foreground">勾选后点「确认」才会更新「世界观 → 伏笔/秘密」的状态；直接关闭则不改动。伏笔回收标记为已回收，秘密新知情者并入知情名单。</p>
        </div>

        <div className="sticky bottom-0 bg-background border-t px-5 py-3 flex items-center justify-end gap-2 rounded-b-xl">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded hover:bg-muted" disabled={saving}>
            忽略
          </button>
          <button
            onClick={handleConfirm}
            disabled={saving || selected.size === 0}
            className="px-3 py-1.5 text-sm rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            确认{selected.size > 0 ? `（${selected.size}）` : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
