import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Plus, Settings, Trash2, ChevronRight, Sun, Moon } from 'lucide-react'
import { novelsApi, type Novel } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'
import NovelWizard from './NovelWizard'

export default function Home() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [wizardOpen, setWizardOpen] = useState(false)
  const { theme, toggleTheme } = useSettingsStore()

  const { data: novels = [], isLoading } = useQuery({
    queryKey: ['novels'],
    queryFn: novelsApi.list,
  })

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除这本小说？此操作不可撤销。')) return
    await novelsApi.delete(id)
    qc.invalidateQueries({ queryKey: ['novels'] })
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="w-6 h-6 text-primary" />
          <h1 className="text-xl font-bold">NovelBot</h1>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md hover:bg-muted transition-colors"
            title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button
            onClick={() => navigate('/settings')}
            className="p-2 rounded-md hover:bg-muted transition-colors"
          >
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-10">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-2xl font-bold">我的小说</h2>
            <p className="text-muted-foreground mt-1">AI 驱动的小说创作工具</p>
          </div>
          <button
            onClick={() => setWizardOpen(true)}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:opacity-90 transition-opacity font-medium"
          >
            <Plus className="w-4 h-4" />
            新建小说
          </button>
        </div>

        {isLoading ? (
          <div className="text-center py-20 text-muted-foreground">加载中...</div>
        ) : novels.length === 0 ? (
          <div className="text-center py-20">
            <BookOpen className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-30" />
            <p className="text-muted-foreground text-lg">还没有小说</p>
            <p className="text-muted-foreground text-sm mt-1">点击「新建小说」开始创作</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {novels.map((novel: Novel) => (
              <div
                key={novel.id}
                onClick={() => navigate(`/novel/${novel.id}`)}
                className="group p-5 border rounded-xl hover:border-primary hover:shadow-sm transition-all cursor-pointer bg-card"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-lg truncate">{novel.title}</h3>
                      <span className="text-xs px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground shrink-0">
                        {novel.genre || '未分类'}
                      </span>
                    </div>
                    <p className="text-muted-foreground text-sm line-clamp-2">{novel.premise}</p>
                    <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
                      <span>第{novel.current_chapter}章</span>
                      <span>{novel.target_length}</span>
                      <span>{novel.writing_style}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 ml-4 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => handleDelete(e, novel.id)}
                      className="p-2 rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-4 h-4 text-muted-foreground" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {wizardOpen && (
        <NovelWizard
          onClose={() => setWizardOpen(false)}
          onComplete={(id) => {
            setWizardOpen(false)
            qc.invalidateQueries({ queryKey: ['novels'] })
            navigate(`/novel/${id}`)
          }}
        />
      )}
    </div>
  )
}
