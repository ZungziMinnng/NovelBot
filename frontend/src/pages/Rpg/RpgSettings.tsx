import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Plus, Pencil, Trash2, X, Loader2, ScrollText, Volume2, Quote,
} from 'lucide-react'
import { rpgApi, type RpgRule, type RpgInstructionPreset } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import SfxSettings from './SfxSettings'

/** 游戏设定页。写作规则是存在后端的独立库（不复用酒馆 / 小说侧），
 *  音效那块只存在浏览器本地，两者放一页但性质不同。页面壳照 RpgPrompts 那套，
 *  规则的交互照酒馆 TavernSettings 的写作规则 tab。 */
export default function RpgSettings() {
  const navigate = useNavigate()

  return (
    <div className="mode-game min-h-screen bg-background relative">
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
      <button onClick={() => navigate('/game')} className="p-2 rounded-md hover:bg-muted" title="返回游戏">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <ScrollText className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">游戏设定</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-3xl mx-auto px-6 py-8 space-y-6">
        <RulesPane />

        <section className="space-y-2 border-t border-border/60 pt-6">
          <h2 className="text-sm font-medium flex items-center gap-2">
            <Quote className="w-4 h-4 text-violet-500" /> 常用 GM 指令
          </h2>
          <InstructionsPane />
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-medium flex items-center gap-2">
            <Volume2 className="w-4 h-4 text-violet-500" /> 音效
          </h2>
          <p className="text-xs text-muted-foreground leading-relaxed">
            只存在这台机器上，不跟着模组和存档走——换台电脑要重新开。
          </p>
          <SfxSettings />
        </section>
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

  const renderForm = () => (
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
  )

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

      {showForm && editingId === null && renderForm()}

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
            <div key={rule.id} className="space-y-2">
            <div
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
            {showForm && editingId === rule.id && renderForm()}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── 常用 GM 指令 ──────────────────────────────────────────────────────────
// 照酒馆 TavernSettings 的 InstructionsPane。这里只管改名和删除，
// 存新的一条更顺手的路是在模组的「GM 指令」那一栏点「存为常用」。

function InstructionsPane() {
  const qc = useQueryClient()
  const { data: presets = [], isLoading } = useQuery({
    queryKey: ['rpg-instruction-presets'],
    queryFn: rpgApi.instructionPresets.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-instruction-presets'] })

  const reset = () => {
    setName('')
    setContent('')
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (preset: RpgInstructionPreset) => {
    setEditingId(preset.id)
    setName(preset.name)
    setContent(preset.content)
    setShowForm(true)
  }

  const submit = async () => {
    if (!name.trim() || !content.trim()) return
    setSaving(true)
    try {
      const body = { name: name.trim(), content: content.trim() }
      if (editingId) {
        await rpgApi.instructionPresets.update(editingId, body)
      } else {
        await rpgApi.instructionPresets.create(body)
      }
      refresh()
      reset()
    } catch {
      toast.error('保存常用指令失败')
    } finally { setSaving(false) }
  }

  const remove = async (preset: RpgInstructionPreset) => {
    if (!await confirmDialog({
      title: `删除常用指令「${preset.name}」？`,
      detail: '已经用了它的模组不受影响——填进模组里的是一份文本副本。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.instructionPresets.delete(preset.id)
      refresh()
    } catch {
      toast.error('删除常用指令失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          存在这里的指令，建模组时点一下就填进「GM 指令」输入框。
          填进去的是一份文本副本，之后改这里不会动到已经建好的模组——
          一条指令悄悄改掉十个模组的演法不像是想要的效果。
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
              placeholder="例：克苏鲁腔"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-violet-500/50"
            />
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">指令正文 *</label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={10}
              placeholder="叙事的腔调、节奏、尺度、哪些东西必须写、哪些绝对不能出现……"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y leading-relaxed
                focus:outline-none focus:ring-1 focus:ring-violet-500/50"
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
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
        </div>
      ) : presets.length === 0 ? (
        <div className="text-center py-10 text-sm text-muted-foreground">
          还没存过常用指令。在模组的「GM 指令」那一栏写好一段，点「存为常用」也能存到这里。
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
