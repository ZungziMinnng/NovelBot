import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Plus, Pencil, Trash2, X, Loader2, ScrollText,
} from 'lucide-react'
import { rpgApi, type RpgRule } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'

/** RPG 设定页。目前只有「写作规则」一块，页面壳照 RpgPrompts 那套，
 *  交互照酒馆 TavernSettings 的写作规则 tab。规则是独立库，不复用酒馆 / 小说侧。 */
export default function RpgSettings() {
  const navigate = useNavigate()

  return (
    <div className="mode-rpg min-h-screen bg-background relative">
      <div className="fixed inset-0 z-0 opacity-[0.10] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#6d3ab0" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/rpg')} className="p-2 rounded-md hover:bg-muted" title="返回 RPG">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ScrollText className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">RPG 设定</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-8 space-y-6">
        <RulesPane />
      </main>
    </div>
  )
}

// ── 写作规则 ──────────────────────────────────────────────────────────────

function RulesPane() {
  const qc = useQueryClient()
  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['rpg-rules'],
    queryFn: rpgApi.rules.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-rules'] })

  const reset = () => {
    setName('')
    setContent('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (rule: RpgRule) => {
    setEditingId(rule.id)
    setName(rule.name)
    setContent(rule.content)
    setShowForm(true)
  }

  const submit = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await rpgApi.rules.update(editingId, { name: name.trim(), content })
      } else {
        await rpgApi.rules.create({
          name: name.trim(), content, sort_order: rules.length + 1,
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存规则失败')
    } finally { setSaving(false) }
  }

  const toggle = async (rule: RpgRule) => {
    try {
      await rpgApi.rules.update(rule.id, { enabled: !rule.enabled })
      refresh()
    } catch {
      toast.error('切换启用状态失败')
    }
  }

  const remove = async (rule: RpgRule) => {
    if (!await confirmDialog({
      title: `确认删除规则「${rule.name}」？`,
      detail: '勾选了它的模组会立刻失去这条规则。只是想暂时不用的话，点「停用」更合适。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.rules.delete(rule.id)
      refresh()
    } catch {
      toast.error('删除规则失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          写在这里的要求会原样拼进 GM 的系统提示词，用来管住叙事的用词用语。规则只是放在这儿，
          还要在每个模组的「写作规则」里勾选才生效，改内容立刻对所有勾了它的模组生效。
          <br />
          与酒馆、小说侧的规则各是一套：那两批是按各自玩法调的，混用会打架。
        </p>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 shrink-0
              bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> 新建规则
          </button>
        )}
      </div>

      {showForm && (
        <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{editingId ? '编辑规则' : '新建规则'}</span>
            <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">名称 *</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例：禁止 AI 腔套话、别替玩家做决定"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-violet-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">规则正文</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
              placeholder="直接写要求，这段会原样进系统提示词。例：禁止使用『显然』『不禁』『嘴角上扬』等套话。"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y leading-relaxed
                focus:outline-none focus:ring-1 focus:ring-violet-500/50"
            />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
            <button
              onClick={submit}
              disabled={!name.trim() || saving}
              className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5
                bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
            >
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
        <div className="text-center py-16 text-sm text-muted-foreground">
          还没有规则。模组默认不注入任何规则，需要时再来写。
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map(rule => (
            <div
              key={rule.id}
              className={`border rounded-lg px-4 py-3 bg-card/50 backdrop-blur-sm ${rule.enabled ? '' : 'opacity-60'}`}
            >
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{rule.name}</span>
                    {!rule.enabled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">已停用</span>
                    )}
                  </div>
                  {rule.content && (
                    <p className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap line-clamp-4">
                      {rule.content}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => toggle(rule)}
                    className="text-xs px-2 py-1 rounded border hover:bg-muted"
                    title={rule.enabled ? '停用后所有模组都不再注入这条' : '重新启用'}
                  >
                    {rule.enabled ? '停用' : '启用'}
                  </button>
                  <button onClick={() => startEdit(rule)} className="p-1.5 rounded hover:bg-muted" title="编辑">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(rule)}
                    className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                    title="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
