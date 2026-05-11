import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle, XCircle, Loader2, Save, Key, Sun, Moon, Radio, RadioTower, Plus, Pencil, Trash2, X } from 'lucide-react'
import { settingsApi, modelLibraryApi, providersApi, PROVIDER_PRESETS, type ModelEntry, type ApiProvider } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

// ── ModelSelect sub-component ─────────────────────────────────────────────

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
      className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
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

// ── Main Settings page ────────────────────────────────────────────────────

export default function Settings() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { theme, toggleTheme, streamingMode, toggleStreamingMode } = useSettingsStore()

  // ── Settings state (model assignments + proxy) ─────────────────────────
  const [writerModel, setWriterModel] = useState('')
  const [fastModel, setFastModel] = useState('')
  const [agentWriterModel, setAgentWriterModel] = useState('')
  const [agentCriticModel, setAgentCriticModel] = useState('')
  const [agentMemoryModel, setAgentMemoryModel] = useState('')
  const [agentOutlineModel, setAgentOutlineModel] = useState('')
  const [agentCharacterModel, setAgentCharacterModel] = useState('')
  const [agentOrchestratorModel, setAgentOrchestratorModel] = useState('')
  const [agentReviewModel, setAgentReviewModel] = useState('')
  const [enableReview, setEnableReview] = useState(false)
  const [reviewInterval, setReviewInterval] = useState(10)
  const [httpsProxy, setHttpsProxy] = useState('')
  const [httpProxy, setHttpProxy] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testModel, setTestModel] = useState('')
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  // ── Provider state ──────────────────────────────────────────────────────
  const { data: providers = [], refetch: refetchProviders } = useQuery({
    queryKey: ['providers'],
    queryFn: providersApi.list,
  })
  const [showProviderForm, setShowProviderForm] = useState(false)
  const [editingProviderId, setEditingProviderId] = useState<number | null>(null)
  const [providerName, setProviderName] = useState('')
  const [providerBaseUrl, setProviderBaseUrl] = useState('')
  const [providerApiKey, setProviderApiKey] = useState('')
  const [providerApiFormat, setProviderApiFormat] = useState('openai')
  const [providerSaving, setProviderSaving] = useState(false)

  // ── Model library state ─────────────────────────────────────────────────
  const { data: models = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formDisplayName, setFormDisplayName] = useState('')
  const [formModelId, setFormModelId] = useState('')
  const [formProviderId, setFormProviderId] = useState<number | null>(null)
  const [formModelType, setFormModelType] = useState('chat')
  const [modelSaving, setModelSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    settingsApi.get().then((s: {
      default_writer_model: string
      default_fast_model: string
      agent_writer_model: string
      agent_critic_model: string
      agent_memory_model: string
      agent_outline_model: string
      agent_character_model: string
      agent_orchestrator_model: string
      agent_review_model: string
      enable_review: boolean
      review_interval: number
      https_proxy: string
      http_proxy: string
    }) => {
      if (cancelled) return
      setWriterModel(s.default_writer_model)
      setFastModel(s.default_fast_model)
      setAgentWriterModel(s.agent_writer_model || '')
      setAgentCriticModel(s.agent_critic_model || '')
      setAgentMemoryModel(s.agent_memory_model || '')
      setAgentOutlineModel(s.agent_outline_model || '')
      setAgentCharacterModel(s.agent_character_model || '')
      setAgentOrchestratorModel(s.agent_orchestrator_model || '')
      setAgentReviewModel(s.agent_review_model || '')
      setEnableReview(s.enable_review ?? false)
      setReviewInterval(s.review_interval ?? 10)
      setHttpsProxy(s.https_proxy || '')
      setHttpProxy(s.http_proxy || '')
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      await settingsApi.update({
        default_writer_model: writerModel,
        default_fast_model: fastModel,
        agent_writer_model: agentWriterModel,
        agent_critic_model: agentCriticModel,
        agent_memory_model: agentMemoryModel,
        agent_outline_model: agentOutlineModel,
        agent_character_model: agentCharacterModel,
        agent_orchestrator_model: agentOrchestratorModel,
        agent_review_model: agentReviewModel,
        enable_review: enableReview,
        review_interval: reviewInterval,
        https_proxy: httpsProxy,
        http_proxy: httpProxy,
      })
      setTesting(true)
      const r = await settingsApi.test(testModel || undefined)
      setTestResult({ ok: r.ok, msg: r.ok ? `连接成功 [${r.api_format}] ${r.model}：${r.response}` : `[${r.api_format}] ${r.model}：${r.error}` })
    } finally {
      setSaving(false)
      setTesting(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await settingsApi.test(testModel || undefined)
      setTestResult({ ok: r.ok, msg: r.ok ? `连接成功 [${r.api_format}] ${r.model}：${r.response}` : `[${r.api_format}] ${r.model}：${r.error}` })
    } finally {
      setTesting(false)
    }
  }

  // ── Provider handlers ──────────────────────────────────────────────────

  const resetProviderForm = () => {
    setProviderName('')
    setProviderBaseUrl('')
    setProviderApiKey('')
    setProviderApiFormat('openai')
    setEditingProviderId(null)
    setShowProviderForm(false)
  }

  const handlePresetClick = (preset: typeof PROVIDER_PRESETS[number]) => {
    // Check if this preset is already added
    const exists = providers.find(p => p.name === preset.name)
    if (exists) {
      // Start editing the existing one
      startEditProvider(exists)
      return
    }
    setProviderName(preset.name)
    setProviderBaseUrl(preset.base_url)
    setProviderApiFormat(preset.api_format)
    setProviderApiKey('')
    setEditingProviderId(null)
    setShowProviderForm(true)
  }

  const startEditProvider = (p: ApiProvider) => {
    setEditingProviderId(p.id)
    setProviderName(p.name)
    setProviderBaseUrl(p.base_url)
    setProviderApiFormat(p.api_format)
    setProviderApiKey('')
    setShowProviderForm(true)
  }

  const handleProviderSubmit = async () => {
    if (!providerName.trim()) return
    setProviderSaving(true)
    try {
      if (editingProviderId !== null) {
        await providersApi.update(editingProviderId, {
          name: providerName,
          base_url: providerBaseUrl,
          api_key: providerApiKey || undefined,
          api_format: providerApiFormat,
        })
      } else {
        await providersApi.create({
          name: providerName,
          base_url: providerBaseUrl,
          api_key: providerApiKey,
          api_format: providerApiFormat,
        })
      }
      qc.invalidateQueries({ queryKey: ['providers'] })
      resetProviderForm()
    } finally {
      setProviderSaving(false)
    }
  }

  const handleProviderDelete = async (id: number) => {
    if (!confirm('确认删除此供应商？')) return
    try {
      await providersApi.delete(id)
      qc.invalidateQueries({ queryKey: ['providers'] })
    } catch (e: any) {
      alert(e?.response?.data?.detail || '删除失败')
    }
  }

  // ── Model library handlers ──────────────────────────────────────────────

  const resetForm = () => {
    setFormDisplayName('')
    setFormModelId('')
    setFormProviderId(null)
    setFormModelType('chat')
    setEditingId(null)
    setShowAddForm(false)
  }

  const startEdit = (m: ModelEntry) => {
    setEditingId(m.id)
    setFormDisplayName(m.display_name)
    setFormModelId(m.model_id)
    setFormProviderId(m.provider_id)
    setFormModelType(m.model_type || 'chat')
    setShowAddForm(true)
  }

  const handleModelSubmit = async () => {
    if (!formModelId.trim() || !formProviderId) return
    setModelSaving(true)
    try {
      if (editingId !== null) {
        await modelLibraryApi.update(editingId, {
          display_name: formDisplayName,
          model_id: formModelId,
          provider_id: formProviderId,
          model_type: formModelType,
        })
      } else {
        await modelLibraryApi.create({
          display_name: formDisplayName,
          model_id: formModelId,
          provider_id: formProviderId,
          model_type: formModelType,
        })
      }
      qc.invalidateQueries({ queryKey: ['model-library'] })
      resetForm()
    } finally {
      setModelSaving(false)
    }
  }

  const handleModelDelete = async (id: number) => {
    if (!confirm('确认删除此模型？')) return
    await modelLibraryApi.delete(id)
    qc.invalidateQueries({ queryKey: ['model-library'] })
  }

  const chatModels = models.filter(m => m.model_type !== 'embedding')

  const formatBadgeColor = (apiFormat: string) => {
    if (apiFormat === 'gemini') return 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
    if (apiFormat === 'anthropic') return 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300'
    return 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h1 className="font-bold text-lg">设置</h1>
        <button
          onClick={toggleTheme}
          className="ml-auto p-2 rounded-md hover:bg-muted transition-colors"
          title={theme === 'dark' ? '切换亮色模式' : '切换深色模式'}
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-10 space-y-8">

        {/* ── 1. 供应商配置 ──────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-2">供应商配置</h2>
          <p className="text-xs text-muted-foreground mb-4">
            添加 API 供应商（中转站或官方直连），每个供应商可配置独立的 Base URL 和 API Key。
          </p>

          {/* Preset chips */}
          <div className="flex flex-wrap gap-2 mb-4">
            {PROVIDER_PRESETS.map(preset => {
              const added = providers.some(p => p.name === preset.name)
              return (
                <button
                  key={preset.name}
                  onClick={() => handlePresetClick(preset)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    added
                      ? 'border-primary/50 bg-primary/10 text-primary'
                      : 'border-border hover:border-muted-foreground/50 hover:bg-muted'
                  }`}
                >
                  {added && <span className="mr-1">&#10003;</span>}
                  {preset.name}
                </button>
              )
            })}
            <button
              onClick={() => { resetProviderForm(); setShowProviderForm(true) }}
              className="text-xs px-3 py-1.5 rounded-full border border-dashed hover:bg-muted transition-colors flex items-center gap-1"
            >
              <Plus className="w-3 h-3" />
              自定义
            </button>
          </div>

          {/* Add / Edit provider form */}
          {showProviderForm && (
            <div className="border rounded-lg p-4 mb-4 bg-muted/30 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{editingProviderId ? '编辑供应商' : '添加供应商'}</span>
                <button onClick={resetProviderForm} className="p-1 rounded hover:bg-muted">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium mb-1 block">供应商名称 *</label>
                  <input
                    value={providerName}
                    onChange={e => setProviderName(e.target.value)}
                    placeholder="例：AiHubMix"
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">API 格式</label>
                  <select
                    value={providerApiFormat}
                    onChange={e => setProviderApiFormat(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="openai">OpenAI 兼容</option>
                    <option value="gemini">Gemini</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block">Base URL</label>
                <input
                  value={providerBaseUrl}
                  onChange={e => setProviderBaseUrl(e.target.value)}
                  placeholder="https://api.example.com/v1"
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
                />
              </div>
              <div>
                <label className="text-xs font-medium mb-1 block">API Key</label>
                <input
                  type="password"
                  value={providerApiKey}
                  onChange={e => setProviderApiKey(e.target.value)}
                  placeholder={editingProviderId ? '留空保持当前 Key 不变' : '输入 API Key'}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={resetProviderForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                  取消
                </button>
                <button
                  onClick={handleProviderSubmit}
                  disabled={!providerName.trim() || providerSaving}
                  className="text-sm px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {providerSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {editingProviderId ? '保存修改' : '添加'}
                </button>
              </div>
            </div>
          )}

          {/* Provider list */}
          {providers.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-6 border rounded-lg border-dashed">
              暂无供应商，点击上方预设或「自定义」添加
            </div>
          ) : (
            <div className="space-y-2">
              {providers.map(p => (
                <div key={p.id} className="flex items-center gap-3 border rounded-lg px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{p.name}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded-full font-mono ${formatBadgeColor(p.api_format)}`}>
                        {p.api_format}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-xs text-muted-foreground font-mono truncate">{p.base_url || '(default)'}</span>
                      {p.api_key_set && (
                        <>
                          <span className="text-xs text-muted-foreground">·</span>
                          <span className="text-xs text-muted-foreground flex items-center gap-1">
                            <Key className="w-3 h-3" />
                            {p.api_key_masked}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => startEditProvider(p)}
                      className="p-1.5 rounded hover:bg-muted transition-colors"
                      title="编辑"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleProviderDelete(p.id)}
                      className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── 2. 模型库 ───────────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-base">模型库</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                管理可选模型，每个模型关联一个供应商，请求将通过该供应商的 API 发送。
              </p>
            </div>
            {!showAddForm && (
              <button
                onClick={() => setShowAddForm(true)}
                className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                添加模型
              </button>
            )}
          </div>

          {/* Add / Edit form */}
          {showAddForm && (
            <div className="border rounded-lg p-4 mb-4 bg-muted/30 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{editingId ? '编辑模型' : '添加新模型'}</span>
                <button onClick={resetForm} className="p-1 rounded hover:bg-muted">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium mb-1 block">显示名称</label>
                  <input
                    value={formDisplayName}
                    onChange={e => setFormDisplayName(e.target.value)}
                    placeholder="例：Gemini 2.0 Flash"
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">模型 ID *</label>
                  <input
                    value={formModelId}
                    onChange={e => setFormModelId(e.target.value)}
                    placeholder="例：gemini-2.0-flash"
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium mb-1 block">供应商 *</label>
                  <select
                    value={formProviderId ?? ''}
                    onChange={e => setFormProviderId(e.target.value ? Number(e.target.value) : null)}
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="">请选择供应商</option>
                    {providers.map(p => (
                      <option key={p.id} value={p.id}>{p.name} ({p.api_format})</option>
                    ))}
                  </select>
                  {providers.length === 0 && (
                    <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">请先在上方添加至少一个供应商</p>
                  )}
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">模型类型</label>
                  <select
                    value={formModelType}
                    onChange={e => setFormModelType(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="chat">聊天模型</option>
                    <option value="embedding">嵌入模型</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={resetForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                  取消
                </button>
                <button
                  onClick={handleModelSubmit}
                  disabled={!formModelId.trim() || !formProviderId || modelSaving}
                  className="text-sm px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
                >
                  {modelSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {editingId ? '保存修改' : '添加'}
                </button>
              </div>
            </div>
          )}

          {/* Model list */}
          {models.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-6 border rounded-lg border-dashed">
              暂无模型，点击「添加模型」开始配置
            </div>
          ) : (
            <div className="space-y-2">
              {models.map(m => (
                <div key={m.id} className="flex items-center gap-3 border rounded-lg px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium truncate">{m.display_name || m.model_id}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded-full font-mono ${formatBadgeColor(m.api_format)}`}>
                        {m.api_format}
                      </span>
                      {m.model_type === 'embedding' && (
                        <span className="text-xs px-1.5 py-0.5 rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300">
                          嵌入
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-xs text-muted-foreground font-mono">{m.model_id}</span>
                      <span className="text-xs text-muted-foreground">·</span>
                      <span className="text-xs text-muted-foreground">{m.provider}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    <button
                      onClick={() => startEdit(m)}
                      className="p-1.5 rounded hover:bg-muted transition-colors"
                      title="编辑"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleModelDelete(m.id)}
                      className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* ── 3. 默认模型配置 ─────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">默认模型配置</h2>
          <p className="text-xs text-muted-foreground mb-4">
            未单独配置的 Agent 将回退到此处的默认模型。
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">创作模型（Writer）</label>
              <ModelSelect
                value={writerModel}
                onChange={setWriterModel}
                placeholder="留空使用全局默认"
                models={chatModels}
              />
              <p className="text-xs text-muted-foreground mt-1">生成章节正文，建议高质量模型</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">快速模型（Fast）</label>
              <ModelSelect
                value={fastModel}
                onChange={setFastModel}
                placeholder="留空使用全局默认"
                models={chatModels}
              />
              <p className="text-xs text-muted-foreground mt-1">摘要/审查/规划，建议经济模型</p>
            </div>
          </div>
        </section>

        {/* ── 4. Agent 独立模型配置 ───────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">Agent 独立模型配置</h2>
          <p className="text-xs text-muted-foreground mb-4">
            留空则使用上方对应的默认模型。可针对每个 Agent 单独指定模型，实现成本与质量的精细控制。
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Writer Agent</label>
              <ModelSelect value={agentWriterModel} onChange={setAgentWriterModel} placeholder="留空使用默认 Writer 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节正文</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Critic Agent</label>
              <ModelSelect value={agentCriticModel} onChange={setAgentCriticModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责审查章节质量</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Memory Agent</label>
              <ModelSelect value={agentMemoryModel} onChange={setAgentMemoryModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责摘要和记忆更新</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Outline Agent</label>
              <ModelSelect value={agentOutlineModel} onChange={setAgentOutlineModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节大纲</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Character Agent</label>
              <ModelSelect value={agentCharacterModel} onChange={setAgentCharacterModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责生成角色卡</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Orchestrator / World Agent</label>
              <ModelSelect value={agentOrchestratorModel} onChange={setAgentOrchestratorModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">负责世界观扩写</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">全文审查 (Review) Agent</label>
              <ModelSelect value={agentReviewModel} onChange={setAgentReviewModel} placeholder="留空使用默认 Fast 模型" models={chatModels} />
              <p className="text-xs text-muted-foreground mt-1">百万上下文全文审查，推荐 DeepSeek V4 Pro</p>
            </div>
          </div>
        </section>

        {/* ── 全文审查配置 ──────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">全文审查</h2>
          <p className="text-xs text-muted-foreground mb-4">
            利用百万上下文模型审查全文一致性，检测情节矛盾、角色不一致、遗忘伏笔等问题。
          </p>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">启用自动审查</p>
                <p className="text-xs text-muted-foreground mt-0.5">生成到指定章节数时自动触发全文审查</p>
              </div>
              <button
                onClick={() => setEnableReview(!enableReview)}
                className={`w-10 h-6 rounded-full transition-colors relative ${enableReview ? 'bg-primary' : 'bg-muted-foreground/30'}`}
              >
                <div className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform ${enableReview ? 'translate-x-5' : 'translate-x-1'}`} />
              </button>
            </div>
            {enableReview && (
              <div className="flex items-center gap-3">
                <label className="text-sm">每隔</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={reviewInterval}
                  onChange={e => setReviewInterval(Number(e.target.value) || 10)}
                  className="w-20 border rounded-lg px-2 py-1.5 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
                <label className="text-sm">章自动触发</label>
              </div>
            )}
          </div>
        </section>

        {/* ── 5. 生成显示模式 ─────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">生成显示模式</h2>
          <p className="text-xs text-muted-foreground mb-4">
            关闭流式显示后，生成过程中不逐字渲染内容，完成后一次性展示。适合 API 连接不稳定的情况。
          </p>
          <button
            onClick={toggleStreamingMode}
            className={`flex items-center gap-3 w-full p-4 rounded-lg border transition-colors text-left ${
              streamingMode
                ? 'border-primary/50 bg-primary/5 dark:bg-primary/10'
                : 'border-border hover:border-muted-foreground/50'
            }`}
          >
            <div className={`p-2 rounded-md ${streamingMode ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}>
              {streamingMode ? <RadioTower className="w-4 h-4" /> : <Radio className="w-4 h-4" />}
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium">{streamingMode ? '流式显示已开启' : '流式显示已关闭'}</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {streamingMode ? '逐字渲染生成内容，实时看到 Token 输出' : '生成完成后一次性显示全文'}
              </p>
            </div>
            <div className={`w-10 h-6 rounded-full transition-colors relative ${streamingMode ? 'bg-primary' : 'bg-muted-foreground/30'}`}>
              <div className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform ${streamingMode ? 'translate-x-5' : 'translate-x-1'}`} />
            </div>
          </button>
        </section>

        {/* ── 6. 网络代理 ──────────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">网络代理</h2>
          <p className="text-xs text-muted-foreground mb-4">
            开启 VPN 时，若无法连接 API，请在此填写本地代理地址。所有 API 请求都会经过此代理。
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">HTTPS 代理</label>
              <input
                value={httpsProxy}
                onChange={e => setHttpsProxy(e.target.value)}
                placeholder="例：http://127.0.0.1:7890"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">用于 HTTPS 请求（所有 API 调用）</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">HTTP 代理</label>
              <input
                value={httpProxy}
                onChange={e => setHttpProxy(e.target.value)}
                placeholder="例：http://127.0.0.1:7890"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">通常与 HTTPS 代理相同</p>
            </div>
          </div>
        </section>

        {/* ── 操作按钮 ─────────────────────────────────────────────────── */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground shrink-0">测试模型：</span>
            <select
              value={testModel}
              onChange={e => setTestModel(e.target.value)}
              disabled={testing || saving}
              className="border rounded-lg px-2 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            >
              <option value="">默认（{fastModel || 'fast model'}）</option>
              {models.map(m => (
                <option key={m.id} value={m.model_id}>
                  [{m.provider}] {m.display_name || m.model_id}{m.model_type === 'embedding' ? '（嵌入）' : ''}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={handleTest}
            disabled={testing || saving}
            className="flex items-center gap-2 border px-4 py-2 rounded-lg text-sm hover:bg-muted disabled:opacity-50 transition-colors shrink-0"
          >
            {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            测试连接
          </button>
          <button
            onClick={handleSave}
            disabled={saving || testing}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50 transition-opacity font-medium"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            {saving ? '保存并测试中...' : '保存配置'}
          </button>
        </div>

        {testResult && (
          <div className={'flex items-start gap-2 p-4 rounded-lg text-sm ' + (testResult.ok ? 'bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300' : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300')}>
            {testResult.ok ? <CheckCircle className="w-4 h-4 mt-0.5 shrink-0" /> : <XCircle className="w-4 h-4 mt-0.5 shrink-0" />}
            <span className="break-all">{testResult.msg}</span>
          </div>
        )}
      </main>
    </div>
  )
}
