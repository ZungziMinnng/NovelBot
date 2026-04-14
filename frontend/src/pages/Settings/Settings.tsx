import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, CheckCircle, XCircle, Loader2, Save, Key, Sun, Moon } from 'lucide-react'
import { settingsApi } from '@/api/client'
import { useSettingsStore } from '@/store/settingsStore'

export default function Settings() {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useSettingsStore()
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
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)

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
      })
      setTesting(true)
      const r = await settingsApi.test()
      setTestResult({ ok: r.ok, msg: r.ok ? `连接成功，模型响应：${r.response}` : r.error })
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
      const r = await settingsApi.test()
      setTestResult({ ok: r.ok, msg: r.ok ? `连接成功，模型响应：${r.response}` : r.error })
    } finally {
      setTesting(false)
    }
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

        <section>
          <h2 className="font-semibold text-base mb-1">默认模型配置</h2>
          <p className="text-xs text-muted-foreground mb-4">
            未单独配置的 Agent 将回退到此处的默认模型。
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">创作模型（Writer）</label>
              <input
                value={writerModel}
                onChange={e => setWriterModel(e.target.value)}
                placeholder="例：gemini-2.0-flash"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">生成章节正文，建议高质量模型</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">快速模型（Fast）</label>
              <input
                value={fastModel}
                onChange={e => setFastModel(e.target.value)}
                placeholder="例：gpt-4o-mini"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">摘要/审查/规划，建议经济模型</p>
            </div>
          </div>
        </section>

        <section>
          <h2 className="font-semibold text-base mb-1">Agent 独立模型配置</h2>
          <p className="text-xs text-muted-foreground mb-4">
            留空则使用上方对应的默认模型。可针对每个 Agent 单独指定模型，实现成本与质量的精细控制。
          </p>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Writer Agent</label>
              <input
                value={agentWriterModel}
                onChange={e => setAgentWriterModel(e.target.value)}
                placeholder="留空使用默认 Writer 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节正文</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Critic Agent</label>
              <input
                value={agentCriticModel}
                onChange={e => setAgentCriticModel(e.target.value)}
                placeholder="留空使用默认 Fast 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责审查章节质量</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Memory Agent</label>
              <input
                value={agentMemoryModel}
                onChange={e => setAgentMemoryModel(e.target.value)}
                placeholder="留空使用默认 Fast 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责摘要和记忆更新</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Outline Agent</label>
              <input
                value={agentOutlineModel}
                onChange={e => setAgentOutlineModel(e.target.value)}
                placeholder="留空使用默认 Fast 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责生成章节大纲</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Character Agent</label>
              <input
                value={agentCharacterModel}
                onChange={e => setAgentCharacterModel(e.target.value)}
                placeholder="留空使用默认 Fast 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责生成角色卡</p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Orchestrator / World Agent</label>
              <input
                value={agentOrchestratorModel}
                onChange={e => setAgentOrchestratorModel(e.target.value)}
                placeholder="留空使用默认 Fast 模型"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
              <p className="text-xs text-muted-foreground mt-1">负责世界观扩写</p>
            </div>
          </div>
        </section>

        <div className="flex items-center gap-3">
          <button
            onClick={handleTest}
            disabled={testing || saving}
            className="flex items-center gap-2 border px-4 py-2 rounded-lg text-sm hover:bg-muted disabled:opacity-50 transition-colors"
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
