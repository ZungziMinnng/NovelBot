import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Loader2, Plus, Trash2, Dices, BookMarked, X, Users, ScrollText,
  Globe2, Clapperboard, Settings2, ChevronDown, ImagePlus, Pin, Backpack,
  Swords, MapPin, Gauge, Sparkles, Clock,
} from 'lucide-react'
import {
  rpgApi, modelLibraryApi, modelSelectValue,
  type ModelEntry, type RpgModule as Module, type RpgWorldEntry, type RpgNpc,
  type RpgInvItem, type RpgBand, type RpgCondition, type RpgSession, type RpgStatDef,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import CharacterForm from './CharacterForm'
import StatDefsSection from './StatDefsSection'
import ActionSection from './ActionSection'
import ItemSection from './ItemSection'
import LocationSection from './LocationSection'
import ConditionEditor from './ConditionEditor'
import { GENRE_PRESETS, type GenrePreset } from './genrePresets'
import { ACCENT, AddRow, CommaInput, DeleteButton, Field, INPUT, PANEL, Section } from './rpgUi'

const BANDS: Array<{ key: RpgBand; label: string }> = [
  { key: 'trivial', label: '轻易' },
  { key: 'easy', label: '简单' },
  { key: 'medium', label: '普通' },
  { key: 'hard', label: '困难' },
  { key: 'extreme', label: '极难' },
]

// never 排第一也是默认值：推动游戏的是数值在动，判定只是冒险题材的调味
const CHECK_MODES: Array<{ key: Module['check_mode']; label: string; hint: string }> = [
  { key: 'never', label: '不判定', hint: '完全不判定，少一次模型调用。都市、养成这类题材一般就用这个。' },
  { key: 'smart', label: 'AI 判断', hint: '由 AI 决定这一步要不要判。闲聊不判，动手才判。' },
  { key: 'always', label: '每轮都判', hint: '任何输入都先判一次。硬核，也最费钱。' },
]

export default function RpgModule() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const moduleId = Number(id)

  const [form, setForm] = useState<Module | null>(null)
  const [saving, setSaving] = useState(false)

  const { data: module, isLoading } = useQuery({
    queryKey: ['rpg-module', moduleId],
    queryFn: () => rpgApi.modules.get(moduleId),
    enabled: Number.isFinite(moduleId) && moduleId > 0,
  })

  // 条件编辑器要拿角色名做下拉，世界书 / 动作 / 地点三处都要，所以在这一层取一次。
  // NpcSection 用的是同一个 queryKey，缓存共享，不会多发请求
  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', moduleId],
    queryFn: () => rpgApi.npcs.list(moduleId),
    enabled: Number.isFinite(moduleId) && moduleId > 0,
  })

  useEffect(() => { if (module) setForm(module) }, [module])

  const set = <K extends keyof Module>(key: K, value: Module[K]) =>
    setForm(prev => (prev ? { ...prev, [key]: value } : prev))

  const handleSave = async () => {
    if (!form || !form.name.trim()) return
    setSaving(true)
    try {
      await rpgApi.modules.update(moduleId, { ...form, name: form.name.trim() })
      qc.invalidateQueries({ queryKey: ['rpg-module', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-modules'] })
      toast.success('已保存')
    } catch {
      toast.error('保存模组失败')
    } finally { setSaving(false) }
  }

  if (isLoading || !form) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
      </div>
    )
  }

  return (
    <div className="mode-rpg min-h-screen bg-background relative">
      <div className="fixed inset-0 z-0 opacity-[0.10] pointer-events-none">
        <Silk speed={2} scale={1.4} color="#6d3ab0" noiseIntensity={1.4} rotation={0} className="w-full h-full" />
      </div>

      <header className="sticky top-0 z-20 border-b border-border/50 bg-background/80 backdrop-blur-md px-6 py-3.5 flex items-center gap-3">
        <button onClick={() => navigate('/rpg')} className="p-2 rounded-md hover:bg-muted" title="返回模组列表">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Dices className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg truncate">{form.name || '模组'}</h1>
        <div className="ml-auto flex items-center gap-3">
          <ThemePicker />
          <button
            onClick={handleSave}
            disabled={!form.name.trim() || saving}
            className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            保存
          </button>
        </div>
      </header>

      <main className="relative z-10 max-w-[1440px] mx-auto px-8 py-12 space-y-8">
        <CoverHeader form={form} set={set} />

        {module && <PlaySection module={module} />}

        {/* 宽屏分两栏：左边是「这是个什么世界」，右边是跑这个世界要用的系统。
            窄屏（<1280px）自动落回单列，顺序和以前一样 */}
        <div className="grid gap-8 xl:grid-cols-2 items-start">
        <div className="space-y-8">
        <Section title="这是个什么世界" desc="每轮都会注入，是整个模组的底色。" icon={Globe2} accent={ACCENT.map}>
          <div className="space-y-5">
            <GenreField form={form} set={set} />
            <Field
              label="世界观" multiline
              value={form.worldview}
              onChange={v => set('worldview', v)}
              placeholder="时代、地理、势力、超自然规则、当下的危机……"
              hint="写世界本身长什么样。具体的地点、人物和秘密放到世界书词条里，按关键词触发更省 token。"
            />
          </div>
        </Section>

        <Section title="故事从哪开始" desc="开新的一局时，这段会作为第一条旁白。" icon={Clapperboard}>
          <div className="space-y-5">
            <Field
              label="开场旁白" multiline
              value={form.opening_scene}
              onChange={v => set('opening_scene', v)}
              placeholder="玩家睁开眼看到的第一幕：在哪、什么时候、身上有什么、眼前有什么麻烦……"
              hint="用第二人称写，结尾把局面留给玩家，不要替他做决定。"
            />
            <Field
              label="起始地点"
              value={form.default_location}
              onChange={v => set('default_location', v)}
              placeholder="例：地窖入口"
              hint="NPC 的常驻地点和这个对上就算在场，所以两边的写法要一致。"
            />
          </div>
        </Section>

        <Collapsible title="叙事风格与生成参数" icon={Settings2}>
          <div className="space-y-5">
            <Field
              label="GM 指令" multiline
              value={form.system_instruction}
              onChange={v => set('system_instruction', v)}
              placeholder="语气偏冷硬还是戏谑、血腥程度、要不要写 NPC 的内心……"
              hint="接在内置 GM 底稿之后，可以覆盖它。「第二人称、只写已发生的、不替玩家做决定」底稿已经写了，不用重复。"
            />
            <Field
              label="叙事样例" multiline
              value={form.narration_sample}
              onChange={v => set('narration_sample', v)}
              placeholder="贴一两段你想要的旁白，定腔调用。"
              hint="只作为文字引用进提示词，不做成对话轮——那会让模型学着连你那一侧一起写。"
            />
            <GenerationParams form={form} set={set} />
          </div>
        </Collapsible>

        <Collapsible title="你自己的备注" icon={ScrollText}>
          <Field
            label="模组介绍" multiline
            value={form.creator_note}
            onChange={v => set('creator_note', v)}
            placeholder="这个模组是干什么的、灵感来源、你自己的备注……"
            hint="AI 不会看到这段内容，只在列表页给你自己认模组用。"
          />
        </Collapsible>
        </div>

        <div className="space-y-8">
        <Section
          title="数值系统"
          desc="整个模组的地基。玩家一套，角色共用一套——改这里要点右上角保存才生效。"
          icon={Gauge}
          accent={ACCENT.save}
        >
          <StatDefsSection form={form} set={set} />
        </Section>

        <Section
          title="时段"
          desc="玩家自己拨的时钟。留空 = 这个模组不管时间，一切照旧。"
          icon={Clock}
          accent={ACCENT.save}
        >
          <CommaInput
            value={form.time_slots || []}
            onChange={v => set('time_slots', v)}
            placeholder="早，中，晚"
          />
          <p className="text-xs text-muted-foreground mt-1.5">
            按播放顺序写，用逗号隔开（中英文逗号都行）。开局时玩家站在第一格，
            「结束这个时段」往后推一格，推过最后一格就算过了一天。开始冒险时还可以按局改。
          </p>
        </Section>

        <ActionSection
          moduleId={moduleId}
          statDefs={form.stat_defs || []}
          relationDefs={form.relation_stat_defs || []}
          npcs={npcs}
          slotNames={form.time_slots || []}
        />

        <ItemSection moduleId={moduleId} statDefs={form.stat_defs || []} />

        <LocationSection
          moduleId={moduleId}
          statDefs={form.stat_defs || []}
          relationDefs={form.relation_stat_defs || []}
          npcs={npcs}
          slotNames={form.time_slots || []}
        />

        <Section title="开局时的背包" desc="建新的一局时整份拷进去，之后每局各玩各的，改模组不影响已开的局。" icon={Backpack} accent={ACCENT.bag}>
          <StartingInventory form={form} set={set} />
        </Section>

        <WorldBookSection
          moduleId={moduleId}
          scanDepth={form.scan_depth}
          onScanDepthChange={v => set('scan_depth', v)}
          statDefs={form.stat_defs || []}
          relationDefs={form.relation_stat_defs || []}
          npcs={npcs}
          slotNames={form.time_slots || []}
        />

        <NpcSection moduleId={moduleId} relationDefs={form.relation_stat_defs || []} />

        <Section title="判定" desc="默认整个关掉。想要骰子味道的模组再打开，成功率由你锁定。" icon={Dices} accent={ACCENT.save}>
          <DifficultySettings form={form} set={set} />
        </Section>
        </div>
        </div>
      </main>
    </div>
  )
}

