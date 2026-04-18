import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Users, List, Zap, Check, Edit3, Trash2, Plus,
  ChevronRight, ChevronLeft, Loader2, PanelRightOpen, PanelRightClose,
  Settings2, Sun, Moon, AlertTriangle, Radio, RadioTower, Square, MessageSquare,
  Terminal, Sparkles, Database,
} from 'lucide-react'
import {
  novelsApi, chaptersApi, charactersApi, generationApi, type Chapter,
  streamChapterGeneration,
} from '@/api/client'
import type { SSEMessage, AgentDoneData, TotalUsageData, OriginalDraftData, NewCharactersData } from '@/api/client'
import AgentStatus from '@/components/AgentStatus/AgentStatus'
import DiffView from '@/components/DiffView/DiffView'
import ContextPanel from '@/components/ContextPanel/ContextPanel'
import NovelSettingsDrawer from '@/components/NovelSettingsDrawer/NovelSettingsDrawer'
import AgentLog, { type AgentLogEntry } from '@/components/AgentLog/AgentLog'
import ChatPanel from '@/components/ChatPanel/ChatPanel'
import DevPanel from '@/components/DevPanel/DevPanel'
import { useSettingsStore } from '@/store/settingsStore'
import { useGenerationStore } from '@/store/generationStore'

