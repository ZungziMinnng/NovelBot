import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2, Circle, Ban, ChevronDown, ChevronRight, ArrowLeft, ArrowRight } from 'lucide-react'
import { novelsApi, outlinesApi, type BuildSSEMessage, type BuildStepData } from '@/api/client'
import { charactersApi, locationsApi, factionsApi, techniquesApi } from '@/api/client'

const STEP_DEFS = [
  { key: 'config', label: '分析配置参数' },
  { key: 'world', label: '世界观·故事核心' },
  { key: 'outline', label: '情节大纲' },
  { key: 'locations', label: '构建地点' },
  { key: 'factions', label: '势力阵营' },
  { key: 'characters', label: '设计角色' },
  { key: 'techniques', label: '力量/功法体系' },
]

type StepStatus = 'pending' | 'running' | 'done' | 'skipped'

interface StepOutput {
  key: string
  text: string
}

export default function BuildMode() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [phase, setPhase] = useState<'building' | 'done' | 'error'>('building')
  const [stepStatuses, setStepStatuses] = useState<Record<string, StepStatus>>(() => {
    const init: Record<string, StepStatus> = {}
    STEP_DEFS.forEach(s => { init[s.key] = 'pending' })
    return init
  })
  const [stepOutputs, setStepOutputs] = useState<StepOutput[]>([])
  const [currentStepKey, setCurrentStepKey] = useState('')
  const [percent, setPercent] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [totalTokens, setTotalTokens] = useState(0)
  const [errorMsg, setErrorMsg] = useState('')

  const outputRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const startTimeRef = useRef(Date.now())
  const timerRef = useRef<ReturnType<typeof setInterval>>()

  useEffect(() => {
    startTimeRef.current = Date.now()
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000))
    }, 1000)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

  const handleMessage = useCallback((msg: BuildSSEMessage) => {
    switch (msg.event) {
      case 'build_step': {
        const d = msg.data as BuildStepData
        setStepStatuses(prev => ({ ...prev, [d.key]: d.status }))
        if (d.status === 'running') {
          setCurrentStepKey(d.key)
          setStepOutputs(prev => [...prev, { key: d.key, text: '' }])
        }
        break
      }
      case 'build_token': {
        setStepOutputs(prev => {
          if (prev.length === 0) return prev
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            text: updated[updated.length - 1].text + (msg.data as string),
          }
          return updated
        })
        setTotalTokens(prev => prev + (msg.data as string).length)
        break
      }
      case 'build_progress': {
        const d = msg.data as { percent: number }
        setPercent(d.percent)
        break
      }
      case 'build_done':
        setPhase('done')
        if (timerRef.current) clearInterval(timerRef.current)
        break
      case 'error':
        setErrorMsg(msg.data as string)
        setPhase('error')
        if (timerRef.current) clearInterval(timerRef.current)
        break
    }
  }, [])

  useEffect(() => {
    const ctrl = novelsApi.streamBuild(novelId, handleMessage, () => {})
    abortRef.current = ctrl
    return () => { ctrl.abort() }
  }, [novelId, handleMessage])

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [stepOutputs])

  const handleCancel = () => {
    abortRef.current?.abort()
    navigate('/')
  }

  const handleEnterEditor = () => {
    qc.invalidateQueries({ queryKey: ['novels'] })
    navigate(`/novel/${novelId}`)
  }

  if (phase === 'done') {
    return <BuildSummary novelId={novelId} elapsed={elapsed} totalTokens={totalTokens} onEnter={handleEnterEditor} onRebuild={() => window.location.reload()} />
  }

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <div className="border-b px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-muted-foreground hover:text-foreground">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <h1 className="font-semibold">
            {phase === 'error' ? '构建出错' : 'AI 正在构建小说世界...'}
          </h1>
        </div>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span>{elapsed}s</span>
          <span>{totalTokens > 1000 ? `${(totalTokens / 1000).toFixed(1)}K` : totalTokens} 字</span>
          <span className="text-primary font-medium">{percent}%</span>
        </div>
      </div>

      <div className="w-full h-1 bg-muted shrink-0">
        <div className="h-full bg-primary transition-all duration-300" style={{ width: `${percent}%` }} />
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-52 border-r p-4 space-y-1 shrink-0">
          {STEP_DEFS.map(s => {
            const status = stepStatuses[s.key]
            return (
              <div key={s.key} className={`flex items-center gap-2 px-2 py-1.5 rounded text-sm ${currentStepKey === s.key ? 'bg-primary/10' : ''}`}>
                {status === 'done' && <Check className="w-4 h-4 text-green-500 shrink-0" />}
                {status === 'running' && <Loader2 className="w-4 h-4 text-primary animate-spin shrink-0" />}
                {status === 'pending' && <Circle className="w-4 h-4 text-muted-foreground/40 shrink-0" />}
                {status === 'skipped' && <Ban className="w-4 h-4 text-muted-foreground/40 shrink-0" />}
                <span className={status === 'skipped' ? 'text-muted-foreground/40' : ''}>{s.label}</span>
              </div>
            )
          })}
        </div>

        <div ref={outputRef} className="flex-1 overflow-y-auto p-6 font-mono text-sm leading-relaxed">
          {phase === 'error' && (
            <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4 text-destructive">
              {errorMsg}
            </div>
          )}
          {stepOutputs.map((so, i) => {
            const def = STEP_DEFS.find(d => d.key === so.key)
            return (
              <div key={i} className="mb-6">
                <div className="text-xs text-primary font-semibold uppercase tracking-wide mb-2">
                  {def?.label || so.key}
                </div>
                <div className="whitespace-pre-wrap text-foreground/80">{so.text}</div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="border-t px-6 py-3 flex justify-end shrink-0">
        {phase === 'error' ? (
          <button onClick={() => navigate('/')} className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90">
            返回首页
          </button>
        ) : (
          <button onClick={handleCancel} className="px-4 py-2 rounded-lg border text-sm text-muted-foreground hover:text-foreground transition-colors">
            取消构建
          </button>
        )}
      </div>
    </div>
  )
}

function BuildSummary({ novelId, elapsed, totalTokens, onEnter, onRebuild }: {
  novelId: number
  elapsed: number
  totalTokens: number
  onEnter: () => void
  onRebuild: () => void
}) {
  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: chars } = useQuery({ queryKey: ['characters', novelId], queryFn: () => charactersApi.list(novelId) })
  const { data: locs } = useQuery({ queryKey: ['locations', novelId], queryFn: () => locationsApi.list(novelId) })
  const { data: facs } = useQuery({ queryKey: ['factions', novelId], queryFn: () => factionsApi.list(novelId) })
  const { data: techs } = useQuery({ queryKey: ['techniques', novelId], queryFn: () => techniquesApi.list(novelId) })
  const { data: outlines } = useQuery({ queryKey: ['outlines', novelId], queryFn: () => outlinesApi.list(novelId) })

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <div className="border-b px-6 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <Check className="w-5 h-5 text-green-500" />
          <h1 className="font-semibold">构建完成！</h1>
        </div>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <span>{elapsed}s</span>
          <span>{totalTokens > 1000 ? `${(totalTokens / 1000).toFixed(1)}K` : totalTokens} 字</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto w-full space-y-4">
        {novel?.core_setting && (
          <SummarySection title="世界观" count="">
            <p className="text-sm text-foreground/80 whitespace-pre-wrap">{novel.core_setting}</p>
          </SummarySection>
        )}

        {outlines && outlines.length > 0 && (
          <SummarySection title="大纲" count={`${outlines.length}章`}>
            <div className="space-y-1">
              {outlines.map(o => (
                <div key={o.id} className="text-sm">
                  <span className="font-medium">第{o.start_chapter}章：{o.title}</span>
                </div>
              ))}
            </div>
          </SummarySection>
        )}

        {locs && locs.length > 0 && (
          <SummarySection title="地点" count={`${locs.length}个`}>
            <div className="flex flex-wrap gap-2">
              {locs.map(l => (
                <span key={l.id} className="px-2 py-1 bg-muted rounded text-sm">{l.name}（{l.type}）</span>
              ))}
            </div>
          </SummarySection>
        )}

        {facs && facs.length > 0 && (
          <SummarySection title="势力" count={`${facs.length}个`}>
            <div className="flex flex-wrap gap-2">
              {facs.map(f => (
                <span key={f.id} className="px-2 py-1 bg-muted rounded text-sm">{f.name}</span>
              ))}
            </div>
          </SummarySection>
        )}

        {chars && chars.length > 0 && (
          <SummarySection title="角色" count={`${chars.length}个`}>
            <div className="space-y-1">
              {chars.map(c => (
                <div key={c.id} className="text-sm">
                  <span className="font-medium">{c.name}</span>
                  <span className="text-muted-foreground ml-1">({c.role})</span>
                  {c.description && <span className="text-foreground/60 ml-2">{c.description}</span>}
                </div>
              ))}
            </div>
          </SummarySection>
        )}

        {techs && techs.length > 0 && (
          <SummarySection title="功法/体系" count={`${techs.length}个`}>
            <div className="flex flex-wrap gap-2">
              {techs.map(t => (
                <span key={t.id} className="px-2 py-1 bg-muted rounded text-sm">{t.name}（{t.type}）</span>
              ))}
            </div>
          </SummarySection>
        )}
      </div>

      <div className="border-t px-6 py-4 flex justify-end gap-3 shrink-0">
        <button onClick={onRebuild} className="px-4 py-2 rounded-lg border text-sm text-muted-foreground hover:text-foreground transition-colors">
          重新构建
        </button>
        <button onClick={onEnter} className="flex items-center gap-2 px-5 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90">
          进入编辑器
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function SummarySection({ title, count, children }: { title: string; count: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="border rounded-lg">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-muted/50 transition-colors">
        <span>{title} {count && <span className="text-muted-foreground font-normal ml-1">({count})</span>}</span>
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && <div className="px-4 pb-3">{children}</div>}
    </div>
  )
}