// ── 开局与存档 ────────────────────────────────────────────────────────────

/** 从这里进游戏。一个模组可以开多局，每局的角色和状态各走各的。 */
function PlaySection({ module }: { module: Module }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)

  const { data: sessions = [], isLoading } = useQuery({
    queryKey: ['rpg-sessions', module.id],
    queryFn: () => rpgApi.sessions.list(module.id),
  })

  const remove = async (sess: RpgSession) => {
    if (!await confirmDialog({
      title: `确认删掉「${sess.title || sess.char_name}」这一局？`,
      detail: '这一局的全部剧情和存档会一起删掉，不可恢复。模组本身不受影响。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.sessions.delete(sess.id)
      qc.invalidateQueries({ queryKey: ['rpg-sessions', module.id] })
    } catch {
      toast.error('删除这一局失败')
    }
  }

  return (
    <Section title="开始冒险" desc="一个模组可以开很多局，每局各玩各的。" icon={Swords}>
      <div className="space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载中...
          </div>
        ) : sessions.map(sess => (
          <div
            key={sess.id}
            role="button"
            tabIndex={0}
            onClick={() => navigate(`/rpg/play/${sess.id}`)}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault(); navigate(`/rpg/play/${sess.id}`)
              }
            }}
            className="group flex items-center gap-3 rounded-lg border border-violet-500/20 bg-violet-500/[0.04]
              px-4 py-3 cursor-pointer hover:bg-violet-500/10 transition-colors focus:outline-none"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">
                {sess.title || sess.char_name || new Date(sess.created_at).toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-3 flex-wrap">
                <span>第 {sess.turn_count} 回合</span>
                {sess.location && (
                  <span className="flex items-center gap-1">
                    <MapPin className="w-3 h-3" />{sess.location}
                  </span>
                )}
                {sess.status !== 'alive' && <span className="text-rose-400">已结束</span>}
              </p>
            </div>
            <button
              onClick={e => { e.stopPropagation(); remove(sess) }}
              className="p-1.5 rounded opacity-0 group-hover:opacity-100 transition-opacity
                hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
              title="删掉这一局"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        <button
          onClick={() => setCreating(true)}
          className="w-full flex items-center justify-center gap-1.5 text-sm py-3 border border-dashed
            border-violet-500/30 rounded-lg text-muted-foreground hover:bg-violet-500/5"
        >
          <Plus className="w-4 h-4" /> 开新的一局
        </button>
      </div>

      {creating && (
        <CharacterForm
          module={module}
          onClose={() => setCreating(false)}
          onCreated={sess => navigate(`/rpg/play/${sess.id}`)}
        />
      )}
    </Section>
  )
}

