import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { ArrowLeft, Loader2, RotateCcw, Save, ScrollText } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgPromptsApi, type RpgPrompt } from '@/api/rpgPrompts'
import { useAuthStore } from '@/store/authStore'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'

export default function RpgPrompts() {
  const navigate = useNavigate()
  const userId = useAuthStore(state => state.user?.id)
  const queryClient = useQueryClient()
  const queryKey = ['rpg-prompts', userId]
  const { data: prompts = [], isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: rpgPromptsApi.list,
  })
  const [selectedName, setSelectedName] = useState('rpg_gm.jinja2')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const selected = prompts.find(prompt => prompt.name === selectedName)
  const content = selected ? drafts[selected.name] ?? selected.content : ''
  const dirty = prompts.some(prompt => drafts[prompt.name] !== undefined && drafts[prompt.name] !== prompt.content)

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const goBack = async () => {
    if (dirty && !await confirmDialog({ title: '提示词尚未保存，仍要离开？', confirmText: '离开' })) return
    navigate('/rpg')
  }

  const accept = (updated: RpgPrompt) => {
    queryClient.setQueryData<RpgPrompt[]>(queryKey, current =>
      current?.map(prompt => prompt.name === updated.name ? updated : prompt),
    )
    setDrafts(current => {
      const next = { ...current }
      delete next[updated.name]
      return next
    })
    setError('')
  }

  const save = async () => {
    if (!selected) return
    setSaving(true)
    setError('')
    try {
      accept(await rpgPromptsApi.update(selected.name, content))
      toast.success('提示词已保存，下次调用生效')
    } catch (cause) {
      setError(isAxiosError(cause) && typeof cause.response?.data?.detail === 'string'
        ? cause.response.data.detail : '保存失败，请稍后重试')
    } finally { setSaving(false) }
  }

  const reset = async () => {
    if (!selected || !await confirmDialog({
      title: `恢复「${selected.label}」默认提示词？`,
      detail: '此项自定义内容和未保存修改将被清除。',
      confirmText: '恢复默认',
    })) return
    setSaving(true)
    setError('')
    try {
      accept(await rpgPromptsApi.reset(selected.name))
      toast.success('已恢复默认提示词')
    } catch {
      setError('恢复失败，请稍后重试')
    } finally { setSaving(false) }
  }

  return (
    <div className="mode-rpg min-h-screen bg-background relative">
      <div className="fixed inset-0 z-0 opacity-[0.10] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#6d3ab0" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={goBack} className="p-2 rounded-md hover:bg-muted" title="返回 RPG">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ScrollText className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">RPG 提示词</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-8 space-y-4">
        <p className="text-sm text-muted-foreground leading-relaxed">
          修改仅对你的账号生效，适用于你的所有 RPG 模组和存档。保存后从下一轮开始使用，已有的叙事和存档不会改写。
          模组自己的叙事风格、世界观和世界书词条仍会一同注入。
        </p>

        {isLoading ? (
          <p className="flex items-center gap-2 py-10"><Loader2 className="w-4 h-4 animate-spin" />加载提示词…</p>
        ) : isError ? (
          <div role="alert" className="space-y-3 py-10">
            <p>提示词加载失败</p>
            <button onClick={() => void refetch()} className="border rounded-lg px-3 py-2 text-sm hover:bg-muted">重试</button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {prompts.map(prompt => (
                <button
                  key={prompt.name}
                  disabled={saving}
                  onClick={() => { setSelectedName(prompt.name); setError('') }}
                  className={`text-sm px-3 py-2 rounded-lg border disabled:opacity-40 ${selectedName === prompt.name ? 'bg-primary/10 border-primary text-primary' : 'hover:bg-muted'}`}
                >
                  {prompt.label}{drafts[prompt.name] !== undefined && drafts[prompt.name] !== prompt.content ? ' · 未保存' : prompt.customized ? ' · 自定义' : ''}
                </button>
              ))}
            </div>

            {selected && (
              <div className="border rounded-lg p-4 bg-card/70 space-y-4">
                <p className="text-sm text-muted-foreground">{selected.description}</p>
                <details className="text-xs text-muted-foreground space-y-2">
                  <summary className="cursor-pointer">模板变量与写法</summary>
                  <p>用 {'{{ 变量名 }}'} 插入信息；保留需要的条件和循环。这里写下的变量名必须是下面这些，写错会在保存时就报错。</p>
                  <dl className="grid gap-2 sm:grid-cols-2">
                    {Object.entries(selected.variables).map(([name, description]) => (
                      <div key={name}><dt className="font-mono text-foreground">{`{{ ${name} }}`}</dt><dd>{description}</dd></div>
                    ))}
                  </dl>
                </details>
                <label htmlFor="rpg-prompt-content" className="block text-sm font-medium">{selected.label}提示词</label>
                <textarea
                  id="rpg-prompt-content"
                  value={content}
                  onChange={event => { setDrafts(current => ({ ...current, [selected.name]: event.target.value })); setError('') }}
                  disabled={saving}
                  maxLength={20000}
                  rows={20}
                  spellCheck={false}
                  className="w-full border rounded-lg px-3 py-2 text-sm font-mono bg-background resize-y leading-relaxed focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-60"
                />
                {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-xs text-muted-foreground">{content.length} / 20000 字符 · {content !== selected.content ? '未保存' : selected.customized ? '已使用自定义提示词' : '使用默认提示词'}</span>
                  <div className="flex gap-2">
                    <button onClick={reset} disabled={saving || (!selected.customized && content === selected.content)} className="flex items-center gap-1.5 border rounded-lg px-3 py-2 text-sm hover:bg-muted disabled:opacity-40">
                      <RotateCcw className="w-4 h-4" />恢复默认
                    </button>
                    <button onClick={save} disabled={saving || !content.trim() || content === selected.content} className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm bg-primary text-primary-foreground disabled:opacity-40">
                      {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}保存提示词
                    </button>
                  </div>
                </div>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">查看默认提示词</summary>
                  <pre className="mt-3 whitespace-pre-wrap font-mono leading-relaxed">{selected.default_content}</pre>
                </details>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
