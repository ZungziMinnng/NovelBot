import { create } from 'zustand'
import { novelsApi, type BuildSSEMessage, type BuildStepData } from '@/api/client'
import toast from 'react-hot-toast'

type StepStatus = 'pending' | 'running' | 'done' | 'skipped'

export interface StepOutput {
  key: string
  text: string
}

const STEP_KEYS = ['config', 'world', 'outline', 'locations', 'factions', 'characters', 'techniques']

function initStatuses(): Record<string, StepStatus> {
  const m: Record<string, StepStatus> = {}
  STEP_KEYS.forEach(k => { m[k] = 'pending' })
  return m
}

interface BuildState {
  isBuilding: boolean
  novelId: number | null
  novelTitle: string
  phase: 'idle' | 'building' | 'done' | 'error'
  stepStatuses: Record<string, StepStatus>
  stepOutputs: StepOutput[]
  currentStepKey: string
  percent: number
  elapsed: number
  totalTokens: number
  errorMsg: string
  abortController: AbortController | null
  runId: number

  startBuild: (novelId: number, title: string, nsfwMode?: boolean) => void
  abortBuild: () => void
  reset: () => void
}

let _timer: ReturnType<typeof setInterval> | null = null
let _startTime = 0
let _nextRunId = 1

export const useBuildStore = create<BuildState>()((set, get) => ({
  isBuilding: false,
  novelId: null,
  novelTitle: '',
  phase: 'idle',
  stepStatuses: initStatuses(),
  stepOutputs: [],
  currentStepKey: '',
  percent: 0,
  elapsed: 0,
  totalTokens: 0,
  errorMsg: '',
  abortController: null,
  runId: 0,

  startBuild: (novelId, title, nsfwMode) => {
    const prev = get()
    if (prev.isBuilding) {
      prev.abortController?.abort()
    }
    if (_timer) clearInterval(_timer)
    const runId = _nextRunId++

    set({
      isBuilding: true,
      novelId,
      novelTitle: title,
      phase: 'building',
      stepStatuses: initStatuses(),
      stepOutputs: [],
      currentStepKey: '',
      percent: 0,
      elapsed: 0,
      totalTokens: 0,
      errorMsg: '',
      abortController: null,
      runId,
    })

    _startTime = Date.now()
    _timer = setInterval(() => {
      if (get().runId === runId) {
        set({ elapsed: Math.floor((Date.now() - _startTime) / 1000) })
      }
    }, 1000)

    const onMessage = (msg: BuildSSEMessage) => {
      if (get().runId !== runId) return
      switch (msg.event) {
        case 'build_step': {
          const d = msg.data as BuildStepData
          set(s => ({
            stepStatuses: { ...s.stepStatuses, [d.key]: d.status },
            currentStepKey: d.status === 'running' ? d.key : s.currentStepKey,
            stepOutputs: d.status === 'running'
              ? [...s.stepOutputs, { key: d.key, text: '' }]
              : s.stepOutputs,
          }))
          break
        }
        case 'build_token': {
          set(s => {
            if (s.stepOutputs.length === 0) return s
            const updated = [...s.stepOutputs]
            const last = updated[updated.length - 1]
            updated[updated.length - 1] = { ...last, text: last.text + (msg.data as string) }
            return {
              stepOutputs: updated,
              totalTokens: s.totalTokens + (msg.data as string).length,
            }
          })
          break
        }
        case 'build_progress': {
          const d = msg.data as { percent: number }
          set({ percent: d.percent })
          break
        }
        case 'build_done':
          if (_timer) { clearInterval(_timer); _timer = null }
          if (get().runId !== runId) return
          set({ phase: 'done', isBuilding: false })
          toast.success(`《${get().novelTitle}》构建完成！`, { duration: 5000 })
          break
        case 'error':
          if (_timer) { clearInterval(_timer); _timer = null }
          if (get().runId !== runId) return
          set({ phase: 'error', isBuilding: false, errorMsg: msg.data as string })
          toast.error(`构建失败：${msg.data}`, { duration: 6000 })
          break
      }
    }

    const ctrl = novelsApi.streamBuild(novelId, nsfwMode ?? false, onMessage, () => {
      if (get().runId !== runId) return
      if (_timer) { clearInterval(_timer); _timer = null }
      const s = get()
      if (s.phase === 'building') {
        set({ isBuilding: false })
      }
    })
    set({ abortController: ctrl })
  },

  abortBuild: () => {
    if (_timer) { clearInterval(_timer); _timer = null }
    get().abortController?.abort()
    set({
      isBuilding: false,
      phase: 'idle',
      abortController: null,
      runId: get().runId + 1,
    })
  },

  reset: () => {
    if (_timer) { clearInterval(_timer); _timer = null }
    set({
      isBuilding: false,
      novelId: null,
      novelTitle: '',
      phase: 'idle',
      stepStatuses: initStatuses(),
      stepOutputs: [],
      currentStepKey: '',
      percent: 0,
      elapsed: 0,
      totalTokens: 0,
      errorMsg: '',
      abortController: null,
      runId: get().runId + 1,
    })
  },
}))
