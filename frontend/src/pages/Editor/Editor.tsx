import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Users, List, Zap, Check, Edit3,
  ChevronRight, ChevronLeft, Loader2, PanelRightOpen, PanelRightClose,
  Settings2, Sun, Moon, AlertTriangle
} from 'lucide-react'
import {
  novelsApi, chaptersApi, type Novel, type Chapter,
  streamChapterGeneration,
} from '@/api/client'
import type { SSEMessage, AgentDoneData, TotalUsageData } from '@/api/client'
import AgentStatus from '@/components/AgentStatus/AgentStatus'
import ContextPanel from '@/components/ContextPanel/ContextPanel'
import NovelSettingsDrawer from '@/components/NovelSettingsDrawer/NovelSettingsDrawer'
import AgentLog, { type AgentLogEntry } from '@/components/AgentLog/AgentLog'
import { useSettingsStore } from '@/store/settingsStore'

export default function Editor() {
  const { id } = useParams<{ id: string }>()
  const [searchParams] = useSearchParams()
  const novelId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme } = useSettingsStore()

  const [selectedChapterNum, setSelectedChapterNum] = useState<number>(
    Number(searchParams.get('chapter')) || 1
  )
  const [isGenerating, setIsGenerating] = useState(false)
  const [agentStage, setAgentStage] = useState('')
  const [streamingText, setStreamingText] = useState('')
  const [instruction, setInstruction] = useState('')
  const [targetWords, setTargetWords] = useState(800)
  const [isEditing, setIsEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [showContext, setShowContext] = useState(true)
  const [showSettingsDrawer, setShowSettingsDrawer] = useState(false)

  // Agent log state (Feature 5)
  const [agentLogEntries, setAgentLogEntries] = useState<AgentLogEntry[]>([])
  const [totalInputTokens, setTotalInputTokens] = useState(0)
  const [totalOutputTokens, setTotalOutputTokens] = useState(0)
  const [showTokens, setShowTokens] = useState(true)
  const [logCollapsed, setLogCollapsed] = useState(false)

  const abortRef = useRef<AbortController | null>(null)
  const contentEndRef = useRef<HTMLDivElement>(null)

  const { data: novel } = useQuery({
    queryKey: ['novel', novelId],
    queryFn: () => novelsApi.get(novelId),
  })

  const { data: chapters = [], refetch: refetchChapters } = useQuery({
    queryKey: ['chapters', novelId],
    queryFn: () => chaptersApi.list(novelId),
  })

  const currentChapter = chapters.find((c: Chapter) => c.number === selectedChapterNum) || null

  useEffect(() => {
    if (currentChapter) {
      setEditContent(currentChapter.content)
      setStreamingText('')
    }
  }, [currentChapter?.id])

  useEffect(() => {
    contentEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [streamingText])

  const handleGenerate = useCallback(() => {
    if (isGenerating || !novel) return
    setIsGenerating(true)
    setStreamingText('')
    setAgentStage('building_context')
    setIsEditing(false)
    setAgentLogEntries([])
    setTotalInputTokens(0)
    setTotalOutputTokens(0)
    setLogCollapsed(false)

    let accumulatedText = ''
    const runningEntries: Map<string, AgentLogEntry> = new Map()
    let entryCounter = 0

    abortRef.current = streamChapterGeneration(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        volume: 1,
        instruction,
        target_words: targetWords,
      },
      (msg: SSEMessage) => {
        if (msg.event === 'stage') {
          setAgentStage(msg.data as string)
        } else if (msg.event === 'token') {
          accumulatedText += msg.data as string
          setStreamingText(accumulatedText)
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
          runningEntries.set(d.agent, entry)
          setAgentLogEntries(prev => [...prev, entry])
        } else if (msg.event === 'agent_done') {
          const d = msg.data as AgentDoneData
          const existing = runningEntries.get(d.agent)
          if (existing) {
            const updated: AgentLogEntry = {
              ...existing,
              status: 'done',
              inputTokens: d.input_tokens,
              outputTokens: d.output_tokens,
              passed: d.passed,
            }
            runningEntries.set(d.agent, updated)
            setAgentLogEntries(prev => prev.map(e => e.id === existing.id ? updated : e))
          }
        } else if (msg.event === 'total_usage') {
          const d = msg.data as TotalUsageData
          setTotalInputTokens(d.input_tokens)
          setTotalOutputTokens(d.output_tokens)
        } else if (msg.event === 'done') {
          setAgentStage('done')
          refetchChapters()
          qc.invalidateQueries({ queryKey: ['characters', novelId] })
        } else if (msg.event === 'error') {
          setAgentStage('error')
          console.error('Generation error:', msg.data)
        }
      },
      () => setIsGenerating(false)
    )
  }, [isGenerating, novel, novelId, selectedChapterNum, instruction, targetWords, refetchChapters, qc])

  const handleConfirm = async () => {
    if (!currentChapter) return
    await chaptersApi.confirm(currentChapter.id)
    refetchChapters()
    qc.invalidateQueries({ queryKey: ['characters', novelId] })
  }

  const handleSaveEdit = async () => {
    if (!currentChapter) return
    await chaptersApi.update(currentChapter.id, { content: editContent, title: currentChapter.title })
    refetchChapters()
    setIsEditing(false)
  }

  const displayText = isEditing
    ? editContent
    : (streamingText || currentChapter?.content || '')

  const isStreaming = isGenerating && streamingText.length > 0

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
          <button
            onClick={() => setShowSettingsDrawer(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md hover:bg-muted transition-colors"
          >
            <Settings2 className="w-3.5 h-3.5" /> 设置
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
                  {c.status === 'confirmed' && <Check className="w-3 h-3 shrink-0 opacity-70" />}
                </div>
                {c.title && c.title !== `第${c.number}章` && (
                  <p className={`text-xs truncate mt-0.5 ${c.number === selectedChapterNum ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                    {c.title}
                  </p>
                )}
              </button>
            ))}
            {/* Next chapter button */}
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

            <div className="flex items-center gap-2 ml-auto">
              {currentChapter?.content && !isGenerating && (
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
                      className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 border rounded-md hover:bg-muted transition-colors">
                      <Check className="w-3 h-3" /> 确认章节
                    </button>
                  )}
                </>
              )}
            </div>
          </div>

          {/* Content Area */}
          <div className="flex-1 overflow-y-auto">
            {isEditing ? (
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                className="w-full h-full p-8 text-base leading-loose resize-none bg-background focus:outline-none novel-content font-serif"
                placeholder="在此输入内容..."
              />
            ) : (
              <div className={`p-8 novel-content text-base leading-loose whitespace-pre-wrap ${isStreaming ? 'streaming-cursor' : ''}`}>
                {displayText || (
                  <span className="text-muted-foreground/50">
                    {isGenerating ? '' : '点击下方「生成章节」开始创作...'}
                  </span>
                )}
                <div ref={contentEndRef} />
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
            <AgentStatus stage={agentStage} visible={isGenerating} />
            <div className="flex items-center gap-2">
              <input
                value={instruction}
                onChange={e => setInstruction(e.target.value)}
                placeholder="生成指令（可选）：重点描写心理活动..."
                className="flex-1 text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
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
              <button
                onClick={handleGenerate}
                disabled={isGenerating}
                className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity shrink-0"
              >
                {isGenerating
                  ? <><Loader2 className="w-4 h-4 animate-spin" /> 生成中</>
                  : <><Zap className="w-4 h-4" /> 生成章节</>
                }
              </button>
            </div>
          </div>
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
    </div>
  )
}
