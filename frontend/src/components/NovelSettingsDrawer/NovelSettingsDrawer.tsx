import { useState, useEffect } from 'react'
import toast from 'react-hot-toast'
import { X, Save, Loader2, ChevronDown, ChevronRight, Wand2, BookOpen } from 'lucide-react'
import { novelsApi, modelLibraryApi, writerPresetsApi, type Novel, type ModelEntry } from '@/api/client'
import { useQueryClient, useQuery } from '@tanstack/react-query'

interface Props {
  novel: Novel
  onClose: () => void
}

const GENRES = ['古代权谋', '现代都市', '玄幻', '悬疑推理', '言情', '科幻', '历史', '其他']
const STYLES = ['严肃厉重', '轻快幽默', '悬念紧张', '细腻文艺', '热血激昂']
const LENGTHS = ['短篇', '中篇', '长篇']

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
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
    >
      <option value="">{placeholder}</option>
      {models.map(m => (
        <option key={m.id} value={m.model_id}>
          [{m.provider}] {m.display_name || m.model_id}
        </option>
      ))}
    </select>
  )
}

export default function NovelSettingsDrawer({ novel, onClose }: Props) {
  const qc = useQueryClient()
  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const [title, setTitle] = useState(novel.title)
  const [genre, setGenre] = useState(novel.genre)
  const [writingStyle, setWritingStyle] = useState(novel.writing_style)
  const [targetLength, setTargetLength] = useState(novel.target_length)
  const [coreSetting, setCoreSetting] = useState(novel.core_setting)
  const [writerSystemPrompt, setWriterSystemPrompt] = useState(novel.writer_system_prompt || '')
  const [writerModel, setWriterModel] = useState(novel.writer_model || '')
  const [fastModel, setFastModel] = useState(novel.fast_model || '')
  const [enableCritic, setEnableCritic] = useState(novel.enable_critic ?? true)
  const [writerTemperature, setWriterTemperature] = useState(novel.writer_temperature ?? 0.85)
  const [writerMaxTokens, setWriterMaxTokens] = useState(novel.writer_max_tokens ?? 4096)
  const [rollingSummaryCount, setRollingSummaryCount] = useState(novel.rolling_summary_count ?? 5)
  const [ragTopK, setRagTopK] = useState(novel.rag_top_k ?? 3)
  const [chatContextRounds, setChatContextRounds] = useState(novel.chat_context_rounds ?? 20)
  const [thinkingLevel, setThinkingLevel] = useState(novel.thinking_level || 'medium')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [optimizing, setOptimizing] = useState(false)
  const [showPromptPreview, setShowPromptPreview] = useState(false)
  const [bookSummary, setBookSummary] = useState(novel.book_summary || '')
  const [generatingBookSummary, setGeneratingBookSummary] = useState(false)

  useEffect(() => {
    setTitle(novel.title)
    setGenre(novel.genre)
    setWritingStyle(novel.writing_style)
    setTargetLength(novel.target_length)
    setCoreSetting(novel.core_setting)
    setWriterSystemPrompt(novel.writer_system_prompt || '')
    setWriterModel(novel.writer_model || '')
    setFastModel(novel.fast_model || '')
    setEnableCritic(novel.enable_critic ?? true)
    setWriterTemperature(novel.writer_temperature ?? 0.85)
    setWriterMaxTokens(novel.writer_max_tokens ?? 4096)
    setRollingSummaryCount(novel.rolling_summary_count ?? 5)
    setRagTopK(novel.rag_top_k ?? 3)
    setChatContextRounds(novel.chat_context_rounds ?? 20)
    setThinkingLevel(novel.thinking_level || 'medium')
    setBookSummary(novel.book_summary || '')
  }, [novel.id])

  const { data: writerPresets = [] } = useQuery({
    queryKey: ['writer-presets'],
    queryFn: writerPresetsApi.list,
  })

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
      const result = await novelsApi.optimizeWorld(novel.id, coreSetting)
      setCoreSetting(result.core_setting)
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
        writing_style: writingStyle,
        target_length: targetLength,
        core_setting: coreSetting,
        book_summary: bookSummary,
        writer_system_prompt: writerSystemPrompt,
        writer_model: writerModel,
        fast_model: fastModel,
        enable_critic: enableCritic,
        writer_temperature: writerTemperature,
        writer_max_tokens: writerMaxTokens,
        rolling_summary_count: rollingSummaryCount,
        rag_top_k: ragTopK,
        chat_context_rounds: chatContextRounds,
        thinking_level: thinkingLevel,
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
        onClick={onClose}
      />
      {/* Drawer */}
      <div className="fixed right-0 top-0 h-full w-96 bg-background border-l shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="font-semibold">小说设置</h2>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
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
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">世界观设定</label>
            <textarea
              value={coreSetting}
              onChange={e => setCoreSetting(e.target.value)}
              disabled={optimizing}
              placeholder="世界观、规则、时代背景..."
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none h-28 focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60 disabled:cursor-not-allowed"
            />
            <button
              onClick={handleOptimizeWorld}
              disabled={optimizing || !coreSetting.trim()}
              className={`mt-1.5 flex items-center gap-1.5 text-xs transition-opacity ${
                optimizing
                  ? 'text-muted-foreground cursor-not-allowed'
                  : !coreSetting.trim()
                  ? 'text-primary opacity-40 cursor-not-allowed'
                  : 'text-primary hover:opacity-75'
              }`}
            >
              {optimizing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
              {optimizing ? '正在优化...' : 'AI 优化世界观'}
            </button>
          </div>

          {/* Book Summary */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">全书概要（长程记忆）</label>
              <button
                onClick={handleGenerateBookSummary}
                disabled={generatingBookSummary}
                className={`flex items-center gap-1.5 text-xs transition-opacity ${
                  generatingBookSummary
                    ? 'text-muted-foreground cursor-not-allowed'
                    : 'text-primary hover:opacity-75'
                }`}
              >
                {generatingBookSummary ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BookOpen className="w-3.5 h-3.5" />}
                {generatingBookSummary ? '生成中...' : '重新整理'}
              </button>
            </div>
            <textarea
              value={bookSummary}
              onChange={e => setBookSummary(e.target.value)}
              placeholder="写了一定章节后，点击「重新整理」让 AI 从所有章节摘要生成全书概要，之后生成新章节时会自动携带此概要作为长程记忆..."
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none h-28 focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <p className="text-xs text-muted-foreground mt-1">覆盖 rolling_summary（5章）无法触及的早期剧情，保存时同步入库。</p>
          </div>

          {/* Custom Writer prompt */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">自定义 Writer 提示词</label>
            {writerPresets.length > 0 && (
              <select
                defaultValue=""
                onChange={e => {
                  const preset = writerPresets.find(p => p.id === Number(e.target.value))
                  if (preset) setWriterSystemPrompt(preset.prompt)
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
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none h-24 focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <p className="text-xs text-muted-foreground mt-1">此提示词将追加到 Writer Agent 模板末尾，优先级最高。</p>

            {/* Prompt preview */}
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
          </div>

          {/* Per-novel model override */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">本小说模型覆盖（可选）</label>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium mb-1 block">Writer 模型</label>
                <ModelSelect
                  value={writerModel}
                  onChange={setWriterModel}
                  placeholder="留空使用全局设置"
                  models={modelLibrary}
                />
              </div>
              <div>
                <label className="text-sm font-medium mb-1 block">Fast 模型</label>
                <ModelSelect
                  value={fastModel}
                  onChange={setFastModel}
                  placeholder="留空使用全局设置"
                  models={modelLibrary}
                />
              </div>
            </div>
          </div>

          {/* Generation params */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">生成参数</label>
            <div className="space-y-4">
              {/* Critic toggle */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Critic 审查</p>
                  <p className="text-xs text-muted-foreground mt-0.5">关闭后跳过质量审查，直接保存生成内容</p>
                </div>
                <button
                  onClick={() => setEnableCritic(v => !v)}
                  className={`relative inline-flex h-6 w-11 shrink-0 rounded-full border-2 border-transparent transition-colors ${enableCritic ? 'bg-primary' : 'bg-muted'}`}
                >
                  <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition-transform ${enableCritic ? 'translate-x-5' : 'translate-x-0'}`} />
                </button>
              </div>

              {/* Thinking level */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Thinking 深度思考</p>
                  <p className="text-xs text-muted-foreground mt-0.5">控制 Gemini 思考强度，关闭可减少空响应</p>
                </div>
                <select
                  value={thinkingLevel}
                  onChange={e => setThinkingLevel(e.target.value)}
                  className="text-sm border rounded-lg px-2 py-1.5 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="off">关闭</option>
                  <option value="low">低</option>
                  <option value="medium">中（默认）</option>
                  <option value="high">高</option>
                </select>
              </div>

              {/* Temperature slider */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
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
                  className="w-full accent-primary"
                />
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>保守 0.1</span>
                  <span>1.5 发散</span>
                </div>
              </div>

              {/* Max tokens */}
              <div>
                <label className="text-sm font-medium mb-1 block">最大输出 Token</label>
                <select
                  value={writerMaxTokens}
                  onChange={e => setWriterMaxTokens(Number(e.target.value))}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value={2048}>2048（约 1500 字）</option>
                  <option value={4096}>4096（约 3000 字，默认）</option>
                  <option value={8192}>8192（约 6000 字）</option>
                  <option value={16384}>16384（约 12000 字）</option>
                </select>
              </div>
            </div>
          </div>

          {/* Generation context */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">生成上下文</label>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium">滚动摘要章数</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={rollingSummaryCount}
                    onChange={e => setRollingSummaryCount(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                    className="w-16 text-center border rounded-lg px-2 py-1 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <p className="text-xs text-muted-foreground">生成章节时携带最近 N 章的摘要作为中程记忆</p>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium">RAG 检索条数</label>
                  <input
                    type="number"
                    min={0}
                    max={10}
                    value={ragTopK}
                    onChange={e => setRagTopK(Math.max(0, Math.min(10, Number(e.target.value) || 0)))}
                    className="w-16 text-center border rounded-lg px-2 py-1 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <p className="text-xs text-muted-foreground">生成章节时从历史章节中检索最相关的 N 条摘要，0 表示关闭</p>
              </div>
            </div>
          </div>

          {/* Chat context */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">对话上下文</label>
            <div className="space-y-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium">对话历史轮数</label>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={chatContextRounds}
                    onChange={e => setChatContextRounds(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
                    className="w-16 text-center border rounded-lg px-2 py-1 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <p className="text-xs text-muted-foreground">与 AI 助手对话时携带的最近消息轮数，0 表示不限制</p>
              </div>
            </div>
          </div>
        </div>

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
      </div>
    </>
  )
}
