import { useNavigate, useParams } from 'react-router-dom'
import { Loader2, Zap, X } from 'lucide-react'
import { useGenerationStore } from '@/store/generationStore'

/**
 * Floating pill shown in the bottom-right corner when a chapter is generating
 * in the background (i.e. the user has navigated away from the Editor).
 * Clicking it returns the user to the relevant novel editor.
 */
export default function GenerationIndicator() {
  const navigate = useNavigate()
  const params = useParams<{ id?: string }>()
  const { isGenerating, novelId, novelTitle, chapterNum, abortController } = useGenerationStore()

  if (!isGenerating || novelId === null) return null

  // Don't show the indicator when the user is already on that novel's editor page
  const currentNovelId = params.id ? Number(params.id) : null
  if (currentNovelId === novelId) return null

  const handleAbort = (e: React.MouseEvent) => {
    e.stopPropagation()
    abortController?.abort()
    useGenerationStore.getState().finishGeneration()
  }

  return (
    <div
      onClick={() => navigate(`/novel/${novelId}?chapter=${chapterNum}`)}
      className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 bg-primary text-primary-foreground px-4 py-2.5 rounded-full shadow-lg cursor-pointer hover:opacity-90 transition-opacity select-none"
      title="点击返回编辑器查看生成进度"
    >
      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
      <Zap className="w-3.5 h-3.5 shrink-0 opacity-80" />
      <span className="text-sm font-medium whitespace-nowrap">
        {novelTitle ? `《${novelTitle}》` : ''}第{chapterNum}章 生成中
      </span>
      <button
        onClick={handleAbort}
        className="ml-1 p-0.5 rounded-full hover:bg-primary-foreground/20 transition-colors"
        title="取消生成"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
