import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { Loader2, RotateCcw, Save } from 'lucide-react'
import toast from 'react-hot-toast'
import { tavernPromptsApi, type TavernPrompt } from '@/api/tavernPrompts'
import { useAuthStore } from '@/store/authStore'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'

export default function TavernPrompts({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const userId = useAuthStore(state => state.user?.id)
  const queryClient = useQueryClient()
  const queryKey = ['tavern-prompts', userId]
  const { data: prompts = [], isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: tavernPromptsApi.list,
  })
  const [selectedName, setSelectedName] = useState('tavern_roleplay.jinja2')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const selected = prompts.find(prompt => prompt.name === selectedName)
  const content = selected ? drafts[selected.name] ?? selected.content : ''
  const dirty = prompts.some(prompt => drafts[prompt.name] !== undefined && drafts[prompt.name] !== prompt.content)

  useEffect(() => {
    onDirtyChange(dirty)
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, onDirtyChange])

  const accept = (updated: TavernPrompt) => {
    queryClient.setQueryData<TavernPrompt[]>(queryKey, current =>
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
      accept(await tavernPromptsApi.update(selected.name, content))
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
      accept(await tavernPromptsApi.reset(selected.name))
      toast.success('已恢复默认提示词')
    } catch {
      setError('恢复失败，请稍后重试')
    } finally { setSaving(false) }
  }

  if (isLoading) return <p className="flex items-center gap-2 py-10"><Loader2 className="w-4 h-4 animate-spin" />加载提示词…</p>
  if (isError) return (
    <div role="alert" className="space-y-3 py-10">
      <p>提示词加载失败</p>
      <button onClick={() => void refetch()} className="border rounded-lg px-3 py-2 text-sm hover:bg-muted">重试</button>
    </div>
  )

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground leading-relaxed">
        修改仅对你的账号生效，适用于你的所有酒馆角色卡和对话。保存后从下一次调用开始使用，已有消息和摘要不会改写。
        角色卡自己的系统指令与勾选的写作规则仍会一同生效。
      </p>
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
            <p>用 {'{{ 变量名 }}'} 插入信息；保留需要的条件和循环。角色卡中的 {'{{user}}'} / {'{{char}}'} 与这里的变量不同，请参考默认模板的写法。</p>
            <dl className="grid gap-2 sm:grid-cols-2">
              {Object.entries(selected.variables).map(([name, description]) => (
                <div key={name}><dt className="font-mono text-foreground">{`{{ ${name} }}`}</dt><dd>{description}</dd></div>
              ))}
            </dl>
          </details>
          <label htmlFor="tavern-prompt-content" className="block text-sm font-medium">{selected.label}提示词</label>
          <textarea
            id="tavern-prompt-content"
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
    </div>
  )
}
