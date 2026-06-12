import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { Loader2, Hammer, X } from 'lucide-react'
import { useBuildStore } from '@/store/buildStore'

export default function BuildIndicator() {
  const navigate = useNavigate()
  const location = useLocation()
  const params = useParams<{ id?: string }>()
  const { isBuilding, novelId, novelTitle, percent } = useBuildStore()

  if (!isBuilding || novelId === null) return null

  const onBuildPage = location.pathname === `/novel/${novelId}/build`
  if (onBuildPage) return null

  const handleAbort = (e: React.MouseEvent) => {
    e.stopPropagation()
    useBuildStore.getState().abortBuild()
  }

  return (
    <div
      onClick={() => navigate(`/novel/${novelId}/build`)}
      className="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 bg-primary text-primary-foreground px-4 py-2.5 rounded-full shadow-lg cursor-pointer hover:opacity-90 transition-opacity select-none"
      title="点击查看构建详情"
    >
      <Loader2 className="w-4 h-4 animate-spin shrink-0" />
      <Hammer className="w-3.5 h-3.5 shrink-0 opacity-80" />
      <span className="text-sm font-medium whitespace-nowrap">
        {novelTitle ? `《${novelTitle}》` : ''}构建中 {percent}%
      </span>
      <button
        onClick={handleAbort}
        className="ml-1 p-0.5 rounded-full hover:bg-primary-foreground/20 transition-colors"
        title="取消构建"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
