import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Download, Loader2, Package, Pencil, Plus, Save, Search, Sparkles, Trash2, X,
} from 'lucide-react'
import {
  EMPTY_DRAFT, LORE_KIND_LABEL, loreApi,
  type LoreDraft, type LoreEntry, type LoreExportTarget, type LoreKind, type LoreSourceItem,
} from '@/api/lore'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import StyleModelSelect, { useStyleModel } from '@/components/StyleLibrary/StyleModelSelect'

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
  origin: LoreSourceItem['origin']
  kind: LoreSourceItem['kind']
  id: number
  name: string
  weight: number
  instruction: string
}

const keyOf = (origin: string, id: number) => `${origin}:${id}`
const weightLabel = (w: number) => (w >= 60 ? '主体' : w >= 30 ? '重要成分' : '点缀')

const toDraft = (e: LoreEntry): LoreDraft => ({
  name: e.name,
  category: e.category,
  level: e.level,
  description: e.description,
  detail: e.detail,
})

function Field({
  label, value, rows = 3, onChange,
}: { label: string; value: string; rows?: number; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="text-xs text-muted-foreground">{label}</span>
      <textarea
        rows={rows}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`${INPUT} mt-1 resize-y`}
      />
    </label>
  )
}

const CATEGORY_HINT: Record<LoreKind, string> = {
  item: '如 消耗品 / 装备 / 关键道具',
  skill: '如 主动 / 被动',
  rule: '',
}

