import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Plus, Pencil, Trash2, X, Loader2, Settings2, ScrollText, Quote,
} from 'lucide-react'
import {
  tavernApi, type TavernRule, type TavernInstructionPreset,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import TavernPrompts from './TavernPrompts'

type Tab = 'rules' | 'instructions' | 'prompts'

export default function TavernSettings() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('rules')
  const [promptsDirty, setPromptsDirty] = useState(false)

  const goBack = async () => {
    if (promptsDirty && !await confirmDialog({ title: '提示词尚未保存，仍要离开？', confirmText: '离开' })) return
    navigate('/tavern')
  }

  return (
    <div className="mode-tavern min-h-screen bg-background relative">
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={goBack} className="p-2 rounded-md hover:bg-muted" title="返回酒馆">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Settings2 className="w-5 h-5 text-pink-500" />
        <h1 className="font-bold text-lg">酒馆设定</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-8 space-y-6">
        <div className="flex flex-wrap items-center gap-2">
          {([
            { id: 'rules' as Tab, label: '写作规则', icon: ScrollText },
            { id: 'instructions' as Tab, label: '常用指令', icon: Quote },
            { id: 'prompts' as Tab, label: '提示词', icon: Pencil },
          ]).map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg transition-colors ${
                tab === id
                  ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                  : 'border hover:bg-muted text-muted-foreground'
              }`}
            >
              <Icon className="w-3.5 h-3.5" /> {label}
            </button>
          ))}
        </div>

        {tab === 'rules' && <RulesPane />}
        {tab === 'instructions' && <InstructionsPane />}
        <div hidden={tab !== 'prompts'}><TavernPrompts onDirtyChange={setPromptsDirty} /></div>
      </main>
    </div>
  )
}

// ── 写作规则 ──────────────────────────────────────────────────────────────

function RulesPane() {
  const qc = useQueryClient()
  const { data: rules = [], isLoading } = useQuery({
    queryKey: ['tavern-rules'],
    queryFn: tavernApi.rules.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['tavern-rules'] })

  const reset = () => {
    setName('')
    setContent('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (rule: TavernRule) => {
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
        await tavernApi.rules.update(editingId, { name: name.trim(), content })
      } else {
        await tavernApi.rules.create({
          name: name.trim(), content, sort_order: rules.length + 1,
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存规则失败')
    } finally { setSaving(false) }
  }

  const toggle = async (rule: TavernRule) => {
    try {
      await tavernApi.rules.update(rule.id, { enabled: !rule.enabled })
      refresh()
    } catch {
      toast.error('切换启用状态失败')
    }
  }

  const remove = async (rule: TavernRule) => {
    if (!await confirmDialog({
      title: `确认删除规则「${rule.name}」？`,
      detail: '勾选了它的角色卡会立刻失去这条规则。只是想暂时不用的话，点「停用」更合适。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.rules.delete(rule.id)
      refresh()
    } catch {
      toast.error('删除规则失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          写在这里的要求会原样拼进角色卡的系统提示词。规则只是放在这儿，
          还要在每张角色卡的「进阶」里勾选才生效，改内容立刻对所有勾了它的卡生效。
          <br />
          与小说侧的规则广场是两套：那批是按写长篇正文调的，套到逐轮对话上会打架。
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
              placeholder="例：别替玩家做决定、少用书面语"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">规则正文</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
              placeholder="直接写要求，这段会原样进系统提示词"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y leading-relaxed
                focus:outline-none focus:ring-1 focus:ring-pink-500/50"
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
          还没有规则。角色卡默认不注入任何规则，需要时再来写。
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
                    title={rule.enabled ? '停用后所有角色卡都不再注入这条' : '重新启用'}
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

// ── 常用指令 ──────────────────────────────────────────────────────────────

function InstructionsPane() {
  const qc = useQueryClient()
  const { data: presets = [], isLoading } = useQuery({
    queryKey: ['tavern-instruction-presets'],
    queryFn: tavernApi.instructionPresets.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['tavern-instruction-presets'] })

  const reset = () => {
    setName('')
    setContent('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (preset: TavernInstructionPreset) => {
    setEditingId(preset.id)
    setName(preset.name)
    setContent(preset.content)
    setShowForm(true)
  }

  const submit = async () => {
    if (!name.trim() || !content.trim()) return
    setSaving(true)
    try {
      if (editingId) {
        await tavernApi.instructionPresets.update(editingId, {
          name: name.trim(), content: content.trim(),
        })
      } else {
        await tavernApi.instructionPresets.create({
          name: name.trim(), content: content.trim(),
        })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存常用指令失败')
    } finally { setSaving(false) }
  }

  const remove = async (preset: TavernInstructionPreset) => {
    if (!await confirmDialog({
      title: `删除常用指令「${preset.name}」？`,
      detail: '已经用了它的角色卡不受影响——填进卡里的是一份文本副本。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.instructionPresets.delete(preset.id)
      refresh()
    } catch {
      toast.error('删除常用指令失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          存在这里的指令，建卡时点一下就填进「系统指令」输入框。
          填进去的是一份文本副本，之后改这里不会动到已经建好的卡——
          一条指令悄悄改掉十张卡的演法不像是想要的效果。
        </p>
        {!showForm && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 shrink-0
              bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> 新建指令
          </button>
        )}
      </div>

      {showForm && (
        <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">{editingId ? '编辑常用指令' : '新建常用指令'}</span>
            <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">名称 *</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例：市井口吻"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">指令正文 *</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
              placeholder="语言风格、知识范围、行为模式、互动规则、特殊能力或限制……"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y leading-relaxed
                focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
            <button
              onClick={submit}
              disabled={!name.trim() || !content.trim() || saving}
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
      ) : presets.length === 0 ? (
        <div className="text-center py-16 text-sm text-muted-foreground">
          还没存过常用指令。在角色卡的「进阶」里写好一段，点「存为常用」也能存到这里。
        </div>
      ) : (
        <div className="space-y-2">
          {presets.map(preset => (
            <div key={preset.id} className="border rounded-lg px-4 py-3 bg-card/50 backdrop-blur-sm">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium">{preset.name}</span>
                  <p className="text-xs text-muted-foreground mt-1 whitespace-pre-wrap line-clamp-4">
                    {preset.content}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button onClick={() => startEdit(preset)} className="p-1.5 rounded hover:bg-muted" title="编辑">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(preset)}
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