export default function Editor() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme, streamingMode, toggleStreamingMode } = useSettingsStore()
  const genStore = useGenerationStore()

  const [selectedChapterNum, setSelectedChapterNum] = useState<number>(
    Number(searchParams.get('chapter')) || 1
  )
  const [editorMode, setEditorMode] = useState<'generate' | 'chat'>('generate')
  const [instruction, setInstruction] = useState('')
  const [targetWords, setTargetWords] = useState(800)
  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [showContext, setShowContext] = useState(true)
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false)
  const [showDiff, setShowDiff] = useState(false)
  const [showTokens, setShowTokens] = useState(true)
  const [logCollapsed, setLogCollapsed] = useState(false)
  const [showDevPanel, setShowDevPanel] = useState(false)
  const [plotSuggestions, setPlotSuggestions] = useState<string[]>([])
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState(false)
  const [newCharCandidates, setNewCharCandidates] = useState<Array<{ name: string; role: string; description: string }>>([])
  const [addingChars, setAddingChars] = useState(false)
  const [isConfirming, setIsConfirming] = useState(false)
  const [fontSize, setFontSize] = useState(() => Number(localStorage.getItem('novel_font_size') || 16))
  const [lineHeight, setLineHeight] = useState(() => Number(localStorage.getItem('novel_line_height') || 2.0))
  const contentEndRef = useRef<HTMLDivElement>(null)

  const { data: novel } = useQuery({
    queryKey: ['novel', novelId],
    queryFn: () => novelsApi.get(novelId),
  })

  const { data: chapters = [], refetch: refetchChapters } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  // Is the global generation currently targeting this novel + chapter?
  const isCurrentlyGenerating =
    genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum

  const currentChapter = chapters.find((c: Chapter) => c.number === selectedChapterNum) || null

  useEffect(() => {
    if (currentChapter) {
      setEditContent(currentChapter.content)
    }
  }, [currentChapter?.id])

  // Scroll to bottom during streaming
  useEffect(() => {
    if (isCurrentlyGenerating && streamingMode) {
      contentEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [genStore.streamingText, isCurrentlyGenerating, streamingMode])

  // Sync selectedChapterNum when coming back via GenerationIndicator link
  useEffect(() => {
    const chapterFromUrl = Number(searchParams.get('chapter'))
    if (chapterFromUrl && chapterFromUrl !== selectedChapterNum) {
      setSelectedChapterNum(chapterFromUrl)
    }
  }, [searchParams])

  // Clear suggestions when chapter changes
  useEffect(() => {
    setPlotSuggestions([])
  }, [selectedChapterNum])

  const handleFetchSuggestions = useCallback(async () => {
    setIsLoadingSuggestions(true)
    setPlotSuggestions([])
    try {
      const suggestions = await generationApi.plotSuggestions(novelId, selectedChapterNum)
      setPlotSuggestions(suggestions)
    } catch (e) {
      console.error('Failed to fetch suggestions:', e)
    } finally {
      setIsLoadingSuggestions(false)
    }
  }, [novelId, selectedChapterNum])

  const handleGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating || !novel) return

    gs.startGeneration(novelId, novel.title, selectedChapterNum)
    setIsEditing(false)
    setLogCollapsed(false)
    setShowDiff(false)
    setPlotSuggestions([])
    setNewCharCandidates([])

    let entryCounter = 0
    const runningEntryIds: Map<string, string> = new Map() // agent name → entryId

    const ctrl = streamChapterGeneration(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        volume: 1,
        instruction,
        target_words: targetWords,
      },
      (msg: SSEMessage) => {
        const s = useGenerationStore.getState()
        if (msg.event === 'stage') {
          s.setAgentStage(msg.data as string)
        } else if (msg.event === 'token') {
          s.appendToken(msg.data as string)
        } else if (msg.event === 'agent_start') {
          const d = msg.data as { agent: string; label: string }
          const entryId = `${d.agent}-${entryCounter++}`
          const entry: AgentLogEntry = {
            id: entryId,
            agent: d.agent,
            label: d.label,
            status: 'running',
            inputTokens: 0,
            outputTokens: 0,
          }
          runningEntryIds.set(d.agent, entryId)
          s.addLogEntry(entry)
        } else if (msg.event === 'agent_done') {
          const d = msg.data as AgentDoneData
          const entryId = runningEntryIds.get(d.agent)
          if (entryId) {
            s.updateLogEntry(entryId, {
              status: 'done',
              inputTokens: d.input_tokens,
              outputTokens: d.output_tokens,
              passed: d.passed,
            })
          }
        } else if (msg.event === 'total_usage') {
          const d = msg.data as TotalUsageData
          s.setTotalTokens(d.input_tokens, d.output_tokens)
        } else if (msg.event === 'done') {
          s.setAgentStage('done')
          // Invalidate queries so data refreshes regardless of which page the user is on
          qc.invalidateQueries({ queryKey: ['chapters', novelId] })
          qc.invalidateQueries({ queryKey: ['characters', novelId] })
        } else if (msg.event === 'original_draft') {
          const d = msg.data as OriginalDraftData
          s.setOriginalDraft(d.text)
          setShowDiff(true)
        } else if (msg.event === 'new_characters') {
          const d = msg.data as NewCharactersData
          if (d.candidates?.length) setNewCharCandidates(d.candidates)
        } else if (msg.event === 'warning') {
          s.setWarning(String(msg.data))
          toast(String(msg.data), { icon: '⚠️' })
        } else if (msg.event === 'error') {
          s.setError(String(msg.data))
        }
      },
      () => {
        useGenerationStore.getState().finishGeneration()
        setLogCollapsed(true)
      }
    )

    useGenerationStore.getState().setAbortController(ctrl)
  }, [novel, novelId, selectedChapterNum, instruction, targetWords, qc])

  const handleAbortOrGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating && gs.novelId === novelId && gs.chapterNum === selectedChapterNum) {
      gs.abortGeneration()
      return
    }
    handleGenerate()
  }, [novelId, selectedChapterNum, handleGenerate])

  const handleConfirm = async () => {
    if (!currentChapter || isConfirming) return
    setIsConfirming(true)
    try {
      await chaptersApi.confirm(currentChapter.id)
      refetchChapters()
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      toast.success('章节已确认，摘要和角色状态已更新')
    } catch {
      toast.error('确认章节失败')
    } finally {
      setIsConfirming(false)
    }
  }

  const handleDelete = async () => {
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
  }

  const handleSaveEdit = async () => {
    if (!currentChapter) return
    try {
      await chaptersApi.update(currentChapter.id, { content: editContent, title: currentChapter.title })
      refetchChapters()
      setIsEditing(false)
    } catch {
      toast.error('保存章节失败')
    }
  }

  const handleAddNewChars = async () => {
    if (!newCharCandidates.length || addingChars) return
    setAddingChars(true)
    try {
      for (const c of newCharCandidates) {
        await charactersApi.create({ ...c, novel_id: novelId })
      }
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setNewCharCandidates([])
    } finally {
      setAddingChars(false)
    }
  }

  const streamingText = isCurrentlyGenerating ? genStore.streamingText : ''
  const agentStage = isCurrentlyGenerating ? genStore.agentStage : ''

  // Show agent log & tokens for current generation OR after it finishes (same novel/chapter)
  const hasGenDataHere =
    genStore.agentLogEntries.length > 0 &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum
  const agentLogEntries = hasGenDataHere ? genStore.agentLogEntries : []
  const totalInputTokens = hasGenDataHere ? genStore.totalInputTokens : 0
  const totalOutputTokens = hasGenDataHere ? genStore.totalOutputTokens : 0

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

  // True after generation completes successfully for this chapter
  const justFinishedHere =
    !genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum &&
    genStore.agentStage === 'done'

  // Fallback: after generation finishes, React Query refetch is async.
  // Use streamingText from store as a bridge until the new chapter data arrives.
  const recentlyFinishedHere =
    !genStore.isGenerating &&
    genStore.novelId === novelId &&
    genStore.chapterNum === selectedChapterNum &&
    genStore.streamingText.length > 0

  // What text to display in the editor area
  const displayText = isEditing
    ? editContent
    : streamingMode && isCurrentlyGenerating
      ? (streamingText || currentChapter?.content || '')
      : (currentChapter?.content || (recentlyFinishedHere ? genStore.streamingText : ''))

  const isStreaming = isCurrentlyGenerating && streamingMode && streamingText.length > 0

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
          <button onClick={() => navigate(`/novel/${novelId}/characters`)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors">
            <Users className="w-3.5 h-3.5" /> 角色
          </button>
          <button onClick={() => navigate(`/novel/${novelId}/outline`)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors">
            <List className="w-3.5 h-3.5" /> 大纲
          </button>
          <button onClick={() => navigate(`/novel/${novelId}/data`)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors">
            <Database className="w-3.5 h-3.5" /> 数据
          </button>
          <button
            onClick={() => setShowSettingsDrawer(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors"
          >
            <Settings2 className="w-3.5 h-3.5" /> 设置
          </button>
          <button
            onClick={() => setShowDevPanel(v => !v)}
            className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors ${showDevPanel ? 'text-primary bg-primary/10' : ''}`}
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
            onClick={toggleTheme}
            className="p-1.5 rounded-md hover:bg-muted transition-colors"
            title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button onClick={() => setShowContext(!showContext)}
            className="p-1.5 rounded-md hover:bg-muted transition-colors">
            {showContext ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Chapter List Sidebar */}
        <div className="w-52 border-r flex flex-col shrink-0">
          <div className="p-3 border-b">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">章节</p>
          </div>
          <div className="overflow-y-auto flex-1 p-2 space-y-0.5">
            {chapters.map((c: Chapter) => (
              <button
                key={c.id}
                onClick={() => setSelectedChapterNum(c.number)}
                className={`w-full text-left px-2.5 py-2 rounded-md text-sm transition-colors ${
                  c.number === selectedChapterNum
                    ? 'bg-primary text-primary-foreground'
                    : 'hover:bg-muted'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="truncate">第{c.number}章</span>
                  {/* Pulse dot when this chapter is generating */}
                  {genStore.isGenerating && genStore.novelId === novelId && genStore.chapterNum === c.number
                    ? <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />
                    : c.status === 'confirmed'
                      ? <Check className="w-3 h-3 shrink-0 opacity-70" />
                      : null}
                </div>
                {c.title && c.title !== `第${c.number}章` && (
                  <p className={`text-xs truncate mt-0.5 ${c.number === selectedChapterNum ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                    {c.title}
                  </p>
                )}
              </button>
            ))}
            <button
              onClick={() => setSelectedChapterNum(
                chapters.length > 0 ? Math.max(...chapters.map((c: Chapter) => c.number)) + 1 : 1
              )}
              className="w-full text-left px-2.5 py-2 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors border border-dashed mt-2"
            >
              + 新章节
            </button>
          </div>
        </div>

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
                <option value={14}>14px</option>
                <option value={16}>16px</option>
                <option value={18}>18px</option>
                <option value={20}>20px</option>
              </select>
              <select
                value={lineHeight}
                onChange={e => { const v = Number(e.target.value); setLineHeight(v); localStorage.setItem('novel_line_height', String(v)) }}
                className="border rounded px-1.5 py-1 bg-background text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                title="行间距"
              >
                <option value={1.5}>1.5×</option>
                <option value={1.8}>1.8×</option>
                <option value={2.0}>2.0×</option>
                <option value={2.5}>2.5×</option>
              </select>
            </div>
            <div className="flex items-center gap-2">
              {currentChapter && !isCurrentlyGenerating && (
                <button
                  onClick={handleDelete}
                  className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md text-destructive hover:bg-destructive/10 transition-colors"
                  title="删除本章"
                >
                  <Trash2 className="w-3 h-3" /> 删除
                </button>
              )}
              {currentChapter?.content && !isCurrentlyGenerating && (
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
                  {currentChapter.status !== 'confirmed' && (
                    <button onClick={handleConfirm}
                      disabled={isConfirming}
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                      {isConfirming ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                      {isConfirming ? '确认中...' : '确认章节'}
                    </button>
                  )}
                </>
              )}
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

          {editorMode === 'generate' && <>
          {/* Content Area */}
          <div className={`flex-1 ${showDiff && !isCurrentlyGenerating && genStore.originalDraft ? 'overflow-hidden' : 'overflow-y-auto'}`}>
            {showDiff && !isCurrentlyGenerating && genStore.originalDraft ? (
              <DiffView
                originalText={genStore.originalDraft}
                revisedText={currentChapter?.content || genStore.streamingText}
                onClose={() => setShowDiff(false)}
              />
            ) : warningMessage && !isCurrentlyGenerating ? (
              <div className="flex flex-col h-full overflow-y-auto">
                <div className="mx-8 mt-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-300 dark:border-amber-700 rounded-lg px-4 py-2.5 flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300 shrink-0">
                  <span className="shrink-0 mt-0.5">⚠</span>
                  <span>{warningMessage}</span>
                </div>
                <div className={`p-8 novel-content whitespace-pre-wrap`} style={{ fontSize: `${fontSize}px`, lineHeight }}>
                  {displayText}
                </div>
              </div>
            ) : errorMessage ? (
              <div className="p-8 flex flex-col items-center justify-center h-full gap-3">
                <div className="max-w-lg w-full bg-destructive/10 border border-destructive/30 rounded-lg p-4">
                  <p className="text-sm font-medium text-destructive mb-1">生成失败</p>
                  <p className="text-xs text-destructive/80 whitespace-pre-wrap break-words">{errorMessage}</p>
                </div>
              </div>
            ) : isEditing ? (
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full h-full p-8 resize-none bg-background focus:outline-none novel-content font-serif"
                style={{ fontSize: `${fontSize}px`, lineHeight }}
                placeholder="在此输入内容..."
              />
            ) : isCurrentlyGenerating && !streamingMode ? (
              <div className="p-8 flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                <Loader2 className="w-8 h-8 animate-spin" />
                <p className="text-sm">AI 正在创作中，完成后自动显示...</p>
                <p className="text-xs opacity-60">切换页面不会中断生成</p>
              </div>
            ) : (
              <div className="h-full flex flex-col overflow-y-auto">
                {currentChapter?.instruction && (
                  <div className="px-8 pt-6 pb-1 shrink-0">
                    <details>
                      <summary className="text-xs text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">
                        📝 本章构思
                      </summary>
                      <p className="mt-2 text-sm text-muted-foreground border-l-2 border-muted pl-3 whitespace-pre-wrap">
                        {currentChapter.instruction}
                      </p>
                    </details>
                  </div>
                )}
                <div className={`p-8 novel-content whitespace-pre-wrap flex-1 ${isStreaming ? 'streaming-cursor' : ''}`} style={{ fontSize: `${fontSize}px`, lineHeight }}>
                  {displayText || (
                    <span className="text-muted-foreground/50">
                      {isCurrentlyGenerating ? '' : '点击下方「生成章节」开始创作...'}
                    </span>
                  )}
                  <div ref={contentEndRef} />
                </div>
              </div>
            )}
          </div>

          {/* Agent Log */}
          <AgentLog
            entries={agentLogEntries}
            totalInputTokens={totalInputTokens}
            totalOutputTokens={totalOutputTokens}
            showTokens={showTokens}
            onToggleTokens={() => setShowTokens(v => !v)}
            collapsed={logCollapsed}
            onToggleCollapse={() => setLogCollapsed(v => !v)}
          />

          {/* Generation Controls */}
          <div className="border-t px-4 py-3 shrink-0 space-y-2">
            <AgentStatus stage={agentStage} visible={isCurrentlyGenerating} />

            {/* Plot Suggestions */}
            {justFinishedHere && plotSuggestions.length === 0 && (
              <div className="flex items-center gap-2">
                <button
                  onClick={handleFetchSuggestions}
                  disabled={isLoadingSuggestions}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 border rounded-lg hover:bg-muted transition-colors disabled:opacity-50"
                >
                  {isLoadingSuggestions
                    ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> 生成建议中...</>
                    : <><Sparkles className="w-3.5 h-3.5" /> 获取下章剧情建议</>
                  }
                </button>
              </div>
            )}
            {plotSuggestions.length > 0 && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                    <Sparkles className="w-3 h-3" /> 下章剧情建议（点击填入指令）
                  </span>
                  <button
                    onClick={() => setPlotSuggestions([])}
                    className="text-xs text-muted-foreground hover:text-foreground px-1"
                  >
                    ×
                  </button>
                </div>
                <div className="flex flex-col gap-1">
                  {plotSuggestions.map((s, i) => (
                    <button
                      key={i}
                      onClick={() => setInstruction(s)}
                      className={`text-left text-xs px-3 py-1.5 rounded-lg border transition-colors hover:bg-muted ${
                        instruction === s ? 'border-primary bg-primary/5 text-primary' : 'border-border'
                      }`}
                    >
                      <span className="text-muted-foreground mr-1.5">{i + 1}.</span>{s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {newCharCandidates.length > 0 && (
              <div className="space-y-1.5 border rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground flex items-center gap-1">
                    <Users className="w-3 h-3" /> 发现新角色（本章首次出现）
                  </span>
                  <button
                    onClick={() => setNewCharCandidates([])}
                    className="text-xs text-muted-foreground hover:text-foreground px-1"
                  >
                    ×
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {newCharCandidates.map((c, i) => (
                    <div key={i} className="flex items-center gap-1.5 text-xs bg-muted px-2.5 py-1.5 rounded-md">
                      <span className="font-medium">{c.name}</span>
                      <span className="text-muted-foreground">·{c.role}</span>
                    </div>
                  ))}
                </div>
                <button
                  onClick={handleAddNewChars}
                  disabled={addingChars}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-primary text-primary-foreground rounded-md hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {addingChars ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
                  一键添加到角色表
                </button>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <textarea
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
                placeholder="生成指令（可选）：重点描写心理活动..."
                rows={3}
                className="w-full text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y min-h-[38px]"
              />
              <div className="flex items-center gap-2">
                <select
                  value={targetWords}
                  onChange={e => setTargetWords(Number(e.target.value))}
                  className="text-sm border rounded-lg px-2 py-2 bg-background focus:outline-none"
                >
                  <option value={500}>500字</option>
                  <option value={800}>800字</option>
                  <option value={1200}>1200字</option>
                  <option value={2000}>2000字</option>
                </select>
                <div className="flex-1" />
                <button
                  onClick={handleAbortOrGenerate}
                  disabled={genStore.isGenerating && !isCurrentlyGenerating}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-opacity shrink-0 ${
                    isCurrentlyGenerating
                      ? 'bg-destructive text-destructive-foreground hover:opacity-90'
                      : 'bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50'
                  }`}
                >
                  {isCurrentlyGenerating
                    ? <><Square className="w-4 h-4" /> 终止</>
                    : genStore.isGenerating
                      ? <><Loader2 className="w-4 h-4 animate-spin" /> 其他章节生成中</>
                      : <><Zap className="w-4 h-4" /> 生成章节</>
                  }
                </button>
              </div>
            </div>
          </div>
          </>}
        </div>

        {/* Context Panel */}
        {showContext && (
          <div className="w-64 border-l flex flex-col shrink-0">
            <div className="p-3 border-b">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">上下文状态</p>
            </div>
            <div className="flex-1 overflow-hidden p-3">
              <ContextPanel novelId={novelId} rollingStage={agentStage} />
            </div>
          </div>
        )}
      </div>

      {/* Novel Settings Drawer */}
      {showSettingsDrawer && novel && (
        <NovelSettingsDrawer
          novel={novel}
          onClose={() => setShowSettingsDrawer(false)}
        />
      )}

      {/* Developer View Panel */}
      {showDevPanel && (
        <DevPanel onClose={() => setShowDevPanel(false)} />
      )}
    </div>
  )
}
