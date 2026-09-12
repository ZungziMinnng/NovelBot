import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Loader2, Plus, Trash2, Dices, BookMarked, X, Users, ScrollText,
  Globe2, Clapperboard, Settings2, ChevronDown, ImagePlus, Pin, Backpack,
  Swords, MapPin, Gauge, Sparkles, Clock, Check, AlertCircle, Wand2,
} from 'lucide-react'
import {
  rpgApi, modelLibraryApi, modelSelectValue,
  type ModelEntry, type RpgModule as Module, type RpgWorldEntry, type RpgNpc,
  type RpgInvItem, type RpgBand, type RpgCondition, type RpgSession, type RpgStatDef,
  type RpgPlayStyle,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import CharacterForm from './CharacterForm'
import WizardPanel from './WizardPanel'
import type { WizardPicked } from './WizardApplyModal'
import StatDefsSection from './StatDefsSection'
import ActionSection from './ActionSection'
import ItemSection from './ItemSection'
import LocationSection from './LocationSection'
import BatchGenerate from './BatchGenerate'
import ConditionEditor from './ConditionEditor'
import { norm, npcPlace } from './condition'
import { GENRE_PRESETS, type GenrePreset } from './genrePresets'
import {
  ACCENT, AddRow, Assist, CommaInput, DeleteButton, Field, INPUT, PANEL, Section,
} from './rpgUi'
import {
  PLAY_STYLES, STYLE_BLOCKS, STYLE_EXAMPLES, styleLabel, type BlockName,
} from './stylePresets'

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

/** 老模组这一列可能是空串，回落到默认类别（后端 `style_block` 也是这么兜的）。
 *  存回去时也得兜：PATCH 的 `play_style` 是个 Literal，空串上去就是 422——
 *  而自动保存是每改一格都发一次，一次 422 就等于这一页什么都存不进去。 */
function styleOf(m: Module | null): RpgPlayStyle {
  return PLAY_STYLES.find(s => s.key === m?.play_style)?.key ?? 'rpg'
}

// ── 自动保存 ──────────────────────────────────────────────────────────────
//
// 这一页以前是「填完点右上角「保存」」。可它长到要滚好几屏，而保存按钮孤零零
// 挂在页头：改最上面那一格的人（比如角色的「AI 调度」，勾完了要往下滚七八栏
// 才看得见保存）根本想不到还得去点它——「我明明点了，退出来又没了」就是这么
// 来的。现在改哪一格都自己存，右上角那块只负责回话。

type SaveState = 'idle' | 'saving' | 'saved' | 'error' | 'blocked'

/**
 * 改了就直接存进库，不等按钮。
 *
 * 三件事必须守住，少一件都会退化成「改了没存上，界面上还显示存上了」：
 *
 * 1. **数据到位之前一个字都不发。** 表单是 null 起步的，早发一步就是拿空表单
 *    把整行盖掉。第一次看到真实值只记基准，不保存。
 * 2. **同一时刻只放一个请求出去。** 打字会连着排好几次，而两个请求谁先落地并
 *    不由发出的顺序决定；后发的先到，库里留下的是上一秒的旧值，界面上却看不出
 *    任何异常。所以有请求在路上时不另发，等它一趟跑完再按**最新那一份**补一次。
 * 3. **存不上要说。** 状态条会一直红着，点它重试；表单收起之前也拦一道。
 *
 * `draft` 就是现在要存的那一份实体，判据和发给后端的内容是同一个东西，不必再
 * 给每一栏单独列依赖。传 null = 这一份**还存不下去**（必填栏空着）：不动基准、
 * 不发请求，只把状态条挂黄，因为「存一半的空名字」比「没存」更糟。
 *
 * 有多行可编辑时，**这份 draft 必须自带它属于哪一行**（`{id, body}`）：收尾那次
 * 保存是在表单已经换人、甚至已经关掉之后才跑的，`save` 闭包里的 `editingId`
 * 那一刻早就不对了，而 draft 一直跟着数据走。
 */
function useAutosave<T>(
  draft: T | null, ready: boolean, save: (data: T) => Promise<void>, delay = 700,
) {
  const [state, setState] = useState<SaveState>('idle')
  const key = draft === null ? null : JSON.stringify(draft)
  // 最后一份「存得下去」的形态。表单收起时它就是收尾那一次要发的内容，
  // 所以**只在 draft 非空时更新**，绝不清成 null
  const latest = useRef<{ key: string; data: T } | null>(null)
  const sent = useRef<string | null>(null)      // 已经存进去的那一份
  const writer = useRef(save)
  const running = useRef(false)
  const ok = useRef(true)
  const waiters = useRef<Array<() => void>>([])
  writer.current = save
  if (draft !== null && key !== null) latest.current = { key, data: draft }

  /** 立刻把欠的那一次存掉。返回是否存成了——存不成的时候调用方不该关表单，
   *  关了就等于默默把改动扔了，而用户看到的只是一闪而过的红字。 */
  const flush = useCallback(async (): Promise<boolean> => {
    if (running.current) {
      // 已经有一个在路上。等它跑完就行：它收尾前会自己把最新那份带出去
      await new Promise<void>(resolve => { waiters.current.push(resolve) })
      return ok.current
    }
    running.current = true
    try {
      while (latest.current && latest.current.key !== sent.current) {
        const shot = latest.current
        setState('saving')
        await writer.current(shot.data)
        sent.current = shot.key
      }
      setState('saved')
      ok.current = true
      return true
    } catch {
      // 基准停在原地：下次再改还会重试，用户也能点状态条自己重试
      setState('error')
      ok.current = false
      return false
    } finally {
      running.current = false
      const waiting = waiters.current
      waiters.current = []
      waiting.forEach(resolve => resolve())
    }
  }, [])

  useEffect(() => {
    if (!ready) {
      // 表单收起了 / 换了一条。先把欠的那一次补掉再清基准——少了这一段，
      // 「改完立刻点收起」就是丢改动，而 debounce 那几百毫秒里用户根本不会
      // 觉得自己是在抢时间
      if (sent.current !== null && sent.current !== latest.current?.key) void flush()
      sent.current = null
      setState('idle')
      return
    }
    if (key === null) { setState('blocked'); return }
    if (sent.current === null) { sent.current = key; return }  // 刚加载出来的，只记基准
    if (sent.current === key) return
    const timer = setTimeout(flush, delay)
    return () => clearTimeout(timer)
  }, [key, ready, delay, flush])

  // 卸载（点了返回、换页）时把欠的那一次送出去。这里没有 setState 的顾虑，
  // 请求也不跟着组件走——但少了它，「改完立刻返回」就是丢改动
  useEffect(() => () => {
    if (sent.current !== null && sent.current !== latest.current?.key) void flush()
  }, [flush])

  return { state, flush }
}

/** 页头 / 表单底部那块状态。以前这里是个「保存」按钮，现在只回话。 */
function SaveBadge({ state, blocked, onRetry }: {
  state: SaveState
  /** 「这一份还存不下去」时说什么。三个表单的必填栏不一样，由调用方给 */
  blocked: string
  onRetry: () => void
}) {
  if (state === 'saving') {
    return <span className="text-xs text-muted-foreground flex items-center gap-1.5">
      <Loader2 className="w-3.5 h-3.5 animate-spin" />保存中
    </span>
  }
  if (state === 'error') {
    return (
      <button onClick={onRetry} className="text-xs text-red-500 flex items-center gap-1.5 hover:underline">
        <AlertCircle className="w-3.5 h-3.5" />没存上，点这里重试
      </button>
    )
  }
  if (state === 'blocked') {
    return <span className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1.5">
      <AlertCircle className="w-3.5 h-3.5" />{blocked}
    </span>
  }
  if (state === 'saved') {
    return <span className="text-xs text-muted-foreground flex items-center gap-1.5">
      <Check className="w-3.5 h-3.5 text-primary" />已保存
    </span>
  }
  return <span className="text-xs text-muted-foreground/70">改动自动保存</span>
}

export default function RpgModule() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const moduleId = Number(id)

  const [form, setForm] = useState<Module | null>(null)

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

  // 只在**换模组**时灌一次表单。不能每次 module 变了就灌：自动保存成功后会回写
  // 查询缓存，那一灌会把用户正在敲的字盖回上一次存下来的值
  const hydrated = useRef(0)
  useEffect(() => {
    if (module && hydrated.current !== module.id) {
      hydrated.current = module.id
      setForm(module)
    }
  }, [module])

  const set = <K extends keyof Module>(key: K, value: Module[K]) =>
    setForm(prev => (prev ? { ...prev, [key]: value } : prev))

  const [wizardOpen, setWizardOpen] = useState(false)

  /** 构思向导写回。主表字段并进 form（autosave 负责存）；地点/角色/道具/动作
   *  逐条建库。顺序必须是 地点→角色→道具动作：后面的引用前面的名字，反过来
   *  角色刚建好、它待的地点还没建，游玩时就在场判定不到。数值定义并进 form 里
   *  的现有列表（追加，不覆盖作者已填的）。 */
  const applyWizard = useCallback(async (picked: WizardPicked) => {
    setForm(prev => {
      if (!prev) return prev
      const next = { ...prev }
      for (const key of ['genre', 'worldview', 'opening_scene', 'system_instruction', 'narration_sample', 'default_location'] as const) {
        const v = picked[key]
        if (typeof v === 'string' && v) next[key] = v
      }
      if (picked.stat_defs?.length) next.stat_defs = [...(prev.stat_defs || []), ...picked.stat_defs]
      if (picked.relation_stat_defs?.length) next.relation_stat_defs = [...(prev.relation_stat_defs || []), ...picked.relation_stat_defs]
      return next
    })

    try {
      for (const loc of picked.locations || []) {
        await rpgApi.locations.create(moduleId, { name: loc.name, description: loc.description, connections: loc.connections })
      }
      for (const npc of picked.npcs || []) {
        await rpgApi.npcs.create(moduleId, {
          name: npc.name, persona: npc.persona, appearance: npc.appearance,
          description: npc.description, location: npc.location, initial_state: npc.initial_state,
        })
      }
      for (const it of picked.items || []) {
        await rpgApi.items.create(moduleId, {
          name: it.name, description: it.description, category: it.category,
          consumable: it.consumable, start_with: it.start_with, effects: it.effects,
        })
      }
      for (const act of picked.actions || []) {
        await rpgApi.actions.create(moduleId, {
          name: act.name, prompt_hint: act.prompt_hint, needs_target: act.needs_target,
          effects: act.effects, relation_effects: act.relation_effects,
        })
      }
    } catch (err) {
      toast.error(`写库时出错，部分内容可能没建上：${err}`)
    }
    qc.invalidateQueries({ queryKey: ['rpg-locations', moduleId] })
    qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
    qc.invalidateQueries({ queryKey: ['rpg-items', moduleId] })
    qc.invalidateQueries({ queryKey: ['rpg-actions', moduleId] })
    setWizardOpen(false)
    toast.success('已填进模组，记得核对一下')
  }, [moduleId, qc])

  /** 现在这一份。名字空着就整份不发：`name` 是必填，存一个空的进去，
   *  模组列表那一格就成了一片空白，而用户只是把它清了准备重打 */
  const draft = form && form.name.trim()
    ? { ...form, name: form.name.trim(), play_style: styleOf(form) }
    : null

  const autosave = useAutosave(draft, !!form, async next => {
    const saved = await rpgApi.modules.update(moduleId, next)
    // 回写缓存而不是 invalidate。这一发是拿表单当真的，重取一次反而会拿服务端
    // 那一份把用户刚敲的字盖回去。列表页那份只管名字和类别，标脏就够
    qc.setQueryData(['rpg-module', moduleId], saved)
    qc.invalidateQueries({ queryKey: ['rpg-modules'] })
  })

  if (isLoading || !form) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
      </div>
    )
  }

  const playStyle = styleOf(form)
  const example = STYLE_EXAMPLES[playStyle]

  /** 喂给「帮我写」的参考。写成函数是为了取点击那一刻的表单值——
   *  作者常常是刚敲完世界观就点旁边的按钮，库里还没有这段 */
  const assistContext = () => ({
    模组名: form.name,
    玩法类别: styleLabel(playStyle),
    题材: form.genre,
    世界观: form.worldview,
  })

  // 判定区块：冒险类默认显示；其他类别只有真开着判定时才显示。
  // 后半个条件是必须的——一个开着判定的模组改成「模拟」之后，判定还在跑，
  // 而界面上再也找不到关掉它的地方
  const showDifficulty = playStyle === 'rpg' || form.check_mode !== 'never'

  /** 右栏的块。顺序按类别来（见 stylePresets.STYLE_BLOCKS），
   *  抽成表是为了只写一遍 JSX，不为三个类别各复制一份右栏 */
  const blocks: Record<BlockName, React.ReactNode> = {
    stats: (
      <Section
        title="数值系统"
        desc="整个模组的地基。玩家一套，角色共用一套——改了就存，下一页就按新的算。"
        icon={Gauge}
        accent={ACCENT.save}
      >
        <StatDefsSection form={form} set={set} example={example.stat} />
      </Section>
    ),
    slots: (
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
        <label className="flex items-start gap-2.5 cursor-pointer mt-3">
          <input
            type="checkbox"
            checked={!!form.offscreen_brief}
            onChange={e => set('offscreen_brief', e.target.checked)}
            className="mt-0.5 accent-[hsl(var(--primary))]"
          />
          <div>
            <span className="text-sm">推时段时写一句「别处」</span>
            <p className="text-xs text-muted-foreground mt-0.5">
              每次结束时段多调一次便宜模型，把玩家见过、此刻不在他身边的人在干什么，
              写一两句进大事记。开着的话按一下时钟就会花钱、也要等一下；
              不勾就是原来那样，纯引擎、零调用。角色卡里的作息表决定每个人这个时段在哪儿。
            </p>
          </div>
        </label>
      </Section>
    ),
    actions: (
      <ActionSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        relationDefs={form.relation_stat_defs || []}
        npcs={npcs}
        slotNames={form.time_slots || []}
        example={example.action}
      />
    ),
    items: (
      <ItemSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        assistContext={assistContext}
      />
    ),
    locations: (
      <LocationSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        relationDefs={form.relation_stat_defs || []}
        npcs={npcs}
        slotNames={form.time_slots || []}
        example={example.location}
        assistContext={assistContext}
      />
    ),
    inventory: (
      <Section title="开局时的背包" desc="建新的一局时整份拷进去，之后每局各玩各的，改模组不影响已开的局。" icon={Backpack} accent={ACCENT.bag}>
        <StartingInventory form={form} set={set} />
      </Section>
    ),
    worldbook: (
      <WorldBookSection
        moduleId={moduleId}
        scanDepth={form.scan_depth}
        onScanDepthChange={v => set('scan_depth', v)}
        statDefs={form.stat_defs || []}
        relationDefs={form.relation_stat_defs || []}
        npcs={npcs}
        slotNames={form.time_slots || []}
      />
    ),
    rules: (
      <RulesSection
        selected={form.enabled_rule_ids || []}
        onChange={ids => set('enabled_rule_ids', ids)}
      />
    ),
    npcs: (
      <NpcSection
        moduleId={moduleId}
        relationDefs={form.relation_stat_defs || []}
        slotNames={form.time_slots || []}
        assistContext={assistContext}
      />
    ),
    difficulty: showDifficulty ? (
      <Section title="判定" desc="默认整个关掉。想要骰子味道的模组再打开，成功率由你锁定。" icon={Dices} accent={ACCENT.save}>
        <DifficultySettings form={form} set={set} />
      </Section>
    ) : null,
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
        <span className="text-[11px] px-2 py-0.5 rounded-full shrink-0 bg-primary/10 text-primary">
          {styleLabel(playStyle)}
        </span>
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => setWizardOpen(true)}
            title="对话式构思：AI 帮你把角色、地点、道具、数值一步步定出来，回填到这份表单"
            className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
          >
            <Wand2 className="w-4 h-4" /> 构思向导
          </button>
          <SaveBadge
            state={autosave.state}
            blocked="模组名还空着，先不存"
            onRetry={autosave.flush}
          />
          <ThemePicker />
        </div>
      </header>

      {wizardOpen && (
        <div className="fixed inset-0 z-40 flex justify-end" onClick={() => setWizardOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="relative w-full max-w-md bg-background border-l shadow-2xl flex flex-col h-full"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0">
              <span className="text-sm font-medium flex items-center gap-1.5">
                <Wand2 className="w-4 h-4 text-primary" /> 构思向导
              </span>
              <button onClick={() => setWizardOpen(false)} className="p-1.5 rounded-md hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <WizardPanel moduleId={moduleId} playStyle={playStyle} onApply={applyWizard} />
            </div>
          </div>
        </div>
      )}

      <main className="relative z-10 max-w-[1440px] mx-auto px-8 py-12 space-y-8">
        <CoverHeader form={form} set={set} />

        {module && <PlaySection module={module} />}

        {/* 宽屏分两栏：左边是「这是个什么世界」，右边是跑这个世界要用的系统。
            窄屏（<1280px）自动落回单列，顺序和以前一样 */}
        <div className="grid gap-8 xl:grid-cols-2 items-start">
        <div className="space-y-8">
        <Section title="这是个什么世界" desc="每轮都会注入，是整个模组的底色。" icon={Globe2} accent={ACCENT.map}>
          <div className="space-y-5">
            <PlayStyleField value={playStyle} onChange={v => set('play_style', v)} />
            <GenreField form={form} set={set} />
            <Field
              label="世界观" multiline
              value={form.worldview}
              onChange={v => set('worldview', v)}
              placeholder="时代、地理、势力、超自然规则、当下的危机……"
              hint="写世界本身长什么样。具体的地点、人物和秘密放到世界书词条里，按关键词触发更省 token。"
              assist={{ moduleId, field: 'worldview', context: assistContext }}
            />
          </div>
        </Section>

        <Section
          title="故事从哪开始"
          desc="开新的一局时，这段是「公共场面」那条线的第一条旁白，玩家进游戏第一眼看到的就是它。"
          icon={Clapperboard}
        >
          <div className="space-y-5">
            <Field
              label="开场旁白" multiline
              value={form.opening_scene}
              onChange={v => set('opening_scene', v)}
              placeholder="玩家睁开眼看到的第一幕：在哪、什么时候、身上有什么、眼前有什么麻烦……"
              hint="用第二人称写，结尾把局面留给玩家，不要替他做决定。单独找某个人说话是另一条线，那边从空白开始（顶上会垫这一段当背景），所以别把只有一个人知道的事写在这里。"
              assist={{ moduleId, field: 'opening_scene', context: assistContext }}
            />
            <Field
              label="起始地点"
              value={form.default_location}
              onChange={v => set('default_location', v)}
              placeholder="例：地窖入口"
              hint="NPC 的常驻地点和这个对上就算在场，所以两边的写法要一致。"
            />
            <OpeningCast
              moduleId={moduleId}
              npcs={npcs}
              start={form.default_location || ''}
              pending={(form.default_location || '') !== (module?.default_location || '')}
              firstSlot={(form.time_slots || [])[0] || ''}
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
              assist={{ moduleId, field: 'system_instruction', context: assistContext }}
            />
            <Field
              label="叙事样例" multiline
              value={form.narration_sample}
              onChange={v => set('narration_sample', v)}
              placeholder="贴一两段你想要的旁白，定腔调用。"
              hint="只作为文字引用进提示词，不做成对话轮——那会让模型学着连你那一侧一起写。"
              assist={{ moduleId, field: 'narration_sample', context: assistContext }}
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
        {STYLE_BLOCKS[playStyle].map(name => (
          blocks[name] ? <Fragment key={name}>{blocks[name]}</Fragment> : null
        ))}
        </div>
        </div>
      </main>
    </div>
  )
}