function DraftForm({
  kind, value, onChange,
}: { kind: LoreKind; value: LoreDraft; onChange: (v: LoreDraft) => void }) {
  const set = (patch: Partial<LoreDraft>) => onChange({ ...value, ...patch })

  if (kind === 'rule') {
    return (
      <div className="space-y-3">
        <label className="block">
          <span className="text-xs text-muted-foreground">名称</span>
          <input value={value.name} onChange={e => set({ name: e.target.value })} className={`${INPUT} mt-1`} />
        </label>
        <Field label="规则正文" value={value.description} rows={8} onChange={v => set({ description: v })} />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[2fr_1fr] gap-3">
        <label className="block">
          <span className="text-xs text-muted-foreground">名称</span>
          <input value={value.name} onChange={e => set({ name: e.target.value })} className={`${INPUT} mt-1`} />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{kind === 'item' ? '稀有度' : '强度'}</span>
          <input
            value={value.level}
            onChange={e => set({ level: e.target.value })}
            placeholder="如 稀有 / 高"
            className={`${INPUT} mt-1`}
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs text-muted-foreground">类别</span>
        <input
          value={value.category}
          onChange={e => set({ category: e.target.value })}
          placeholder={CATEGORY_HINT[kind]}
          className={`${INPUT} mt-1`}
        />
      </label>
      <Field label="简述" value={value.description} rows={2} onChange={v => set({ description: v })} />
      <Field label="使用方式与限制" value={value.detail} rows={4} onChange={v => set({ detail: v })} />
    </div>
  )
}

function SourcePanel({
  kind, selected, onToggle,
}: { kind: LoreKind; selected: Set<string>; onToggle: (s: LoreSourceItem) => void }) {
  const [search, setSearch] = useState('')
  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['lore-sources', kind],
    queryFn: () => loreApi.sources(kind),
  })

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase()
    const map = new Map<string, LoreSourceItem[]>()
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
        <p className="text-xs text-muted-foreground">
          没有可用的来源，先去小说、模组或设定库里攒点{LORE_KIND_LABEL[kind]}。
        </p>
      ) : (
        <div className="space-y-1.5 max-h-[32rem] overflow-y-auto pr-1">
          {groups.map(([group, items]) => (
            <details key={`${group}-${search}`} open={!!search.trim()} className="border rounded-lg">
              <summary className="text-xs px-3 py-2 cursor-pointer select-none">
                {group}（{items.length}）
              </summary>
              <div className="px-2 pb-2 space-y-1">
                {items.map(s => {
                  const on = selected.has(keyOf(s.origin, s.id))
                  return (
                    <label
                      key={keyOf(s.origin, s.id)}
                      className={`flex items-start gap-2.5 rounded-lg px-2 py-1.5 cursor-pointer ${
                        on ? 'bg-primary/10 ring-1 ring-inset ring-primary/20' : 'hover:bg-muted/50'
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => onToggle(s)}
                        className="accent-primary shrink-0 mt-1"
                      />
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

function FuseTab({ kind }: { kind: LoreKind }) {
  const qc = useQueryClient()
  const [model, setModel] = useStyleModel()
  const [refs, setRefs] = useState<SelectedSource[]>([])
  const [goal, setGoal] = useState('')
  const [draft, setDraft] = useState<LoreDraft | null>(null)
  const [busy, setBusy] = useState(false)

  const selected = useMemo(() => new Set(refs.map(r => keyOf(r.origin, r.id))), [refs])
  const patch = (i: number, p: Partial<SelectedSource>) =>
    setRefs(refs.map((x, j) => (j === i ? { ...x, ...p } : x)))

  const toggle = (item: LoreSourceItem) => {
    const k = keyOf(item.origin, item.id)
    if (selected.has(k)) {
      setRefs(refs.filter(r => keyOf(r.origin, r.id) !== k))
      return
    }
    if (refs.length >= 8) {
      toast.error('最多只能选 8 个来源')
      return
    }
    setRefs([...refs, {
      origin: item.origin, kind: item.kind, id: item.id, name: item.name, weight: 50, instruction: '',
    }])
  }

  const runFuse = async (needConfirm: boolean) => {
    if (busy || refs.length === 0) return
    if (needConfirm && !await confirmDialog({
      title: '重融合会覆盖当前草稿',
      detail: '右栏里已经手动改过的内容会一起消失。',
      confirmText: '重融合',
      danger: true,
    })) return
    setBusy(true)
    try {
      const res = await loreApi.fuse({
        sources: refs.map(({ origin, kind: k, id, weight, instruction }) => ({
          origin, kind: k, id, weight, instruction: instruction.trim(),
        })),
        goal: goal.trim(),
        model_ref: model,
      })
      setDraft(res)
    } catch (e) {
      toast.error(errDetail(e, '融合失败'))
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (!draft) return
    if (!draft.name.trim()) {
      toast.error(`先给${LORE_KIND_LABEL[kind]}起个名字`)
      return
    }
    try {
      await loreApi.create({
        ...draft,
        name: draft.name.trim(),
        kind,
        sources: refs.map(r => ({ ...r })),
      })
      toast.success('已存进设定库')
      qc.invalidateQueries({ queryKey: ['lore-entries', kind] })
      qc.invalidateQueries({ queryKey: ['lore-sources', kind] })
    } catch (e) {
      toast.error(errDetail(e, '保存失败'))
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <SourcePanel kind={kind} selected={selected} onToggle={toggle} />

      <section className={CARD}>
        <h2 className="text-sm font-medium mb-3">
          配方
          <span className="ml-2 text-xs font-normal text-muted-foreground">已选 {refs.length}/8</span>
        </h2>
        {refs.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            从左边挑几个{LORE_KIND_LABEL[kind]}，再定好各占多少分量。
          </p>
        ) : (
          <div className="space-y-3">
            {refs.map((r, i) => (
              <div key={keyOf(r.origin, r.id)} className="border rounded-lg p-3 space-y-2">
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
                  placeholder="例：只取它的副作用设定"
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
            placeholder={`例：揉一条够狠但代价明确的${LORE_KIND_LABEL[kind]}`}
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
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          {busy ? '融合中…' : '融合'}
        </button>
      </section>

      <section className={CARD}>
        <h2 className="text-sm font-medium mb-3">结果</h2>
        {!draft ? (
          <p className="text-xs text-muted-foreground">还没融合。选好来源、调好比例，点「融合」。</p>
        ) : (
          <>
            <DraftForm kind={kind} value={draft} onChange={setDraft} />
            <div className="flex flex-wrap gap-2 mt-4">
              <button onClick={() => runFuse(true)} disabled={busy} className={BTN_PRIMARY}>
                {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />} 重融合
              </button>
              <button onClick={save} className={BTN_GHOST}>
                <Save className="w-3.5 h-3.5" /> 存进设定库
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

function NewTab({ kind, onSaved }: { kind: LoreKind; onSaved: () => void }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState<LoreDraft>(EMPTY_DRAFT)

  const save = async () => {
    if (!draft.name.trim()) {
      toast.error(`先给${LORE_KIND_LABEL[kind]}起个名字`)
      return
    }
    try {
      await loreApi.create({ ...draft, name: draft.name.trim(), kind, sources: [] })
      toast.success('已存进设定库')
      qc.invalidateQueries({ queryKey: ['lore-entries', kind] })
      qc.invalidateQueries({ queryKey: ['lore-sources', kind] })
      onSaved()
    } catch (e) {
      toast.error(errDetail(e, '保存失败'))
    }
  }

  return (
    <section className={`${CARD} max-w-2xl`}>
      <h2 className="text-sm font-medium mb-3">新建{LORE_KIND_LABEL[kind]}</h2>
      <DraftForm kind={kind} value={draft} onChange={setDraft} />
      <div className="flex gap-2 mt-4">
        <button onClick={save} className={BTN_PRIMARY}>
          <Save className="w-3.5 h-3.5" /> 存进设定库
        </button>
        <button onClick={() => setDraft(EMPTY_DRAFT)} className={BTN_GHOST}>清空</button>
      </div>
    </section>
  )
}

function MineTab({ kind, onNew }: { kind: LoreKind; onNew: () => void }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<LoreDraft>(EMPTY_DRAFT)
  const [exporting, setExporting] = useState<LoreEntry | null>(null)
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['lore-entries', kind],
    queryFn: () => loreApi.list(kind),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['lore-entries', kind] })
    qc.invalidateQueries({ queryKey: ['lore-sources', kind] })
  }
  const closeEditor = () => { setEditing(null); setDraft(EMPTY_DRAFT) }
  const openEdit = (e: LoreEntry) => { setEditing(e.id); setDraft(toDraft(e)) }

  const saveDraft = async () => {
    if (editing === null) return
    if (!draft.name.trim()) {
      toast.error(`先给${LORE_KIND_LABEL[kind]}起个名字`)
      return
    }
    try {
      await loreApi.update(editing, { ...draft, name: draft.name.trim() })
      toast.success('已更新')
      closeEditor()
      invalidate()
    } catch (e) {
      toast.error(errDetail(e, '保存失败'))
    }
  }

  const remove = async (e: LoreEntry) => {
    if (!await confirmDialog({
      title: `确认删除「${e.name}」？`,
      detail: '只删设定库里的这一份，不会动它的来源。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await loreApi.remove(e.id)
      invalidate()
    } catch {
      toast.error('删除失败')
    }
  }

  return (
    <>
      <div className="flex items-center justify-between gap-3 mb-4">
        <p className="text-xs text-muted-foreground">共 {entries.length} 条{LORE_KIND_LABEL[kind]}</p>
        <button onClick={onNew} className={BTN_PRIMARY}>
          <Plus className="w-3.5 h-3.5" /> 新建
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
        </div>
      ) : entries.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          还没有{LORE_KIND_LABEL[kind]}。去「融合」页融一条，或者点「新建」自己写。
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {entries.map(e => (
            <div key={e.id} className={CARD}>
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium truncate">{e.name}</p>
                  {(e.category || e.level) && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {[e.category, e.level].filter(Boolean).join(' · ')}
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {e.description || '（没有简述）'}
                  </p>
                  <p className="text-xs text-muted-foreground mt-2 truncate">
                    来源：{e.sources.map(s => s.name).filter(Boolean).join('、') || '无记录'}
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    更新于 {new Date(e.updated_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-0.5 shrink-0">
                  <button onClick={() => openEdit(e)} className={ICON_BTN} title="编辑" aria-label="编辑">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => setExporting(e)} className={ICON_BTN} title="导出" aria-label="导出">
                    <Download className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(e)}
                    className={`${ICON_BTN} hover:text-destructive`}
                    title="删除"
                    aria-label="删除"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {editing === e.id && (
                <div className="mt-4 border-t pt-4">
                  <DraftForm kind={kind} value={draft} onChange={setDraft} />
                  <div className="flex gap-2 mt-3">
                    <button onClick={saveDraft} className={BTN_PRIMARY}>
                      <Save className="w-3.5 h-3.5" /> 保存
                    </button>
                    <button onClick={closeEditor} className={BTN_GHOST}>取消</button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {exporting && <ExportDialog entry={exporting} onClose={() => setExporting(null)} />}
    </>
  )
}

const TARGETS: { value: LoreExportTarget; label: string }[] = [
  { value: 'novel', label: '小说' },
  { value: 'tavern', label: '酒馆角色卡' },
  { value: 'rpg', label: 'RPG 模组' },
]

function ExportDialog({ entry, onClose }: { entry: LoreEntry; onClose: () => void }) {
  const [target, setTarget] = useState<LoreExportTarget>('novel')
  const [novelId, setNovelId] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [cardId, setCardId] = useState('')
  const [busy, setBusy] = useState(false)

  const withStats = entry.kind !== 'rule'

  const { data: novels = [] } = useQuery({
    queryKey: ['lore-novels'], queryFn: loreApi.novels, enabled: target === 'novel',
  })
  const { data: modules = [] } = useQuery({
    queryKey: ['lore-modules'], queryFn: loreApi.modules, enabled: target === 'rpg',
  })
  const { data: cards = [] } = useQuery({
    queryKey: ['lore-cards'], queryFn: loreApi.cards, enabled: target === 'tavern' && withStats,
  })

  const blocked =
    (target === 'novel' && !novelId) ||
    (target === 'rpg' && !moduleId) ||
    (target === 'tavern' && withStats && !cardId)

  const submit = async () => {
    setBusy(true)
    try {
      await loreApi.export(entry.id, {
        target,
        novel_id: target === 'novel' ? Number(novelId) : undefined,
        module_id: target === 'rpg' ? Number(moduleId) : undefined,
        card_id: target === 'tavern' && withStats ? Number(cardId) : undefined,
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
          <p className="font-semibold text-sm flex-1 truncate">导出「{entry.name}」</p>
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
                  name="lore-export-target"
                  checked={target === t.value}
                  onChange={() => setTarget(t.value)}
                  className="accent-primary"
                />
                <span className="text-sm">{t.label}</span>
              </label>
            ))}
          </div>

          {target === 'novel' && (
            <label className="block">
              <span className="text-xs text-muted-foreground">目标小说</span>
              <select value={novelId} onChange={e => setNovelId(e.target.value)} className={`${INPUT} mt-1`}>
                <option value="">请选择小说</option>
                {novels.map(n => <option key={n.id} value={String(n.id)}>{n.title}</option>)}
              </select>
            </label>
          )}

          {target === 'rpg' && (
            <>
              <label className="block">
                <span className="text-xs text-muted-foreground">目标模组</span>
                <select value={moduleId} onChange={e => setModuleId(e.target.value)} className={`${INPUT} mt-1`}>
                  <option value="">请选择模组</option>
                  {modules.map(m => <option key={m.id} value={String(m.id)}>{m.name}</option>)}
                </select>
              </label>
              {withStats && (
                <p className="text-xs text-muted-foreground">
                  数值效果不会带过去，导出后请在模组里设置。
                </p>
              )}
            </>
          )}

          {target === 'tavern' && withStats && (
            <>
              <label className="block">
                <span className="text-xs text-muted-foreground">目标角色卡</span>
                <select value={cardId} onChange={e => setCardId(e.target.value)} className={`${INPUT} mt-1`}>
                  <option value="">请选择角色卡</option>
                  {cards.map(c => <option key={c.id} value={String(c.id)}>{c.name}</option>)}
                </select>
              </label>
              <p className="text-xs text-muted-foreground">会作为一条世界书词条加入所选角色卡。</p>
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

const KINDS: LoreKind[] = ['item', 'skill', 'rule']

const TABS = [
  { key: 'new', label: '新建' },
  { key: 'fuse', label: '融合' },
  { key: 'mine', label: '已存设定' },
] as const

export default function Lore() {
  const navigate = useNavigate()
  const [kind, setKind] = useState<LoreKind>('item')
  const [tab, setTab] = useState<'new' | 'fuse' | 'mine'>('new')

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
          <Package className="w-4 h-4" />
        </span>
        <h1 className="font-bold text-lg">设定库</h1>
        <span className="hidden sm:inline text-xs text-muted-foreground">
          把各处的道具、技能、规则收进一册
        </span>
      </header>

      <main className="relative z-10 max-w-7xl mx-auto px-5 sm:px-6 pt-8 pb-16">
        <div className="flex items-center gap-1 mb-4">
          {KINDS.map(k => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`px-3.5 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                kind === k
                  ? 'border-primary/40 bg-primary/5 text-foreground'
                  : 'border-transparent text-muted-foreground hover:bg-muted'
              }`}
            >
              {LORE_KIND_LABEL[k]}
            </button>
          ))}
        </div>

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

        {tab === 'new' && <NewTab key={kind} kind={kind} onSaved={() => setTab('mine')} />}
        {tab === 'fuse' && <FuseTab key={kind} kind={kind} />}
        {tab === 'mine' && <MineTab key={kind} kind={kind} onNew={() => setTab('new')} />}
      </main>
    </div>
  )
}
