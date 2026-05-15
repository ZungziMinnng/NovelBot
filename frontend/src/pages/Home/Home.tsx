import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { BookOpen, Plus, Settings, Trash2, ChevronRight, PenTool, Edit3, Info } from 'lucide-react'
import { novelsApi, writerPresetsApi, type Novel, type WriterPreset } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import NovelWizard from './NovelWizard'
import PresetModal from './PresetModal'

function getGreeting(): string {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

function formatWordCount(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万`
  return String(n)
}

type Tab = 'novels' | 'presets'

export default function Home() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [wizardOpen, setWizardOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('novels')
  const [presetModal, setPresetModal] = useState<{ open: boolean; preset: WriterPreset | null }>({ open: false, preset: null })
  const { data: novels = [], isLoading } = useQuery({
    queryKey: ['novels'],
    queryFn: novelsApi.list,
  })

  const { data: presets = [], isLoading: presetsLoading } = useQuery({
    queryKey: ['writer-presets'],
    queryFn: writerPresetsApi.list,
  })

  const { data: dashboard } = useQuery({
    queryKey: ['dashboard'],
    queryFn: novelsApi.dashboard,
  })

  const greeting = useMemo(() => getGreeting(), [])

  const savePreset = useMutation({
    mutationFn: (data: { id?: number; name: string; prompt: string }) =>
      data.id ? writerPresetsApi.update(data.id, { name: data.name, prompt: data.prompt }) : writerPresetsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['writer-presets'] })
      setPresetModal({ open: false, preset: null })
    },
  })

  const deletePreset = useMutation({
    mutationFn: writerPresetsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['writer-presets'] }),
  })

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除这本小说？此操作不可撤销。')) return
    try {
      await novelsApi.delete(id)
      qc.invalidateQueries({ queryKey: ['novels'] })
    } catch {
      toast.error('删除小说失败')
    }
  }

  const handleDeletePreset = (e: React.MouseEvent, id: number) => {
    e.stopPropagation()
    if (!confirm('确认删除此预设？')) return
    deletePreset.mutate(id)
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
          <ThemePicker />
          <button
            onClick={() => navigate('/about')}
            className="p-2 rounded-md hover:bg-muted transition-colors"
            title="架构说明"
          >
            <Info className="w-4 h-4" />
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
        {/* Greeting + Stats */}
        {dashboard && (
          <div className="mb-8 p-6 rounded-xl bg-gradient-to-r from-primary/5 to-primary/10 border">
            <h2 className="text-xl font-bold mb-3">{greeting}，创作者</h2>
            <div className="flex flex-wrap gap-6 text-sm">
              <div>
                <span className="text-2xl font-bold text-primary">{dashboard.total_novels}</span>
                <span className="text-muted-foreground ml-1.5">本小说</span>
              </div>
              <div>
                <span className="text-2xl font-bold text-primary">{formatWordCount(dashboard.total_words)}</span>
                <span className="text-muted-foreground ml-1.5">字</span>
              </div>
              <div>
                <span className="text-2xl font-bold text-primary">{dashboard.total_entities}</span>
                <span className="text-muted-foreground ml-1.5">个设定</span>
              </div>
            </div>
          </div>
        )}

        {/* Tab header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="flex items-center gap-1 mb-2">
              <button
                onClick={() => setActiveTab('novels')}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeTab === 'novels' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
              >
                <span className="flex items-center gap-1.5"><BookOpen className="w-4 h-4" />我的小说</span>
              </button>
              <button
                onClick={() => setActiveTab('presets')}
                className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${activeTab === 'presets' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}
              >
                <span className="flex items-center gap-1.5"><PenTool className="w-4 h-4" />写手预设</span>
              </button>
            </div>
            <p className="text-muted-foreground mt-1">
              {activeTab === 'novels' ? 'AI 驱动的小说创作工具' : '管理可复用的 Writer 系统提示词'}
            </p>
          </div>
          {activeTab === 'novels' ? (
            <button
              onClick={() => setWizardOpen(true)}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:opacity-90 transition-opacity font-medium"
            >
              <Plus className="w-4 h-4" />
              新建小说
            </button>
          ) : (
            <button
              onClick={() => setPresetModal({ open: true, preset: null })}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:opacity-90 transition-opacity font-medium"
            >
              <Plus className="w-4 h-4" />
              新建预设
            </button>
          )}
        </div>

        {/* Novels tab */}
        {activeTab === 'novels' && (
          <>
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
                          {dashboard?.novel_words[novel.id] != null && (
                            <span>{formatWordCount(dashboard.novel_words[novel.id])}字</span>
                          )}
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
          </>
        )}

        {/* Presets tab */}
        {activeTab === 'presets' && (
          <>
            {presetsLoading ? (
              <div className="text-center py-20 text-muted-foreground">加载中...</div>
            ) : presets.length === 0 ? (
              <div className="text-center py-20">
                <PenTool className="w-16 h-16 text-muted-foreground mx-auto mb-4 opacity-30" />
                <p className="text-muted-foreground text-lg">还没有预设</p>
                <p className="text-muted-foreground text-sm mt-1">点击「新建预设」创建 Writer 提示词模板</p>
              </div>
            ) : (
              <div className="grid gap-4">
                {presets.map((preset: WriterPreset) => (
                  <div
                    key={preset.id}
                    onClick={() => setPresetModal({ open: true, preset })}
                    className="group p-5 border rounded-xl hover:border-primary hover:shadow-sm transition-all cursor-pointer bg-card"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <h3 className="font-semibold text-lg truncate mb-1">{preset.name}</h3>
                        <p className="text-muted-foreground text-sm line-clamp-3 whitespace-pre-wrap">
                          {preset.prompt || '(空提示词)'}
                        </p>
                      </div>
                      <div className="flex items-center gap-1 ml-4 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => { e.stopPropagation(); setPresetModal({ open: true, preset }) }}
                          className="p-2 rounded-md hover:bg-muted transition-colors"
                        >
                          <Edit3 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={(e) => handleDeletePreset(e, preset.id)}
                          className="p-2 rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
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
          onBuild={(id) => {
            setWizardOpen(false)
            qc.invalidateQueries({ queryKey: ['novels'] })
            navigate(`/novel/${id}/build`)
          }}
        />
      )}

      {presetModal.open && (
        <PresetModal
          preset={presetModal.preset}
          onClose={() => setPresetModal({ open: false, preset: null })}
          onSave={(data) => savePreset.mutate({ id: presetModal.preset?.id, ...data })}
        />
      )}
    </div>
  )
}
