import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Download, Flame, Loader2, Pencil, Save, Search, Trash2, X } from 'lucide-react'
import {
  forgeApi,
  type ForgeCharacter, type ForgeDraft, type ForgeExportTarget, type ForgeSourceItem,
} from '@/api/forge'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ExampleTurnsEditor from '@/components/ExampleTurnsEditor'
import StyleModelSelect, { useStyleModel } from '@/components/StyleLibrary/StyleModelSelect'
import CardAvatar from '@/pages/Tavern/CardAvatar'

const INPUT =
  'w-full border bg-background rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring'
const CARD = 'border rounded-xl bg-card p-4 sm:p-5'
const BTN =
  'flex items-center justify-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-40'
const BTN_PRIMARY = `${BTN} bg-primary text-primary-foreground hover:opacity-90`
const BTN_GHOST = `${BTN} border hover:bg-muted`
const ICON_BTN = 'p-1.5 rounded-md hover:bg-muted text-muted-foreground'

const errDetail = (e: unknown, fallback: string) =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback

interface SelectedSource {
  kind: ForgeSourceItem['kind']
  id: number
  name: string
  weight: number
  instruction: string
}

const keyOf = (kind: string, id: number) => `${kind}:${id}`
const weightLabel = (w: number) => (w >= 60 ? '主体' : w >= 30 ? '重要成分' : '点缀')

const toDraft = (c: ForgeCharacter): ForgeDraft => ({
  name: c.name,
  age: c.age,
  description: c.description,
  personality: c.personality,
  speech_style: c.speech_style,
  appearance: c.appearance,
  background: c.background,
  abilities: c.abilities,
  relationships: c.relationships,
  dialogue_examples: c.dialogue_examples || [],
})

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="text-xs text-muted-foreground">{label}</span>
      <textarea
        rows={3}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`${INPUT} mt-1 resize-y`}
      />
    </label>
  )
}

function DraftForm({ value, onChange }: { value: ForgeDraft; onChange: (v: ForgeDraft) => void }) {
  const set = (patch: Partial<ForgeDraft>) => onChange({ ...value, ...patch })
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[2fr_1fr] gap-3">
        <label className="block">
          <span className="text-xs text-muted-foreground">名字</span>
          <input value={value.name} onChange={e => set({ name: e.target.value })} className={`${INPUT} mt-1`} />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">年龄</span>
          <input value={value.age} onChange={e => set({ age: e.target.value })} placeholder="如 17 / 不详" className={`${INPUT} mt-1`} />
        </label>
      </div>
      <Field label="简介" value={value.description} onChange={v => set({ description: v })} />
      <Field label="性格" value={value.personality} onChange={v => set({ personality: v })} />
      <Field label="说话风格" value={value.speech_style} onChange={v => set({ speech_style: v })} />
      <Field label="外貌" value={value.appearance} onChange={v => set({ appearance: v })} />
      <Field label="背景" value={value.background} onChange={v => set({ background: v })} />
      <Field label="能力" value={value.abilities} onChange={v => set({ abilities: v })} />
      <Field label="关系" value={value.relationships} onChange={v => set({ relationships: v })} />
      <ExampleTurnsEditor
        variant="dialogue"
        value={value.dialogue_examples}
        onChange={v => set({ dialogue_examples: v })}
      />
    </div>
  )
}

