import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, List, Zap, Check, Edit3, Trash2,
  ChevronRight, ChevronLeft, Loader2, PanelRightOpen, PanelRightClose,
  Settings2, AlertTriangle, Radio, RadioTower, MessageSquare,
  Terminal, BookOpen, ClipboardCheck, Gauge, Search, GitCompare,
} from 'lucide-react'
import {
  novelsApi, chaptersApi, modelLibraryApi, charactersApi, worldEntitiesApi,
  locationsApi, factionsApi, techniquesApi,
  type Chapter, type ReviewResult,
} from '@/api/client'
import AgentLog from '@/components/AgentLog/AgentLog'
import ContextPanel from '@/components/ContextPanel/ContextPanel'
import NovelSettingsDrawer from '@/components/NovelSettingsDrawer/NovelSettingsDrawer'
import ChatPanel from '@/components/ChatPanel/ChatPanel'
import DevPanel from '@/components/DevPanel/DevPanel'
import ReviewModal from '@/components/ReviewModal/ReviewModal'
import OutlineModal from '@/components/OutlineModal/OutlineModal'
import { useSettingsStore } from '@/store/settingsStore'
import { useGenerationStore } from '@/store/generationStore'
import { useEditorStore } from '@/store/editorStore'
import { useGenerationStream } from './useGenerationStream'
import EditorSidebar from './EditorSidebar'
import ChapterContentArea from './ChapterContentArea'
import GenerationBar, { type BarMode } from './GenerationBar'
import ThemePicker from '@/components/ThemePicker/ThemePicker'

