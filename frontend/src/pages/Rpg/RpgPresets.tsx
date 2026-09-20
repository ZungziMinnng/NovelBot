import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ArrowLeft, Library, Plus, Pencil, X, Loader2 } from 'lucide-react'
import {
  rpgApi, type RpgActionPreset, type RpgActionSeed, type RpgStatDef, type RpgStatPreset,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import StatDefsSection, { type StatDraft } from './StatDefsSection'
import ActionFields from './ActionFields'
import { AddRow, DeleteButton, INPUT } from './rpgUi'
import {
  BUILTIN_ACTION_PACKS, BUILTIN_STAT_PACKS, defsForKeys, emptySeed, usedKeys,
  type ActionPack, type StatPack,
} from './presetLib'

/**
 * 通用套装库。数值和动作各存一个库，新建模组时挑一套套进去。
 *
 * 页面壳照 RpgSettings，列表交互照它的 RulesPane——只是少一个「停用」，
 * 理由见 StatPane 里那条注释。
 */
export default function RpgPresets() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<'stat' | 'action'>('stat')

  return (
    <div className="mode-game min-h-screen bg-background relative">
      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center gap-3">
        <button onClick={() => navigate('/game')} className="p-2 rounded-md hover:bg-muted" title="返回游戏">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Library className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg">通用套装</h1>
        <div className="ml-auto">
          <ThemePicker />
        </div>
      </header>

      <main className="relative z-10 max-w-5xl mx-auto px-6 py-8 space-y-6">
        <p className="text-xs text-muted-foreground leading-relaxed">
          把调顺手的数值和动作各存成一套，新建模组时在模组编辑页点「从库套用」就能套进去。
          <br />
          套用是<strong>拷贝一次就断开</strong>的：套完之后改这儿不会影响已经建好的模组，改模组也不会写回来。
          数值和动作是两个独立的库，套的时候可以任意搭配。
        </p>

        {/* 分 tab 而不是上下堆两张表：两边摊开有几十行，谁也翻不到底 */}
        <div className="flex gap-1.5">
          <button
            onClick={() => setTab('stat')}
            className={`flex-1 text-xs px-3 py-2 rounded-lg border transition-colors ${
              tab === 'stat' ? 'bg-primary/15 text-primary border-primary/40' : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            数值套装
          </button>
          <button
            onClick={() => setTab('action')}
            className={`flex-1 text-xs px-3 py-2 rounded-lg border transition-colors ${
              tab === 'action' ? 'bg-primary/15 text-primary border-primary/40' : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            动作套装
          </button>
        </div>

        {tab === 'stat' ? <StatPane /> : <ActionPane />}
      </main>
    </div>
  )
}

// ── 数值套装 ──────────────────────────────────────────────────────────────

function StatPane() {
  const qc = useQueryClient()
  const { data: mine = [], isLoading } = useQuery({
    queryKey: ['rpg-stat-presets'],
    queryFn: rpgApi.statPresets.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [draft, setDraft] = useState<StatDraft>({ stat_defs: [], relation_stat_defs: [] })
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-stat-presets'] })

  const reset = () => {
    setName('')
    setNote('')
    setDraft({ stat_defs: [], relation_stat_defs: [] })
    setEditingId(null)
    setShowForm(false)
  }

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」 */
  const body = () => ({
    name: name.trim(),
    note,
    stat_defs: draft.stat_defs || [],
    relation_stat_defs: draft.relation_stat_defs || [],
  })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，而用户只是把它
   *  清了准备重打。新建的套装还没有 id，整份等「创建」一起提交 */
  const autosave = useFormAutosave(
    editingId !== null && name.trim() ? { id: editingId, body: body() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.statPresets.update(id, body)
      refresh()
    },
  )

  const startEdit = (row: RpgStatPreset) => {
    // 换一套之前先把上一套欠着的那一次存掉。待存的那一份只有最新一格，
    // 不补发的话它会被下一套的草稿顶掉
    void autosave.flush()
    setEditingId(row.id)
    setName(row.name)
    setNote(row.note || '')
    // 必须 structuredClone：row 是 react-query 缓存里那个对象，直接塞进表单
    // 等于让编辑器改缓存——点「取消」之后列表上还是改了一半的样子
    setDraft({
      stat_defs: structuredClone(row.stat_defs || []),
      relation_stat_defs: structuredClone(row.relation_stat_defs || []),
    })
    setShowForm(true)
  }

  const setDraftField = <K extends keyof StatDraft>(key: K, value: StatDraft[K]) =>
    setDraft(prev => ({ ...prev, [key]: value }) as StatDraft)

  /** 收起表单。改过的东西已经存进库了，所以这里没得「取消」——但没存成的时候
   *  不能收：收了就等于把改动默默扔掉，而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      await rpgApi.statPresets.create({ ...body(), sort_order: mine.length + 1 })
      refresh()
      reset()
    } catch {
      toast.error('保存数值套装失败')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (row: RpgStatPreset) => {
    if (!await confirmDialog({
      title: `确认删除「${row.name}」？`,
      // 和写作规则那句正好相反：规则是活引用，删了所有勾上它的模组当场受影响；
      // 套装在套用那一刻就被拷走了，删库里这份动不了任何已经建好的模组
      detail: '已经套用过它的模组不受影响——套用是拷贝一次就断开的。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.statPresets.delete(row.id)
      refresh()
    } catch {
      toast.error('删除数值套装失败')
    }
  }

  const saveAs = async (pack: StatPack) => {
    try {
      const created = await rpgApi.statPresets.create({
        name: `${pack.name}（我的）`,
        note: pack.note,
        // structuredClone 是必须的：内置套装是模块级常量，编辑器改到它的引用，
        // 这次会话里所有内置套装都跟着变，刷新又变回去——最难查的那种
        stat_defs: structuredClone(pack.stat_defs),
        relation_stat_defs: structuredClone(pack.relation_stat_defs),
        sort_order: mine.length + 1,
      })
      await refresh()
      startEdit(created)   // 另存为的唯一动机就是要改它，直接进编辑态
    } catch {
      toast.error('另存为失败')
    }
  }

  const renderForm = () => (
    <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑数值套装' : '新建数值套装'}</span>
        <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
      </div>
      <div>
        <label className="text-xs font-medium mb-1 block">名称 *</label>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="例：都市打工那套"
          className={INPUT}
        />
      </div>
      <div>
        <label className="text-xs font-medium mb-1 block">一句话说明</label>
        <input
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="例：卡的是时间和钱，适合打工攒钱的局"
          className={INPUT}
        />
      </div>
      <StatDefsSection form={draft} set={setDraftField} />
      <div className="flex items-center gap-2">
        {editingId !== null && (
          <span className="mr-auto">
            <SaveBadge
              state={autosave.state}
              blocked="名字还空着，先不存"
              onRetry={autosave.flush}
            />
          </span>
        )}
        <button onClick={editingId ? close : reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
          {editingId ? '收起' : '取消'}
        </button>
        <button
          onClick={editingId ? autosave.flush : submit}
          disabled={!name.trim() || saving}
          className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5
            bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {editingId ? '立即保存' : '创建'}
        </button>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      {showForm && editingId === null && renderForm()}

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
        </div>
      ) : (
        // 这里没有「启用 / 停用」：写作规则有，是因为规则会被自动注入 prompt，
        // 停用是个有意义的中间态；套装只在作者点「套用」的那一秒被读一次
        <div className="space-y-5">
          <div className="space-y-2">
            <h2 className="text-xs font-medium text-muted-foreground">内置套装</h2>
            {/* 不写这句的话，内置行上只有一个「另存为」，看着像编辑和删除按钮漏了 */}
            <p className="text-xs text-muted-foreground/70">
              内置的三套改不了也删不掉。点「另存为」复制成自己的那一份，就能随便改了。
            </p>
            {BUILTIN_STAT_PACKS.map(pack => (
              <PresetRow
                key={pack.key}
                name={pack.name}
                note={pack.note}
                summary={`${pack.stat_defs.length} 项玩家数值 · ${pack.relation_stat_defs.length} 项关系数值`}
                chips={[...pack.stat_defs, ...pack.relation_stat_defs].map(d => d.name).filter(Boolean)}
                readonly
                onSaveAs={() => saveAs(pack)}
              />
            ))}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-medium text-muted-foreground">我的套装</h2>
              {!showForm && (
                <button
                  onClick={() => setShowForm(true)}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded border hover:bg-muted"
                >
                  <Plus className="w-3 h-3" /> 新建套装
                </button>
              )}
            </div>
            {mine.length === 0 ? (
              <div className="text-center py-16 text-sm text-muted-foreground space-y-3">
                <p>还没有自己的套装。从上面的内置套装「另存为」一份再改，或者从零建一套。</p>
                {/* 空态里再给一个入口：标题行那个按钮在一排小字里太容易被看漏 */}
                {!showForm && (
                  <button
                    onClick={() => setShowForm(true)}
                    className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border hover:bg-muted"
                  >
                    <Plus className="w-3 h-3" /> 新建套装
                  </button>
                )}
              </div>
            ) : (
              mine.map(row => (
                <div key={row.id} className="space-y-2">
                  <PresetRow
                    name={row.name}
                    note={row.note}
                    summary={
                      `${(row.stat_defs || []).length} 项玩家数值 · ${(row.relation_stat_defs || []).length} 项关系数值`
                    }
                    chips={
                      [...(row.stat_defs || []), ...(row.relation_stat_defs || [])]
                        .map((d: RpgStatDef) => d.name).filter(Boolean)
                    }
                    onEdit={() => startEdit(row)}
                    onDelete={() => remove(row)}
                  />
                  {showForm && editingId === row.id && renderForm()}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── 动作套装 ──────────────────────────────────────────────────────────────

function ActionPane() {
  const qc = useQueryClient()
  const { data: mine = [], isLoading } = useQuery({
    queryKey: ['rpg-action-presets'],
    queryFn: rpgApi.actionPresets.list,
  })
  // 和 StatPane 共用同一个 queryKey，两个 tab 来回切不会各拉一次
  const { data: statPresets = [] } = useQuery({
    queryKey: ['rpg-stat-presets'],
    queryFn: rpgApi.statPresets.list,
  })

  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [note, setNote] = useState('')
  const [actions, setActions] = useState<RpgActionSeed[]>([])
  const [refKey, setRefKey] = useState('')
  const [saving, setSaving] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-action-presets'] })

  const reset = () => {
    setName('')
    setNote('')
    setActions([])
    setRefKey('')
    setEditingId(null)
    setShowForm(false)
  }

  /** 发给后端的形态。手动提交和自动保存**共用这一份**——两边各写一遍清洗，
   *  迟早分叉成「点保存存对了、自动保存存错了」。`refKey` 不在里面：那只是为了
   *  让下面的下拉有名字可选，从来就不进库 */
  const body = () => ({
    name: name.trim(),
    note,
    // 名字空的是「点了一下添加动作」留下的空行。存进库以后每次套用都会多出
    // 一个没有字的按钮，作者还得回过头挨个删
    actions: actions.filter(a => a.name.trim()),
  })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，而用户只是把它
   *  清了准备重打。新建的套装还没有 id，整份等「创建」一起提交 */
  const autosave = useFormAutosave(
    editingId !== null && name.trim() ? { id: editingId, body: body() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.actionPresets.update(id, body)
      refresh()
    },
  )

  const startEdit = (row: RpgActionPreset) => {
    // 换一套之前先把上一套欠着的那一次存掉。待存的那一份只有最新一格，
    // 不补发的话它会被下一套的草稿顶掉
    void autosave.flush()
    setEditingId(row.id)
    setName(row.name)
    setNote(row.note || '')
    // 理由同 StatPane.startEdit：这是缓存里那个对象，不克隆就是在改缓存
    setActions(structuredClone(row.actions || []))
    // 参考套装不进库，所以改一套旧的时候无从知道当初参考的是哪套，只能空着
    setRefKey('')
    setShowForm(true)
  }

  /** 参考数值套装：只用来凑出效果编辑器里能选的数值名 */
  const packOf = (key: string): StatPack | undefined => {
    if (key.startsWith('b:')) return BUILTIN_STAT_PACKS.find(p => p.key === key.slice(2))
    if (key.startsWith('u:')) {
      const row = statPresets.find(p => p.id === Number(key.slice(2)))
      return row && {
        id: row.id,
        name: row.name,
        note: row.note || '',
        stat_defs: row.stat_defs || [],
        relation_stat_defs: row.relation_stat_defs || [],
      }
    }
    return undefined
  }
  const ref = packOf(refKey)
  // defsForKeys 还会把动作里已经填过的键补回选项，否则那些 <select> 渲染成空白行
  const statDefs = defsForKeys(ref?.stat_defs ?? [], usedKeys(actions))
  const relationDefs = defsForKeys(ref?.relation_stat_defs ?? [], usedKeys(actions, true))

  /** 收起表单。改过的东西已经存进库了，所以这里没得「取消」——但没存成的时候
   *  不能收：收了就等于把改动默默扔掉，而用户只看到红字一闪 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      await rpgApi.actionPresets.create({ ...body(), sort_order: mine.length + 1 })
      refresh()
      reset()
    } catch {
      toast.error('保存动作套装失败')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (row: RpgActionPreset) => {
    if (!await confirmDialog({
      title: `确认删除「${row.name}」？`,
      // 同 StatPane.remove
      detail: '已经套用过它的模组不受影响——套用是拷贝一次就断开的。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.actionPresets.delete(row.id)
      refresh()
    } catch {
      toast.error('删除动作套装失败')
    }
  }

  const saveAs = async (pack: ActionPack) => {
    try {
      const created = await rpgApi.actionPresets.create({
        name: `${pack.name}（我的）`,
        note: pack.note,
        // 同 StatPane.saveAs：内置套装是模块级常量，写它的引用会污染整个会话
        actions: structuredClone(pack.actions),
        sort_order: mine.length + 1,
      })
      await refresh()
      startEdit(created)   // 另存为的唯一动机就是要改它，直接进编辑态
    } catch {
      toast.error('另存为失败')
    }
  }

  const renderForm = () => (
    <div className="border rounded-lg p-4 bg-muted/30 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{editingId ? '编辑动作套装' : '新建动作套装'}</span>
        <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
      </div>
      <div>
        <label className="text-xs font-medium mb-1 block">名称 *</label>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="例：校园日常那套按钮"
          className={INPUT}
        />
      </div>
      <div>
        <label className="text-xs font-medium mb-1 block">一句话说明</label>
        <input
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="例：偏对话和约人，动手的地方少"
          className={INPUT}
        />
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-medium">参考数值套装</span>
        <select
          value={refKey}
          onChange={e => setRefKey(e.target.value)}
          className="border rounded-lg px-2 py-1.5 text-xs bg-background/60 focus:outline-none"
        >
          <option value="">不选</option>
          {BUILTIN_STAT_PACKS.map(p => (
            <option key={p.key} value={`b:${p.key}`}>{p.name}（内置）</option>
          ))}
          {statPresets.map(p => (
            <option key={p.id} value={`u:${p.id}`}>{p.name}</option>
          ))}
        </select>
        {/* 选它只为了下面几个下拉有名字可选。动作套装要能搬到任何模组去，
            把一份数值定义捎带存进来，套用时就会和模组里已有的那套对不上 */}
        <span className="text-xs text-muted-foreground">
          只决定下面能选哪些数值名，不会存进这个动作套装。
        </span>
      </div>

      <div className="space-y-2">
        {actions.map((a, i) => (
          <div key={i} className="border rounded-lg p-3 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">动作 {i + 1}</span>
              <DeleteButton onClick={() => setActions(actions.filter((_, n) => n !== i))} />
            </div>
            <ActionFields
              value={a}
              onChange={next => setActions(actions.map((x, n) => (n === i ? next : x)))}
              statDefs={statDefs}
              relationDefs={relationDefs}
            />
          </div>
        ))}
        <AddRow onClick={() => setActions([...actions, emptySeed()])}>添加动作</AddRow>
        <p className="text-xs text-muted-foreground leading-relaxed">
          可用条件（按钮什么时候能点）不存在套装里——它引用的角色名、道具名和时段都是某个模组特有的，
          搬到别的模组一条都对不上。套用之后在模组里单独设。
        </p>
      </div>

      <div className="flex items-center gap-2">
        {editingId !== null && (
          <span className="mr-auto">
            <SaveBadge
              state={autosave.state}
              blocked="名字还空着，先不存"
              onRetry={autosave.flush}
            />
          </span>
        )}
        <button onClick={editingId ? close : reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
          {editingId ? '收起' : '取消'}
        </button>
        <button
          onClick={editingId ? autosave.flush : submit}
          disabled={!name.trim() || saving}
          className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5
            bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {editingId ? '立即保存' : '创建'}
        </button>
      </div>
    </div>
  )

  return (
    <div className="space-y-4">
      {showForm && editingId === null && renderForm()}

      {isLoading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
        </div>
      ) : (
        <div className="space-y-5">
          <div className="space-y-2">
            <h2 className="text-xs font-medium text-muted-foreground">内置套装</h2>
            {/* 不写这句的话，内置行上只有一个「另存为」，看着像编辑和删除按钮漏了 */}
            <p className="text-xs text-muted-foreground/70">
              内置的三套改不了也删不掉。点「另存为」复制成自己的那一份，就能随便改了。
            </p>
            {BUILTIN_ACTION_PACKS.map(pack => (
              <PresetRow
                key={pack.key}
                name={pack.name}
                note={pack.note}
                summary={`${pack.actions.length} 个动作`}
                chips={pack.actions.map(a => a.name).filter(Boolean)}
                readonly
                onSaveAs={() => saveAs(pack)}
              />
            ))}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-medium text-muted-foreground">我的套装</h2>
              {!showForm && (
                <button
                  onClick={() => setShowForm(true)}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded border hover:bg-muted"
                >
                  <Plus className="w-3 h-3" /> 新建套装
                </button>
              )}
            </div>
            {mine.length === 0 ? (
              <div className="text-center py-16 text-sm text-muted-foreground space-y-3">
                <p>还没有自己的套装。从上面的内置套装「另存为」一份再改，或者从零建一套。</p>
                {/* 空态里再给一个入口：标题行那个按钮在一排小字里太容易被看漏 */}
                {!showForm && (
                  <button
                    onClick={() => setShowForm(true)}
                    className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border hover:bg-muted"
                  >
                    <Plus className="w-3 h-3" /> 新建套装
                  </button>
                )}
              </div>
            ) : (
              mine.map(row => (
                <div key={row.id} className="space-y-2">
                  <PresetRow
                    name={row.name}
                    note={row.note}
                    summary={`${(row.actions || []).length} 个动作`}
                    chips={(row.actions || []).map((a: RpgActionSeed) => a.name).filter(Boolean)}
                    onEdit={() => startEdit(row)}
                    onDelete={() => remove(row)}
                  />
                  {showForm && editingId === row.id && renderForm()}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** 列表里的一行。两个库、内置和我的共用一份：抄四份迟早长成四种样子 */
function PresetRow({
  name, note, summary, chips, readonly = false, onSaveAs, onEdit, onDelete,
}: {
  name: string
  note?: string
  summary: string
  chips: string[]
  /** true = 内置套装，只能「另存为」 */
  readonly?: boolean
  onSaveAs?: () => void
  onEdit?: () => void
  onDelete?: () => void
}) {
  return (
    <div className={`border rounded-lg px-4 py-3 bg-card/50 backdrop-blur-sm ${readonly ? 'opacity-75' : ''}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium">{name}</span>
            {readonly && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">内置</span>
            )}
          </div>
          {note && <p className="text-xs text-muted-foreground mt-1">{note}</p>}
          <p className="text-xs text-muted-foreground mt-1">{summary}</p>
          {chips.length > 0 && (
            <div className="flex items-center flex-wrap gap-1 mt-1.5">
              {chips.slice(0, 8).map((c, i) => (
                <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                  {c}
                </span>
              ))}
              {chips.length > 8 && (
                <span className="text-[11px] text-muted-foreground">+{chips.length - 8}</span>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {readonly ? (
            <button
              onClick={onSaveAs}
              title="内置套装改不了。另存为自己的那一份，编辑和删除就都有了"
              className="text-xs px-2 py-1 rounded border hover:bg-muted"
            >
              另存为
            </button>
          ) : (
            <>
              <button onClick={onEdit} className="p-1.5 rounded hover:bg-muted" title="编辑">
                <Pencil className="w-3.5 h-3.5" />
              </button>
              <DeleteButton onClick={() => onDelete?.()} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}