function SourcePanel({ selected, onToggle }: { selected: Set<string>; onToggle: (s: ForgeSourceItem) => void }) {
  const [search, setSearch] = useState('')
  const { data: sources = [], isLoading } = useQuery({ queryKey: ['forge-sources'], queryFn: forgeApi.sources })

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const map = new Map<string, ForgeSourceItem[]>()
    for (const s of sources) {
      if (q && !s.name.toLowerCase().includes(q)) continue
      map.set(s.group, [...(map.get(s.group) ?? []), s])
    }
    return [...map.entries()]
  }, [sources, search])

  return (
    <section className={CARD}>
      <h2 className="text-sm font-medium mb-3">来源</h2>
      <div className="relative mb-3">
        <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="按名字搜索"
          className={`${INPUT} pl-8`}
        />
      </div>
      {isLoading ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" /> 读取来源…
        </p>
      ) : groups.length === 0 ? (
        <p className="text-xs text-muted-foreground">没有可用的来源角色，先去酒馆或小说里捏几个。</p>
      ) : (
        <div className="space-y-1.5 max-h-[32rem] overflow-y-auto pr-1">
          {groups.map(([group, items]) => (
            <details key={`${group}-${search}`} open={!!search.trim()} className="border rounded-lg">
              <summary className="text-xs px-3 py-2 cursor-pointer select-none">
                {group}（{items.length}）
              </summary>
              <div className="px-2 pb-2 space-y-1">
                {items.map(s => {
                  const on = selected.has(keyOf(s.kind, s.id))
                  return (
                    <label
                      key={keyOf(s.kind, s.id)}
                      className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 cursor-pointer ${
                        on ? 'bg-primary/10 ring-1 ring-inset ring-primary/20' : 'hover:bg-muted/50'
                      }`}
                    >
                      <input type="checkbox" checked={on} onChange={() => onToggle(s)} className="accent-primary shrink-0" />
                      <CardAvatar name={s.name} url={s.avatar_url} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm truncate">{s.name}</span>
                        {s.brief && (
                          <span className="block text-[11px] text-muted-foreground truncate">{s.brief}</span>
                        )}
                      </span>
                    </label>
                  )
                })}
              </div>
            </details>
          ))}
        </div>
      )}
    </section>
  )
}

function FuseTab() {
  const qc = useQueryClient()
  const [model, setModel] = useStyleModel()
  const [refs, setRefs] = useState<SelectedSource[]>([])
  const [goal, setGoal] = useState('')
  const [draft, setDraft] = useState<ForgeDraft | null>(null)
  const [busy, setBusy] = useState(false)

  const selected = useMemo(() => new Set(refs.map(r => keyOf(r.kind, r.id))), [refs])
  const patch = (i: number, p: Partial<SelectedSource>) =>
    setRefs(refs.map((x, j) => (j === i ? { ...x, ...p } : x)))

  const toggle = (item: ForgeSourceItem) => {
    const k = keyOf(item.kind, item.id)
    if (selected.has(k)) {
      setRefs(refs.filter(r => keyOf(r.kind, r.id) !== k))
      return
    }
    if (refs.length >= 8) {
      toast.error('最多只能选 8 个来源')
      return
    }
    setRefs([...refs, { kind: item.kind, id: item.id, name: item.name, weight: 50, instruction: '' }])
  }

  const runFuse = async (needConfirm: boolean) => {
    if (busy || refs.length === 0) return
    if (needConfirm && !await confirmDialog({
      title: '重炼会覆盖当前草稿',
      detail: '右栏里已经手动改过的内容会一起消失。',
      confirmText: '重炼',
      danger: true,
    })) return
    setBusy(true)
    try {
      const res = await forgeApi.fuse({
        sources: refs.map(({ kind, id, weight, instruction }) => ({ kind, id, weight, instruction: instruction.trim() })),
        goal: goal.trim(),
        model_ref: model,
      })
      setDraft(res)
    } catch (e) {
      toast.error(errDetail(e, '炼制失败'))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (!draft) return
    if (!draft.name.trim()) {
      toast.error('先给角色起个名字')
      return
    }
    try {
      await forgeApi.create({
        ...draft,
        name: draft.name.trim(),
        sources: refs.map(({ kind, id, weight, instruction, name }) => ({ kind, id, weight, instruction, name })),
      })
      toast.success('已保存到成品')
      qc.invalidateQueries({ queryKey: ['forge-characters'] })
    } catch (e) {
      toast.error(errDetail(e, '保存失败'))
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <SourcePanel selected={selected} onToggle={toggle} />

      <section className={CARD}>
        <h2 className="text-sm font-medium mb-3">
          配方
          <span className="ml-2 text-xs font-normal text-muted-foreground">已选 {refs.length}/8</span>
        </h2>
        {refs.length === 0 ? (
          <p className="text-xs text-muted-foreground">从左边挑几个角色，再定好各占多少分量。</p>
        ) : (
          <div className="space-y-3">
            {refs.map((r, i) => (
              <div key={keyOf(r.kind, r.id)} className="border rounded-lg p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm truncate flex-1">{r.name}</span>
                  <button
                    onClick={() => setRefs(refs.filter((_, j) => j !== i))}
                    className={`${ICON_BTN} hover:text-destructive`}
                    title="移除"
                    aria-label="移除"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="range" min={0} max={100} step={5} value={r.weight}
                    onChange={e => patch(i, { weight: Number(e.target.value) })}
                    className="flex-1 accent-primary"
                  />
                  <span className="w-20 text-right text-xs tabular-nums text-muted-foreground">
                    {r.weight} · {weightLabel(r.weight)}
                  </span>
                </div>
                <input
                  value={r.instruction}
                  onChange={e => patch(i, { instruction: e.target.value })}
                  placeholder="例：取她的嘴硬和剑术"
                  className={INPUT}
                />
              </div>
            ))}
          </div>
        )}

        <label className="block mt-4">
          <span className="text-xs text-muted-foreground">整体目标（可空）</span>
          <textarea
            rows={2}
            value={goal}
            onChange={e => setGoal(e.target.value)}
            placeholder="例：炼一个既会嘴硬又肯替人挡刀的角色"
            className={`${INPUT} mt-1 resize-y`}
          />
        </label>
        <div className="mt-3">
          <StyleModelSelect value={model} onChange={setModel} />
        </div>
        <button
          onClick={() => runFuse(false)}
          disabled={busy || refs.length === 0}
          className={`${BTN_PRIMARY} w-full mt-4`}
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Flame className="w-3.5 h-3.5" />}
          {busy ? '炼制中…' : '开炉'}
        </button>
      </section>

      <section className={CARD}>
        <h2 className="text-sm font-medium mb-3">结果</h2>
        {!draft ? (
          <p className="text-xs text-muted-foreground">还没开炉。选好来源、调好比例，点「开炉」。</p>
        ) : (
          <>
            <DraftForm value={draft} onChange={setDraft} />
            <div className="flex flex-wrap gap-2 mt-4">
              <button onClick={() => runFuse(true)} disabled={busy} className={BTN_PRIMARY}>
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Flame className="w-3.5 h-3.5" />} 重炼
              </button>
              <button onClick={save} className={BTN_GHOST}>
                <Save className="w-3.5 h-3.5" /> 保存到成品
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

function MineTab() {
  const qc = useQueryClient()
  const [editId, setEditId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<ForgeDraft | null>(null)
  const [exporting, setExporting] = useState<ForgeCharacter | null>(null)
  const { data: chars = [], isLoading } = useQuery({ queryKey: ['forge-characters'], queryFn: forgeApi.list })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['forge-characters'] })

  const saveEdit = async () => {
    if (editId === null || !editDraft) return
    try {
      await forgeApi.update(editId, editDraft)
      toast.success('已更新')
      setEditId(null)
      setEditDraft(null)
      invalidate()
    } catch (e) {
      toast.error(errDetail(e, '保存失败'))
    }
  }

  const remove = async (c: ForgeCharacter) => {
    if (!await confirmDialog({
      title: `确认删除成品「${c.name}」？`,
      detail: '只删熔炉里的这一份，不会动它的来源角色。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await forgeApi.remove(c.id)
      invalidate()
    } catch {
      toast.error('删除失败')
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    )
  }

  if (chars.length === 0) {
    return <p className="text-sm text-muted-foreground">还没有成品。去「炼制」页炼一个人出来再保存。</p>
  }

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        {chars.map(c => (
          <div key={c.id} className={CARD}>
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate">{c.name}</p>
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  {c.description || '（没有简介）'}
                </p>
                <p className="text-xs text-muted-foreground mt-2 truncate">
                  来源：{c.sources.map(s => s.name).filter(Boolean).join('、') || '无记录'}
                </p>
                <p className="text-[11px] text-muted-foreground mt-1">
                  更新于 {new Date(c.updated_at).toLocaleString()}
                </p>
              </div>
              <div className="flex items-center gap-0.5 shrink-0">
                <button
                  onClick={() => { setEditId(c.id); setEditDraft(toDraft(c)) }}
                  className={ICON_BTN}
                  title="编辑"
                  aria-label="编辑"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => setExporting(c)} className={ICON_BTN} title="导出" aria-label="导出">
                  <Download className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => remove(c)}
                  className={`${ICON_BTN} hover:text-destructive`}
                  title="删除"
                  aria-label="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {editId === c.id && editDraft && (
              <div className="mt-4 border-t pt-4">
                <DraftForm value={editDraft} onChange={setEditDraft} />
                <div className="flex gap-2 mt-3">
                  <button onClick={saveEdit} className={BTN_PRIMARY}>
                    <Save className="w-3.5 h-3.5" /> 保存
                  </button>
                  <button onClick={() => { setEditId(null); setEditDraft(null) }} className={BTN_GHOST}>
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {exporting && <ExportDialog char={exporting} onClose={() => setExporting(null)} />}
    </>
  )
}

const TARGETS: { value: ForgeExportTarget; label: string }[] = [
  { value: 'tavern', label: '酒馆角色卡' },
  { value: 'npc', label: 'RPG 模组 NPC' },
  { value: 'novel', label: '小说角色' },
]

function ExportDialog({ char, onClose }: { char: ForgeCharacter; onClose: () => void }) {
  const [target, setTarget] = useState<ForgeExportTarget>('tavern')
  const [moduleId, setModuleId] = useState('')
  const [novelId, setNovelId] = useState('')
  const [busy, setBusy] = useState(false)

  const { data: modules = [] } = useQuery({
    queryKey: ['forge-modules'], queryFn: forgeApi.modules, enabled: target === 'npc',
  })
  const { data: novels = [] } = useQuery({
    queryKey: ['forge-novels'], queryFn: forgeApi.novels, enabled: target === 'novel',
  })

  const blocked = (target === 'npc' && !moduleId) || (target === 'novel' && !novelId)

  const submit = async () => {
    setBusy(true)
    try {
      await forgeApi.export(char.id, {
        target,
        module_id: target === 'npc' ? Number(moduleId) : undefined,
        novel_id: target === 'novel' ? Number(novelId) : undefined,
      })
      toast.success('已导出')
      onClose()
    } catch (e) {
      toast.error(errDetail(e, '导出失败'))
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-xl border bg-card shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b flex items-center gap-3">
          <p className="font-semibold text-sm flex-1 truncate">导出「{char.name}」</p>
          <button onClick={onClose} className={ICON_BTN} aria-label="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div className="space-y-1.5">
            {TARGETS.map(t => (
              <label
                key={t.value}
                className={`flex items-center gap-2.5 border rounded-lg px-3 py-2 cursor-pointer ${
                  target === t.value ? 'border-primary/40 bg-primary/5' : 'hover:bg-muted/50'
                }`}
              >
                <input
                  type="radio"
                  name="forge-export-target"
                  checked={target === t.value}
                  onChange={() => setTarget(t.value)}
                  className="accent-primary"
                />
                <span className="text-sm">{t.label}</span>
              </label>
            ))}
          </div>

          {target === 'npc' && (
            <label className="block">
              <span className="text-xs text-muted-foreground">目标模组</span>
              <select value={moduleId} onChange={e => setModuleId(e.target.value)} className={`${INPUT} mt-1`}>
                <option value="">请选择模组</option>
                {modules.map(m => <option key={m.id} value={String(m.id)}>{m.name}</option>)}
              </select>
            </label>
          )}

          {target === 'novel' && (
            <>
              <label className="block">
                <span className="text-xs text-muted-foreground">目标小说</span>
                <select value={novelId} onChange={e => setNovelId(e.target.value)} className={`${INPUT} mt-1`}>
                  <option value="">请选择小说</option>
                  {novels.map(n => <option key={n.id} value={String(n.id)}>{n.title}</option>)}
                </select>
              </label>
              <p className="text-xs text-muted-foreground">
                小说角色没有背景/关系栏，这两项会并入简述；对话示例不会导出。
              </p>
            </>
          )}

          <button onClick={submit} disabled={busy || blocked} className={`${BTN_PRIMARY} w-full`}>
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />} 确认导出
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

const TABS = [
  { key: 'fuse', label: '炼制' },
  { key: 'mine', label: '我的成品' },
] as const

export default function Forge() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<'fuse' | 'mine'>('fuse')

  return (
    <div className="min-h-screen bg-background relative">
      <div aria-hidden className="page-glow" />
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-md hover:bg-muted"
          title="返回模式选择"
          aria-label="返回模式选择"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
          <Flame className="w-4 h-4" />
        </span>
        <h1 className="font-bold text-lg">熔炉</h1>
        <span className="hidden sm:inline text-xs text-muted-foreground">
          把几个角色丢进去，炼一个新的人出来
        </span>
      </header>

      <main className="relative z-10 max-w-7xl mx-auto px-5 sm:px-6 pt-8 pb-16">
        <div className="flex gap-1 border-b mb-5">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 -mb-px border-b-2 text-sm font-medium transition-colors ${
                tab === t.key
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'fuse' ? <FuseTab /> : <MineTab />}
      </main>
    </div>
  )
}
