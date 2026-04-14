import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Sun, Moon } from 'lucide-react'
import { novelsApi, chaptersApi } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

export default function Outline() {
  const { id } = useParams<{ id: string }>()
  const novelId = Number(id)
  const navigate = useNavigate()

  const { theme, toggleTheme } = useSettingsStore()
  const { data: novel } = useQuery({ queryKey: ['novel', novelId], queryFn: () => novelsApi.get(novelId) })
  const { data: chapters = [] } = useQuery({ queryKey: ['chapters', novelId], queryFn: () => chaptersApi.list(novelId) })

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/novel/' + novelId)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">{novel?.title} · 大纲</h1>
        <button
          onClick={toggleTheme}
          className="ml-auto p-2 rounded-md hover:bg-muted transition-colors"
          title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </header>
      <main className="max-w-3xl mx-auto px-6 py-8">
        <div className="space-y-2">
          {chapters.map((chapter) => (
            <div key={chapter.id} className="border rounded-lg p-4 hover:border-primary/50 transition-colors">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs text-muted-foreground font-mono">第{chapter.number}章</span>
                    <span className={chapter.status === 'confirmed' ? 'text-xs px-1.5 py-0.5 rounded-full bg-green-100 text-green-700' : 'text-xs px-1.5 py-0.5 rounded-full bg-yellow-100 text-yellow-700'}>
                      {chapter.status === 'confirmed' ? '已确认' : '草稿'}
                    </span>
                    <span className="text-xs text-muted-foreground">{chapter.word_count}字</span>
                  </div>
                  <p className="font-medium text-sm">{chapter.title}</p>
                  {chapter.summary && <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{chapter.summary}</p>}
                </div>
                <button onClick={() => navigate('/novel/' + novelId + '?chapter=' + chapter.number)}
                  className="text-xs text-primary hover:underline shrink-0">
                  编辑
                </button>
              </div>
            </div>
          ))}
          {chapters.length === 0 && (
            <div className="text-center py-20 text-muted-foreground">
              <p>大纲将在生成章节后自动填充</p>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}