import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Plus, Pencil, Trash2, Sparkles, Loader2, Save, ChevronLeft } from 'lucide-react'
import { outlinesApi, type OutlineEntry } from '@/api/client'
import toast from 'react-hot-toast'

interface OutlineModalProps {
  novelId: number
  currentChapter: number
  onClose: () => void
}

export default function OutlineModal({ novelId, currentChapter, onClose }: OutlineModalProps) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<OutlineEntry | 'new' | null>(null)

  const { data: outlines = [], isLoading } = useQuery({
    queryKey: ['outlines', novelId],
    queryFn: () => outlinesApi.list(novelId),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => outlinesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['outlines', novelId] })
      toast.success('已删除')
    },
  })

  const expandMut = useMutation({
    mutationFn: (id: number) => outlinesApi.expand(id),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['outlines', novelId] })
      toast.success(`已细化生成 ${created.length} 条大纲`)
    },
    onError: () => toast.error('细化失败，请重试'),
  })

  const handleDelete = (id: number) => {
    if (confirm('确定删除此大纲？')) deleteMut.mutate(id)
  }

  if (editing) {
    return (
      <ModalShell onClose={onClose}>
        <OutlineForm
          novelId={novelId}
          currentChapter={currentChapter}
          outline={editing === 'new' ? null : editing}
          onBack={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            qc.invalidateQueries({ queryKey: ['outlines', novelId] })
          }}
        />
      </ModalShell>
    )
  }

  return (
    <ModalShell onClose={onClose}>
      <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
        <h2 className="text-base font-semibold">章节大纲</h2>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setEditing('new')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-primary-foreground rounded-lg text-xs font-medium hover:opacity-90"
          >
            <Plus className="w-3.5 h-3.5" /> 新建大纲
          </button>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : outlines.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground text-sm">
            暂无大纲，点击"新建大纲"开始规划
          </div>
        ) : (
          <div className="space-y-3">
            {outlines.map(o => {
              const isRange = o.start_chapter !== o.end_chapter
              const rangeLabel = isRange
                ? `第 ${o.start_chapter}-${o.end_chapter} 章`
                : `第 ${o.start_chapter} 章`
              const isCurrent = currentChapter >= o.start_chapter && currentChapter <= o.end_chapter
              return (
                <div
                  key={o.id}
                  className={`border rounded-lg p-4 transition-colors ${
                    isCurrent ? 'border-primary/40 bg-primary/5' : 'hover:bg-muted/30'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          isRange
                            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                            : 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                        }`}>
                          {rangeLabel}
                        </span>
                        {o.title && <span className="text-sm font-medium truncate">{o.title}</span>}
                        {isCurrent && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">当前</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                        {o.content || '（空）'}
                      </p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => setEditing(o)}
                        className="p-1.5 rounded hover:bg-muted"
                        title="编辑"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      {isRange && (
                        <button
                          onClick={() => expandMut.mutate(o.id)}
                          disabled={expandMut.isPending}
                          className="p-1.5 rounded hover:bg-muted text-blue-600 dark:text-blue-400"
                          title="细化为逐章大纲"
                        >
                          {expandMut.isPending ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Sparkles className="w-3.5 h-3.5" />
                          )}
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(o.id)}
                        disabled={deleteMut.isPending}
                        className="p-1.5 rounded hover:bg-muted text-destructive"
                        title="删除"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </ModalShell>
  )
}

function ModalShell({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed inset-y-4 left-1/2 -translate-x-1/2 w-full max-w-2xl bg-background border rounded-xl shadow-2xl z-50 flex flex-col">
        {children}
      </div>
    </>
  )
}

function OutlineForm({
  novelId,
  currentChapter,
  outline,
  onBack,
  onSaved,
}: {
  novelId: number
  currentChapter: number
  outline: OutlineEntry | null
  onBack: () => void
  onSaved: () => void
}) {
  const [startCh, setStartCh] = useState(outline?.start_chapter ?? currentChapter)
  const [endCh, setEndCh] = useState(outline?.end_chapter ?? currentChapter)
  const [title, setTitle] = useState(outline?.title ?? '')
  const [content, setContent] = useState(outline?.content ?? '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (endCh < startCh) {
      toast.error('结束章节不能小于起始章节')
      return
    }
    if (!content.trim()) {
      toast.error('请填写大纲内容')
      return
    }
    setSaving(true)
    try {
      if (outline) {
        await outlinesApi.update(outline.id, {
          start_chapter: startCh,
          end_chapter: endCh,
          title,
          content,
        })
        toast.success('大纲已更新')
      } else {
        await outlinesApi.create({
          novel_id: novelId,
          start_chapter: startCh,
          end_chapter: endCh,
          title,
          content,
        })
        toast.success('大纲已创建')
      }
      onSaved()
    } catch {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="flex items-center gap-3 px-6 py-4 border-b shrink-0">
        <button onClick={onBack} className="p-1 rounded hover:bg-muted">
          <ChevronLeft className="w-4 h-4" />
        </button>
        <h2 className="text-base font-semibold">{outline ? '编辑大纲' : '新建大纲'}</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium whitespace-nowrap">起始章节</label>
            <input
              type="number"
              min={1}
              value={startCh}
              onChange={e => setStartCh(Number(e.target.value))}
              className="w-20 border rounded-lg px-2 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <span className="text-muted-foreground">—</span>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium whitespace-nowrap">结束章节</label>
            <input
              type="number"
              min={startCh}
              value={endCh}
              onChange={e => setEndCh(Number(e.target.value))}
              className="w-20 border rounded-lg px-2 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          <span className="text-xs text-muted-foreground ml-auto">
            {startCh === endCh ? '单章大纲' : `范围大纲（${endCh - startCh + 1} 章）`}
          </span>
        </div>

        <div>
          <label className="text-xs font-medium mb-1.5 block">标题（可选）</label>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="如：主角突破金丹期"
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        <div>
          <label className="text-xs font-medium mb-1.5 block">大纲内容</label>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder="描述这些章节的核心事件、角色发展、剧情走向..."
            rows={10}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y min-h-[120px]"
          />
        </div>
      </div>

      <div className="px-6 py-4 border-t shrink-0">
        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {outline ? '更新大纲' : '创建大纲'}
        </button>
      </div>
    </>
  )
}
