import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, List, Zap, Check, Edit3, Trash2,
  ChevronRight, ChevronLeft, Loader2, PanelRightOpen, PanelRightClose,
  Settings2, AlertTriangle, Radio, RadioTower, MessageSquare,
  Terminal, BookOpen, ClipboardCheck, Gauge, Search, GitCompare, ScrollText, Send,
  LayoutDashboard,
} from 'lucide-react'
import {
  novelsApi, chaptersApi, modelLibraryApi, charactersApi, worldEntitiesApi,
  locationsApi, factionsApi, techniquesApi, outlinesApi, findModelEntry,
  type Chapter, type ReviewResult,
} from '@/api/client'
import AgentLog from '@/components/AgentLog/AgentLog'
import ContextPanel from '@/components/ContextPanel/ContextPanel'
import NovelSettingsDrawer from '@/components/NovelSettingsDrawer/NovelSettingsDrawer'
import ChatPanel from '@/components/ChatPanel/ChatPanel'
import DevPanel from '@/components/DevPanel/DevPanel'
import ReviewModal from '@/components/ReviewModal/ReviewModal'
import OutlineModal from '@/components/OutlineModal/OutlineModal'
import CharacterCardModal from '@/components/CharacterCardModal/CharacterCardModal'
import { ThreadResolutionsModal } from '@/components/ThreadsModal/ThreadResolutionsModal'
import SubmissionModal from '@/components/SubmissionModal/SubmissionModal'
import { useSettingsStore } from '@/store/settingsStore'
import { useGenerationStore } from '@/store/generationStore'
import { useEditorStore } from '@/store/editorStore'
import { useGenerationStream } from './useGenerationStream'
import { useAutosave } from './useAutosave'
import EditorSidebar from './EditorSidebar'
import ChapterContentArea from './ChapterContentArea'
import GenerationBar, { type BarMode } from './GenerationBar'
import DiscoveryPanel from './DiscoveryPanel'
import ChapterDashboard from './ChapterDashboard'
import ThemePicker from '@/components/ThemePicker/ThemePicker'

