import { useState, useEffect } from 'react'
import { X, Save, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { novelsApi, modelLibraryApi, type Novel, type ModelEntry } from '@/api/client'
import { useQueryClient } from '@tanstack/react-query'

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
  const [modelLibrary, setModelLibrary] = useState<ModelEntry[]>([])
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
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [showPromptPreview, setShowPromptPreview] = useState(false)

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
  }, [novel.id])

  useEffect(() => {
    modelLibraryApi.list().then(setModelLibrary)
  }, [])

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
        writer_system_prompt: writerSystemPrompt,
        writer_model: writerModel,
        fast_model: fastModel,
        enable_critic: enableCritic,
        writer_temperature: writerTemperature,
        writer_max_tokens: writerMaxTokens,
      })
      qc.invalidateQueries({ queryKey: ['novel', novel.id] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
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
                </div>
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
                </div>
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
              placeholder="世界观、规则、时代背景..."
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-none h-28 focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          {/* Custom Writer prompt */}
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 block">自定义 Writer 提示词</label>
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
