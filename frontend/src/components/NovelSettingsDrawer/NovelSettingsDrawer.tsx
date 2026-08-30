import { useState, useEffect, useRef, useCallback } from 'react'
import toast from 'react-hot-toast'
import { X, Save, Loader2, ChevronDown, ChevronRight, Wand2, BookOpen, FileText, Cpu, FlaskConical, AlertTriangle, ListChecks, ExternalLink, Palette } from 'lucide-react'
import { novelsApi, modelLibraryApi, writerPresetsApi, promptRulesApi, modelSelectValue, type Novel, type ModelEntry, type ExampleTurn } from '@/api/client'
import { useQueryClient, useQuery } from '@tanstack/react-query'
import { ContextConfigContent } from '@/components/TokenPanel/TokenPanel'
import ExampleTurnsEditor from '@/components/ExampleTurnsEditor'
import { WRITING_STYLES } from '@/constants/writingStyles'

type CreationSection = 'prompt' | 'rules' | 'genreCard' | 'models' | 'review' | 'fulltext' | null

const CREATION_SECTIONS: { key: CreationSection & string; label: string; desc: string; icon: typeof FileText }[] = [
  { key: 'prompt', label: '提示词与示例', desc: 'Writer 自定义提示词、示例轮', icon: FileText },
  { key: 'rules', label: '写作规则', desc: '选择本书启用的规则广场条目', icon: ListChecks },
  { key: 'genreCard', label: '题材腔调卡', desc: '默认按题材自动匹配，可手动指定或关闭', icon: Palette },
  { key: 'models', label: '模型与生成参数', desc: '模型覆盖、温度、Token、摘要、RAG、Thinking', icon: Cpu },
  { key: 'fulltext', label: '全文上下文（实验）', desc: '将前 N 章正文全量传入上下文', icon: FlaskConical },
]

type Tab = 'content' | 'creation' | 'context'

interface Props {
  novel: Novel
  initialTab?: Tab
  onClose: () => void
}

const GENRES = ['古代权谋', '现代都市', '玄幻', '悬疑推理', '言情', '科幻', '历史', '其他']
const STYLES = WRITING_STYLES
const LENGTHS = ['短篇', '中篇', '长篇']
const RANK_SEPARATOR = '\n\n---等级体系---\n\n'

function ModelSelect({
  value,
  onChange,
  placeholder,
  models,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  models: ModelEntry[]
}) {
  return (
    <select
      value={modelSelectValue(models, value)}
      onChange={e => onChange(e.target.value)}
      className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
    >
      <option value="">{placeholder}</option>
      {models.map(m => (
        <option key={m.id} value={String(m.id)}>
          [{m.provider}] {m.display_name || m.model_id}
        </option>
      ))}
    </select>
  )
}

/** 从 core_setting 拆分出背景设定和等级设定 */
function splitCoreSetting(raw: string): { bg: string; rank: string; hasSep: boolean } {
  const idx = raw.indexOf(RANK_SEPARATOR)
  if (idx >= 0) {
    return { bg: raw.slice(0, idx), rank: raw.slice(idx + RANK_SEPARATOR.length), hasSep: true }
  }
  return { bg: raw, rank: '', hasSep: false }
}

/** 合并背景设定和等级设定为 core_setting */
function mergeCoreSetting(bg: string, rank: string): string {
  if (!rank.trim()) return bg
  return bg + RANK_SEPARATOR + rank
}

const MIN_WIDTH = 320
const MAX_WIDTH = 640

