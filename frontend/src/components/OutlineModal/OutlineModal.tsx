import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Plus, Pencil, Trash2, Sparkles, Loader2, Save, ChevronLeft, Stethoscope } from 'lucide-react'
import { outlinesApi, type OutlineEntry, type OutlineHealth } from '@/api/client'
import toast from 'react-hot-toast'

interface OutlineModalProps {
  novelId: number
  currentChapter: number
  onClose: () => void
}

export default function OutlineModal({ novelId, currentChapter, onClose }: OutlineModalProps) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<OutlineEntry | 'new' | null>(null)
  const [showHealth, setShowHealth] = useState(false)
  // 大纲一变体检结论就过期了，两个 key 一起刷
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['outlines', novelId] })
    qc.invalidateQueries({ queryKey: ['outline-health', novelId] })
  }

  const { data: health } = useQuery({
    queryKey: ['outline-health', novelId],
    queryFn: () => outlinesApi.health(novelId),
    enabled: showHealth,
  })

  const { data: outlines = [], isLoading } = useQuery({
    queryKey: ['outlines', novelId],
    queryFn: () => outlinesApi.list(novelId),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => outlinesApi.delete(id),
    onSuccess: () => {
      refresh()
      toast.success('已删除')
    },
  })

  const expandMut = useMutation({
    mutationFn: (id: number) => outlinesApi.expand(id),
    onSuccess: (created) => {
      refresh()
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
            refresh()
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
            onClick={() => setShowHealth(v => !v)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border ${
              showHealth ? 'bg-muted' : 'hover:bg-muted'
            }`}
          >
            <Stethoscope className="w-3.5 h-3.5" /> 大纲体检
          </button>
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
        {showHealth && <HealthPanel health={health} />}
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
                          <span className="text-[0.625rem] px-1.5 py-0.5 rounded bg-primary/10 text-primary">当前</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground line-clamp-3 whitespace-pre-wrap">
                        {o.content || '（空）'}
                      </p>
                      <PlanBadges outline={o} />
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

/** 体检只报告，不拦截任何操作 */
function HealthPanel({ health }: { health: OutlineHealth | undefined }) {
  if (!health) {
    return (
      <div className="flex items-center gap-2 mb-4 p-4 border rounded-lg text-xs text-muted-foreground">
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> 正在体检...
      </div>
    )
  }
  const groups = [
    { title: '全书章纲', findings: health.chapters },
    ...health.volumes.map(v => ({ title: `第 ${v.number} 卷 ${v.title}`, findings: v.findings })),
  ].filter(g => g.findings.length)

  return (
    <div className="mb-4 p-4 border rounded-lg space-y-3">
      <div className="text-xs text-muted-foreground">
        共 {health.chapter_count} 条章纲
        {health.total_target_words > 0 && `，全书目标约 ${health.total_target_words} 字`}
        。以下只是提醒，不影响写作
      </div>
      {groups.length === 0 ? (
        <div className="text-xs text-green-600 dark:text-green-400">没查出问题</div>
      ) : (
        groups.map(g => (
          <div key={g.title} className="space-y-1.5">
            <div className="text-xs font-medium">{g.title}</div>
            {g.findings.map((f, i) => (
              <div key={i} className="text-xs pl-2 border-l-2"
                style={{ borderColor: f.level === 'warn' ? 'rgb(234 179 8)' : 'rgb(148 163 184)' }}>
                <div className={f.level === 'warn' ? 'text-yellow-600 dark:text-yellow-400' : ''}>{f.label}</div>
                <div className="text-muted-foreground">{f.detail}</div>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  )
}

function PlanBadges({ outline }: { outline: OutlineEntry }) {
  const items = [
    outline.chapter_role,
    outline.emotion_tone && `${outline.emotion_tone}${outline.emotion_intensity ? ` ${outline.emotion_intensity}` : ''}`,
    outline.hook_type && `钩子·${outline.hook_type}${outline.hook_strength ? ` ${outline.hook_strength}` : ''}`,
  ].filter(Boolean) as string[]
  if (!items.length) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {items.map(t => (
        <span key={t} className="text-[0.625rem] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
          {t}
        </span>
      ))}
    </div>
  )
}

const FIELD_CLS = 'w-full border rounded-lg px-2 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring'

function PlanSelect({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-xs font-medium mb-1 block">{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} className={FIELD_CLS}>
        <option value="">未规划</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}

/** 0 = 未规划，1-5 越大越强 */
function PlanLevel({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <div>
      <label className="text-xs font-medium mb-1 block">{label}</label>
      <select value={value} onChange={e => onChange(Number(e.target.value))} className={FIELD_CLS}>
        <option value={0}>未规划</option>
        {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
      </select>
    </div>
  )
}

function ModalShell({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" />
      <div className="fixed inset-y-4 left-1/2 -translate-x-1/2 w-full max-w-4xl bg-background border rounded-xl shadow-2xl z-50 flex flex-col">
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
  const [plan, setPlan] = useState({
    chapter_role: outline?.chapter_role ?? '',
    emotion_tone: outline?.emotion_tone ?? '',
    emotion_intensity: outline?.emotion_intensity ?? 0,
    hook_type: outline?.hook_type ?? '',
    hook_strength: outline?.hook_strength ?? 0,
  })
  const [saving, setSaving] = useState(false)

  const { data: options } = useQuery({
    queryKey: ['outline-plan-options'],
    queryFn: () => outlinesApi.planOptions(),
    staleTime: Infinity,
  })

  const isSingle = startCh === endCh

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
      // 范围大纲没有单章计划，存空值避免细化后残留上一层的钩子
      const planPayload = isSingle
        ? plan
        : { chapter_role: '', emotion_tone: '', emotion_intensity: 0, hook_type: '', hook_strength: 0 }
      if (outline) {
        await outlinesApi.update(outline.id, {
          start_chapter: startCh,
          end_chapter: endCh,
          title,
          content,
          ...planPayload,
        })
        toast.success('大纲已更新')
      } else {
        await outlinesApi.create({
          novel_id: novelId,
          start_chapter: startCh,
          end_chapter: endCh,
          title,
          content,
          ...planPayload,
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

        {isSingle && (
          <div className="border rounded-lg p-4 space-y-3">
            <div className="text-xs font-medium">
              执行计划（可选）
              <span className="ml-2 font-normal text-muted-foreground">
                填了就会注入写作提示词，指导本章的节奏和结尾写法
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <PlanSelect
                label="本章定位" value={plan.chapter_role} options={options?.chapter_roles ?? []}
                onChange={v => setPlan({ ...plan, chapter_role: v })}
              />
              <PlanSelect
                label="情绪基调" value={plan.emotion_tone} options={options?.emotion_tones ?? []}
                onChange={v => setPlan({ ...plan, emotion_tone: v })}
              />
              <PlanLevel
                label="情绪强度" value={plan.emotion_intensity}
                onChange={v => setPlan({ ...plan, emotion_intensity: v })}
              />
              <PlanSelect
                label="章尾钩子" value={plan.hook_type} options={options?.hook_types ?? []}
                onChange={v => setPlan({ ...plan, hook_type: v })}
              />
              <PlanLevel
                label="钩子强度" value={plan.hook_strength}
                onChange={v => setPlan({ ...plan, hook_strength: v })}
              />
            </div>
          </div>
        )}
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