// ── 通用外壳 ──────────────────────────────────────────────────────────────

function Collapsible({ title, icon: Icon, children }: { title: string; icon: typeof Dices; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <section className={`${PANEL} backdrop-blur-sm`}>
      <button onClick={() => setOpen(o => !o)} className="w-full px-6 py-4 flex items-center gap-3 text-left">
        <div className="p-2 rounded-lg bg-muted text-muted-foreground shrink-0">
          <Icon className="w-4 h-4" />
        </div>
        <h2 className="font-semibold text-sm flex-1">{title}</h2>
        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && <div className="px-6 pb-6">{children}</div>}
    </section>
  )
}

/** 表单内部的折叠块。Collapsible 是整页级别的卡片，塞进表单里太重了 */
function Fold({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="border rounded-lg bg-background/40">
      <summary className="px-3 py-2 text-xs text-muted-foreground cursor-pointer select-none">
        {title}
      </summary>
      <div className="px-3 pb-3">{children}</div>
    </details>
  )
}

// ── 封面与名字 ────────────────────────────────────────────────────────────

function CoverHeader({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  const pick = async (file?: File) => {
    if (!file) return
    setBusy(true)
    try {
      const updated = await rpgApi.modules.uploadCover(form.id, file)
      set('cover_url', updated.cover_url)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || '上传封面失败')
    } finally { setBusy(false) }
  }

  const clear = async () => {
    setBusy(true)
    try {
      await rpgApi.modules.deleteCover(form.id)
      set('cover_url', '')
    } catch {
      toast.error('删除封面失败')
    } finally { setBusy(false) }
  }

  return (
    <div className={`${PANEL} backdrop-blur-sm p-6 flex items-center gap-5`}>
      <button
        onClick={() => fileRef.current?.click()}
        disabled={busy}
        className="w-20 h-20 rounded-xl shrink-0 flex items-center justify-center overflow-hidden
          ring-1 ring-violet-500/25 bg-gradient-to-br from-violet-500/35 to-indigo-700/25
          text-violet-900 dark:text-violet-200 hover:ring-violet-500/60 transition-colors"
        title="换封面"
      >
        {busy
          ? <Loader2 className="w-5 h-5 animate-spin" />
          : form.cover_url
            ? <img src={form.cover_url} alt={form.name} className="w-full h-full object-cover" />
            : <ImagePlus className="w-6 h-6" />}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        className="hidden"
        onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }}
      />
      <div className="flex-1 min-w-0">
        <label className="text-sm font-medium mb-2 block">模组名字</label>
        <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="例：锈锁地窖" className={INPUT} />
        {form.cover_url && (
          <button onClick={clear} className="text-xs text-muted-foreground hover:text-red-400 mt-2">
            移除封面
          </button>
        )}
      </div>
    </div>
  )
}

