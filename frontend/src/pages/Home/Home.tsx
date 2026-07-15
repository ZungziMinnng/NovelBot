import { useState, useMemo, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { BookOpen, Plus, Settings, Trash2, ChevronRight, PenTool, Edit3, Info, Eye, EyeOff, Copy } from 'lucide-react'
import { novelsApi, writerPresetsApi, type Novel, type WriterPreset, type ExampleTurn } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import SpotlightCard from '@/components/SpotlightCard/SpotlightCard'
import { useBuildStore } from '@/store/buildStore'
import { useSettingsStore } from '@/store/settingsStore'
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
  const [copyModal, setCopyModal] = useState<{ open: boolean; novel: Novel | null }>({ open: false, novel: null })
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

  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
  const hiddenNovelIds = useSettingsStore((s) => s.hiddenNovelIds)
  const toggleNovelHidden = useSettingsStore((s) => s.toggleNovelHidden)
  const [showHidden, setShowHidden] = useState(false)
  const greeting = useMemo(() => getGreeting(), [])

  // 三击「x 本小说」数字：切换隐藏小说的显隐（复用 logo 三击彩蛋模式）
  const countClickRef = useRef<number[]>([])
  const handleCountClick = useCallback(() => {
    const now = Date.now()
    const arr = countClickRef.current
    arr.push(now)
    if (arr.length > 3) arr.shift()
    if (arr.length === 3 && now - arr[0] < 800) {
      countClickRef.current = []
      setShowHidden((v) => {
        const next = !v
        const cnt = useSettingsStore.getState().hiddenNovelIds.length
        if (cnt > 0) toast(next ? `已显示 ${cnt} 本隐藏小说` : '已隐藏', { icon: next ? '👁️' : '🙈', duration: 1500 })
        return next
      })
    }
  }, [])

  const visibleNovels = showHidden ? novels : novels.filter((n) => !hiddenNovelIds.includes(n.id))

  const clickTimesRef = useRef<number[]>([])
  const handleLogoClick = useCallback(() => {
    const now = Date.now()
    clickTimesRef.current.push(now)
    if (clickTimesRef.current.length > 3) clickTimesRef.current.shift()
    if (clickTimesRef.current.length === 3 && now - clickTimesRef.current[0] < 600) {
      clickTimesRef.current = []
      useSettingsStore.getState().toggleNsfwMode()
      const enabled = useSettingsStore.getState().nsfwMode
      toast(enabled ? '已开启创作自由模式' : '已关闭创作自由模式', { icon: enabled ? '🔓' : '🔒', duration: 2000 })
    }
  }, [])

  const savePreset = useMutation({
    mutationFn: (data: { id?: number; name: string; prompt: string; examples: ExampleTurn[] }) =>
      data.id
        ? writerPresetsApi.update(data.id, { name: data.name, prompt: data.prompt, examples: data.examples })
        : writerPresetsApi.create({ name: data.name, prompt: data.prompt, examples: data.examples }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['writer-presets'] })
      setPresetModal({ open: false, preset: null })
    },
  })

  const deletePreset = useMutation({
    mutationFn: writerPresetsApi.delete,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['writer-presets'] }),
  })

  const duplicateNovel = useMutation({
    mutationFn: ({ id, mode }: { id: number; mode: 'full' | 'settings' }) => novelsApi.duplicate(id, mode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['novels'] })
      qc.invalidateQueries({ queryKey: ['dashboard'] })
      setCopyModal({ open: false, novel: null })
      toast.success('已复制小说')
    },
    onError: () => toast.error('复制失败'),
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

  const silkColor = useMemo(() => {
    if (nsfwMode) return '#4A1942'
    const root = document.documentElement
    const style = getComputedStyle(root)
    const h = style.getPropertyValue('--primary').trim().split(' ')[0] || '220'
    const hue = parseFloat(h)
    const r = Math.round(128 + 40 * Math.cos((hue * Math.PI) / 180))
    const g = Math.round(128 + 40 * Math.cos(((hue - 120) * Math.PI) / 180))
    const b = Math.round(128 + 40 * Math.cos(((hue - 240) * Math.PI) / 180))
    return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
  }, [nsfwMode])

  return (
    <div className="min-h-screen bg-background relative">
      {/* Silk Background */}
      <div className="fixed inset-0 z-0 opacity-20 pointer-events-none">
        <Silk speed={3} scale={1} color={silkColor} noiseIntensity={1.2} rotation={0} className="w-full h-full" />
      </div>

      {/* Header */}
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2 cursor-pointer select-none" onClick={handleLogoClick}>
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

      <main className="relative z-10 max-w-4xl mx-auto px-6 py-10">
        {/* Greeting + Stats */}
        {dashboard && (
          <div className={`mb-8 p-6 rounded-xl border bg-gradient-to-r ${nsfwMode ? 'from-purple-500/10 to-pink-500/10' : 'from-primary/5 to-primary/10'}`}>
            <h2 className="text-xl font-bold mb-1">{nsfwMode ? '欢迎回来，造物主' : `${greeting}，创作者`}</h2>
            {nsfwMode && <p className="text-sm text-muted-foreground mb-3">尽情释放你的创作欲望</p>}
            {!nsfwMode && <div className="mb-3" />}
            <div className="flex flex-wrap gap-6 text-sm">
              <div onClick={handleCountClick} className="cursor-pointer select-none" title="">
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
              {activeTab === 'novels'
                ? (nsfwMode ? '无限制的成人内容创作平台' : 'AI 驱动的小说创作工具')
                : '管理可复用的 Writer 系统提示词'}
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
                {visibleNovels.map((novel: Novel) => {
                  const isHidden = hiddenNovelIds.includes(novel.id)
                  return (
                  <SpotlightCard
                    key={novel.id}
                    className="rounded-xl border border-border/60 bg-card/80 backdrop-blur-sm cursor-pointer"
                    spotlightColor={nsfwMode ? 'rgba(192, 38, 211, 0.08)' : 'rgba(255, 255, 255, 0.06)'}
                  >
                    <div
                      onClick={() => navigate(`/novel/${novel.id}`)}
                      className={`group p-5 ${isHidden ? 'opacity-50' : ''}`}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <h3 className="font-semibold text-lg truncate">{novel.title}</h3>
                            <span className="text-xs px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground shrink-0">
                              {novel.genre || '未分类'}
                            </span>
                            {isHidden && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0 flex items-center gap-1">
                                <EyeOff className="w-3 h-3" />已隐藏
                              </span>
                            )}
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
                            onClick={(e) => { e.stopPropagation(); toggleNovelHidden(novel.id) }}
                            className="p-2 rounded-md hover:bg-muted transition-colors"
                            title={isHidden ? '取消隐藏' : '隐藏此小说'}
                          >
                            {isHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setCopyModal({ open: true, novel }) }}
                            className="p-2 rounded-md hover:bg-muted transition-colors"
                            title="复制小说"
                          >
                            <Copy className="w-4 h-4" />
                          </button>
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
                  </SpotlightCard>
                  )
                })}
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
                  <SpotlightCard
                    key={preset.id}
                    className="rounded-xl border border-border/60 bg-card/80 backdrop-blur-sm cursor-pointer"
                    spotlightColor={nsfwMode ? 'rgba(192, 38, 211, 0.08)' : 'rgba(255, 255, 255, 0.06)'}
                  >
                    <div
                      onClick={() => setPresetModal({ open: true, preset })}
                      className="group p-5"
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
                  </SpotlightCard>
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
          onBuild={async (id) => {
            setWizardOpen(false)
            qc.invalidateQueries({ queryKey: ['novels'] })
            const novel = await novelsApi.get(id)
            useBuildStore.getState().startBuild(id, novel.title, useSettingsStore.getState().nsfwMode)
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

      {copyModal.open && copyModal.novel && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center"
          onClick={() => !duplicateNovel.isPending && setCopyModal({ open: false, novel: null })}
        >
          <div className="bg-background rounded-xl p-5 w-96 space-y-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
            <div>
              <h3 className="font-medium">复制《{copyModal.novel.title}》</h3>
              <p className="text-sm text-muted-foreground mt-1">选择复制范围</p>
            </div>
            <div className="grid gap-2">
              <button
                disabled={duplicateNovel.isPending}
                onClick={() => duplicateNovel.mutate({ id: copyModal.novel!.id, mode: 'full' })}
                className="text-left px-4 py-3 rounded-lg border hover:border-primary hover:bg-muted transition-colors disabled:opacity-50"
              >
                <div className="font-medium text-sm">全部</div>
                <div className="text-xs text-muted-foreground mt-0.5">含设定、角色、章节正文与记忆</div>
              </button>
              <button
                disabled={duplicateNovel.isPending}
                onClick={() => duplicateNovel.mutate({ id: copyModal.novel!.id, mode: 'settings' })}
                className="text-left px-4 py-3 rounded-lg border hover:border-primary hover:bg-muted transition-colors disabled:opacity-50"
              >
                <div className="font-medium text-sm">仅设定</div>
                <div className="text-xs text-muted-foreground mt-0.5">含世界观、角色、大纲等设定，不含章节正文，写作进度归零</div>
              </button>
            </div>
            <div className="flex justify-end">
              <button
                disabled={duplicateNovel.isPending}
                onClick={() => setCopyModal({ open: false, novel: null })}
                className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted disabled:opacity-50"
              >
                {duplicateNovel.isPending ? '复制中...' : '取消'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