export default function NovelSettingsDrawer({ novel, initialTab, onClose }: Props) {
  const qc = useQueryClient()
  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })

  // ── Tab state ──
  const [activeTab, setActiveTab] = useState<Tab>(initialTab || 'content')
  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    if (tab !== 'creation') setActiveSection(null)
  }

  // ── Resizable drawer ──
  const [drawerWidth, setDrawerWidth] = useState(384)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(384)

  const onMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging.current) return
    const delta = startX.current - e.clientX
    const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth.current + delta))
    setDrawerWidth(newWidth)
  }, [])

  const onMouseUp = useCallback(() => {
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  useEffect(() => {
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [onMouseMove, onMouseUp])

  const handleDragStart = (e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = drawerWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  // ── Novel content fields ──
  const [title, setTitle] = useState(novel.title)
  const [genre, setGenre] = useState(novel.genre)
  const [genreCard, setGenreCard] = useState(novel.genre_card || '')
  const [writingStyle, setWritingStyle] = useState(novel.writing_style)
  const [targetLength, setTargetLength] = useState(novel.target_length)
  const [coreSetting, setCoreSetting] = useState(novel.core_setting)

  // ── World-setting split ──
  const initSplit = splitCoreSetting(novel.core_setting)
  const [splitWorld, setSplitWorld] = useState(initSplit.hasSep)
  const [backgroundSetting, setBackgroundSetting] = useState(initSplit.bg)
  const [rankSetting, setRankSetting] = useState(initSplit.rank)

  // ── Creation settings fields ──
  const [bookSummary, setBookSummary] = useState(novel.book_summary || '')
  const [writerSystemPrompt, setWriterSystemPrompt] = useState(novel.writer_system_prompt || '')
  const [writerExamples, setWriterExamples] = useState<ExampleTurn[]>(novel.writer_examples || [])
  const [writerModel, setWriterModel] = useState(novel.writer_model || '')
  const [fastModel, setFastModel] = useState(novel.fast_model || '')
  const [criticModel, setCriticModel] = useState(novel.critic_model || '')
  const [embeddingModel, setEmbeddingModel] = useState(novel.embedding_model || '')
  const [enableCritic, setEnableCritic] = useState(novel.enable_critic ?? true)
  const [enableDetailReview, setEnableDetailReview] = useState(novel.enable_detail_review ?? false)
  const [detailReviewModel, setDetailReviewModel] = useState(novel.detail_review_model || '')
  const [writerTemperature, setWriterTemperature] = useState(novel.writer_temperature ?? 0.85)
  const [writerUseCustomTemperature, setWriterUseCustomTemperature] = useState(novel.writer_use_custom_temperature ?? true)
  const [writerMaxTokens, setWriterMaxTokens] = useState(novel.writer_max_tokens ?? 16384)
  const [rollingSummaryCount, setRollingSummaryCount] = useState(novel.rolling_summary_count ?? 8)
  const [ragTopK, setRagTopK] = useState(novel.rag_top_k ?? 6)
  const [chatContextRounds, setChatContextRounds] = useState(novel.chat_context_rounds ?? 20)
  const [deepseekThinking, setDeepseekThinking] = useState(novel.deepseek_thinking_level || 'high')
  const [geminiThinking, setGeminiThinking] = useState(novel.gemini_thinking_level || 'medium')
  const [geminiStream, setGeminiStream] = useState(novel.gemini_stream ?? true)
  const [enableFullTextContext, setEnableFullTextContext] = useState(novel.enable_full_text_context ?? false)
  const [fullTextChapters, setFullTextChapters] = useState(novel.full_text_chapters ?? 20)
  const [enabledRuleIds, setEnabledRuleIds] = useState<number[] | null>(novel.enabled_rule_ids)

  // ── UI state ──
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [showCardPreview, setShowCardPreview] = useState(false)
  const [generatingBookSummary, setGeneratingBookSummary] = useState(false)
  const [activeSection, setActiveSection] = useState<CreationSection>(null)

  useEffect(() => {
    setTitle(novel.title)
    setGenre(novel.genre)
    setGenreCard(novel.genre_card || '')
    setWritingStyle(novel.writing_style)
    setTargetLength(novel.target_length)
    setCoreSetting(novel.core_setting)
    const s = splitCoreSetting(novel.core_setting)
    setSplitWorld(s.hasSep)
    setBackgroundSetting(s.bg)
    setRankSetting(s.rank)
    setBookSummary(novel.book_summary || '')
    setWriterSystemPrompt(novel.writer_system_prompt || '')
    setWriterExamples(novel.writer_examples || [])
    setWriterModel(novel.writer_model || '')
    setFastModel(novel.fast_model || '')
    setCriticModel(novel.critic_model || '')
    setEmbeddingModel(novel.embedding_model || '')
    setEnableCritic(novel.enable_critic ?? true)
    setEnableDetailReview(novel.enable_detail_review ?? false)
    setDetailReviewModel(novel.detail_review_model || '')
    setWriterTemperature(novel.writer_temperature ?? 0.85)
    setWriterUseCustomTemperature(novel.writer_use_custom_temperature ?? true)
    setWriterMaxTokens(novel.writer_max_tokens ?? 16384)
    setRollingSummaryCount(novel.rolling_summary_count ?? 8)
    setRagTopK(novel.rag_top_k ?? 6)
    setChatContextRounds(novel.chat_context_rounds ?? 20)
    setDeepseekThinking(novel.deepseek_thinking_level || 'high')
    setGeminiThinking(novel.gemini_thinking_level || 'medium')
    setGeminiStream(novel.gemini_stream ?? true)
    setEnableFullTextContext(novel.enable_full_text_context ?? false)
    setFullTextChapters(novel.full_text_chapters ?? 20)
    setEnabledRuleIds(novel.enabled_rule_ids)
  }, [novel.id])

  const { data: writerPresets = [] } = useQuery({
    queryKey: ['writer-presets'],
    queryFn: writerPresetsApi.list,
  })

  const { data: promptRules = [], isSuccess: rulesLoaded } = useQuery({
    queryKey: ['prompt-rules'],
    queryFn: promptRulesApi.list,
  })

  const { data: genreCardData } = useQuery({
    queryKey: ['genre-cards'],
    queryFn: novelsApi.genreCards,
    staleTime: Infinity,
  })
  const genreCards = genreCardData?.cards ?? []
  const genreCardOff = genreCardData?.off_value ?? 'none'
  // 镜像后端 match_card_name：先按正式卡名（长名优先），再按别名（长名优先）。
  // 少了别名这一步，前端会说"匹配不到卡"而后端其实命中了
  const autoMatched = (() => {
    if (!genre) return ''
    const byName = [...genreCards]
      .sort((a, b) => b.name.length - a.name.length)
      .find(c => genre.includes(c.name))
    if (byName) return byName.name
    const byAlias = genreCards
      .flatMap(c => c.aliases.map(alias => ({ alias, name: c.name })))
      .sort((a, b) => b.alias.length - a.alias.length)
      .find(x => genre.includes(x.alias))
    return byAlias?.name ?? ''
  })()
  const activeCardName = genreCard === genreCardOff
    ? ''
    : (genreCards.some(c => c.name === genreCard) ? genreCard : autoMatched)
  const activeCardBody = genreCards.find(c => c.name === activeCardName)?.body ?? ''

  // null 表示本书从未配置过规则，后端据此走内置默认。这里保留 null 而不是塌成 []，
  // 否则规则还没加载完就点保存会把 [] 写进库，本书的护栏被静默清空
  const builtinDefaultIds = promptRules.filter(r => r.is_builtin && r.enabled).map(r => r.id)
  const effectiveRuleIds = enabledRuleIds ?? builtinDefaultIds
  const ruleSelectionReady = enabledRuleIds !== null || rulesLoaded

  const toggleRule = (id: number) => {
    setEnabledRuleIds(
      effectiveRuleIds.includes(id)
        ? effectiveRuleIds.filter(x => x !== id)
        : [...effectiveRuleIds, id]
    )
  }

  // ── World-setting split toggle ──
  const handleToggleSplit = () => {
    if (splitWorld) {
      const merged = mergeCoreSetting(backgroundSetting, rankSetting)
      setCoreSetting(merged)
      setSplitWorld(false)
    } else {
      const s = splitCoreSetting(coreSetting)
      setBackgroundSetting(s.bg)
      setRankSetting(s.rank)
      setSplitWorld(true)
    }
  }

  const getFinalCoreSetting = () => {
    if (splitWorld) return mergeCoreSetting(backgroundSetting, rankSetting)
    return coreSetting
  }

  const handleGenerateBookSummary = async () => {
    setGeneratingBookSummary(true)
    try {
      const result = await novelsApi.refreshBookSummary(novel.id)
      setBookSummary(result.book_summary)
      qc.invalidateQueries({ queryKey: ['novel', novel.id] })
    } catch {
      toast.error('生成全书概要失败')
    } finally {
      setGeneratingBookSummary(false)
    }
  }

  const handleOptimizeWorld = async () => {
    setOptimizing(true)
    try {
      const textToOptimize = splitWorld ? backgroundSetting : coreSetting
      const result = await novelsApi.optimizeWorld(novel.id, textToOptimize)
      if (splitWorld) {
        setBackgroundSetting(result.core_setting)
      } else {
        setCoreSetting(result.core_setting)
      }
    } catch {
      toast.error('优化世界观失败')
    } finally {
      setOptimizing(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    try {
      await novelsApi.update(novel.id, {
        title,
        genre,
        genre_card: genreCard,
        writing_style: writingStyle,
        target_length: targetLength,
        core_setting: getFinalCoreSetting(),
        book_summary: bookSummary,
        writer_system_prompt: writerSystemPrompt,
        writer_examples: writerExamples,
        writer_model: writerModel,
        fast_model: fastModel,
        critic_model: criticModel,
        embedding_model: embeddingModel,
        enable_critic: enableCritic,
        enable_detail_review: enableDetailReview,
        detail_review_model: detailReviewModel,
        writer_temperature: writerTemperature,
        writer_use_custom_temperature: writerUseCustomTemperature,
        writer_max_tokens: writerMaxTokens,
        rolling_summary_count: rollingSummaryCount,
        rag_top_k: ragTopK,
        chat_context_rounds: chatContextRounds,
        deepseek_thinking_level: deepseekThinking,
        gemini_thinking_level: geminiThinking,
        gemini_stream: geminiStream,
        enable_full_text_context: enableFullTextContext,
        full_text_chapters: fullTextChapters,
        // 用户没动过勾选就不提交，让库里继续保持 null（走内置默认）
        ...(enabledRuleIds !== null ? { enabled_rule_ids: enabledRuleIds } : {}),
      })
      qc.invalidateQueries({ queryKey: ['novel', novel.id] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      toast.error('保存设置失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={() => { setActiveSection(null); onClose() }}
      />
      {/* Drawer */}
      <div
        className="fixed right-0 top-0 h-full bg-background border-l shadow-2xl z-50 flex flex-col"
        style={{ width: drawerWidth }}
      >
        {/* Resize handle */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 transition-colors z-10"
          onMouseDown={handleDragStart}
        />

        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="font-semibold">小说设置</h2>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex px-5 pt-3 pb-0 gap-1 shrink-0">
          {([
            { key: 'content' as const, label: '小说内容' },
            { key: 'creation' as const, label: '创作设置' },
            { key: 'context' as const, label: '上下文配置' },
          ]).map(tab => (
            <button
              key={tab.key}
              onClick={() => handleTabChange(tab.key)}
              className={`flex-1 py-2 text-sm font-medium rounded-t-lg border border-b-0 transition-colors ${
                activeTab === tab.key
                  ? 'bg-background text-foreground border-border'
                  : 'bg-muted/40 text-muted-foreground border-transparent hover:text-foreground'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* ═══════════════════ Tab 1: 小说内容 ═══════════════════ */}
          {activeTab === 'content' && (
            <>
              {/* Basic info */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">基本信息</label>
                <div className="space-y-3">
                  <div>
                    <label className="text-sm font-medium mb-1 block">标题</label>
                    <input
                      value={title}
                      onChange={e => setTitle(e.target.value)}
                      className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-2 block">类型</label>
                    <div className="flex flex-wrap gap-1.5">
                      {GENRES.map(g => (
                        <button
                          key={g}
                          onClick={() => setGenre(g)}
                          className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${genre === g ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}
                        >
                          {g}
                        </button>
                      ))}
                      <button
                        onClick={() => { if (GENRES.includes(genre)) setGenre('') }}
                        className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${!GENRES.includes(genre) ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}
                      >
                        自定义
                      </button>
                    </div>
                    {!GENRES.includes(genre) && (
                      <input
                        value={genre}
                        onChange={e => setGenre(e.target.value)}
                        placeholder="输入自定义类型..."
                        className="mt-1.5 w-full border rounded-lg px-3 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                    )}
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-2 block">写作风格</label>
                    <div className="flex flex-wrap gap-1.5">
                      {STYLES.map(s => (
                        <button
                          key={s}
                          onClick={() => setWritingStyle(s)}
                          className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${writingStyle === s ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}
                        >
                          {s}
                        </button>
                      ))}
                      <button
                        onClick={() => { if (STYLES.includes(writingStyle)) setWritingStyle('') }}
                        className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${!STYLES.includes(writingStyle) ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}
                      >
                        自定义
                      </button>
                    </div>
                    {!STYLES.includes(writingStyle) && (
                      <input
                        value={writingStyle}
                        onChange={e => setWritingStyle(e.target.value)}
                        placeholder="输入自定义风格..."
                        className="mt-1.5 w-full border rounded-lg px-3 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                    )}
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-2 block">目标长度</label>
                    <div className="flex gap-2">
                      {LENGTHS.map(l => (
                        <button
                          key={l}
                          onClick={() => setTargetLength(l)}
                          className={`flex-1 py-1.5 rounded-lg text-sm border transition-colors ${targetLength === l ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}
                        >
                          {l}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* World setting */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">世界观设定</label>
                  <button
                    onClick={handleToggleSplit}
                    className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                      splitWorld ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'
                    }`}
                  >
                    {splitWorld ? '合并显示' : '拆分等级体系'}
                  </button>
                </div>

                {splitWorld ? (
                  <div className="space-y-3">
                    <div>
                      <label className="text-sm font-medium mb-1 block">背景设定</label>
                      <textarea
                        value={backgroundSetting}
                        onChange={e => setBackgroundSetting(e.target.value)}
                        disabled={optimizing}
                        placeholder="世界背景、时代、国家、势力分布..."
                        className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y min-h-[7rem] focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60 disabled:cursor-not-allowed"
                      />
                    </div>
                    <div>
                      <label className="text-sm font-medium mb-1 block">等级设定</label>
                      <textarea
                        value={rankSetting}
                        onChange={e => setRankSetting(e.target.value)}
                        placeholder="修炼等级、境界划分、战力体系..."
                        className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y min-h-[7rem] focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                    </div>
                  </div>
                ) : (
                  <textarea
                    value={coreSetting}
                    onChange={e => setCoreSetting(e.target.value)}
                    disabled={optimizing}
                    placeholder="世界观、规则、时代背景..."
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y min-h-[7rem] focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60 disabled:cursor-not-allowed"
                  />
                )}
                <button
                  onClick={handleOptimizeWorld}
                  disabled={optimizing || (!splitWorld && !coreSetting.trim()) || (splitWorld && !backgroundSetting.trim())}
                  className={`mt-1.5 flex items-center gap-1.5 text-xs transition-opacity ${
                    optimizing
                      ? 'text-muted-foreground cursor-not-allowed'
                      : 'text-primary hover:opacity-75 disabled:opacity-40 disabled:cursor-not-allowed'
                  }`}
                >
                  {optimizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
                  {optimizing ? '正在优化...' : splitWorld ? 'AI 优化背景设定' : 'AI 优化世界观'}
                </button>
              </div>

              {/* 全书概要（长程记忆） */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">全书概要（长程记忆）</label>
                  <button
                    onClick={handleGenerateBookSummary}
                    disabled={generatingBookSummary}
                    className={`flex items-center gap-1.5 text-xs transition-opacity ${
                      generatingBookSummary ? 'text-muted-foreground cursor-not-allowed' : 'text-primary hover:opacity-75'
                    }`}
                  >
                    {generatingBookSummary ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BookOpen className="w-3.5 h-3.5" />}
                    {generatingBookSummary ? '生成中...' : '重新整理'}
                  </button>
                </div>
                <textarea
                  value={bookSummary}
                  onChange={e => setBookSummary(e.target.value)}
                  placeholder="写了一定章节后，点击「重新整理」让 AI 从所有章节摘要生成全书概要..."
                  className="w-full border rounded-lg px-4 py-3 text-sm bg-background resize-y min-h-[10rem] focus:outline-none focus:ring-1 focus:ring-ring"
                />
                <p className="text-xs text-muted-foreground mt-1.5">覆盖 rolling_summary 无法触及的早期剧情，保存时同步入库。</p>
              </div>
            </>
          )}

          {/* ═══════════════════ Tab 2: 创作设置（菜单列表）═══════════════════ */}
          {activeTab === 'creation' && (
            <div className="space-y-1">
              {CREATION_SECTIONS.map(({ key, label, desc, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setActiveSection(key)}
                  className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-left hover:bg-muted/60 transition-colors group"
                >
                  <div className="p-2 rounded-lg bg-muted group-hover:bg-primary/10 transition-colors shrink-0">
                    <Icon className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{label}</p>
                    <p className="text-xs text-muted-foreground truncate">{desc}</p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
                </button>
              ))}
            </div>
          )}

          {/* ═══════════════════ Tab 3: 上下文配置 ═══════════════════ */}
          {activeTab === 'context' && (
            <ContextConfigContent novelId={novel.id} novel={novel} />
          )}
        </div>

        {activeTab !== 'context' && (
          <div className="px-5 py-4 border-t shrink-0">
            <button
              onClick={handleSave}
              disabled={saving}
              className="w-full flex items-center justify-center gap-2 bg-primary text-primary-foreground py-2 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {saved ? '已保存' : saving ? '保存中...' : '保存'}
            </button>
          </div>
        )}
      </div>

      {/* ═══════════ Creation detail panel (slides left) ═══════════ */}
      {activeSection && (
        <>
          <div className="fixed inset-0 z-[55]" onClick={() => setActiveSection(null)} />
          <div
            className="fixed top-0 h-full bg-background border-r shadow-2xl z-[56] flex flex-col"
            style={{ width: 480, right: drawerWidth }}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
              <h3 className="text-sm font-semibold">
                {CREATION_SECTIONS.find(s => s.key === activeSection)?.label}
              </h3>
              <button onClick={() => setActiveSection(null)} className="p-1.5 rounded-md hover:bg-muted transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              {/* ── 提示词与示例 ── */}
              {activeSection === 'prompt' && (
                <>
                  <div>
                    <label className="text-sm font-medium mb-2 block">自定义 Writer 提示词</label>
                    {writerPresets.length > 0 && (
                      <select
                        defaultValue=""
                        onChange={e => {
                          const preset = writerPresets.find(p => p.id === Number(e.target.value))
                          if (preset) {
                            setWriterSystemPrompt(preset.prompt)
                            setWriterExamples(preset.examples || [])
                          }
                          e.target.value = ''
                        }}
                        className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring mb-2"
                      >
                        <option value="">从预设填充...</option>
                        {writerPresets.map(p => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                    )}
                    <textarea
                      value={writerSystemPrompt}
                      onChange={e => setWriterSystemPrompt(e.target.value)}
                      placeholder="追加到 Writer 系统提示词末尾，例如：叙述视角为第一人称、对话使用古文风格..."
                      className="w-full border rounded-lg px-4 py-3 text-sm bg-background resize-y min-h-[8rem] focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    <p className="text-xs text-muted-foreground mt-1.5">此提示词将追加到 Writer Agent 模板末尾，优先级最高。</p>

                    <div className="mt-3 border rounded-lg overflow-hidden">
                      <button
                        onClick={() => setShowPromptPreview(v => !v)}
                        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted transition-colors"
                      >
                        {showPromptPreview ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                        预览完整 Writer System Prompt
                      </button>
                      {showPromptPreview && (
                        <pre className="px-3 py-2 text-xs leading-relaxed bg-muted/40 whitespace-pre-wrap break-words border-t font-mono max-h-64 overflow-y-auto">
{writerSystemPrompt.trim()
  ? writerSystemPrompt.trim()
  : `你是一位专业的中文小说作家，擅长${genre || '（未设置类型）'}类型的写作，文风${writingStyle || '（未设置风格）'}。
你的任务是根据以下背景资料，创作小说的章节正文。

严格要求：
- 保持角色性格和状态的一致性
- 情节必须符合已有大纲走向
- 不要与历史章节内容重复或矛盾
- 直接输出正文，不要章节标题
- 目标字数约 （生成时由用户指定） 字
- 严格遵守用户指令中指定的角色姓名，不得擅自更改或替换`}
                        </pre>
                      )}
                    </div>

                    <ExampleTurnsEditor value={writerExamples} onChange={setWriterExamples} />
                  </div>
                </>
              )}

              {/* ── 写作规则 ── */}
              {activeSection === 'rules' && (
                <div className="space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-xs text-muted-foreground">
                      勾选的规则会拼进本书 Writer 的系统提示词。规则内容在规则广场里改，改完立刻生效。
                    </p>
                    <a
                      href="/rules"
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-primary hover:underline flex items-center gap-1 shrink-0"
                    >
                      管理规则库 <ExternalLink className="w-3 h-3" />
                    </a>
                  </div>

                  {enabledRuleIds === null && (
                    <p className="text-xs px-3 py-2 rounded-lg bg-muted/60 text-muted-foreground">
                      本书未配置，当前默认启用全部内置规则。改动勾选后才会写入本书。
                    </p>
                  )}

                  {!ruleSelectionReady ? (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground py-6">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载规则库...
                    </div>
                  ) : promptRules.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-6">规则库是空的，先去规则广场新建规则。</p>
                  ) : (
                    <div className="space-y-1.5">
                      {promptRules.map(rule => (
                        <label
                          key={rule.id}
                          className={`flex items-start gap-2.5 px-3 py-2.5 border rounded-lg cursor-pointer hover:bg-muted/40 transition-colors ${rule.enabled ? '' : 'opacity-50'}`}
                        >
                          <input
                            type="checkbox"
                            checked={effectiveRuleIds.includes(rule.id)}
                            onChange={() => toggleRule(rule.id)}
                            className="mt-0.5 shrink-0"
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm">{rule.name}</span>
                              {rule.is_builtin && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">内置</span>
                              )}
                              {!rule.enabled && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                                  规则库已停用，不会注入
                                </span>
                              )}
                            </div>
                            {rule.content && (
                              <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 whitespace-pre-wrap">{rule.content}</p>
                            )}
                          </div>
                        </label>
                      ))}
                    </div>
                  )}

                  {enabledRuleIds !== null && effectiveRuleIds.length === 0 && (
                    <p className="text-xs px-3 py-2 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-500">
                      一条都没勾选，保存后本书将不带任何写作规则（包括去 AI 味护栏）。
                    </p>
                  )}
                </div>
              )}

              {/* ── 题材腔调卡 ── */}
              {activeSection === 'genreCard' && (
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground">
                    题材卡给写手校准场景选择、对话声线和爽点落法，作为参考资料注入，不会出现在正文里。
                    默认按「类型」（当前：{genre || '未设置'}）自动匹配。
                  </p>

                  <div className="space-y-1.5">
                    <label className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer hover:bg-muted/60 transition-colors">
                      <input
                        type="radio"
                        checked={genreCard === ''}
                        onChange={() => setGenreCard('')}
                        className="mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">自动匹配（推荐）</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {autoMatched
                            ? `按当前类型命中「${autoMatched}」，改类型时跟着变`
                            : `当前类型匹配不到卡，本书不会注入题材卡`}
                        </p>
                      </div>
                    </label>

                    {genreCards.map(card => (
                      <label
                        key={card.name}
                        className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer hover:bg-muted/60 transition-colors"
                      >
                        <input
                          type="radio"
                          checked={genreCard === card.name}
                          onChange={() => setGenreCard(card.name)}
                          className="mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium">{card.name}</p>
                          {card.aliases.length > 0 && (
                            <p className="text-[0.625rem] text-muted-foreground mt-0.5">
                              也涵盖：{card.aliases.join('、')}
                            </p>
                          )}
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 whitespace-pre-wrap">
                            {card.body.replace(/\*\*/g, '')}
                          </p>
                        </div>
                      </label>
                    ))}

                    <label className="flex items-start gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer hover:bg-muted/60 transition-colors">
                      <input
                        type="radio"
                        checked={genreCard === genreCardOff}
                        onChange={() => setGenreCard(genreCardOff)}
                        className="mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium">不使用题材卡</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          本书完全不注入，适合自定义提示词里已经写了腔调要求
                        </p>
                      </div>
                    </label>
                  </div>

                  {activeCardBody && (
                    <div>
                      <button
                        onClick={() => setShowCardPreview(!showCardPreview)}
                        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        {showCardPreview ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                        查看「{activeCardName}」注入的完整内容
                      </button>
                      {showCardPreview && (
                        <pre className="mt-2 text-xs bg-muted/50 rounded-lg p-3 whitespace-pre-wrap max-h-64 overflow-y-auto">
                          {activeCardBody}
                        </pre>
                      )}
                    </div>
                  )}

                  <p className="text-xs px-3 py-2 rounded-lg bg-muted/60 text-muted-foreground">
                    上下文配置页的「题材腔调卡」开关是临时调整这一次的上下文，这里选的是作品长期设定。
                  </p>
                </div>
              )}

              {/* ── 模型选择 ── */}
              {activeSection === 'models' && (
                <div className="space-y-4">
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Writer 模型</label>
                    <ModelSelect value={writerModel} onChange={v => {
                      setWriterModel(v)
                      if (enableFullTextContext) {
                        setEnableFullTextContext(false)
                        toast('已自动关闭全文上下文，切换模型后需手动重新开启', { icon: '⚠️' })
                      }
                    }} placeholder="留空使用全局设置" models={modelLibrary.filter(m => m.model_type !== 'embedding')} />
                    <p className="text-xs text-muted-foreground mt-1.5">用于章节正文生成的主力模型</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Fast 模型</label>
                    <ModelSelect value={fastModel} onChange={setFastModel} placeholder="留空使用全局设置" models={modelLibrary.filter(m => m.model_type !== 'embedding')} />
                    <p className="text-xs text-muted-foreground mt-1.5">用于摘要、角色分析等低成本任务</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">Critic 模型</label>
                    <ModelSelect value={criticModel} onChange={setCriticModel} placeholder="留空使用 Fast 模型" models={modelLibrary.filter(m => m.model_type !== 'embedding')} />
                    <p className="text-xs text-muted-foreground mt-1.5">用于章节审查和评分</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">细节审查模型</label>
                    <ModelSelect value={detailReviewModel} onChange={setDetailReviewModel} placeholder="留空使用全局设置" models={modelLibrary.filter(m => m.model_type !== 'embedding')} />
                    <p className="text-xs text-muted-foreground mt-1.5">用于剧情细节审查，检查连续性、重复、矛盾和时间线问题</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium mb-1.5 block">嵌入模型</label>
                    <select
                      value={modelSelectValue(modelLibrary, embeddingModel)}
                      onChange={e => setEmbeddingModel(e.target.value)}
                      className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      <option value="">默认 (all-MiniLM-L6-v2, 本地)</option>
                      {modelLibrary.filter(m => m.model_type === 'embedding').map(m => (
                        <option key={m.id} value={String(m.id)}>
                          [{m.provider}] {m.display_name || m.model_id}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-muted-foreground mt-1.5">
                      用于 RAG 向量检索，中文小说推荐使用中文优化的嵌入模型。更换后将自动重建向量库
                    </p>
                  </div>

                  <div className="border-t pt-5 space-y-5">
                    <p className="text-sm font-semibold">生成参数</p>
                    <div className="flex items-center justify-between">
                      <div className="flex-1 mr-4">
                        <p className="text-sm font-medium">DeepSeek 深度思考</p>
                        <p className="text-xs text-muted-foreground mt-1">DeepSeek 模型的 reasoning_effort，关闭可减少空响应并约束输出长度</p>
                      </div>
                      <select
                        value={deepseekThinking}
                        onChange={e => setDeepseekThinking(e.target.value)}
                        className="text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      >
                        <option value="off">关闭</option>
                        <option value="high">高（默认）</option>
                        <option value="max">最高</option>
                      </select>
                    </div>

                    <div className="flex items-center justify-between">
                      <div className="flex-1 mr-4">
                        <p className="text-sm font-medium">Gemini 深度思考</p>
                        <p className="text-xs text-muted-foreground mt-1">Gemini 模型的 thinking_level，关闭可减少空响应</p>
                      </div>
                      <select
                        value={geminiThinking}
                        onChange={e => setGeminiThinking(e.target.value)}
                        className="text-sm border rounded-lg px-3 py-2 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      >
                        <option value="off">关闭</option>
                        <option value="low">低</option>
                        <option value="medium">中（默认）</option>
                        <option value="high">高</option>
                      </select>
                    </div>

                    <div className="flex items-center justify-between">
                      <div className="flex-1 mr-4">
                        <p className="text-sm font-medium">Gemini 真实流式</p>
                        <p className="text-xs text-muted-foreground mt-1">逐字输出、减少等待。关闭时为一次性大请求，在不稳定代理上易被闪断导致整章失败；建议保持开启</p>
                      </div>
                      <button
                        onClick={() => setGeminiStream(!geminiStream)}
                        className={`relative w-10 h-5 rounded-full transition-colors ${geminiStream ? 'bg-primary' : 'bg-muted-foreground/30'}`}
                      >
                        <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${geminiStream ? 'translate-x-5' : ''}`} />
                      </button>
                    </div>

                    <div className="border-t pt-5">
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium">生成温度</label>
                        <span className="text-sm font-mono text-muted-foreground">{writerTemperature.toFixed(2)}</span>
                      </div>
                      <input
                        type="range"
                        min={0.1}
                        max={1.5}
                        step={0.05}
                        value={writerTemperature}
                        onChange={e => setWriterTemperature(Number(e.target.value))}
                        disabled={!writerUseCustomTemperature}
                        className={`w-full accent-primary ${!writerUseCustomTemperature ? 'opacity-30' : ''}`}
                      />
                      <div className="flex justify-between text-xs text-muted-foreground mt-1">
                        <span>保守 0.1</span>
                        <span>1.5 发散</span>
                      </div>
                      <div className="flex items-center gap-2 mt-2">
                        <button
                          onClick={() => setWriterUseCustomTemperature(v => !v)}
                          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors ${writerUseCustomTemperature ? 'bg-primary' : 'bg-muted'}`}
                        >
                          <span className={`inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${writerUseCustomTemperature ? 'translate-x-4' : 'translate-x-0'}`} />
                        </button>
                        <span className="text-xs text-muted-foreground">
                          {writerUseCustomTemperature ? '发送温度参数（关闭以兼容不支持温度的模型）' : '不发送温度参数（使用模型默认值）'}
                        </span>
                      </div>
                    </div>

                    <div>
                      <label className="text-sm font-medium mb-1.5 block">最大输出 Token</label>
                      <select
                        value={writerMaxTokens}
                        onChange={e => setWriterMaxTokens(Number(e.target.value))}
                        className="w-full border rounded-lg px-3 py-2.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      >
                        <option value={2048}>2048（约 1500 字）</option>
                        <option value={4096}>4096（约 3000 字）</option>
                        <option value={8192}>8192（约 6000 字）</option>
                        <option value={16384}>16384（约 12000 字，默认）</option>
                      </select>
                    </div>

                    <div className="border-t pt-5 space-y-5">
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="text-sm font-medium">滚动摘要最大章数</label>
                          <input
                            type="number"
                            min={3}
                            max={12}
                            value={rollingSummaryCount}
                            onChange={e => setRollingSummaryCount(Math.max(3, Math.min(12, Number(e.target.value) || 3)))}
                            className="w-20 text-center border rounded-lg px-2 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                          />
                        </div>
                        <p className="text-xs text-muted-foreground">动态预算内从近到远装填，至少保障 3 章；该值仅作为上限</p>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <label className="text-sm font-medium">RAG 最大检索条数</label>
                          <input
                            type="number"
                            min={0}
                            max={10}
                            value={ragTopK}
                            onChange={e => setRagTopK(Math.max(0, Math.min(10, Number(e.target.value) || 0)))}
                            className="w-20 text-center border rounded-lg px-2 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                          />
                        </div>
                        <p className="text-xs text-muted-foreground">在动态预算和相关性约束内选取历史摘要；该值仅作为上限，0 表示关闭</p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* ── 全文上下文（实验）── */}
              {activeSection === 'fulltext' && (
                <div className="space-y-5">
                  <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
                    <div className="flex gap-2">
                      <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                      <div className="text-xs text-amber-700 dark:text-amber-400 space-y-1">
                        <p className="font-medium">实验性功能</p>
                        <p>开启后，上下文构建时会将前 N 章的完整正文一字不差地传入 LLM，Token 消耗极高。</p>
                        <p>建议搭配高性价比模型使用，如 DeepSeek V3/R1、Gemini 免费额度等。切换 Writer 模型时此功能会自动关闭。</p>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex-1 mr-4">
                      <p className="text-sm font-medium">启用全文上下文</p>
                      <p className="text-xs text-muted-foreground mt-1">将前 N 章正文全量作为上下文记忆传给 LLM</p>
                    </div>
                    <button
                      onClick={() => {
                        if (!enableFullTextContext) {
                          const ok = window.confirm(
                            '开启全文上下文会大幅增加 Token 消耗，请确保使用高性价比模型（如 DeepSeek V3/R1、Gemini 免费额度等）。\n\n确定开启？'
                          )
                          if (!ok) return
                        }
                        setEnableFullTextContext(v => !v)
                      }}
                      className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors ${enableFullTextContext ? 'bg-primary' : 'bg-muted'}`}
                    >
                      <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${enableFullTextContext ? 'translate-x-5' : 'translate-x-0'}`} />
                    </button>
                  </div>

                  {enableFullTextContext && (
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <label className="text-sm font-medium">读取章节数</label>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={fullTextChapters}
                          onChange={e => setFullTextChapters(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
                          className="w-20 text-center border rounded-lg px-2 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                        />
                      </div>
                      <p className="text-xs text-muted-foreground">将当前章节之前最近 N 章的完整正文作为上下文传入</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Save button in detail panel */}
            <div className="px-6 py-4 border-t shrink-0">
              <button
                onClick={handleSave}
                disabled={saving}
                className="w-full flex items-center justify-center gap-2 bg-primary text-primary-foreground py-2.5 rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
                {saved ? '已保存' : saving ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