/**
 * 开场时谁在场。
 *
 * **这不是一个新字段。** 「在场」在这套引擎里只有一个定义：角色的常驻地点和
 * 当前地点一模一样（后端 `rpg_context.here_npcs`、前端 `condition.onstage`），
 * 而角色在游玩过程中从不移动（没有任何地方写 npc.location）。所以「开场人物」
 * 就是「常驻地点 = 起始地点的那些人」，勾上等于替作者把那一栏填好。
 *
 * 为什么要单独摆一格：开场旁白里写了「赫敏抬头看你」，但她的常驻地点在别处，
 * 于是侧栏名单里没有她、私聊也找不到她、她的性格也不会进提示词——作者只会
 * 觉得「开场白里明明有她」。那一栏在右边的角色卡里，隔着半个页面，没人会去对。
 *
 * 读的是**表单里那一份**起始地点，不是库里那一份：这一栏改完几百毫秒就会自己
 * 落库，为这点空档禁止勾人是白等（原先那样还得回头点保存，正是被自动保存替掉的
 * 那一套）。勾了之后两边各发各的请求，谁先到都一样——模组那边是地名，这边也是
 * 地名，最终要对上的是字符串本身。
 */
function OpeningCast({ moduleId, npcs, start, pending, firstSlot }: {
  moduleId: number
  npcs: RpgNpc[]
  /** 表单里的起始地点（改了就立刻照它算谁在眼前） */
  start: string
  /** 这一栏刚改过，还在等着自动保存落库 */
  pending: boolean
  /** 时段表的第一格。开局就站在这一格上，所以开场实际按这个时段算 */
  firstSlot: string
}) {
  const qc = useQueryClient()
  const [busy, setBusy] = useState<number | null>(null)

  // 主角模板不登场，不能出现在开场名单里（同 world_npcs / knownNpcs 的过滤）
  const cast = npcs.filter(n => (n.role || 'npc') !== 'protagonist')
  // 用 npcPlace 不用 npc.location：有作息表的人开局站在作息表指定的地方，
  // 按常驻地点显示会让作者以为他在场，进游戏却发现人不在
  const here = (npc: RpgNpc) => !!start && norm(npcPlace(npc, firstSlot)) === norm(start)
  /** 作息表把他支到别处去了。这时勾选也改不动，得说清楚为什么 */
  const pinned = (npc: RpgNpc) =>
    (firstSlot ? ((npc.slot_locations || {})[firstSlot] || '').trim() : '') || ''

  const toggle = async (npc: RpgNpc) => {
    setBusy(npc.id)
    try {
      // 取消勾选清空而不是还原成别的地名：原来的值就是起始地点，没有「别处」可还
      await rpgApi.npcs.update(npc.id, { location: here(npc) ? '' : start })
      await qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
    } catch {
      toast.error('改常驻地点失败')
    } finally { setBusy(null) }
  }

  return (
    <div>
      <label className="text-xs font-medium mb-1.5 block">开场人物</label>
      {cast.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          还没有角色卡。在「角色卡」里加了人，这里就能勾谁开场就在眼前。
        </p>
      ) : !start ? (
        <p className="text-xs text-muted-foreground">先填上面的起始地点，才知道把人放在哪。</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {cast.map(npc => (
            <button
              key={npc.id}
              onClick={() => toggle(npc)}
              // 作息表把他支到别处时这一格点不动：这里只能改常驻地点，改了也没用，
              // 与其让他以为勾上了，不如直接说清楚该去哪儿改
              disabled={busy !== null || (!!pinned(npc) && !here(npc))}
              title={
                pinned(npc) && !here(npc)
                  ? `作息表里「${firstSlot}」写的是「${pinned(npc)}」，开局他不在${start}。要改去下面的角色卡`
                  : here(npc)
                    ? (pinned(npc)
                        ? `作息表里「${firstSlot}」就是「${start}」，开局就在眼前`
                        : `常驻地点是「${start}」，开局就在眼前。点一下清空`)
                    : `常驻地点${npc.location ? `是「${npc.location}」` : '是空的'}，点一下改成「${start}」`
              }
              className={`text-xs px-2.5 py-1 rounded-lg border transition-colors disabled:opacity-40 ${
                here(npc)
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'hover:bg-muted text-muted-foreground'
              }`}
            >
              {npc.name}
            </button>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground mt-1.5">
        {pending
          ? '上面的起始地点刚改过，正在自动保存——不耽误这一格，勾完两边就对上了。'
          : '勾上就是把他的常驻地点设成起始地点——开局站在你面前、名单里有他、能单独找他说话。这一格和上面每一格一样，改了就存。'}
      </p>
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

// ── 玩法类别 ──────────────────────────────────────────────────────────────

/** 类别真的会改三件事：注入给模型的玩法规则、右栏的板块顺序、判定区块露不露。
 *  所以它不是个标签，改完这一页立刻就变。 */
function PlayStyleField({
  value, onChange,
}: {
  value: RpgPlayStyle
  onChange: (v: RpgPlayStyle) => void
}) {
  return (
    <div>
      <label className="text-sm font-medium mb-2 block">怎么玩</label>
      <div className="flex gap-1.5">
        {PLAY_STYLES.map(s => (
          <button
            key={s.key}
            onClick={() => onChange(s.key)}
            title={s.hint}
            className={`flex-1 text-xs px-3 py-2 rounded-lg border transition-colors ${
              value === s.key
                ? 'bg-primary/15 text-primary border-primary/40'
                : 'text-muted-foreground hover:bg-muted'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground mt-1.5">
        {PLAY_STYLES.find(s => s.key === value)?.hint}
        {' '}这一段会写进 GM 提示词；下面的题材管的是「什么世界」，两件事互不替代。
      </p>
    </div>
  )
}

// ── 游戏类型与预设 ────────────────────────────────────────────────────────

/** 题材进 GM 提示词。真正值钱的是旁边那几个预设——
 *  空白的数值表是最劝退的东西，套一套再改比从零想快得多。
 *  预设**不**按玩法类别过滤：同一个魔法学院，模拟和冒险都跑得起来。 */
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
      // 子表当场落库：它们各有自己的接口，攒进模组那一次提交里反而更难说清
      await Promise.all([
        ...preset.actions.map((a, i) =>
          rpgApi.actions.create(form.id, { ...a, requires: {}, sort_order: i + 1 })),
        // 不覆写 consumable / start_with：这两条由每个道具自己在种子里写
        // （消耗品消耗、开局就有；装备和关键道具两样都不是）。写死 consumable
        // 会把「古旧笔记」和「项圈」也变成用一次就少一个
        ...preset.items.map((it, i) =>
          rpgApi.items.create(form.id, { ...it, usable: true, sort_order: i + 1 })),
        ...preset.locations.map((l, i) =>
          rpgApi.locations.create(form.id, { ...l, enter_requires: {}, sort_order: i + 1 })),
      ])
      for (const key of ['rpg-actions', 'rpg-items', 'rpg-locations']) {
        qc.invalidateQueries({ queryKey: [key, form.id] })
      }
      if (!form.default_location && preset.locations.length > 0) {
        set('default_location', preset.locations[0].name)
      }
      toast.success('已套用')
    } catch {
      toast.error('套用预设失败')
    } finally { setBusy('') }
  }

  return (
    <div>
      <label className="text-sm font-medium mb-2 block">题材</label>
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
        这一栏是「这一局开场凭空多一件」，比如剧本指定的信物。想让某件道具本身开局就在身上
        （每一局都有），去上面「道具」里勾「开局就带在身上」——那样它还带着定义里的说明。
        两边的名字和「道具」里的定义对上，玩家才点得出精确效果；对不上也能带着走，只是没有数值变化。
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
            裁决、结算、建议共用。这几次只吐 JSON，用便宜的就行。
          </p>
        </div>
      </div>

      <div>
        <label className="text-xs font-medium mb-1 block">总结模型</label>
        <select
          value={modelSelectValue(models, form.summary_model_ref)}
          onChange={e => set('summary_model_ref', e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
        >
          <option value="">跟随判定模型</option>
          {usable.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
        </select>
        <p className="text-xs text-muted-foreground mt-1.5">
          把超出上下文轮数的旧剧情压成梗概。它单独拎出来是因为要求不一样：
          这一段压错了会一路带到局终（下一次总结是在它的基础上接着写的），别用太便宜的。
        </p>
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

/** 写作规则勾选器。库在 RPG 设定页管理，这里只勾选哪几条注入这个模组。
 *  照酒馆 TavernCard 的 RulesSection。 */
function RulesSection({
  selected, onChange,
}: {
  selected: number[]
  onChange: (ids: number[]) => void
}) {
  const { data: rules = [] } = useQuery({
    queryKey: ['rpg-rules'],
    queryFn: rpgApi.rules.list,
  })

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  return (
    <Section
      title="写作规则"
      desc="管住叙事的用词用语。默认不启用，勾上的规则会原样拼进 GM 的系统提示词。"
      icon={ScrollText}
    >
      {rules.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          还没有写作规则。
          <Link to="/rpg/settings" className="text-primary hover:underline ml-1">去 RPG 设定写一条</Link>
        </p>
      ) : (
        <>
          <div className="space-y-2">
            {rules.map(rule => (
              <label
                key={rule.id}
                className={`flex items-start gap-2.5 border rounded-lg px-3 py-2 cursor-pointer hover:bg-muted/50 ${
                  rule.enabled ? '' : 'opacity-50'
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(rule.id)}
                  onChange={() => toggle(rule.id)}
                  className="mt-0.5 accent-[hsl(var(--primary))]"
                />
                <div className="min-w-0">
                  <span className="text-sm">{rule.name}</span>
                  {!rule.enabled && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground ml-2">
                      库里已停用
                    </span>
                  )}
                  {rule.content && (
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{rule.content}</p>
                  )}
                </div>
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            <Link to="/rpg/settings" className="text-primary hover:underline">去 RPG 设定管理规则</Link>
          </p>
        </>
      )}
    </Section>
  )
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
    // 换一条之前先把上一条欠着的那一次存掉。它自带 id，所以哪怕请求是在
    // 表单已经换人之后才发出去的，也不会写到新那一条身上
    void autosave.flush()
    setEditingId(entry.id)
    setForm({
      keywords: entry.keywords, content: entry.content, constant: entry.constant,
      depth: entry.depth, trigger_condition: entry.trigger_condition || {},
    })
    setShowForm(true)
  }

  /** 必填栏空着就整份不发。存一条既没关键词又没内容的词条进去，等于在模组里
   *  埋一个永远不触发、列表上还看不出毛病的废物 */
  const valid = form.constant || !!form.keywords.trim()
  const canSave = valid && !!form.content.trim()

  /** 改哪一格就存哪一格。新建的还没有 id，整份等「添加」一起提交 */
  const autosave = useAutosave(
    editingId !== null && canSave ? { id: editingId, body: form } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.worldEntries.update(id, body)
      refresh()
    },
  )

  /** 收起之前先把欠的那一次存掉；没存成就不收——收了就等于默默把改动扔掉 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!canSave) return
    try {
      await rpgApi.worldEntries.create(moduleId, { ...form, sort_order: entries.length + 1 })
      refresh()
      reset()
    } catch {
      toast.error('添加词条失败')
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
              <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
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
            <div className="flex items-center gap-2 justify-end">
              {/* 新的这条还没有 id，没得存，所以不挂状态条——「取消 / 添加」已经
                  把话说清楚了 */}
              {editingId !== null && (
                <span className="mr-auto">
                  <SaveBadge
                    state={autosave.state}
                    blocked="关键词或内容还空着，先不存"
                    onRetry={autosave.flush}
                  />
                </span>
              )}
              <button onClick={close} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                {editingId !== null ? '收起' : '取消'}
              </button>
              {editingId === null && (
                <button
                  onClick={submit}
                  disabled={!canSave}
                  className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                >
                  添加
                </button>
              )}
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
  slot_locations: Record<string, string>
  keywords: string
  ai_scheduled: boolean
  profile_sections: Record<string, string>
  dialogue_examples: { user: string; assistant: string }[]
  initial_state: Record<string, number | boolean>
}

const EMPTY_NPC: NpcForm = {
  name: '', role: 'npc', description: '', persona: '', appearance: '',
  location: '', slot_locations: {}, keywords: '', ai_scheduled: false,
  profile_sections: {}, dialogue_examples: [], initial_state: {},
}

// 后端拿 key 当标签直接拼进提示词，所以这里存的就是中文。
// 外貌单独一栏（只在首次见面注入），不重复放进档案
const PROFILE_KEYS: Array<[string, string]> = [
  ['背景故事', '出身、成长经历、重要事件、当前身份、人生转折……'],
  ['能力特长', '会什么、擅长什么、弱点和限制……'],
  ['关系网络', '和别的角色什么关系、有什么矛盾、藏着什么……'],
]

function NpcSection({ moduleId, relationDefs, slotNames, assistContext }: {
  moduleId: number
  relationDefs: RpgStatDef[]
  /** 模组的时段表。空 = 这个模组没有时钟，作息表那一栏整个不出现 */
  slotNames: string[]
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
}) {
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
    // 换一张卡之前先把上一张欠着的那一次存掉。它自带 id，所以哪怕请求是在
    // 表单已经换人之后才发出去的，也不会写到新那张身上
    void autosave.flush()
    setEditingId(npc.id)
    setForm({
      name: npc.name, role: npc.role, description: npc.description,
      persona: npc.persona, appearance: npc.appearance,
      location: npc.location, slot_locations: npc.slot_locations || {},
      keywords: npc.keywords,
      ai_scheduled: npc.ai_scheduled,
      profile_sections: npc.profile_sections || {},
      dialogue_examples: npc.dialogue_examples || [],
      initial_state: npc.initial_state || {},
    })
    setShowForm(true)
  }

  /** 空着的时段不存。存一个 {"早": ""} 进去，前端每次都要把它连同常驻地点
   *  再判一遍，后端也一样——两处判空迟早有一处漏掉 */
  const payload = () => ({
    ...form,
    name: form.name.trim(),
    slot_locations: Object.fromEntries(
      Object.entries(form.slot_locations).filter(([, v]) => (v || '').trim()),
    ),
  })

  /** 改哪一格就存哪一格。名字空着整份不发——后端这一列非空，存一个空名字进去，
   *  侧栏名单上就是一行没有名字的东西，而用户只是把它清了准备重打。
   *  新建的角色还没有 id，整份等「添加」一起提交 */
  const autosave = useAutosave(
    editingId !== null && form.name.trim() ? { id: editingId, body: payload() } : null,
    showForm && editingId !== null,
    async ({ id, body }) => {
      await rpgApi.npcs.update(id, body)
      refresh()
    },
  )

  /** 收起之前先把欠的那一次存掉；没存成就不收——收了就等于默默把改动扔掉 */
  const close = async () => { if (await autosave.flush()) reset() }

  const submit = async () => {
    if (!form.name.trim()) return
    try {
      await rpgApi.npcs.create(moduleId, { ...payload(), sort_order: npcs.length + 1 })
      refresh()
      reset()
    } catch {
      toast.error('添加 NPC 失败')
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

  /** 写这个人的时候额外带上他已有的那几栏：只给世界观的话，
   *  三栏会各写出一个互相不认识的人 */
  const npcContext = () => ({
    ...assistContext(),
    角色名: form.name,
    这个人是谁: form.description,
    性格: form.persona,
    外貌: form.appearance,
  })

  const setExample = (i: number, patch: Partial<{ user: string; assistant: string }>) =>
    setForm(f => ({
      ...f,
      dialogue_examples: f.dialogue_examples.map((ex, j) => (j === i ? { ...ex, ...patch } : ex)),
    }))

  /**
   * 勾了调度、可他哪儿也不会去时，把话说出来。
   *
   * 调度只替不在场的人写「在做什么」，**不替她挪窝**（挪了的话地点面板和地图
   * 迷雾都会开始说谎）。而「在哪儿」完全由作息表和常驻地点决定——两样都空着
   * 的时候，她会一直站在玩家开局那个地方，看起来就是「勾了调度她怎么还在这儿」，
   * 活像功能坏了。这条边界界面上原本一个字都没写。
   */
  const placeHint = !form.ai_scheduled ? ''
    : slotNames.length === 0
      ? '这个模组没设时段（右边「时段」那一格是空的），她不会换地方——调度只替她写「在做什么」。'
      : !Object.values(form.slot_locations).some(v => (v || '').trim())
        ? (form.location
            ? `作息表空着，她每个时段都在常驻地（${form.location}），不会自己走开。想让她某个时段待在别处，填上面的作息表；在对话里直接叫她过去也行。`
            : '常驻地点和作息表都空着，她哪儿都算不上「在场」——侧栏里不会出现这个人。把作息表每一格都填上就行（早 大礼堂、中 图书馆、晚 公共休息室），常驻地点空着没关系：它只是某一格留空时的替补。嫌早/中/晚太粗，就去右边「时段」里多写几格。')
        : ''

  return (
    <Section
      title="角色卡"
      desc="玩家走到他所在的地点，或在话里提到他，这个人才会进这一轮的提示词。标成「主角模板」的那张不登场，只在开局时预填玩家自己。"
      icon={Users}
      accent={ACCENT.cast}
    >
      <div className="space-y-2">
        {npcs.map(npc => {
          const schedule = Object.entries(npc.slot_locations || {})
            .filter(([, at]) => (at || '').trim())
            .map(([slot, at]) => `${slot}在${at}`)
          return (
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
                {/* 这一枚是唯一「会持续花钱」的标记，所以和上面两枚颜色分开：
                    扫一眼就知道哪几个人每回合都在调模型 */}
                {npc.ai_scheduled && (
                  <span
                    title="玩家没提到她时，模型会替她记一句「最近在做什么」。每回合一次模型调用"
                    className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                  >
                    AI 调度
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap line-clamp-2">
                {npc.persona || npc.description || '（没写性格）'}
              </p>
              {schedule.length > 0 && (
                <p className="text-[11px] text-muted-foreground/80 mt-1 truncate">
                  作息：{schedule.join(' · ')}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button onClick={() => startEdit(npc)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                编辑
              </button>
              <DeleteButton onClick={() => remove(npc)} />
            </div>
          </div>
          )
        })}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{editingId ? '编辑角色' : '新增角色'}</span>
              <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
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

            {/* 作息表。这一栏改的是「他此刻在哪儿」的取值方式，不是另加一条在场规则：
                某个时段留空就落回上面的常驻地点 */}
            {slotNames.length > 0 && form.role !== 'protagonist' && (
              <div>
                <label className="text-xs font-medium mb-1.5 block">作息：哪个时段在哪儿</label>
                <div className="space-y-1.5">
                  {slotNames.map(name => (
                    <div key={name} className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground w-14 shrink-0 truncate">{name}</span>
                      <input
                        value={form.slot_locations[name] || ''}
                        onChange={e => setForm(f => ({
                          ...f, slot_locations: { ...f.slot_locations, [name]: e.target.value },
                        }))}
                        placeholder="留空 = 用常驻地点"
                        className={INPUT}
                      />
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground mt-1.5">
                  填了就在这个时段待在填的地方，玩家要找他得去那儿；留空就一直在常驻地点。
                  没有固定落脚点的人（学生、行商）把每一格都填上就行，常驻地点空着没关系。
                  要让某个人某个时段「谁也找不到」，填一个玩家不去的地方就行。
                </p>
              </div>
            )}

            {/* AI 调度。和上面作息表并排的是两种「她不在场时怎么办」：
                作息表决定她在哪儿，这一条决定她在那儿干什么 */}
            {form.role !== 'protagonist' && (
              <div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.ai_scheduled}
                    onChange={e => setForm({ ...form, ai_scheduled: e.target.checked })}
                    className="mt-0.5 accent-primary"
                  />
                  <span className="text-xs font-medium">启用 AI 调度</span>
                </label>
                <p className="text-xs text-muted-foreground mt-1.5 ml-6 leading-relaxed">
                  玩家这一轮没和她说话、也没提到她时，让模型替她记一句「最近在做什么」，
                  下回见面时她会带着这段日子。每回合多一次模型调用，玩的时候能在这张卡上
                  看到记了什么，觉得不对可以划掉。
                </p>
                {placeHint && (
                  <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1.5 ml-6 leading-relaxed">
                    {placeHint}
                  </p>
                )}
              </div>
            )}

            <div>
              <textarea
                value={form.description}
                onChange={e => setForm({ ...form, description: e.target.value })}
                placeholder="一句话是谁：身份、和玩家什么关系……"
                className={`${INPUT} resize-y min-h-[3.5rem]`}
              />
              <Assist
                moduleId={moduleId}
                field="npc_description"
                context={npcContext}
                value={form.description}
                onApply={v => setForm(f => ({ ...f, description: v }))}
              />
            </div>

            <div>
              <textarea
                value={form.persona}
                onChange={e => setForm({ ...form, persona: e.target.value })}
                placeholder="性格与说话方式：他想要什么、怕什么、开口是什么调子……"
                className={`${INPUT} resize-y min-h-[5rem]`}
              />
              <Assist
                moduleId={moduleId}
                field="npc_persona"
                context={npcContext}
                value={form.persona}
                onApply={v => setForm(f => ({ ...f, persona: v }))}
              />
            </div>

            <div>
              <textarea
                value={form.appearance}
                onChange={e => setForm({ ...form, appearance: e.target.value })}
                placeholder="外貌（选填）"
                className={`${INPUT} resize-y min-h-[4rem]`}
              />
              <Assist
                moduleId={moduleId}
                field="npc_appearance"
                context={npcContext}
                value={form.appearance}
                onApply={v => setForm(f => ({ ...f, appearance: v }))}
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

            <div className="flex items-center gap-2 justify-end">
              {/* 新的这张卡还没有 id，没得存，所以不挂状态条——「取消 / 添加」已经
                  把话说清楚了 */}
              {editingId !== null && (
                <span className="mr-auto">
                  <SaveBadge
                    state={autosave.state}
                    blocked="名字还空着，先不存"
                    onRetry={autosave.flush}
                  />
                </span>
              )}
              <button onClick={close} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                {editingId !== null ? '收起' : '取消'}
              </button>
              {editingId === null && (
                <button
                  onClick={submit}
                  disabled={!form.name.trim()}
                  className="text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
                >
                  添加
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <AddRow onClick={() => setShowForm(true)}>添加角色</AddRow>
            <BatchGenerate<{
              name: string; persona: string; appearance: string; description: string
              location: string; initial_state: Record<string, number>
            }>
              moduleId={moduleId}
              kind="npc"
              placeholder="想生成什么角色？比如：生成霍格沃兹里三个教授"
              renderRow={(n) => {
                const sub = [n.location, ...Object.entries(n.initial_state || {}).map(([k, v]) => `${k} ${v}`)]
                  .filter(Boolean).join(' · ')
                return sub ? <span className="text-xs text-muted-foreground truncate">{sub}</span> : null
              }}
              onApply={async (list) => {
                for (const n of list) {
                  await rpgApi.npcs.create(moduleId, {
                    name: n.name, persona: n.persona, appearance: n.appearance,
                    description: n.description, location: n.location,
                    initial_state: n.initial_state, sort_order: npcs.length + 1,
                  })
                }
                refresh()
              }}
            />
          </div>
        )}
      </div>
    </Section>
  )
}
