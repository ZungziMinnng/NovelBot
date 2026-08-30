import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Plus, Pencil, Trash2, X, Loader2, ScrollText, Lock } from 'lucide-react'
import { promptRulesApi, type PromptRule } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'

const CATEGORIES = [
  { value: 'guardrail', label: '底线护栏' },
  { value: 'style', label: '文风' },
  { value: 'structure', label: '结构节奏' },
  { value: 'other', label: '其他' },
]

function categoryLabel(value: string): string {
  return CATEGORIES.find(c => c.value === value)?.label || value
}

export default function Rules() {
  const navigate = useNavigate()
  // 入口在小说编辑器头部，返回上一页才能回到那本书；直接开 /rules 时兜底回首页
  const goBack = () => (window.history.length > 1 ? navigate(-1) : navigate('/'))
  const qc = useQueryClient()
  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['prompt-rules'],
    queryFn: promptRulesApi.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [formName, setFormName] = useState('')
  const [formContent, setFormContent] = useState('')
  const [formCategory, setFormCategory] = useState('style')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['prompt-rules'] })

  const resetForm = () => {
    setFormName('')
    setFormContent('')
    setFormCategory('style')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (rule: PromptRule) => {
    setEditingId(rule.id)
    setFormName(rule.name)
    setFormContent(rule.content)
    setFormCategory(rule.category)
    setShowForm(true)
  }

  const handleSubmit = async () => {
    if (!formName.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await promptRulesApi.update(editingId, {
          name: formName.trim(), content: formContent, category: formCategory,
        })
      } else {
        await promptRulesApi.create({
          name: formName.trim(), content: formContent, category: formCategory,
          sort_order: rules.length + 1,
        })
      }
      refresh()
      resetForm()
    } catch {
      toast.error('保存规则失败')
    } finally { setSaving(false) }
  }

  const handleToggle = async (rule: PromptRule) => {
    try {
      await promptRulesApi.update(rule.id, { enabled: !rule.enabled })
      refresh()
    } catch {
      toast.error('切换启用状态失败')
    }
  }

  const handleDelete = async (rule: PromptRule) => {
    if (!confirm(`确认删除规则「${rule.name}」？勾选了它的小说会立刻失去这条规则。`)) return
    try {
      await promptRulesApi.delete(rule.id)
      refresh()
    } catch {
      toast.error('删除规则失败')
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b px-6 py-4 flex items-center gap-3">
        <button onClick={goBack} className="p-2 rounded-md hover:bg-muted">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ScrollText className="w-5 h-5 text-primary" />
        <h1 className="font-bold text-lg">规则广场</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            {rules.length} 条规则 · 在每本小说的设置里勾选启用。改动内容立刻对所有勾选它的小说生效
          </p>
          {!showForm && (
            <button onClick={() => setShowForm(true)}
              className="flex items-center gap-1.5 text-sm border rounded-lg px-3 py-1.5 hover:bg-muted transition-colors shrink-0">
              <Plus className="w-3.5 h-3.5" /> 新建规则
            </button>
          )}
        </div>

        {showForm && (
          <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑规则' : '新建规则'}</span>
              <button onClick={resetForm} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="text-xs font-medium mb-1 block">名称 *</label>
                <input value={formName} onChange={e => setFormName(e.target.value)}
                  placeholder="例：去AI味、对话要有潜台词"
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
              </div>
              <div className="w-32">
                <label className="text-xs font-medium mb-1 block">分类</label>
                <select value={formCategory} onChange={e => setFormCategory(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring">
                  {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium mb-1 block">规则正文</label>
              <textarea value={formContent} onChange={e => setFormContent(e.target.value)} rows={12}
                placeholder="这段文字会原样拼进 Writer 的系统提示词，直接写要求即可"
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-y font-mono leading-relaxed" />
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={resetForm} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleSubmit} disabled={!formName.trim() || saving}
                className="text-sm px-4 py-1.5 bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5">
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {editingId ? '保存修改' : '创建'}
              </button>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
          </div>
        ) : rules.length === 0 ? (
          <div className="text-center py-20 text-muted-foreground">
            <p>暂无规则，点击「新建规则」开始</p>
          </div>
        ) : (
          <div className="space-y-2">
            {rules.map(rule => (
              <div key={rule.id} className={`border rounded-lg px-4 py-3 ${rule.enabled ? '' : 'opacity-60'}`}>
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{rule.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                        {categoryLabel(rule.category)}
                      </span>
                      {rule.is_builtin && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary flex items-center gap-1">
                          <Lock className="w-2.5 h-2.5" /> 内置
                        </span>
                      )}
                      {!rule.enabled && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">已停用</span>
                      )}
                    </div>
                    {rule.content && (
                      <p className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap line-clamp-4">{rule.content}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => handleToggle(rule)}
                      className="text-xs px-2 py-1 rounded border hover:bg-muted"
                      title={rule.enabled ? '停用后所有小说都不再注入这条规则' : '重新启用'}>
                      {rule.enabled ? '停用' : '启用'}
                    </button>
                    <button onClick={() => startEdit(rule)} className="p-1.5 rounded hover:bg-muted" title="编辑">
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => handleDelete(rule)}
                      disabled={rule.is_builtin}
                      className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-current"
                      title={rule.is_builtin ? '内置规则不可删除，可停用' : '删除'}>
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
