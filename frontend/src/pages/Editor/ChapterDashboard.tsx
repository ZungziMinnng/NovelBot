import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, Save, Stethoscope, Target, KeyRound, AlertTriangle } from 'lucide-react'
import {
  outlinesApi, storyThreadsApi, chaptersApi,
  type OutlineEntry, type StoryThread, type ProseFinding,
} from '@/api/client'

interface Props {
  novelId: number
  chapterNum: number
  /** 编辑器里当前显示的正文，可能还没保存 */
  displayText: string
  targetWords: number
}

const FIELD_CLS = 'w-full border rounded px-1.5 py-1 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring'

/** 章级计划的五个字段，空串/0 表示未规划 */
type Plan = Pick<OutlineEntry, 'chapter_role' | 'emotion_tone' | 'emotion_intensity' | 'hook_type' | 'hook_strength'>

const emptyPlan: Plan = {
  chapter_role: '', emotion_tone: '', emotion_intensity: 0, hook_type: '', hook_strength: 0,
}

const pickPlan = (o: OutlineEntry): Plan => ({
  chapter_role: o.chapter_role,
  emotion_tone: o.emotion_tone,
  emotion_intensity: o.emotion_intensity,
  hook_type: o.hook_type,
  hook_strength: o.hook_strength,
})

function Section({ icon, title, extra, children }: {
  icon: React.ReactNode; title: string; extra?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="border rounded-lg p-2.5 space-y-2">
      <div className="flex items-center gap-1.5">
        <span className="text-muted-foreground">{icon}</span>
        <span className="text-xs font-medium">{title}</span>
        <span className="ml-auto">{extra}</span>
      </div>
      {children}
    </div>
  )
}

function PlanField({ label, value, options, onChange }: {
  label: string; value: string; options: string[]; onChange: (v: string) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)} className={FIELD_CLS}>
        <option value="">未规划</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  )
}