// ── 游戏类型与预设 ────────────────────────────────────────────────────────

/** 类型进 GM 提示词。真正值钱的是旁边那几个预设——
 *  空白的数值表是最劝退的东西，套一套再改比从零想快得多。 */
function GenreField({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')

  const apply = async (preset: GenrePreset) => {
    const hasStats = (form.stat_defs || []).length > 0 || (form.relation_stat_defs || []).length > 0
    if (hasStats && !await confirmDialog({
      title: `用「${preset.label}」覆盖现在的数值表？`,
      detail: '现有的数值定义会被换掉，动作、道具、地点则是追加，不删已有的。',
      confirmText: '套用',
    })) return

    setBusy(preset.key)
    try {
      set('genre', preset.genre)
      set('stat_defs', preset.stat_defs)
      set('relation_stat_defs', preset.relation_stat_defs)
      // 子表直接落库：它们各有自己的接口，攒到「保存」那一下反而更难说清
      await Promise.all([
        ...preset.actions.map((a, i) =>
          rpgApi.actions.create(form.id, { ...a, requires: {}, sort_order: i + 1 })),
        ...preset.items.map((it, i) =>
          rpgApi.items.create(form.id, { ...it, usable: true, consumable: true, sort_order: i + 1 })),
        ...preset.locations.map((l, i) =>
          rpgApi.locations.create(form.id, { ...l, enter_requires: {}, sort_order: i + 1 })),
      ])
      for (const key of ['rpg-actions', 'rpg-items', 'rpg-locations']) {
        qc.invalidateQueries({ queryKey: [key, form.id] })
      }
      if (!form.default_location && preset.locations.length > 0) {
        set('default_location', preset.locations[0].name)
      }
      toast.success('已套用，数值表记得点右上角保存')
    } catch {
      toast.error('套用预设失败')
    } finally { setBusy('') }
  }

  return (
    <div>
      <label className="text-sm font-medium mb-2 block">游戏类型</label>
      <input
        value={form.genre}
        onChange={e => set('genre', e.target.value)}
        placeholder="例：现代都市生活 / 魔法学院 / 互动养成"
        className={INPUT}
      />
      <div className="flex flex-wrap gap-1.5 mt-2">
        {GENRE_PRESETS.map(preset => (
          <button
            key={preset.key}
            onClick={() => apply(preset)}
            disabled={!!busy}
            title={preset.desc}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg
              bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20 disabled:opacity-50"
          >
            {busy === preset.key
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Sparkles className="w-3 h-3" />}
            {preset.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-1.5">
        这句话直接写进 GM 提示词。点上面的预设会把数值、动作、道具、地点一次填好。
      </p>
    </div>
  )
}

// ── 开局背包 ──────────────────────────────────────────────────────────────

function StartingInventory({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const items = form.default_inventory || []

  const setItem = (i: number, patch: Partial<RpgInvItem>) =>
    set('default_inventory', items.map((it, n) => (n === i ? { ...it, ...patch } : it)))

  return (
    <div>
      <div className="space-y-2">
        {items.map((item, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              value={item.name}
              onChange={e => setItem(i, { name: e.target.value })}
              placeholder="物品名"
              className={`${INPUT} flex-1`}
            />
            <input
              type="number" min={1}
              value={item.qty}
              onChange={e => setItem(i, { qty: Math.max(1, Number(e.target.value) || 1) })}
              className={`${INPUT} w-20`}
            />
            <input
              value={item.note || ''}
              onChange={e => setItem(i, { note: e.target.value })}
              placeholder="备注（选填）"
              className={`${INPUT} flex-1`}
            />
            <DeleteButton onClick={() => set('default_inventory', items.filter((_, n) => n !== i))} />
          </div>
        ))}
        <AddRow onClick={() => set('default_inventory', [...items, { name: '', qty: 1, note: '' }])}>
          添加物品
        </AddRow>
      </div>
      <p className="text-xs text-muted-foreground mt-1.5">
        名字和上面「道具」里的定义对上，玩家才点得出精确效果；对不上也能带着走，只是没有数值变化。
      </p>
    </div>
  )
}

// ── 判定 ──────────────────────────────────────────────────────────────────

function DifficultySettings({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const table = form.rate_table
  const off = form.check_mode === 'never'

  return (
    <div className="space-y-5">
      <div>
        <label className="text-xs font-medium mb-1.5 block">什么时候判定</label>
        <div className="flex gap-1.5">
          {CHECK_MODES.map(mode => (
            <button
              key={mode.key}
              onClick={() => set('check_mode', mode.key)}
              className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                form.check_mode === mode.key
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'hover:bg-muted text-muted-foreground'
              }`}
            >
              {mode.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          {CHECK_MODES.find(m => m.key === form.check_mode)?.hint}
        </p>
      </div>

      {!off && (
        <>
          <div>
            <label className="text-xs font-medium mb-1.5 block">各档位的成功率</label>
            <div className="grid grid-cols-5 gap-3">
              {BANDS.map(band => (
                <div key={band.key}>
                  <span className="text-xs text-muted-foreground mb-1 block">{band.label}</span>
                  <input
                    type="number" min={5} max={95}
                    value={table[band.key]}
                    onChange={e => set('rate_table', {
                      ...table, [band.key]: Math.max(5, Math.min(95, Number(e.target.value) || 5)),
                    })}
                    className={INPUT}
                  />
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-1.5">
              百分数。数值每高于 10 点一点再加 4%，两头永远留 5%——100% 必成的判定不如不判。
              差 20% 以内是「险胜」：做成了，但要付出代价。
            </p>
          </div>

          <div className="w-40">
            <label className="text-xs font-medium mb-1.5 block">整体难度偏移</label>
            <input
              type="number" min={-30} max={30}
              value={form.difficulty_bias}
              onChange={e => set('difficulty_bias', Math.max(-30, Math.min(30, Number(e.target.value) || 0)))}
              className={INPUT}
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              加到每个成功率上。-10 更硬核，+10 更手软。
            </p>
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={form.random_check}
              onChange={e => set('random_check', e.target.checked)}
              className="mt-0.5 accent-[hsl(var(--primary))]"
            />
            <div>
              <span className="text-sm">掷随机数</span>
              <p className="text-xs text-muted-foreground mt-0.5">
                关掉就纯看成功率：同一个存档重玩，同样的输入必然同样的结果。
              </p>
            </div>
          </label>
        </>
      )}
    </div>
  )
}

// ── 生成参数 ──────────────────────────────────────────────────────────────

function GenerationParams({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  const usable = models.filter((m: ModelEntry) => m.model_type !== 'embedding')
  // 负温度 = 整个参数不发给供应商，llm_client 里 `if temperature >= 0` 已有这个约定
  const tempOff = form.temperature < 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium mb-1 block">叙事模型</label>
          <select
            value={modelSelectValue(models, form.model_ref)}
            onChange={e => set('model_ref', e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
          >
            <option value="">跟随默认</option>
            {usable.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
          </select>
          <p className="text-xs text-muted-foreground mt-1.5">写旁白的那次调用，挑好的。</p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">判定与结算模型</label>
          <select
            value={modelSelectValue(models, form.fast_model_ref)}
            onChange={e => set('fast_model_ref', e.target.value)}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
          >
            <option value="">跟随默认</option>
            {usable.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
          </select>
          <p className="text-xs text-muted-foreground mt-1.5">
            裁决、结算、摘要、建议共用。这几次只吐 JSON，用便宜的就行。
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium mb-1 block">旁白长度</label>
          <div className="flex items-center gap-2">
            <input
              type="number" min={0} max={2000} step={50}
              value={form.reply_length}
              onChange={e => set('reply_length', Math.max(0, Number(e.target.value) || 0))}
              className={`${INPUT} w-28`}
            />
            <span className="text-xs text-muted-foreground">字，0 = 不作要求</span>
          </div>
          <p className="text-xs text-muted-foreground mt-1.5">软要求，不是硬截断。</p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">上下文轮数</label>
          <input
            type="number" min={1} max={100}
            value={form.context_turns}
            onChange={e => set('context_turns', Math.max(1, Number(e.target.value) || 1))}
            className={INPUT}
          />
          <p className="text-xs text-muted-foreground mt-1.5">更早的会压成梗概。</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium mb-1 block">温度</label>
          <input
            type="number" min={0} max={2} step={0.05}
            value={tempOff ? '' : form.temperature}
            disabled={tempOff}
            onChange={e => set('temperature', Number(e.target.value))}
            className={`${INPUT} disabled:opacity-40`}
          />
          <label className="flex items-center gap-1.5 mt-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={tempOff}
              onChange={e => set('temperature', e.target.checked ? -1 : 0.9)}
              className="accent-[hsl(var(--primary))]"
            />
            <span className="text-xs text-muted-foreground">不传</span>
          </label>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">单次上限</label>
          <input
            type="number" min={256} max={32768} step={256}
            value={form.max_tokens}
            onChange={e => set('max_tokens', Number(e.target.value))}
            className={INPUT}
          />
          <p className="text-xs text-muted-foreground mt-1.5">tokens，安全网。</p>
        </div>
      </div>
    </div>
  )
}

// ── 世界书 ────────────────────────────────────────────────────────────────

interface EntryForm {
  keywords: string
  content: string
  constant: boolean
  depth: number
  trigger_condition: RpgCondition
}

const EMPTY_ENTRY: EntryForm = {
  keywords: '', content: '', constant: false, depth: 0, trigger_condition: {},
}

function WorldBookSection({
  moduleId, scanDepth, onScanDepthChange, statDefs, relationDefs, npcs, slotNames,
}: {
  moduleId: number
  scanDepth: number
  onScanDepthChange: (v: number) => void
  statDefs: RpgStatDef[]
  relationDefs: RpgStatDef[]
  npcs: RpgNpc[]
  slotNames: string[]
}) {
  const qc = useQueryClient()
  const { data: entries = [] } = useQuery({
    queryKey: ['rpg-world-book', moduleId],
    queryFn: () => rpgApi.worldEntries.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<EntryForm>(EMPTY_ENTRY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-world-book', moduleId] })
  const reset = () => { setForm(EMPTY_ENTRY); setEditingId(null); setShowForm(false) }

  const startEdit = (entry: RpgWorldEntry) => {
    setEditingId(entry.id)
    setForm({
      keywords: entry.keywords, content: entry.content, constant: entry.constant,
      depth: entry.depth, trigger_condition: entry.trigger_condition || {},
    })
    setShowForm(true)
  }

  const submit = async () => {
    if ((!form.constant && !form.keywords.trim()) || !form.content.trim()) return
    try {
      if (editingId) {
        await rpgApi.worldEntries.update(editingId, form)
      } else {
        await rpgApi.worldEntries.create(moduleId, { ...form, sort_order: entries.length + 1 })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存词条失败')
    }
  }

  const toggle = async (entry: RpgWorldEntry) => {
    try {
      await rpgApi.worldEntries.update(entry.id, { enabled: !entry.enabled })
      refresh()
    } catch {
      toast.error('切换词条状态失败')
    }
  }

  const remove = async (entry: RpgWorldEntry) => {
    if (!await confirmDialog({ title: '确认删除这条世界书词条？', confirmText: '删除', danger: true })) return
    try {
      await rpgApi.worldEntries.delete(entry.id)
      refresh()
    } catch {
      toast.error('删除词条失败')
    }
  }

  return (
    <Section
      title="世界书"
      desc="关键词命中才注入，不命中就不占 token。加上条件之后，「常驻 + 好感≥50」就是一条到线才解锁的剧情。"
      icon={BookMarked}
      accent={ACCENT.map}
    >
      <div className="mb-4 pb-4 border-b flex items-center gap-2 flex-wrap">
        <label className="text-xs font-medium">关键词扫描范围</label>
        <input
          type="number" min={1} max={20}
          value={scanDepth}
          onChange={e => onScanDepthChange(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
          className={`${INPUT} w-16`}
        />
        <span className="text-xs text-muted-foreground">
          条消息{scanDepth <= 1 ? '：只看玩家刚发的这句' : `：这句 + 往回 ${scanDepth - 1} 条`}
        </span>
        <p className="text-xs text-muted-foreground w-full">
          调大了旁白自己也会参与匹配，同一条词条容易连着触发好几轮。想让某条设定一直在，用「常驻」比调大这个稳。
        </p>
      </div>

      <div className="space-y-2">
        {entries.map(entry => (
          <div key={entry.id} className={`border rounded-lg px-3 py-2 ${entry.enabled ? '' : 'opacity-60'}`}>
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  {entry.constant && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15
                      text-amber-700 dark:text-amber-300 flex items-center gap-1">
                      <Pin className="w-2.5 h-2.5" /> 常驻
                    </span>
                  )}
                  {Object.keys(entry.trigger_condition || {}).length > 0 && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                      有条件
                    </span>
                  )}
                  {entry.keywords
                    // 分隔符必须与后端保持一致，否则这里显示成两个词、实际却当成一个来匹配
                    ? entry.keywords.split(/[,，、;；\n]+/).filter(Boolean).map((kw, i) => (
                        <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                          {kw}
                        </span>
                      ))
                    : !entry.constant && <span className="text-xs text-muted-foreground">（没有关键词）</span>}
                  {entry.depth > 0 && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                      深度 {entry.depth}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap line-clamp-3">{entry.content}</p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={() => toggle(entry)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                  {entry.enabled ? '停用' : '启用'}
                </button>
                <button onClick={() => startEdit(entry)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                  编辑
                </button>
                <DeleteButton onClick={() => remove(entry)} />
              </div>
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑词条' : '新增词条'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <input
              value={form.keywords}
              onChange={e => setForm({ ...form, keywords: e.target.value })}
              disabled={form.constant}
              placeholder={form.constant ? '常驻词条不看关键词' : '关键词（逗号或顿号分隔，如：地窖，锈锁）'}
              className={`${INPUT} disabled:opacity-50`}
            />
            <textarea
              value={form.content}
              onChange={e => setForm({ ...form, content: e.target.value })}
              placeholder="要注入的设定内容"
              className={`${INPUT} resize-y min-h-[6rem]`}
            />
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={form.constant}
                onChange={e => setForm({ ...form, constant: e.target.checked })}
                className="mt-0.5 accent-[hsl(var(--primary))]"
              />
              <div>
                <span className="text-sm">常驻</span>
                <p className="text-xs text-muted-foreground mt-0.5">
                  不看关键词，每轮都注入。代价是一直占 token。
                </p>
              </div>
            </label>
            <div>
              <label className="text-xs font-medium mb-1 block">插入深度</label>
              <input
                type="number" min={0} max={20}
                value={form.depth}
                onChange={e => setForm({ ...form, depth: Math.max(0, Number(e.target.value) || 0) })}
                className={`${INPUT} w-24`}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                0 = 放在系统提示词里。填 1 会贴在玩家这一条发言前面，2 是再往前一条。离当前对话越近模型越不会忽略。
              </p>
            </div>
            <div>
              <label className="text-xs font-medium mb-1.5 block">生效条件</label>
              <ConditionEditor
                value={form.trigger_condition}
                onChange={v => setForm({ ...form, trigger_condition: v })}
                statDefs={statDefs}
                relationDefs={relationDefs}
                npcs={npcs}
                slotNames={slotNames}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                条件只是附加约束：关键词词条要「命中关键词并且满足条件」；常驻词条则是满足条件后每轮都注入。
              </p>
            </div>
            <div className="flex gap-2 justify-end">
              <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button
                onClick={submit}
                disabled={(!form.constant && !form.keywords.trim()) || !form.content.trim()}
                className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {editingId ? '保存' : '添加'}
              </button>
            </div>
          </div>
        ) : (
          <AddRow onClick={() => setShowForm(true)}>添加词条</AddRow>
        )}
      </div>
    </Section>
  )
}

// ── NPC ───────────────────────────────────────────────────────────────────

interface NpcForm {
  name: string
  role: RpgNpc['role']
  description: string
  persona: string
  appearance: string
  location: string
  keywords: string
  profile_sections: Record<string, string>
  dialogue_examples: { user: string; assistant: string }[]
  initial_state: Record<string, number | boolean>
}

const EMPTY_NPC: NpcForm = {
  name: '', role: 'npc', description: '', persona: '', appearance: '',
  location: '', keywords: '', profile_sections: {}, dialogue_examples: [], initial_state: {},
}

// 后端拿 key 当标签直接拼进提示词，所以这里存的就是中文。
// 外貌单独一栏（只在首次见面注入），不重复放进档案
const PROFILE_KEYS: Array<[string, string]> = [
  ['背景故事', '出身、成长经历、重要事件、当前身份、人生转折……'],
  ['能力特长', '会什么、擅长什么、弱点和限制……'],
  ['关系网络', '和别的角色什么关系、有什么矛盾、藏着什么……'],
]

function NpcSection({ moduleId, relationDefs }: { moduleId: number; relationDefs: RpgStatDef[] }) {
  const qc = useQueryClient()
  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', moduleId],
    queryFn: () => rpgApi.npcs.list(moduleId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NpcForm>(EMPTY_NPC)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
  const reset = () => { setForm(EMPTY_NPC); setEditingId(null); setShowForm(false) }

  const startEdit = (npc: RpgNpc) => {
    setEditingId(npc.id)
    setForm({
      name: npc.name, role: npc.role, description: npc.description,
      persona: npc.persona, appearance: npc.appearance,
      location: npc.location, keywords: npc.keywords,
      profile_sections: npc.profile_sections || {},
      dialogue_examples: npc.dialogue_examples || [],
      initial_state: npc.initial_state || {},
    })
    setShowForm(true)
  }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      if (editingId) {
        await rpgApi.npcs.update(editingId, { ...form, name: form.name.trim() })
      } else {
        await rpgApi.npcs.create(moduleId, { ...form, name: form.name.trim(), sort_order: npcs.length + 1 })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存 NPC 失败')
    }
  }

  const remove = async (npc: RpgNpc) => {
    if (!await confirmDialog({
      title: `确认删除 NPC「${npc.name}」？`,
      detail: '已经开的局里，它的好感和状态会一起失效。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await rpgApi.npcs.delete(npc.id)
      refresh()
    } catch {
      toast.error('删除 NPC 失败')
    }
  }

  const setProfile = (key: string, text: string) =>
    setForm(f => ({ ...f, profile_sections: { ...f.profile_sections, [key]: text } }))

  const setExample = (i: number, patch: Partial<{ user: string; assistant: string }>) =>
    setForm(f => ({
      ...f,
      dialogue_examples: f.dialogue_examples.map((ex, j) => (j === i ? { ...ex, ...patch } : ex)),
    }))

  return (
    <Section
      title="角色卡"
      desc="玩家走到他所在的地点，或在话里提到他，这个人才会进这一轮的提示词。标成「主角模板」的那张不登场，只在开局时预填玩家自己。"
      icon={Users}
      accent={ACCENT.cast}
    >
      <div className="space-y-2">
        {npcs.map(npc => (
          <div key={npc.id} className="border rounded-lg px-3 py-2 flex items-start gap-3">
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium">{npc.name}</span>
                {npc.role === 'protagonist' && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">
                    主角模板
                  </span>
                )}
                {npc.location && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                    {npc.location}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap line-clamp-2">
                {npc.persona || npc.description || '（没写性格）'}
              </p>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(npc)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(npc)} />
            </div>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑角色' : '新增角色'}</span>
              <button onClick={reset} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>

            <div className="flex gap-1.5">
              {(['npc', 'protagonist'] as const).map(role => (
                <button
                  key={role}
                  onClick={() => setForm({ ...form, role })}
                  className={`text-xs px-3 py-1.5 rounded-lg border ${
                    form.role === role
                      ? 'bg-primary/15 text-primary border-primary/40'
                      : 'text-muted-foreground hover:bg-muted'
                  }`}
                >
                  {role === 'npc' ? 'NPC' : '主角模板'}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-2">
              <input
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="名字"
                className={INPUT}
              />
              <input
                value={form.location}
                onChange={e => setForm({ ...form, location: e.target.value })}
                placeholder="常驻地点（要和地点表里的写法一致）"
                className={INPUT}
              />
            </div>

            <textarea
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="一句话是谁：身份、和玩家什么关系……"
              className={`${INPUT} resize-y min-h-[3.5rem]`}
            />

            <textarea
              value={form.persona}
              onChange={e => setForm({ ...form, persona: e.target.value })}
              placeholder="性格与说话方式：他想要什么、怕什么、开口是什么调子……"
              className={`${INPUT} resize-y min-h-[5rem]`}
            />

            <div>
              <textarea
                value={form.appearance}
                onChange={e => setForm({ ...form, appearance: e.target.value })}
                placeholder="外貌（选填）"
                className={`${INPUT} resize-y min-h-[4rem]`}
              />
              <p className="text-xs text-muted-foreground mt-1.5">只在玩家第一次见到他时注入，之后就省掉了。</p>
            </div>

            <Fold title="详细档案（选填）">
              <div className="space-y-2">
                {PROFILE_KEYS.map(([key, hint]) => (
                  <div key={key}>
                    <label className="block text-xs text-muted-foreground mb-1">{key}</label>
                    <textarea
                      value={form.profile_sections[key] || ''}
                      onChange={e => setProfile(key, e.target.value)}
                      placeholder={hint}
                      className={`${INPUT} resize-y min-h-[4rem]`}
                    />
                  </div>
                ))}
              </div>
            </Fold>

            <Fold title="对话示例（选填）">
              <div className="space-y-2">
                {form.dialogue_examples.map((ex, i) => (
                  <div key={i} className="border rounded-lg p-2 space-y-1.5 bg-background/40">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">第 {i + 1} 组</span>
                      <span className="flex-1" />
                      <DeleteButton
                        onClick={() => setForm({
                          ...form,
                          dialogue_examples: form.dialogue_examples.filter((_, j) => j !== i),
                        })}
                      />
                    </div>
                    <textarea
                      value={ex.user}
                      onChange={e => setExample(i, { user: e.target.value })}
                      placeholder="玩家说了什么"
                      className={`${INPUT} resize-y min-h-[3rem]`}
                    />
                    <textarea
                      value={ex.assistant}
                      onChange={e => setExample(i, { assistant: e.target.value })}
                      placeholder="他会怎么回"
                      className={`${INPUT} resize-y min-h-[3rem]`}
                    />
                  </div>
                ))}
                <AddRow onClick={() => setForm({
                  ...form,
                  dialogue_examples: [...form.dialogue_examples, { user: '', assistant: '' }],
                })}>
                  添加一组
                </AddRow>
                <p className="text-xs text-muted-foreground">
                  比写十行性格管用：模型照着这个语气学，比照着形容词学准。
                </p>
              </div>
            </Fold>

            {form.role === 'npc' && relationDefs.length > 0 && (
              <Fold title="关系数值的起点（选填）">
                <div className="grid grid-cols-2 gap-2">
                  {relationDefs.map(def => (
                    <div key={def.name} className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground shrink-0">{def.name}</span>
                      <input
                        type="number"
                        value={String(form.initial_state[def.name] ?? def.initial)}
                        onChange={e => setForm({
                          ...form,
                          initial_state: { ...form.initial_state, [def.name]: Number(e.target.value) || 0 },
                        })}
                        className={INPUT}
                      />
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground mt-1.5">
                  不填就用数值表里的起点。这里是给「一见面就恨你」这种角色开小灶的。
                </p>
              </Fold>
            )}

            <div>
              <input
                value={form.keywords}
                onChange={e => setForm({ ...form, keywords: e.target.value })}
                placeholder="额外触发词（选填，逗号分隔）"
                className={INPUT}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                人不在场但玩家提到这些词时也注入，比如他的外号、他负责的东西。
              </p>
            </div>

            <div className="flex gap-2 justify-end">
              <button onClick={reset} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">取消</button>
              <button
                onClick={submit}
                disabled={!form.name.trim()}
                className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {editingId ? '保存' : '添加'}
              </button>
            </div>
          </div>
        ) : (
          <AddRow onClick={() => setShowForm(true)}>添加角色</AddRow>
        )}
      </div>
    </Section>
  )
}
