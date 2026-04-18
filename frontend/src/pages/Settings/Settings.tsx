import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle, XCircle, Loader2, Save, Key, Sun, Moon, Radio, RadioTower, Plus, Pencil, Trash2, X } from 'lucide-react'
import { settingsApi, modelLibraryApi, PROVIDERS, type ModelEntry } from '@/api/client'
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

  // ── API & model settings state ──────────────────────────────────────────
  const [apiKey, setApiKey] = useState('')
  const [maskedKey, setMaskedKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://aihubmix.com/v1')
  const [writerModel, setWriterModel] = useState('')
  const [fastModel, setFastModel] = useState('')
  const [agentWriterModel, setAgentWriterModel] = useState('')
  const [agentCriticModel, setAgentCriticModel] = useState('')
  const [agentMemoryModel, setAgentMemoryModel] = useState('')
  const [agentOutlineModel, setAgentOutlineModel] = useState('')
  const [agentCharacterModel, setAgentCharacterModel] = useState('')
  const [agentOrchestratorModel, setAgentOrchestratorModel] = useState('')
  const [geminiBaseUrl, setGeminiBaseUrl] = useState('')
  const [anthropicBaseUrl, setAnthropicBaseUrl] = useState('')
  const [httpsProxy, setHttpsProxy] = useState('')
  const [httpProxy, setHttpProxy] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testModel, setTestModel] = useState('')
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

  // ── Model library state ─────────────────────────────────────────────────
  const { data: models = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const [showAddForm, setShowAddForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formDisplayName, setFormDisplayName] = useState('')
  const [formModelId, setFormModelId] = useState('')
  const [formProvider, setFormProvider] = useState(PROVIDERS[0].label)
  const [formApiFormat, setFormApiFormat] = useState(PROVIDERS[0].api_format)
  const [modelSaving, setModelSaving] = useState(false)

  useEffect(() => {
    settingsApi.get().then((s: {
      aihubmix_api_key_masked: string
      aihubmix_base_url: string
      default_writer_model: string
      default_fast_model: string
      agent_writer_model: string
      agent_critic_model: string
      agent_memory_model: string
      agent_outline_model: string
      agent_character_model: string
      agent_orchestrator_model: string
      gemini_base_url: string
      anthropic_base_url: string
      https_proxy: string
      http_proxy: string
    }) => {
      setMaskedKey(s.aihubmix_api_key_masked || '')
      setBaseUrl(s.aihubmix_base_url)
      setWriterModel(s.default_writer_model)
      setFastModel(s.default_fast_model)
      setAgentWriterModel(s.agent_writer_model || '')
      setAgentCriticModel(s.agent_critic_model || '')
      setAgentMemoryModel(s.agent_memory_model || '')
      setAgentOutlineModel(s.agent_outline_model || '')
      setAgentCharacterModel(s.agent_character_model || '')
      setAgentOrchestratorModel(s.agent_orchestrator_model || '')
      setGeminiBaseUrl(s.gemini_base_url || '')
      setAnthropicBaseUrl(s.anthropic_base_url || '')
      setHttpsProxy(s.https_proxy || '')
      setHttpProxy(s.http_proxy || '')
    })
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      await settingsApi.update({
        aihubmix_api_key: apiKey || undefined,
        aihubmix_base_url: baseUrl,
        default_writer_model: writerModel,
        default_fast_model: fastModel,
        agent_writer_model: agentWriterModel,
        agent_critic_model: agentCriticModel,
        agent_memory_model: agentMemoryModel,
        agent_outline_model: agentOutlineModel,
        agent_character_model: agentCharacterModel,
        agent_orchestrator_model: agentOrchestratorModel,
        gemini_base_url: geminiBaseUrl,
        anthropic_base_url: anthropicBaseUrl,
        https_proxy: httpsProxy,
        http_proxy: httpProxy,
      })
      setTesting(true)
      const r = await settingsApi.test(testModel || undefined)
      setTestResult({ ok: r.ok, msg: r.ok ? `连接成功 [${r.api_format}] ${r.model}：${r.response}` : `[${r.api_format}] ${r.model}：${r.error}` })
      const s = await settingsApi.get()
      setMaskedKey(s.aihubmix_api_key_masked || '')
      setApiKey('')
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

  // ── Model library handlers ──────────────────────────────────────────────

  const resetForm = () => {
    setFormDisplayName('')
    setFormModelId('')
    setFormProvider(PROVIDERS[0].label)
    setFormApiFormat(PROVIDERS[0].api_format)
    setEditingId(null)
    setShowAddForm(false)
  }

  const handleProviderChange = (label: string) => {
    setFormProvider(label)
    const p = PROVIDERS.find(p => p.label === label)
    if (p) setFormApiFormat(p.api_format)
  }

  const startEdit = (m: ModelEntry) => {
    setEditingId(m.id)
    setFormDisplayName(m.display_name)
    setFormModelId(m.model_id)
    setFormProvider(m.provider)
    setFormApiFormat(m.api_format)
    setShowAddForm(true)
  }

  const handleModelSubmit = async () => {
    if (!formModelId.trim()) return
    setModelSaving(true)
    try {
      if (editingId !== null) {
        await modelLibraryApi.update(editingId, {
          display_name: formDisplayName,
          model_id: formModelId,
          provider: formProvider,
          api_format: formApiFormat,
        })
      } else {
        await modelLibraryApi.create({
          display_name: formDisplayName,
          model_id: formModelId,
          provider: formProvider,
          api_format: formApiFormat,
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
    loadModels()
  }

  const providerBadgeColor = (apiFormat: string) => {
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

        {/* ── 1. API 配置 ─────────────────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-4">API 配置</h2>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1 block">API Key</label>
              {maskedKey && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
                  <Key className="w-3 h-3" />
                  当前 Key：<span className="font-mono">{maskedKey}</span>
                </div>
              )}
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={maskedKey ? '留空保持当前 Key 不变' : '输入 AiHubMix API Key'}
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">API Base URL</label>
              <input
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          </div>
        </section>

        {/* ── 2. 模型库 ───────────────────────────────────────────────── */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="font-semibold text-base">模型库</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                管理可选模型，下方下拉框将从此列表中读取。
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
                  <label className="text-xs font-medium mb-1 block">提供商</label>
                  <select
                    value={formProvider}
                    onChange={e => handleProviderChange(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {PROVIDERS.map(p => (
                      <option key={p.label} value={p.label}>{p.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium mb-1 block">API 格式（自动填充）</label>
                  <input
                    value={formApiFormat}
                    readOnly
                    className="w-full border rounded-lg px-3 py-2 text-sm bg-muted text-muted-foreground cursor-not-allowed"
                  />
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button onClick={resetForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                  取消
                </button>
                <button
                  onClick={handleModelSubmit}
                  disabled={!formModelId.trim() || modelSaving}
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
                      <span className={`text-xs px-1.5 py-0.5 rounded-full font-mono ${providerBadgeColor(m.api_format)}`}>
                        {m.api_format}
                      </span>
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
                models={models}
              />
              <p className="text-xs text-muted-foreground mt-1">生成章节正文，建议高质量模型</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">快速模型（Fast）</label>
              <ModelSelect
                value={fastModel}
                onChange={setFastModel}
                placeholder="留空使用全局默认"
                models={models}
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
              <ModelSelect value={agentWriterModel} onChange={setAgentWriterModel} placeholder="留空使用默认 Writer 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节正文</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Critic Agent</label>
              <ModelSelect value={agentCriticModel} onChange={setAgentCriticModel} placeholder="留空使用默认 Fast 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责审查章节质量</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Memory Agent</label>
              <ModelSelect value={agentMemoryModel} onChange={setAgentMemoryModel} placeholder="留空使用默认 Fast 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责摘要和记忆更新</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Outline Agent</label>
              <ModelSelect value={agentOutlineModel} onChange={setAgentOutlineModel} placeholder="留空使用默认 Fast 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节大纲</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Character Agent</label>
              <ModelSelect value={agentCharacterModel} onChange={setAgentCharacterModel} placeholder="留空使用默认 Fast 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责生成角色卡</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Orchestrator / World Agent</label>
              <ModelSelect value={agentOrchestratorModel} onChange={setAgentOrchestratorModel} placeholder="留空使用默认 Fast 模型" models={models} />
              <p className="text-xs text-muted-foreground mt-1">负责世界观扩写</p>
            </div>
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

        {/* ── 6. 网络代理 + 原生端点 ──────────────────────────────────── */}
        <section>
          <h2 className="font-semibold text-base mb-1">网络代理</h2>
          <p className="text-xs text-muted-foreground mb-4">
            开启 VPN 时，若无法连接 API，请在此填写本地代理地址。留空则自动读取系统环境变量。
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
              <p className="text-xs text-muted-foreground mt-1">用于 HTTPS 请求（AiHubMix API）</p>
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
            <div>
              <label className="text-sm font-medium mb-1 block">Gemini 原生端点</label>
              <input
                value={geminiBaseUrl}
                onChange={e => setGeminiBaseUrl(e.target.value)}
                placeholder="https://aihubmix.com/gemini"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">默认 AiHubMix 代理端点，留空则直连 Google</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Claude 原生端点</label>
              <input
                value={anthropicBaseUrl}
                onChange={e => setAnthropicBaseUrl(e.target.value)}
                placeholder="留空使用 SDK 默认（直连 Anthropic）"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring font-mono"
              />
              <p className="text-xs text-muted-foreground mt-1">Anthropic 原生格式端点，填写 AIHubMix 端点时走代理</p>
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
                  [{m.provider}] {m.display_name || m.model_id}
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