function PlanLevelField({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <select value={value} onChange={e => onChange(Number(e.target.value))} className={FIELD_CLS}>
        <option value={0}>未规划</option>
        {[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}
      </select>
    </label>
  )
}

export default function ChapterDashboard({ novelId, chapterNum, displayText, targetWords }: Props) {
  const qc = useQueryClient()

  const { data: outlines = [] } = useQuery({
    queryKey: ['outlines', novelId],
    queryFn: () => outlinesApi.list(novelId),
  })
  const { data: options } = useQuery({
    queryKey: ['plan-options'],
    queryFn: () => outlinesApi.planOptions(),
    staleTime: Infinity,
  })
  const { data: threads = [] } = useQuery({
    queryKey: ['story-threads', novelId],
    queryFn: () => storyThreadsApi.list(novelId),
  })

  // 章级大纲优先；只有范围大纲覆盖时没有单章计划可改，得先在大纲里细化
  const chapterOutline = outlines.find(o => o.start_chapter === chapterNum && o.end_chapter === chapterNum)
  const rangeOutline = outlines.find(
    o => o.start_chapter !== o.end_chapter && o.start_chapter <= chapterNum && chapterNum <= o.end_chapter,
  )

  return (
    <div className="space-y-2">
      <PlanSection
        outline={chapterOutline}
        rangeOutline={rangeOutline}
        chapterNum={chapterNum}
        options={options}
        onSaved={() => {
          qc.invalidateQueries({ queryKey: ['outlines', novelId] })
          qc.invalidateQueries({ queryKey: ['outline-health', novelId] })
        }}
      />
      <ThreadsSection threads={threads} chapterNum={chapterNum} />
      <ProseSection displayText={displayText} targetWords={targetWords} />
    </div>
  )
}

function PlanSection({ outline, rangeOutline, chapterNum, options, onSaved }: {
  outline?: OutlineEntry
  rangeOutline?: OutlineEntry
  chapterNum: number
  options?: { chapter_roles: string[]; emotion_tones: string[]; hook_types: string[] }
  onSaved: () => void
}) {
  const [plan, setPlan] = useState<Plan>(emptyPlan)
  const [saving, setSaving] = useState(false)

  // 切章或大纲刷新后同步表单，否则会把上一章的计划写到这一章
  useEffect(() => {
    setPlan(outline ? pickPlan(outline) : emptyPlan)
  }, [outline?.id, outline?.updated_at])

  const dirty = outline ? JSON.stringify(plan) !== JSON.stringify(pickPlan(outline)) : false

  const save = async () => {
    if (!outline) return
    setSaving(true)
    try {
      await outlinesApi.update(outline.id, plan)
      toast.success('本章计划已保存')
      onSaved()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  if (!outline) {
    return (
      <Section icon={<Target className="w-3.5 h-3.5" />} title={`第 ${chapterNum} 章计划`}>
        {rangeOutline ? (
          <div className="space-y-1.5">
            <p className="text-xs text-muted-foreground">
              这一章由第 {rangeOutline.start_chapter}-{rangeOutline.end_chapter} 章的范围大纲覆盖，没有单章计划。
              要按章规划，先在「大纲」里把它细化为逐章大纲。
            </p>
            {rangeOutline.content && (
              <p className="text-xs whitespace-pre-wrap line-clamp-6 bg-muted/50 rounded p-1.5">{rangeOutline.content}</p>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">这一章还没有大纲。去「大纲」里补一条，这里就能直接改本章的定位、情绪和钩子。</p>
        )}
      </Section>
    )
  }

  return (
    <Section
      icon={<Target className="w-3.5 h-3.5" />}
      title={`第 ${chapterNum} 章计划`}
      extra={dirty && (
        <button onClick={save} disabled={saving}
          className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded bg-primary text-primary-foreground disabled:opacity-50">
          {saving ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Save className="w-2.5 h-2.5" />}
          保存
        </button>
      )}
    >
      {outline.title && <div className="text-xs font-medium">{outline.title}</div>}
      <div className="grid grid-cols-2 gap-1.5">
        <PlanField label="本章定位" value={plan.chapter_role} options={options?.chapter_roles ?? []}
          onChange={v => setPlan({ ...plan, chapter_role: v })} />
        <PlanField label="情绪基调" value={plan.emotion_tone} options={options?.emotion_tones ?? []}
          onChange={v => setPlan({ ...plan, emotion_tone: v })} />
        <PlanLevelField label="情绪强度" value={plan.emotion_intensity}
          onChange={v => setPlan({ ...plan, emotion_intensity: v })} />
        <PlanLevelField label="钩子强度" value={plan.hook_strength}
          onChange={v => setPlan({ ...plan, hook_strength: v })} />
      </div>
      <PlanField label="章尾钩子" value={plan.hook_type} options={options?.hook_types ?? []}
        onChange={v => setPlan({ ...plan, hook_type: v })} />
      {outline.content && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">本章大纲</summary>
          <p className="whitespace-pre-wrap mt-1 bg-muted/50 rounded p-1.5">{outline.content}</p>
        </details>
      )}
    </Section>
  )
}

function ThreadsSection({ threads, chapterNum }: { threads: StoryThread[]; chapterNum: number }) {
  const active = threads.filter(t => t.status === 'active')
  // 到期的排前面（due_chapter 为 0 表示没设期限），其次按重要度
  const sorted = [...active].sort((a, b) => {
    const aDue = a.due_chapter > 0 && a.due_chapter <= chapterNum
    const bDue = b.due_chapter > 0 && b.due_chapter <= chapterNum
    if (aDue !== bDue) return aDue ? -1 : 1
    return b.importance - a.importance
  })
  const dueCount = active.filter(t => t.due_chapter > 0 && t.due_chapter <= chapterNum).length

  return (
    <Section
      icon={<KeyRound className="w-3.5 h-3.5" />}
      title="在场的伏笔/秘密"
      extra={
        <span className="text-[11px] text-muted-foreground">
          {dueCount > 0 ? <span className="text-amber-600 dark:text-amber-400">{dueCount} 条到期</span> : `${active.length} 条`}
        </span>
      }
    >
      {sorted.length === 0 ? (
        <p className="text-xs text-muted-foreground">当前没有活跃的伏笔或秘密。</p>
      ) : (
        <div className="space-y-1">
          {sorted.slice(0, 12).map(t => {
            const overdue = t.due_chapter > 0 && t.due_chapter <= chapterNum
            return (
              <div key={t.id} className={`rounded p-1.5 text-xs ${overdue ? 'bg-amber-500/10' : 'bg-muted/50'}`}>
                <div className="flex items-center gap-1">
                  <span className={`shrink-0 text-[11px] px-1 rounded ${
                    t.kind === 'secret'
                      ? 'bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300'
                      : 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300'
                  }`}>
                    {t.kind === 'secret' ? '秘密' : '伏笔'}
                  </span>
                  <span className="font-medium truncate">{t.title || t.content.slice(0, 12)}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                    {t.due_chapter > 0 ? `第${t.due_chapter}章前` : `第${t.source_chapter}章埋`}
                  </span>
                </div>
                {t.title && <div className="text-muted-foreground mt-0.5 line-clamp-2">{t.content}</div>}
              </div>
            )
          })}
          {sorted.length > 12 && (
            <p className="text-[11px] text-muted-foreground">还有 {sorted.length - 12} 条，完整清单在左侧「世界」页。</p>
          )}
        </div>
      )}
    </Section>
  )
}

function ProseSection({ displayText, targetWords }: { displayText: string; targetWords: number }) {
  const [findings, setFindings] = useState<ProseFinding[] | null>(null)
  const [running, setRunning] = useState(false)

  // 正文一变旧结论就不作数了，清掉而不是留着误导
  useEffect(() => { setFindings(null) }, [displayText])

  const words = displayText.replace(/\s/g, '').length
  const ratio = targetWords > 0 ? words / targetWords : 0
  const wordsOff = targetWords > 0 && words > 0 && (ratio < 0.9 || ratio > 1.15)

  const run = async () => {
    setRunning(true)
    try {
      const r = await chaptersApi.lint(displayText)
      setFindings(r.findings)
      if (r.findings.length === 0) toast.success('没查出机械问题')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '体检失败')
    } finally {
      setRunning(false)
    }
  }

  // 同类只报首例，跟 Critic 的 format_issues 一个思路，避免同一条刷屏
  const grouped = findings ? Object.values(
    findings.reduce<Record<string, { f: ProseFinding; count: number }>>((acc, f) => {
      acc[f.label] = acc[f.label] ? { f: acc[f.label].f, count: acc[f.label].count + 1 } : { f, count: 1 }
      return acc
    }, {}),
  ) : []

  return (
    <Section
      icon={<Stethoscope className="w-3.5 h-3.5" />}
      title="正文体检"
      extra={
        <button onClick={run} disabled={running || !displayText.trim()}
          className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border hover:bg-muted disabled:opacity-50">
          {running && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
          检查
        </button>
      }
    >
      <div className="flex items-center gap-1.5 text-xs">
        <span className={wordsOff ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}>
          {words} 字{targetWords > 0 ? ` / 目标 ${targetWords}` : ''}
        </span>
        {wordsOff && <AlertTriangle className="w-3 h-3 text-amber-600 dark:text-amber-400" />}
      </div>

      {findings === null ? (
        <p className="text-xs text-muted-foreground">点「检查」跑一遍套式句、复读、描写密度这些机械问题，用的是和审稿一样的规则。</p>
      ) : grouped.length === 0 ? (
        <p className="text-xs text-muted-foreground">没查出机械问题。</p>
      ) : (
        <div className="space-y-1">
          {grouped.map(({ f, count }) => (
            <div key={f.label} className={`rounded p-1.5 text-xs ${f.severity === 'blocking' ? 'bg-red-500/10' : 'bg-muted/50'}`}>
              <div className="flex items-center gap-1">
                <span className={`shrink-0 text-[11px] px-1 rounded ${
                  f.severity === 'blocking'
                    ? 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300'
                    : 'bg-muted text-muted-foreground'
                }`}>
                  {f.severity === 'blocking' ? '要改' : '提醒'}
                </span>
                <span className="font-medium">{f.label}</span>
                {count > 1 && <span className="text-[11px] text-muted-foreground">×{count}</span>}
              </div>
              {f.evidence && <div className="text-muted-foreground mt-0.5 line-clamp-2">{f.evidence}</div>}
            </div>
          ))}
        </div>
      )}
    </Section>
  )
}