export default function Editor() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { streamingMode, toggleStreamingMode } = useSettingsStore()
  const genStore = useGenerationStore()

  // ── Chapter Selection ────────────────────────────────────────────────────
  const [selectedChapterNum, setSelectedChapterNum] = useState<number>(
    Number(searchParams.get('chapter')) || 1,
  )
  useEffect(() => {
    const chapterFromUrl = Number(searchParams.get('chapter'))
    if (chapterFromUrl && chapterFromUrl !== selectedChapterNum) {
      setSelectedChapterNum(chapterFromUrl)
    }
  }, [searchParams])

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
  const [showContext, setShowContext] = useState(true)
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
  const [isConfirming, setIsConfirming] = useState(false)
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('novel_font_size') || 16))
  const [lineHeight, setLineHeight] = useState(() => Number(localStorage.getItem('novel_line_height') || 2.0))
  const [fontFamily, setFontFamily] = useState(() => localStorage.getItem('novel_font_family') || '')
  const [fontWeight, setFontWeight] = useState(() => localStorage.getItem('novel_font_weight') || '')
  const [fontColor, setFontColor] = useState(() => localStorage.getItem('novel_font_color') || '')
  const [rewriteModel, setRewriteModel] = useState('')

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

  const entityList = useMemo(() => {
    const items: Array<{ name: string; type: string; typeLabel: string; description: string }> = []
    for (const c of characters) items.push({ name: c.name, type: 'character', typeLabel: '角色', description: c.role || c.description || '' })
    for (const e of worldEntities) items.push({ name: e.name, type: 'entity', typeLabel: e.type === 'system' ? '系统' : '道具', description: e.description || '' })
    for (const l of locations) items.push({ name: l.name, type: 'location', typeLabel: '地点', description: l.description || '' })
    for (const f of factions) items.push({ name: f.name, type: 'faction', typeLabel: '势力', description: f.description || '' })
    for (const t of techniques) items.push({ name: t.name, type: 'technique', typeLabel: '功法', description: t.description || '' })
    return items
  }, [characters, worldEntities, locations, factions, techniques])

  const currentChapter = chapters.find((c: Chapter) => c.number === selectedChapterNum) || null
  const selectedVolume = currentChapter?.volume ?? novel?.current_volume ?? 1

  // Sync editContent when chapter changes
  useEffect(() => {
    if (currentChapter) setEditContent(currentChapter.content)
  }, [currentChapter?.id])

  // ── Generation Stream ─────────────────────────────────────────────────────
  const resetRewriteModel = useCallback(() => setRewriteModel(''), [])
  const gen = useGenerationStream(novelId, selectedChapterNum, selectedVolume, instruction, targetWords, novel?.title || '', rewriteModel, resetRewriteModel)

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
  const handleConfirm = useCallback(async () => {
    if (!currentChapter || isConfirming) return
    setIsConfirming(true)
    try {
      const result = await chaptersApi.confirm(currentChapter.id)
      refetchChapters()
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      if (result.book_summary_refreshed) {
        qc.invalidateQueries({ queryKey: ['novel', novelId] })
        toast.success('章节已确认，摘要和角色状态已更新，全书概要已自动刷新')
      } else {
        toast.success('章节已确认，摘要和角色状态已更新')
      }
    } catch {
      toast.error('确认章节失败')
    } finally {
      setIsConfirming(false)
    }
  }, [currentChapter, isConfirming, novelId, qc, refetchChapters])

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

  const handleSaveEdit = useCallback(async () => {
    if (!currentChapter) return
    try {
      const updated = await chaptersApi.update(currentChapter.id, { content: editContent, title: currentChapter.title })
      qc.setQueryData<Chapter[]>(['chapters', novelId], (old = []) =>
        old.map(ch => ch.id === updated.id ? updated : ch),
      )
      setEditContent(updated.content)
      await refetchChapters()
      setIsEditing(false)
    } catch {
      toast.error('保存章节失败')
    }
  }, [currentChapter, editContent, novelId, qc, refetchChapters])

  const handleNewChapter = useCallback(() => {
    setSelectedChapterNum(
      chapters.length > 0 ? Math.max(...chapters.map((c: Chapter) => c.number)) + 1 : 1,
    )
  }, [chapters])

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="h-screen flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <header className="border-b px-4 py-3 flex items-center gap-3 shrink-0">
        <button onClick={() => navigate('/')} className="p-1.5 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-semibold text-sm truncate max-w-48">{novel?.title}</h1>
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

            <div className="flex items-center gap-1.5 ml-auto">
              <select
                value={fontSize}
                onChange={e => { const v = Number(e.target.value); setFontSize(v); localStorage.setItem('novel_font_size', String(v)) }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                title="字体大小"
              >
                <option value={12}>12px</option>
                <option value={14}>14px</option>
                <option value={16}>16px</option>
                <option value={18}>18px</option>
                <option value={20}>20px</option>
                <option value={22}>22px</option>
                <option value={24}>24px</option>
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
                    className="text-[10px] text-muted-foreground hover:text-foreground px-0.5"
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
                      <button onClick={() => { setIsEditing(true); setEditContent(currentChapter.content) }}
                        className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors">
                        <Edit3 className="w-3 h-3" /> 手动编辑
                      </button>
                    ) : (
                      <button onClick={handleSaveEdit}
                        className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors">
                        <Check className="w-3 h-3" /> 保存编辑
                      </button>
                    )}
                    <button onClick={handleConfirm}
                      disabled={isConfirming}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                      {isConfirming ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      {isConfirming ? '确认中...' : currentChapter.status === 'confirmed' ? '重新确认' : '确认章节'}
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
              <ChatPanel novelId={novelId} novel={novel} />
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
              agentStage={genStore.agentStage}
              isCurrentlyGenerating={gen.isCurrentlyGenerating}
              isOtherGenerating={genStore.isGenerating && !gen.isCurrentlyGenerating}
              justFinishedHere={justFinishedHere}
              instruction={instruction}
              targetWords={targetWords}
              onInstructionChange={(v) => setInstruction(novelId, v)}
              onTargetWordsChange={(v) => setTargetWords(novelId, v)}
              onGenerate={gen.handleGenerate}
              onAbortOrGenerate={barMode === 'rewrite' ? gen.handleRewriteOrAbort : gen.handleAbortOrGenerate}
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
              modelLibrary={modelLibrary}

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
              entities={entityList}
            />
          </>}
        </div>

        {/* Right Sidebar: Context + Agent Log tabs */}
        {showContext && (
          <div className="w-72 border-l flex flex-col shrink-0">
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
                  <ContextPanel novelId={novelId} rollingStage={genStore.agentStage} contextSteps={genStore.contextSteps} />
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

    </div>
  )
}
