import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { BookOpen, Plus, Settings, Trash2, ChevronRight, PenTool, Edit3, Info, Eye, EyeOff, Copy, LogOut, ArrowLeft } from 'lucide-react'
import { novelsApi, writerPresetsApi, authApi, type Novel, type WriterPreset, type ExampleTurn } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import SpotlightCard, { LIST_CARD, LIST_CARD_BAR, LIST_CARD_HIT } from '@/components/SpotlightCard/SpotlightCard'
import { useSettingsStore } from '@/store/settingsStore'
import { useAuthStore } from '@/store/authStore'
import PresetModal from './PresetModal'
import NovelPreviewModal from './NovelPreviewModal'
import MemoBoard from '@/components/MemoBoard/MemoBoard'

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
  const [activeTab, setActiveTab] = useState<Tab>('novels')
  const [presetModal, setPresetModal] = useState<{ open: boolean; preset: WriterPreset | null }>({ open: false, preset: null })
  const [copyModal, setCopyModal] = useState<{ open: boolean; novel: Novel | null }>({ open: false, novel: null })
  const [previewNovel, setPreviewNovel] = useState<Novel | null>(null)
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

  const authUser = useAuthStore((s) => s.user)
  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {}
    useAuthStore.getState().clear()
    navigate('/login', { replace: true })
  }, [navigate])

  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
  // 隐藏名单存在服务端（users 表）。localStorage 按源隔离，
  // 从 localhost:5173 和 127.0.0.1:8000 打开会各存一份，换入口就"忘了"
  const hiddenNovelIds = authUser?.hidden_novel_ids ?? []
  const hiddenPresetIds = authUser?.hidden_preset_ids ?? []
  const persistHidden = useMutation({
    mutationFn: (data: { hidden_novel_ids?: number[]; hidden_preset_ids?: number[] }) =>
      authApi.updateMe(data),
    onSuccess: (user) => useAuthStore.getState().setUser(user),
    onError: () => toast.error('保存隐藏状态失败'),
  })
  const toggleNovelHidden = useCallback((id: number) => {
    const cur = useAuthStore.getState().user?.hidden_novel_ids ?? []
    persistHidden.mutate({
      hidden_novel_ids: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    })
  }, [persistHidden])
  const togglePresetHidden = useCallback((id: number) => {
    const cur = useAuthStore.getState().user?.hidden_preset_ids ?? []
    persistHidden.mutate({
      hidden_preset_ids: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    })
  }, [persistHidden])
  const [showHidden, setShowHidden] = useState(false)
  const greeting = useMemo(() => getGreeting(), [])

  // 一次性搬迁：把旧版存在 localStorage 的隐藏名单并进服务端，然后清掉本地副本。
  // 只在当前源确实有残留时才发请求，所以每个源最多跑一次。
  const migratedRef = useRef(false)
  useEffect(() => {
    if (migratedRef.current || !authUser) return
    const { hiddenNovelIds: oldNovels, hiddenPresetIds: oldPresets } = useSettingsStore.getState()
    if (oldNovels.length === 0 && oldPresets.length === 0) return
    migratedRef.current = true
    authApi
      .updateMe({
        hidden_novel_ids: [...new Set([...(authUser.hidden_novel_ids ?? []), ...oldNovels])],
        hidden_preset_ids: [...new Set([...(authUser.hidden_preset_ids ?? []), ...oldPresets])],
      })
      .then((user) => {
        useAuthStore.getState().setUser(user)
        useSettingsStore.getState().clearLegacyHidden()
      })
      .catch(() => { migratedRef.current = false })
  }, [authUser])

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
        const cnt = (useAuthStore.getState().user?.hidden_novel_ids ?? []).length
        if (cnt > 0) toast(next ? `已显示 ${cnt} 本隐藏小说` : '已隐藏', { icon: next ? '👁️' : '🙈', duration: 1500 })
        return next
      })
    }
  }, [])

  const visibleNovels = showHidden ? novels : novels.filter((n) => !hiddenNovelIds.includes(n.id))
  const visiblePresets = showHidden ? presets : presets.filter((p) => !hiddenPresetIds.includes(p.id))

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

  return (
    <div className="min-h-screen bg-background relative">
      <div aria-hidden className="page-glow" />
      {/* Header */}
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-4 sm:px-6 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {/* 单独的返回按钮：logo 自己带三击彩蛋，不能兼作导航 */}
          <button
            onClick={() => navigate('/')}
            className="p-2 rounded-full hover:bg-muted transition-colors"
            title="返回模式选择"
            aria-label="返回模式选择"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-2.5 cursor-pointer select-none" onClick={handleLogoClick}>
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <BookOpen className="w-4 h-4" />
            </span>
            <h1 className="text-lg font-bold">小说</h1>
          </div>
        </div>
        <div className="flex items-center gap-0.5 sm:gap-1">
          {authUser && (
            <button
              onClick={() => navigate('/account')}
              className="mr-1 flex items-center gap-2 rounded-full py-1 pl-1 pr-1 sm:pr-3 text-sm text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground transition-colors"
              title="用户设置"
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-primary/15 text-xs font-semibold uppercase text-primary">
                {authUser.username.slice(0, 1)}
              </span>
              <span className="hidden max-w-[8rem] truncate sm:inline">{authUser.username}</span>
            </button>
          )}
          <ThemePicker />
          <button
            onClick={() => navigate('/about')}
            className="p-2 rounded-full hover:bg-muted transition-colors"
            title="架构说明"
            aria-label="架构说明"
          >
            <Info className="w-4 h-4" />
          </button>
          <button
            onClick={() => navigate('/settings')}
            className="p-2 rounded-full hover:bg-muted transition-colors"
            title="设置"
            aria-label="设置"
          >
            <Settings className="w-[18px] h-[18px]" />
          </button>
          <button
            onClick={handleLogout}
            className="p-2 rounded-full hover:bg-muted transition-colors"
            title="登出"
            aria-label="登出"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="relative z-10 max-w-4xl mx-auto px-5 sm:px-6 pt-12 pb-16 sm:pt-16">
        {/* Greeting + Stats */}
        <div className="reveal mb-10">
          <p className="mb-3 text-xs font-medium tracking-[0.2em] text-primary">NOVEL</p>
          <h2 className="font-display text-4xl sm:text-5xl font-bold leading-tight tracking-tight">
            {nsfwMode ? '欢迎回来，造物主' : `${greeting}，创作者`}
          </h2>
          <p className="mt-3 text-sm sm:text-base text-muted-foreground">
            {nsfwMode ? '尽情释放你的创作欲望' : '接着写，或者开一本新的。'}
          </p>
          {dashboard && (
            <dl className="mt-8 grid grid-cols-3 overflow-hidden rounded-2xl border border-foreground/10 bg-card shadow-sm">
              {[
                { value: dashboard.total_novels, unit: '本小说', onClick: handleCountClick },
                { value: formatWordCount(dashboard.total_words), unit: '字' },
                { value: dashboard.total_entities, unit: '个设定' },
              ].map((s, i) => (
                <div
                  key={s.unit}
                  onClick={s.onClick}
                  className={`flex flex-col-reverse px-4 py-4 sm:px-6 sm:py-5 select-none ${i > 0 ? 'border-l border-foreground/[0.08]' : ''} ${s.onClick ? 'cursor-pointer' : ''}`}
                >
                  <dt className="mt-1 text-xs sm:text-sm text-muted-foreground">{s.unit}</dt>
                  <dd className="font-display text-2xl sm:text-3xl font-bold tabular-nums text-foreground">{s.value}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>

        <div className="mb-10">
          <MemoBoard scope="novel" />
        </div>

        {/* Tab header */}
        <div className="reveal flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6" style={{ '--i': 2 } as React.CSSProperties}>
          <div className="min-w-0">
            <div role="tablist" aria-label="列表切换" className="inline-flex items-center gap-1 rounded-full border border-foreground/10 bg-card p-1 shadow-sm">
              <button
                role="tab"
                aria-selected={activeTab === 'novels'}
                onClick={() => setActiveTab('novels')}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${activeTab === 'novels' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05]'}`}
              >
                <span className="flex items-center gap-1.5"><BookOpen className="w-4 h-4" />我的小说</span>
              </button>
              <button
                role="tab"
                aria-selected={activeTab === 'presets'}
                onClick={() => setActiveTab('presets')}
                className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${activeTab === 'presets' ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05]'}`}
              >
                <span className="flex items-center gap-1.5"><PenTool className="w-4 h-4" />写手预设</span>
              </button>
            </div>
            <p className="text-sm text-muted-foreground mt-2.5 pl-1">
              {activeTab === 'novels'
                ? (nsfwMode ? '无限制的成人内容创作平台' : 'AI 驱动的小说创作工具')
                : '管理可复用的 Writer 系统提示词'}
            </p>
          </div>
          {activeTab === 'novels' ? (
            <button
              onClick={() => navigate('/novel/new')}
              className="self-start sm:self-auto flex items-center gap-1.5 text-sm bg-primary text-primary-foreground px-5 py-2.5 rounded-full hover:opacity-95 font-medium shrink-0"
            >
              <Plus className="w-4 h-4" />
              新建小说
            </button>
          ) : (
            <button
              onClick={() => setPresetModal({ open: true, preset: null })}
              className="self-start sm:self-auto flex items-center gap-1.5 text-sm bg-primary text-primary-foreground px-5 py-2.5 rounded-full hover:opacity-95 font-medium shrink-0"
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
                    className={`${LIST_CARD} cursor-pointer`}
                    spotlightColor="hsl(var(--primary) / 0.09)"
                  >
                    <span aria-hidden className={LIST_CARD_BAR} />
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => setPreviewNovel(novel)}
                      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPreviewNovel(novel) } }}
                      className={`relative group p-5 sm:p-6 rounded-2xl ${LIST_CARD_HIT} ${isHidden ? 'opacity-50' : ''}`}
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1.5">
                            <h3 className="font-display text-xl font-bold truncate">{novel.title}</h3>
                            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                              {novel.genre || '未分类'}
                            </span>
                            {isHidden && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0 flex items-center gap-1">
                                <EyeOff className="w-3 h-3" />已隐藏
                              </span>
                            )}
                          </div>
                          <p className="text-muted-foreground text-sm line-clamp-2">{novel.premise}</p>
                          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-4 text-xs text-muted-foreground tabular-nums">
                            <span>共{dashboard?.novel_chapters[novel.id] ?? 0}章</span>
                            {dashboard?.novel_words[novel.id] != null && (
                              <span>{formatWordCount(dashboard.novel_words[novel.id])}字</span>
                            )}
                            <span>{novel.target_length}</span>
                            <span>{novel.writing_style}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-0.5 -ml-2 sm:ml-4 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
                          <button
                            onClick={(e) => { e.stopPropagation(); toggleNovelHidden(novel.id) }}
                            className="p-2 rounded-full hover:bg-muted transition-colors"
                            title={isHidden ? '取消隐藏' : '隐藏此小说'}
                          >
                            {isHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setCopyModal({ open: true, novel }) }}
                            className="p-2 rounded-full hover:bg-muted transition-colors"
                            title="复制小说"
                          >
                            <Copy className="w-4 h-4" />
                          </button>
                          <button
                            onClick={(e) => handleDelete(e, novel.id)}
                            className="p-2 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors"
                            title="删除"
                            aria-label="删除"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); navigate(`/novel/${novel.id}`) }}
                            className="p-2 rounded-full hover:bg-muted transition-colors"
                            title="进入创作"
                          >
                            <PenTool className="w-4 h-4" />
                          </button>
                          <ChevronRight className="w-4 h-4 text-muted-foreground transition-transform duration-300 group-hover:translate-x-0.5" />
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
                {visiblePresets.map((preset: WriterPreset) => {
                  const isHidden = hiddenPresetIds.includes(preset.id)
                  return (
                  <SpotlightCard
                    key={preset.id}
                    className={`${LIST_CARD} cursor-pointer`}
                    spotlightColor="hsl(var(--primary) / 0.09)"
                  >
                    <span aria-hidden className={LIST_CARD_BAR} />
                    <div
                      role="button"
                      tabIndex={0}
                      onClick={() => setPresetModal({ open: true, preset })}
                      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setPresetModal({ open: true, preset }) } }}
                      className={`relative group p-5 sm:p-6 rounded-2xl ${LIST_CARD_HIT} ${isHidden ? 'opacity-50' : ''}`}
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1.5">
                            <h3 className="font-display text-xl font-bold truncate">{preset.name}</h3>
                            {isHidden && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground shrink-0 flex items-center gap-1">
                                <EyeOff className="w-3 h-3" />已隐藏
                              </span>
                            )}
                          </div>
                          <p className="text-muted-foreground text-sm line-clamp-3 whitespace-pre-wrap">
                            {preset.prompt || '(空提示词)'}
                          </p>
                        </div>
                        <div className="flex items-center gap-0.5 -ml-2 sm:ml-4 transition-opacity [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100 [@media(hover:hover)]:group-focus-within:opacity-100">
                          <button
                            onClick={(e) => { e.stopPropagation(); togglePresetHidden(preset.id) }}
                            className="p-2 rounded-full hover:bg-muted transition-colors"
                            title={isHidden ? '取消隐藏' : '隐藏此预设'}
                          >
                            {isHidden ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setPresetModal({ open: true, preset }) }}
                            className="p-2 rounded-full hover:bg-muted transition-colors"
                            title="编辑预设"
                            aria-label="编辑预设"
                          >
                            <Edit3 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={(e) => handleDeletePreset(e, preset.id)}
                            className="p-2 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors"
                            title="删除"
                            aria-label="删除"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
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
      </main>

      {previewNovel && (
        <NovelPreviewModal
          novel={previewNovel}
          onClose={() => setPreviewNovel(null)}
          onEnter={() => navigate(`/novel/${previewNovel.id}`)}
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
