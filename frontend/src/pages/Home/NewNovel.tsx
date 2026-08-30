import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { novelsApi, type BrainstormExtract } from '@/api/client'
import { useBuildStore } from '@/store/buildStore'
import { useSettingsStore } from '@/store/settingsStore'
import { useBrainstormStore } from '@/store/brainstormStore'
import NovelWizard from './NovelWizard'
import BrainstormPanel from './BrainstormPanel'
import type { FormSnapshot } from './ApplyExtractModal'

const MIN_FORM_WIDTH = 380
const MAX_FORM_WIDTH = 900

export default function NewNovel() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const snapshotRef = useRef<FormSnapshot>({ title: '', genre: '', writing_style: '', premise: '', plot_design: '', core_setting: '', world_rules_seed: '', ending: '', protagonist_arc: '' })
  const applyRef = useRef<((picked: Partial<BrainstormExtract>) => void) | null>(null)
  const getFormSnapshot = useCallback(() => snapshotRef.current, [])
  const handleApply = useCallback((picked: Partial<BrainstormExtract>) => {
    applyRef.current?.(picked)
  }, [])

  const [formWidth, setFormWidth] = useState(
    () => Number(localStorage.getItem('new_novel_form_width')) || 640,
  )
  useEffect(() => {
    localStorage.setItem('new_novel_form_width', String(formWidth))
  }, [formWidth])
  const dragRef = useRef({ startX: 0, startW: 0 })

  // 把手在左栏右边缘：鼠标往右拖是变宽
  const handleResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragRef.current = { startX: e.clientX, startW: e.currentTarget.parentElement!.offsetWidth }
    const onMove = (ev: MouseEvent) => {
      const { startX, startW } = dragRef.current
      setFormWidth(Math.max(MIN_FORM_WIDTH, Math.min(MAX_FORM_WIDTH, startW + ev.clientX - startX)))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [])

  return (
    <div className="h-screen flex flex-col bg-background">
      <header className="border-b px-5 py-3 flex items-center gap-3 shrink-0">
        <button
          onClick={() => navigate('/novels')}
          className="p-2 rounded-md hover:bg-muted transition-colors"
          title="返回小说列表"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="min-w-0">
          <h1 className="font-semibold truncate">开一本新书</h1>
          <p className="text-xs text-muted-foreground">左边填参数，右边和 AI 聊清楚要写什么</p>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div
          className="relative border-r shrink-0 flex flex-col min-w-0"
          style={{ width: formWidth }}
        >
          <NovelWizard
            snapshotRef={snapshotRef}
            applyRef={applyRef}
            onCancel={() => navigate('/novels')}
            onComplete={(id) => {
              qc.invalidateQueries({ queryKey: ['novels'] })
              useBrainstormStore.getState().reset()
              navigate(`/novel/${id}`)
            }}
            onBuild={async (id) => {
              qc.invalidateQueries({ queryKey: ['novels'] })
              useBrainstormStore.getState().reset()
              const novel = await novelsApi.get(id)
              useBuildStore.getState().startBuild(id, novel.title, useSettingsStore.getState().nsfwMode)
              navigate(`/novel/${id}/build`)
            }}
          />
          <div
            onMouseDown={handleResize}
            className="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-primary/30 transition-colors"
          />
        </div>

        <div className="flex-1 min-w-0">
          <BrainstormPanel getFormSnapshot={getFormSnapshot} onApply={handleApply} />
        </div>
      </div>
    </div>
  )
}