export default function Editor() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { streamingMode, toggleStreamingMode } = useSettingsStore()
  const genStore = useGenerationStore()

  // ── Chapter Selection ────────────────────────────────────────────────────
  const setLastChapter = useEditorStore((s) => s.setLastChapter)
  // 初始章节优先级：URL ?chapter= > 上次浏览的章节（持久化）> 第 1 章。
  // 从大纲/数据等页面用裸 /novel/:id 返回（丢了 query）时，靠持久化恢复而非跳回第 1 章。
  const [selectedChapterNum, setSelectedChapterNum] = useState<number>(
    () => Number(searchParams.get('chapter')) || useEditorStore.getState().getLastChapter(novelId) || 1,
  )
  useEffect(() => {
    const chapterFromUrl = Number(searchParams.get('chapter'))
    if (chapterFromUrl && chapterFromUrl !== selectedChapterNum) {
      setSelectedChapterNum(chapterFromUrl)
    }
  }, [searchParams])
  // 将当前章节回写 URL + 持久化：离开编辑器再返回时恢复到原章节，而非默认跳回第 1 章
  // （避免误在第 1 章重新生成）。URL 用 replace 不污染浏览器历史；持久化兜底裸 URL 返回。
  useEffect(() => {
    setLastChapter(novelId, selectedChapterNum)
    if (Number(searchParams.get('chapter')) !== selectedChapterNum) {
      const next = new URLSearchParams(searchParams)
      next.set('chapter', String(selectedChapterNum))
      setSearchParams(next, { replace: true })
    }
  }, [selectedChapterNum])

  // ── Editor Mode ───────────────────────────────────────────────────────────
  const [editorMode, setEditorMode] = useState<'generate' | 'chat'>('generate')

  // ── Editor State ──────────────────────────────────────────────────────────
  const editorDraft = useEditorStore((s) => s.getDraft(novelId))
  const setInstruction = useEditorStore((s) => s.setInstruction)
  const setTargetWords = useEditorStore((s) => s.setTargetWords)
  const instruction = editorDraft.instruction
  const targetWords = editorDraft.targetWords
  const [barMode, setBarMode] = useState<BarMode>('write')
  const annotations = useEditorStore((s) => s.getAnnotations(novelId, selectedChapterNum))
  const addAnnotation = useEditorStore((s) => s.addAnnotation)
  const removeAnnotation = useEditorStore((s) => s.removeAnnotation)
  const clearAnnotations = useEditorStore((s) => s.clearAnnotations)

  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  // editContent 当前属于哪一章。切章时它会晚一帧才被覆盖，自动保存靠这个避免存错章。
  const [editContentChapterId, setEditContentChapterId] = useState<number | undefined>(undefined)
  const [showContext, setShowContext] = useState(true)
  // 本章仪表盘默认收起：它和上下文状态抢横向空间，别一进来就把正文挤窄
  const [showDashboard, setShowDashboard] = useState(
    () => localStorage.getItem('novel_show_dashboard') === '1',
  )
  useEffect(() => {
    localStorage.setItem('novel_show_dashboard', showDashboard ? '1' : '0')
  }, [showDashboard])
  const [dashboardWidth, setDashboardWidth] = useState(
    () => Number(localStorage.getItem('novel_dashboard_width')) || 340,
  )
  useEffect(() => {
    localStorage.setItem('novel_dashboard_width', String(dashboardWidth))
  }, [dashboardWidth])
  const dashDragRef = useRef({ startX: 0, startW: 0 })

  // 这一列在最右侧，把手在左边缘：鼠标往左拖是变宽，位移和 EditorSidebar 相反
  const handleDashboardResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dashDragRef.current = { startX: e.clientX, startW: e.currentTarget.parentElement!.offsetWidth }
    const onMove = (ev: MouseEvent) => {
      const { startX, startW } = dashDragRef.current
      setDashboardWidth(Math.max(240, Math.min(880, startW + startX - ev.clientX)))
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
  const [rightTab, setRightTab] = useState<'context' | 'agent'>('context')
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false)
  const [settingsDrawerTab, setSettingsDrawerTab] = useState<'content' | 'creation' | 'context'>('content')
  const [showDiff, setShowDiff] = useState(false)
  const [showTokens, setShowTokens] = useState(true)
  const [logCollapsed, setLogCollapsed] = useState(false)
  const [showDevPanel, setShowDevPanel] = useState(false)
  const [showReviewModal, setShowReviewModal] = useState(false)
  const [reviewResult, setReviewResult] = useState<ReviewResult | null>(null)
  const [showOutlineModal, setShowOutlineModal] = useState(false)
  const [showSubmissionModal, setShowSubmissionModal] = useState(false)
  const [confirmQueue, setConfirmQueue] = useState<number[]>([])
  const [confirmingId, setConfirmingId] = useState<number | null>(null)
  const confirmWorkerBusy = useRef(false)
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('novel_font_size') || 16))
  const [lineHeight, setLineHeight] = useState(() => Number(localStorage.getItem('novel_line_height') || 2.0))
  const [fontFamily, setFontFamily] = useState(() => localStorage.getItem('novel_font_family') || '')
  const [fontWeight, setFontWeight] = useState(() => localStorage.getItem('novel_font_weight') || '')
  const [fontColor, setFontColor] = useState(() => localStorage.getItem('novel_font_color') || '')
  const [rewriteModel, setRewriteModel] = useState('')
  const [pov, setPov] = useState('')

  // ── Novel Data ────────────────────────────────────────────────────────────
  const { data: novel } = useQuery({
    queryKey: ['novel', novelId],
    queryFn: () => novelsApi.get(novelId),
  })

  const { data: chapters = [], refetch: refetchChapters } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: () => modelLibraryApi.list(),
  })

  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })
  const { data: worldEntities = [] } = useQuery({
    queryKey: ['world-entities', novelId],
    queryFn: () => worldEntitiesApi.list(novelId),
  })
  const { data: locations = [] } = useQuery({
    queryKey: ['locations', novelId],
    queryFn: () => locationsApi.list(novelId),
  })
  const { data: factions = [] } = useQuery({
    queryKey: ['factions', novelId],
    queryFn: () => factionsApi.list(novelId),
  })
  const { data: techniques = [] } = useQuery({
    queryKey: ['techniques', novelId],
    queryFn: () => techniquesApi.list(novelId),
  })
  // 和 ChapterDashboard 共用同一个 query key，不会多发一次请求
  const { data: outlines = [] } = useQuery({
    queryKey: ['outlines', novelId],
    queryFn: () => outlinesApi.list(novelId),
  })

  const entityList = useMemo(() => {
    const items: Array<{ name: string; type: string; typeLabel: string; description: string }> = []
    for (const c of characters) items.push({ name: c.name, type: 'character', typeLabel: '角色', description: c.role || c.description || '' })
    for (const e of worldEntities) items.push({ name: e.name, type: 'entity', typeLabel: e.type === 'system' ? '系统' : '道具', description: e.description || '' })
    for (const l of locations) items.push({ name: l.name, type: 'location', typeLabel: '地点', description: l.description || '' })
    for (const f of factions) items.push({ name: f.name, type: 'faction', typeLabel: '势力', description: f.description || '' })
    for (const t of techniques) items.push({ name: t.name, type: 'technique', typeLabel: '功法', description: t.description || '' })
    return items
  }, [characters, worldEntities, locations, factions, techniques])

  // 只认单章细纲：范围大纲太粗，写这一章时等于没纲
  const hasChapterOutline = outlines.some(
    o => o.start_chapter === selectedChapterNum && o.end_chapter === selectedChapterNum,
  )
  const [draftingOutline, setDraftingOutline] = useState(false)
  const handleDraftOutline = useCallback(async () => {
    setDraftingOutline(true)
    try {
      await outlinesApi.draftChapter(novelId, selectedChapterNum)
      qc.invalidateQueries({ queryKey: ['outlines', novelId] })
      qc.invalidateQueries({ queryKey: ['outline-health', novelId] })
      toast.success(`第${selectedChapterNum}章细纲已生成，可在右侧「本章」里改`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '生成细纲失败')
    } finally {
      setDraftingOutline(false)
    }
  }, [novelId, selectedChapterNum, qc])

  const currentChapter = chapters.find((c: Chapter) => c.number === selectedChapterNum) || null
  // 新章节继承最新一章的卷号（chapters 按 number 升序）；novel.current_volume 可能停在过时值
  const selectedVolume = currentChapter?.volume ?? chapters[chapters.length - 1]?.volume ?? 1

  // Sync editContent when chapter changes
  useEffect(() => {
    if (currentChapter) {
      setEditContent(currentChapter.content)
      setEditContentChapterId(currentChapter.id)
    }
  }, [currentChapter?.id])

  // ── Generation Stream ─────────────────────────────────────────────────────
  const resetRewriteModel = useCallback(() => setRewriteModel(''), [])
  const gen = useGenerationStream(novelId, selectedChapterNum, selectedVolume, instruction, targetWords, novel?.title || '', rewriteModel, resetRewriteModel, pov)

  // Derived state after generation completes for this chapter
  const justFinishedHere =
    !genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum &&
    genStore.agentStage === 'done'

  const recentlyFinishedHere =
    !genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum &&
    genStore.streamingText.length > 0

  // ── Display Text ──────────────────────────────────────────────────────────
  const displayText = isEditing
    ? editContent
    : streamingMode && gen.isCurrentlyGenerating
      ? (genStore.streamingText || currentChapter?.content || '')
      : currentChapter
        ? currentChapter.content
        : (recentlyFinishedHere ? genStore.streamingText : '')

  const isStreaming = gen.isCurrentlyGenerating && streamingMode && genStore.streamingText.length > 0

  // ── Error / Warning ──────────────────────────────────────────────────────
  const errorMessage = (
    !genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum &&
    genStore.agentStage === 'error'
  ) ? genStore.errorMessage : ''

  const warningMessage = (
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum
  ) ? genStore.warningMessage : ''

  // ── Agent Log ─────────────────────────────────────────────────────────────
  const hasGenDataHere =
    genStore.agentLogEntries.length > 0 &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum
  const agentLogEntries = hasGenDataHere ? genStore.agentLogEntries : []
  const totalInputTokens = hasGenDataHere ? genStore.totalInputTokens : 0
  const totalOutputTokens = hasGenDataHere ? genStore.totalOutputTokens : 0
  const canShowReviewDiff =
    hasGenDataHere &&
    !gen.isCurrentlyGenerating &&
    !!genStore.originalDraft &&
    !!displayText

  useEffect(() => {
    if (agentLogEntries.length > 0 && gen.isCurrentlyGenerating) {
      setRightTab('agent')
    }
  }, [agentLogEntries.length > 0 && gen.isCurrentlyGenerating])

  // ── Handlers ──────────────────────────────────────────────────────────────
  const handleConfirm = useCallback(() => {
    if (!currentChapter) return
    const id = currentChapter.id
    setConfirmQueue(prev => (prev.includes(id) ? prev : [...prev, id]))
  }, [currentChapter])

  // 按章号从小到大依次确认排队中的章节（单 worker，保证累积状态顺序正确）
  useEffect(() => {
    if (confirmWorkerBusy.current || confirmingId !== null || confirmQueue.length === 0) return
    const numById = new Map(chapters.map(c => [c.id, c.number]))
    const nextId = [...confirmQueue].sort((a, b) => (numById.get(a) ?? 0) - (numById.get(b) ?? 0))[0]
    const chapterNum = numById.get(nextId) ?? 0
    confirmWorkerBusy.current = true
    setConfirmingId(nextId)
    ;(async () => {
      try {
        const result = await chaptersApi.confirm(nextId)
        refetchChapters()
        qc.invalidateQueries({ queryKey: ['characters', novelId] })
        if (result.book_summary_refreshed) {
          qc.invalidateQueries({ queryKey: ['novel', novelId] })
          toast.success(`第${chapterNum}章已确认，摘要和角色状态已更新，全书概要已自动刷新`)
        } else {
          toast.success(`第${chapterNum}章已确认，摘要和角色状态已更新`)
        }
        // 状态没能回滚（后面还有已确认章节、缺快照、更新失败）时要让作者知道，
        // 否则他以为改完正文状态就跟着干净了
        if (result.char_warning) {
          toast(result.char_warning, { duration: 8000, icon: '⚠' })
        }
      } catch {
        toast.error(`第${chapterNum}章确认失败`)
      } finally {
        setConfirmQueue(prev => prev.filter(x => x !== nextId))
        setConfirmingId(null)
        confirmWorkerBusy.current = false
      }
    })()
  }, [confirmQueue, confirmingId, chapters, novelId, qc, refetchChapters])

  const handleDelete = useCallback(async () => {
    if (!currentChapter) return
    if (!window.confirm(`确认删除第 ${currentChapter.number} 章？此操作不可撤销。`)) return
    try {
      await chaptersApi.delete(currentChapter.id)
      const remaining = chapters.filter((c: Chapter) => c.id !== currentChapter.id)
      if (remaining.length > 0) {
        const prev = [...remaining].reverse().find((c: Chapter) => c.number < currentChapter.number)
        const next = remaining.find((c: Chapter) => c.number > currentChapter.number)
        setSelectedChapterNum((prev || next)!.number)
      } else {
        setSelectedChapterNum(1)
      }
      refetchChapters()
    } catch {
      toast.error('删除章节失败')
    }
  }, [currentChapter, chapters, refetchChapters])

  // 自动保存会带着自己的快照调用（可能是上一章的 id），所以内容和 id 都由参数传入，
  // 不从闭包读 currentChapter/editContent。
  const persistChapter = useCallback(async (chapterId: number, content: string) => {
    const updated = await chaptersApi.update(chapterId, { content })
    qc.setQueryData<Chapter[]>(['chapters', novelId], (old = []) =>
      old.map(ch => ch.id === updated.id ? updated : ch),
    )
  }, [novelId, qc])

  const autosave = useAutosave({
    // 生成中一律停掉自动保存：生成结束会把新正文写进 currentChapter，此时若还在编辑态，
    // 自动保存会拿编辑框里的旧正文盖掉刚生成的内容。
    enabled: isEditing && !gen.isCurrentlyGenerating,
    chapterId: currentChapter?.id,
    contentChapterId: editContentChapterId,
    content: editContent,
    baseline: currentChapter?.content,
    onSave: persistChapter,
  })

  const handleSaveEdit = useCallback(async () => {
    if (!currentChapter) return
    try {
      await persistChapter(currentChapter.id, editContent)
      await refetchChapters()
      setIsEditing(false)
    } catch {
      toast.error('保存章节失败')
    }
  }, [currentChapter, editContent, persistChapter, refetchChapters])

  // Ctrl+S 是写作时的肌肉记忆，不接的话浏览器会弹「保存网页」
  useEffect(() => {
    if (!isEditing) return
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault()
        void handleSaveEdit()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isEditing, handleSaveEdit])

  const handleNewChapter = useCallback(() => {
    setSelectedChapterNum(
      chapters.length > 0 ? Math.max(...chapters.map((c: Chapter) => c.number)) + 1 : 1,
    )
  }, [chapters])

  const handleWriterModelChange = useCallback(async (modelId: string) => {
    try {
      await novelsApi.update(novelId, { writer_model: modelId })
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
      const model = findModelEntry(modelLibrary, modelId)
      const modelName = model?.display_name || model?.model_id || modelId
      toast.success(modelId ? `Writer 模型已切换为 ${modelName}` : 'Writer 模型已恢复全局默认')
    } catch {
      toast.error('切换模型失败')
    }
  }, [modelLibrary, novelId, qc])

  const handleToggleCritic = useCallback(async () => {
    const next = !novel?.enable_critic
    try {
      await novelsApi.update(novelId, { enable_critic: next })
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
      toast.success(next ? 'Critic 审查已开启' : 'Critic 审查已关闭')
    } catch {
      toast.error('切换 Critic 审查失败')
    }
  }, [novelId, novel?.enable_critic, qc])

  const handleToggleDetailReview = useCallback(async () => {
    const next = !novel?.enable_detail_review
    try {
      await novelsApi.update(novelId, { enable_detail_review: next })
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
      toast.success(next ? '细节审查已开启' : '细节审查已关闭')
    } catch {
      toast.error('切换细节审查失败')
    }
  }, [novelId, novel?.enable_detail_review, qc])

  const handleQuickParamsChange = useCallback(async (patch: Partial<{
    writer_temperature: number
    writer_use_custom_temperature: boolean
    gemini_thinking_level: string
    deepseek_thinking_level: string
  }>) => {
    // 乐观更新，避免拖动温度滑块时因请求往返而卡顿
    qc.setQueryData<typeof novel>(['novel', novelId], (old) => old ? { ...old, ...patch } : old)
    try {
      await novelsApi.update(novelId, patch)
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
    } catch {
      toast.error('保存生成参数失败')
      qc.invalidateQueries({ queryKey: ['novel', novelId] })
    }
  }, [novelId, qc])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <header className="border-b px-4 py-3 flex items-center gap-3 shrink-0">
        <button onClick={() => navigate('/novels')} className="p-1.5 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-semibold text-sm truncate max-w-48">{novel?.title}</h1>
        <button onClick={() => navigate('/rules')}
          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors"
          title="规则广场">
          <ScrollText className="w-3.5 h-3.5" /> 规则广场
        </button>
        <div className="flex items-center gap-1 ml-auto">
          {novel && !novel.core_setting && (
            <span className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50 px-2 py-1 rounded-md border border-amber-200 dark:border-amber-800 mr-1">
              <AlertTriangle className="w-3 h-3" />
              未设置世界观
            </span>
          )}
          <button onClick={() => navigate(`/novel/${novelId}/outline`)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 transition-colors">
            <List className="w-3.5 h-3.5" /> 总览
          </button>
          <button onClick={() => navigate(`/novel/${novelId}/data`)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md text-teal-600 dark:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-900/30 transition-colors">
            <Terminal className="w-3.5 h-3.5" /> 数据
          </button>
          <button onClick={() => setShowOutlineModal(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 transition-colors">
            <BookOpen className="w-3.5 h-3.5" /> 大纲
          </button>
          <button onClick={() => setShowReviewModal(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/30 transition-colors">
            <ClipboardCheck className="w-3.5 h-3.5" /> 审查
          </button>
          <button onClick={() => setShowSubmissionModal(true)}
            title="书名简介、导出稿件、过审预检"
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-900/30 transition-colors">
            <Send className="w-3.5 h-3.5" /> 投稿
          </button>
          <div className="w-px h-4 bg-border mx-0.5" />
          <button onClick={() => { setSettingsDrawerTab('context'); setShowSettingsDrawer(true) }}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground">
            <Gauge className="w-3.5 h-3.5" /> Token
          </button>
          <button
            onClick={() => { setSettingsDrawerTab('content'); setShowSettingsDrawer(true) }}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors text-muted-foreground"
          >
            <Settings2 className="w-3.5 h-3.5" /> 设置
          </button>
          <button
            onClick={() => setShowDevPanel(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors ${showDevPanel ? 'text-primary bg-primary/10' : 'text-muted-foreground'}`}
            title="开发者视图"
          >
            <Terminal className="w-3.5 h-3.5" /> Dev
          </button>
          <button
            onClick={toggleStreamingMode}
            className={`p-1.5 rounded-md hover:bg-muted transition-colors ${streamingMode ? 'text-primary' : 'text-muted-foreground'}`}
            title={streamingMode ? '流式显示已开启（点击关闭）' : '流式显示已关闭（点击开启）'}
          >
            {streamingMode ? <RadioTower className="w-4 h-4" /> : <Radio className="w-4 h-4" />}
          </button>
          <button
            onClick={() => setShowDashboard(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors ${showDashboard ? 'text-primary bg-primary/10' : 'text-muted-foreground'}`}
            title="本章仪表盘"
          >
            <LayoutDashboard className="w-3.5 h-3.5" /> 本章
          </button>
          <ThemePicker size="sm" />
          <button onClick={() => setShowContext(!showContext)}
            className="p-1.5 rounded-md hover:bg-muted transition-colors">
            {showContext ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <EditorSidebar
          novelId={novelId}
          novel={novel}
          chapters={chapters}
          selectedChapterNum={selectedChapterNum}
          isGenerating={genStore.isGenerating}
          generatingNovelId={genStore.novelId}
          generatingChapterNum={genStore.chapterNum}
          onSelectChapter={setSelectedChapterNum}
          onNewChapter={handleNewChapter}
          onOpenSettings={() => setShowSettingsDrawer(true)}
        />

        {/* Main Editor */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Toolbar */}
          <div className="border-b px-4 py-2.5 flex items-center gap-3 shrink-0">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <ChevronLeft
                className="w-4 h-4 cursor-pointer hover:text-foreground"
                onClick={() => setSelectedChapterNum(Math.max(1, selectedChapterNum - 1))}
              />
              <span className="font-medium text-foreground">第{selectedChapterNum}章</span>
              <ChevronRight
                className="w-4 h-4 cursor-pointer hover:text-foreground"
                onClick={() => setSelectedChapterNum(selectedChapterNum + 1)}
              />
            </div>

            {currentChapter?.word_count ? (
              <span className="text-xs text-muted-foreground">{currentChapter.word_count}字</span>
            ) : null}
            {currentChapter?.model_used ? (
              <span className="text-xs text-muted-foreground" title="本章生成模型">· {currentChapter.model_used}</span>
            ) : null}

            <div className="flex items-center gap-1.5 ml-auto">
              <select
                value={fontSize}
                onChange={e => { const v = Number(e.target.value); setFontSize(v); localStorage.setItem('novel_font_size', String(v)) }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                title="字体大小"
              >
                <option value={12}>12px</option>
                <option value={13}>13px</option>
                <option value={14}>14px</option>
                <option value={15}>15px</option>
                <option value={16}>16px</option>
                <option value={17}>17px</option>
                <option value={18}>18px</option>
                <option value={19}>19px</option>
                <option value={20}>20px</option>
                <option value={22}>22px</option>
                <option value={24}>24px</option>
                <option value={26}>26px</option>
                <option value={28}>28px</option>
                <option value={32}>32px</option>
              </select>
              <select
                value={lineHeight}
                onChange={e => { const v = Number(e.target.value); setLineHeight(v); localStorage.setItem('novel_line_height', String(v)) }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                title="行间距"
              >
                <option value={1.2}>1.2&#215;</option>
                <option value={1.5}>1.5&#215;</option>
                <option value={1.8}>1.8&#215;</option>
                <option value={2.0}>2.0&#215;</option>
                <option value={2.5}>2.5&#215;</option>
                <option value={3.0}>3.0&#215;</option>
              </select>
              <select
                value={fontFamily}
                onChange={e => { setFontFamily(e.target.value); localStorage.setItem('novel_font_family', e.target.value) }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring max-w-[90px]"
                title="字体"
              >
                <option value="">默认</option>
                <option value="SimSun, serif">宋体</option>
                <option value="KaiTi, serif">楷体</option>
                <option value="FangSong, serif">仿宋</option>
                <option value="Microsoft YaHei, sans-serif">微软雅黑</option>
                <option value="SimHei, sans-serif">黑体</option>
                <option value="Source Han Serif SC, serif">思源宋体</option>
                <option value="Noto Sans SC, sans-serif">Noto Sans</option>
              </select>
              <select
                value={fontWeight}
                onChange={e => { setFontWeight(e.target.value); if (e.target.value) localStorage.setItem('novel_font_weight', e.target.value); else localStorage.removeItem('novel_font_weight') }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                title="字体粗细"
              >
                <option value="">常规</option>
                <option value="300">细体</option>
                <option value="500">中等</option>
                <option value="600">半粗</option>
                <option value="700">加粗</option>
              </select>
              <div className="flex items-center gap-0.5" title="字体颜色">
                <input
                  type="color"
                  value={fontColor || '#000000'}
                  onChange={e => { setFontColor(e.target.value); localStorage.setItem('novel_font_color', e.target.value) }}
                  className="w-6 h-6 border rounded cursor-pointer bg-transparent p-0"
                />
                {fontColor && (
                  <button
                    onClick={() => { setFontColor(''); localStorage.removeItem('novel_font_color') }}
                    className="text-[0.625rem] text-muted-foreground hover:text-foreground px-0.5"
                    title="重置为默认颜色"
                  >
                    ×
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                {currentChapter && !gen.isCurrentlyGenerating && (
                  <button
                    onClick={handleDelete}
                    className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md text-destructive hover:bg-destructive/10 transition-colors"
                    title="删除本章"
                  >
                    <Trash2 className="w-3 h-3" /> 删除
                  </button>
                )}
                {canShowReviewDiff && (
                  <button
                    onClick={() => setShowDiff(true)}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md transition-colors ${
                      showDiff ? 'bg-primary/10 text-primary border-primary/40' : 'hover:bg-muted'
                    }`}
                    title="查看修订前后的剧情对比"
                  >
                    <GitCompare className="w-3 h-3" /> 修订对比
                  </button>
                )}
                {currentChapter?.content && !gen.isCurrentlyGenerating && (
                  <>
                    {!isEditing ? (
                      <button onClick={() => { setIsEditing(true); setEditContent(currentChapter.content); setEditContentChapterId(currentChapter.id) }}
                        className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors">
                        <Edit3 className="w-3 h-3" /> 手动编辑
                      </button>
                    ) : (
                      <>
                        <span className="text-xs text-muted-foreground px-1" title="编辑会在停手 2 秒后自动保存，切换章节也会先保存">
                          {autosave.state === 'saving' ? '保存中…'
                            : autosave.state === 'error' ? <span className="text-destructive">自动保存失败</span>
                            : autosave.state === 'dirty' ? '未保存'
                            : autosave.state === 'saved' ? '已自动保存' : '自动保存已开'}
                        </span>
                        <button onClick={handleSaveEdit}
                          title="保存并退出编辑（Ctrl+S）"
                          className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors">
                          <Check className="w-3 h-3" /> 保存编辑
                        </button>
                      </>
                    )}
                    <button onClick={handleConfirm}
                      disabled={confirmQueue.includes(currentChapter.id)}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                      {confirmQueue.includes(currentChapter.id) ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      {confirmingId === currentChapter.id ? '确认中...' : confirmQueue.includes(currentChapter.id) ? '排队中...' : currentChapter.status === 'confirmed' ? '重新确认' : '确认章节'}
                    </button>
                    <button
                      onClick={() => currentChapter?.id && gen.handleDiscover(currentChapter.id)}
                      disabled={gen.isDiscovering}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {gen.isDiscovering ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                      {gen.isDiscovering ? '发现中...' : '重新发现'}
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* Mode Tabs */}
          <div className="border-b px-4 flex items-center gap-1 shrink-0">
            <button
              onClick={() => setEditorMode('generate')}
              className={`flex items-center gap-1.5 text-xs px-3 py-2 border-b-2 transition-colors ${
                editorMode === 'generate'
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Zap className="w-3.5 h-3.5" /> 生成
            </button>
            <button
              onClick={() => setEditorMode('chat')}
              className={`flex items-center gap-1.5 text-xs px-3 py-2 border-b-2 transition-colors ${
                editorMode === 'chat'
                  ? 'border-primary text-primary font-medium'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" /> 对话
            </button>
          </div>

          {/* Chat Mode */}
          {editorMode === 'chat' && novel && (
            <div className="flex-1 overflow-hidden">
              <ChatPanel novelId={novelId} novel={novel} chapterNumber={selectedChapterNum} />
            </div>
          )}

          {/* Generate Mode */}
          {editorMode === 'generate' && <>
            {/* Content Area */}
            <ChapterContentArea
              displayText={displayText}
              isEditing={isEditing}
              editContent={editContent}
              warningMessage={warningMessage}
              errorMessage={errorMessage}
              isCurrentlyGenerating={gen.isCurrentlyGenerating}
              isStreaming={isStreaming}
              streamingMode={streamingMode}
              showDiff={showDiff}
              originalDraft={genStore.originalDraft}
              currentChapter={currentChapter}
              fontSize={fontSize}
              lineHeight={lineHeight}
              fontFamily={fontFamily}
              fontWeight={fontWeight}
              fontColor={fontColor}

              instruction={instruction}
              onEditContentChange={setEditContent}
              onCloseDiff={() => setShowDiff(false)}
              rewriteMode={barMode === 'rewrite'}
              onAddParagraphAnnotation={(paragraph) => {
                const text = prompt(`段落${paragraph}的批注内容：`)
                if (text?.trim()) {
                  addAnnotation(novelId, selectedChapterNum, {
                    id: `${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
                    paragraph,
                    text: text.trim(),
                  })
                }
              }}
            />

            {/* Generation Controls */}
            <GenerationBar
              barMode={barMode}
              onBarModeChange={setBarMode}
              hasChapterContent={!!currentChapter?.content}
              agentStage={hasGenDataHere ? genStore.agentStage : ''}
              isCurrentlyGenerating={gen.isCurrentlyGenerating}
              isOtherGenerating={genStore.isGenerating && !gen.isCurrentlyGenerating}
              justFinishedHere={justFinishedHere}
              instruction={instruction}
              targetWords={targetWords}
              onInstructionChange={(v) => setInstruction(novelId, v)}
              onTargetWordsChange={(v) => setTargetWords(novelId, v)}
              pov={pov}
              onPovChange={setPov}
              povOptions={characters.map((c) => c.name)}
              onGenerate={gen.handleGenerate}
              onAbortOrGenerate={barMode === 'rewrite' ? gen.handleRewriteOrAbort : gen.handleAbortOrGenerate}
              hasChapterOutline={hasChapterOutline}
              draftingOutline={draftingOutline}
              onDraftOutline={handleDraftOutline}
              annotations={annotations}
              onRemoveAnnotation={(id) => removeAnnotation(novelId, selectedChapterNum, id)}
              onClearAnnotations={() => clearAnnotations(novelId, selectedChapterNum)}
              onAddGlobalAnnotation={(text) => addAnnotation(novelId, selectedChapterNum, {
                id: `${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
                text,
              })}
              onRewrite={gen.handleRewrite}
              rewriteModel={rewriteModel}
              onRewriteModelChange={setRewriteModel}
              writerModel={novel?.writer_model || ''}
              onWriterModelChange={handleWriterModelChange}
              modelLibrary={modelLibrary}
              enableCritic={novel?.enable_critic ?? true}
              enableDetailReview={novel?.enable_detail_review ?? false}
              onToggleCritic={handleToggleCritic}
              onToggleDetailReview={handleToggleDetailReview}
              writerTemperature={novel?.writer_temperature ?? 0.85}
              writerUseCustomTemperature={novel?.writer_use_custom_temperature ?? true}
              geminiThinkingLevel={novel?.gemini_thinking_level || 'medium'}
              deepseekThinkingLevel={novel?.deepseek_thinking_level || 'high'}
              onQuickParamsChange={handleQuickParamsChange}
              entities={entityList}
            />
          </>}
        </div>

        {/* 本章仪表盘：写这一章时要盯的东西，排在上下文状态左边 */}
        {showDashboard && (
          <div className="relative border-l flex flex-col shrink-0" style={{ width: dashboardWidth }}>
            <div
              onMouseDown={handleDashboardResize}
              className="absolute top-0 left-0 w-1.5 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors z-10"
            />
            <div className="px-3 py-2 border-b shrink-0 text-xs font-medium">本章仪表盘</div>
            <div className="p-2 flex-1 overflow-auto">
              <ChapterDashboard
                novelId={novelId}
                chapterNum={selectedChapterNum}
                displayText={displayText}
                targetWords={targetWords}
              />
            </div>
          </div>
        )}

        {/* Right Sidebar: top half = Context + Agent Log tabs, bottom half = entity discovery */}
        {showContext && (
          <div className="w-72 border-l flex flex-col shrink-0">
            <div className="basis-1/2 min-h-0 flex flex-col">
              <div className="flex border-b shrink-0">
                <button
                  onClick={() => setRightTab('context')}
                  className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                    rightTab === 'context' ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  上下文状态
                </button>
                <button
                  onClick={() => setRightTab('agent')}
                  className={`flex-1 px-3 py-2 text-xs font-medium transition-colors ${
                    rightTab === 'agent' ? 'text-foreground border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  Agent 日志{agentLogEntries.length > 0 ? ` (${agentLogEntries.length})` : ''}
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                {rightTab === 'context' ? (
                  <div className="p-3 h-full overflow-auto">
                    <ContextPanel novelId={novelId} rollingStage={hasGenDataHere ? genStore.agentStage : ''} contextSteps={hasGenDataHere ? genStore.contextSteps : []} />
                  </div>
                ) : (
                  <div className="p-3 h-full overflow-auto">
                    <AgentLog
                      entries={agentLogEntries}
                      totalInputTokens={totalInputTokens}
                      totalOutputTokens={totalOutputTokens}
                      showTokens={showTokens}
                      onToggleTokens={() => setShowTokens(v => !v)}
                      canShowReviewDiff={canShowReviewDiff}
                      onShowReviewDiff={() => setShowDiff(true)}
                      collapsed={logCollapsed}
                      onToggleCollapse={() => setLogCollapsed(v => !v)}
                    />
                  </div>
                )}
              </div>
            </div>
            <div className="basis-1/2 min-h-0 border-t flex flex-col">
              <div className="px-3 py-2 border-b shrink-0 text-xs font-medium">
                待确认发现
                {(() => {
                  const total = gen.newCharCandidates.length + gen.newEntityCandidates.length + gen.newLocationCandidates.length + gen.newTechCandidates.length + gen.newFactionCandidates.length + gen.newThreads.length
                  return total > 0 ? ` (${total})` : ''
                })()}
              </div>
              <div className="p-3 flex-1 overflow-auto">
                <DiscoveryPanel
                  newCharCandidates={gen.newCharCandidates}
                  selectedCharIndices={gen.selectedCharIndices}
                  addingChars={gen.addingChars}
                  onToggleChar={gen.toggleCharSelection}
                  onAddChars={gen.handleAddNewChars}
                  onDismissChars={() => gen.setNewCharCandidates([])}
                  newEntityCandidates={gen.newEntityCandidates}
                  selectedEntityIndices={gen.selectedEntityIndices}
                  addingEntities={gen.addingEntities}
                  onToggleEntity={gen.toggleEntitySelection}
                  onAddEntities={gen.handleAddNewEntities}
                  onDismissEntities={() => gen.setNewEntityCandidates([])}
                  newLocationCandidates={gen.newLocationCandidates}
                  selectedLocationIndices={gen.selectedLocationIndices}
                  addingLocations={gen.addingLocations}
                  onToggleLocation={gen.toggleLocationSelection}
                  onAddLocations={gen.handleAddNewLocations}
                  onDismissLocations={() => gen.setNewLocationCandidates([])}
                  newTechCandidates={gen.newTechCandidates}
                  selectedTechIndices={gen.selectedTechIndices}
                  addingTechs={gen.addingTechs}
                  onToggleTech={gen.toggleTechSelection}
                  onAddTechs={gen.handleAddNewTechs}
                  onDismissTechs={() => gen.setNewTechCandidates([])}
                  newFactionCandidates={gen.newFactionCandidates}
                  selectedFactionIndices={gen.selectedFactionIndices}
                  addingFactions={gen.addingFactions}
                  onToggleFaction={gen.toggleFactionSelection}
                  onAddFactions={gen.handleAddNewFactions}
                  onDismissFactions={() => gen.setNewFactionCandidates([])}
                  newThreads={gen.newThreads}
                  selectedThreadIndices={gen.selectedThreadIndices}
                  addingThreads={gen.addingThreads}
                  onToggleThread={gen.toggleThreadSelection}
                  onAddThreads={gen.handleAddNewThreads}
                  onDismissThreads={() => gen.setNewThreads([])}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Novel Settings Drawer */}
      {showSettingsDrawer && novel && (
        <NovelSettingsDrawer
          novel={novel}
          initialTab={settingsDrawerTab}
          onClose={() => setShowSettingsDrawer(false)}
        />
      )}

      {/* Developer View Panel */}
      {showDevPanel && (
        <DevPanel onClose={() => setShowDevPanel(false)} />
      )}

      {/* Review Modal */}
      {showReviewModal && (
        <ReviewModal
          novelId={novelId}
          result={reviewResult}
          onResult={setReviewResult}
          onClose={() => setShowReviewModal(false)}
        />
      )}

      {/* Outline Modal */}
      {showOutlineModal && (
        <OutlineModal
          novelId={novelId}
          currentChapter={selectedChapterNum}
          onClose={() => setShowOutlineModal(false)}
        />
      )}

      {/* Submission Modal：书名简介 / 导出 / 过审预检 */}
      {showSubmissionModal && novel && (
        <SubmissionModal novel={novel} onClose={() => setShowSubmissionModal(false)} />
      )}

      {/* Character Card Review Modal (after confirming discovered characters) */}
      {gen.reviewCharacters.length > 0 && (
        <CharacterCardModal
          key={gen.reviewCharacters[gen.reviewCharacters.length - 1].id}
          character={gen.reviewCharacters[gen.reviewCharacters.length - 1]}
          onClose={() => {
            const remaining = gen.reviewCharacters.slice(0, -1)
            gen.setReviewCharacters(remaining)
            if (remaining.length === 0) {
              qc.invalidateQueries({ queryKey: ['characters', novelId] })
            }
          }}
          onUpdated={(updated) => {
            gen.setReviewCharacters(prev =>
              prev.map(c => c.id === updated.id ? updated : c)
            )
            qc.invalidateQueries({ queryKey: ['characters', novelId] })
          }}
          onDeleted={(charId) => {
            gen.setReviewCharacters(prev => prev.filter(c => c.id !== charId))
            qc.invalidateQueries({ queryKey: ['characters', novelId] })
          }}
        />
      )}

      {/* 本章检测到的伏笔回收/秘密公开候选（需确认更新） */}
      {gen.threadResolutions.length > 0 && (
        <ThreadResolutionsModal
          novelId={novelId}
          resolutions={gen.threadResolutions}
          currentChapter={selectedChapterNum}
          onClose={() => gen.setThreadResolutions([])}
        />
      )}

    </div>
  )
}
