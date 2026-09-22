import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Loader2, Plus, Trash2, Dices, BookMarked, X, Users, ScrollText,
  Globe2, Clapperboard, Settings2, ImagePlus, Pin, Backpack, UserRound,
  Swords, MapPin, Gauge, Sparkles, Clock, Check, Wand2, MessageSquare,
  ChevronLeft, ChevronRight, BookOpen, BookmarkPlus, Eraser,
} from 'lucide-react'
import {
  rpgApi, modelLibraryApi, modelSelectValue, groupModelsByProvider,
  type RpgModule as Module, type RpgWorldEntry, type RpgNpc,
  type RpgInvItem, type RpgBand, type RpgCondition, type RpgSession, type RpgStatDef,
  type RpgPlayStyle, type RpgImageConfig,
} from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import { SaveBadge } from '@/components/SaveBadge/SaveBadge'
import { useFormAutosave } from '@/lib/useFormAutosave'
import CharacterForm from './CharacterForm'
import { protagonistCard } from './protagonist'
import WizardPanel from './WizardPanel'
import type { WizardPicked } from './WizardApplyModal'
import { applyWizardEntities, mergeWizardFields } from './wizardApply'
import StatDefsSection from './StatDefsSection'
import { StatPresetBar } from './PresetTools'
import ActionSection from './ActionSection'
import ItemSection from './ItemSection'
import SkillSection from './SkillSection'
import TaskSection from './TaskSection'
import LocationSection from './LocationSection'
import NpcAvatarField from './NpcAvatarField'
import ImageSettingsDrawer from './ImageSettingsDrawer'
import TriggerGuide from './TriggerGuide'
import BatchGenerate from './BatchGenerate'
import ConditionEditor from './ConditionEditor'
import { norm, npcPlace } from './condition'
import { GENRE_PRESETS, type GenrePreset } from './genrePresets'
import { GAMEPLAY_MODEL_FIELDS, EXTRA_MODEL_FIELDS, isEmbeddingField } from './modelSettings'
import {
  ACCENT, AddRow, Assist, CommaInput, DeleteButton, Field, INPUT, NumInput, PANEL, Section,
} from './rpgUi'
import {
  PLAY_STYLES, STYLE_BLOCKS, STYLE_EXAMPLES, blockTitle, styleLabel, type BlockName,
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

export default function RpgModule() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const moduleId = Number(id)
  // 从哪一局点进来的。玩到一半出来改设定，改完想直接回去接着玩，而不是回列表
  // 里再把这一局找出来——但那是**另加一颗按钮**的事，左上角那个箭头仍然是
  // 「退出去选模组」，两条路不能合并成一个。
  // 地址栏是玩家能改的，所以要验一下是正整数，不然 /game/play/abc 会把播放页打崩
  const [search] = useSearchParams()
  const fromSession = Number(search.get('from'))
  const backToPlay = Number.isInteger(fromSession) && fromSession > 0 ? fromSession : null

  const [formState, setForm] = useState<Module | null>(null)

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
  const [imageOpen, setImageOpen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [activePanel, setActivePanel] = useState('world')
  const [panelDirection, setPanelDirection] = useState(1)

  const applyWizard = useCallback(async (picked: WizardPicked) => {
    try {
      // 台账要在开写之前取：applyWizardEntities 靠它认出「上一轮向导建的行」并先删掉
      const written = formState?.wizard_state || {}
      const state = await applyWizardEntities(moduleId, picked, written)
      setForm(prev => (prev ? { ...mergeWizardFields(prev, picked, written), wizard_state: state } : prev))
      setWizardOpen(false)
      toast.success('已回填，上一轮向导填的内容已换成这一轮的')
    } finally {
      qc.invalidateQueries({ queryKey: ['rpg-locations', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-items', moduleId] })
      qc.invalidateQueries({ queryKey: ['rpg-actions', moduleId] })
    }
  }, [moduleId, formState?.wizard_state, qc])

  /** 现在这一份。名字空着就整份不发：`name` 是必填，存一个空的进去，
   *  模组列表那一格就成了一片空白，而用户只是把它清了准备重打 */
  const draft = formState && formState.name.trim()
    ? { ...formState, name: formState.name.trim(), play_style: styleOf(formState) }
    : null

  const autosave = useFormAutosave(draft, !!formState, async next => {
    const saved = await rpgApi.modules.update(moduleId, next)
    // 回写缓存而不是 invalidate。这一发是拿表单当真的，重取一次反而会拿服务端
    // 那一份把用户刚敲的字盖回去。列表页那份只管名字和类别，标脏就够
    qc.setQueryData(['rpg-module', moduleId], saved)
    qc.invalidateQueries({ queryKey: ['rpg-modules'] })
  })

  if (isLoading || !formState) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中...
      </div>
    )
  }

  const form = formState
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

  // 判定区块三种类别都显示。以前只有冒险类显示、其他类别要在真开着判定时才显示，
  // 那是个死循环：关着判定就看不到这一块，看不到就永远打不开它（模拟和 SLG 的默认
  // 恰好都是关的）。默认值仍然按类别给（见 stylePresets.STYLE_DEFAULTS），
  // 「默认关」由那个默认值表达，不靠把设置项藏起来

  /** 一摊数据一个块。顺序按类别来（见 stylePresets.STYLE_BLOCKS），
   *  抽成表是为了只写一遍 JSX，不为三个类别各复制一份。
   *  world / narration 不在这里：它们是整页的头和尾，各自还要拼别的东西
   *  （PlayStyleField、GenerationParams），下面单独建 */
  const blocks: Record<Exclude<BlockName, 'world' | 'narration'>, React.ReactNode> = {
    stats: (
      <Section
        title="数值系统"
        desc="整个模组的地基。玩家一套，角色共用一套——改了就存，下一页就按新的算。"
        icon={Gauge}
        accent={ACCENT.save}
      >
        {/* 工具条放在这儿而不是 StatDefsSection 内部：那个编辑器套装库自己也在用，
            在库里编辑一套数值时出现「从库套用」是荒谬的 */}
        <div className="mb-4"><StatPresetBar form={form} set={set} /></div>
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
        {/* 起因是玩家会忘记按那颗按钮，时间就彻底冻住：作息表不换班、
            剧情临时挪过的位置永久盖住作者排的班、跨天恢复永远不发生 */}
        <div className="grid grid-cols-2 gap-3 mt-3">
          <div>
            <label className="text-xs font-medium mb-1 block">每时段行动上限</label>
            <div className="flex items-center gap-2">
              <input
                type="number" min={0} max={99}
                value={form.slot_budget ?? 0}
                onChange={e => set('slot_budget', Math.max(0, Number(e.target.value) || 0))}
                className={`${INPUT} w-28`}
              />
              <span className="text-xs text-muted-foreground">格，0 = 关</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1.5">
              点动作、用道具、放技能、移动各算一格，攒满自动往后推一格。
              纯聊天不算——话多不等于世界该变。
            </p>
          </div>
          <div>
            <label className="text-xs font-medium mb-1 block">聊到几条就提醒</label>
            <div className="flex items-center gap-2">
              <input
                type="number" min={0} max={999}
                value={form.chat_nudge ?? 0}
                onChange={e => set('chat_nudge', Math.max(0, Number(e.target.value) || 0))}
                className={`${INPUT} w-28`}
              />
              <span className="text-xs text-muted-foreground">条，0 = 关</span>
            </div>
            <p className="text-xs text-muted-foreground mt-1.5">
              只把「结束这个时段」那颗按钮点亮，时间一格都不动。推不推还是玩家自己定。
            </p>
          </div>
        </div>
        {/* 上面那两栏都是「只提醒」，这一栏是唯一一个让引擎真的动时间的开关。
            摆在它们下面而不是并排：它改的是「聊天到底算不算时间」这条规则，
            不是又一个阈值 */}
        <label className="flex items-start gap-2.5 cursor-pointer mt-3">
          <input
            type="checkbox"
            checked={!!form.free_costs_slot}
            onChange={e => set('free_costs_slot', e.target.checked)}
            className="mt-0.5 accent-[hsl(var(--primary))]"
          />
          <div>
            <span className="text-sm">自由打字演完一幕也占一格</span>
            <p className="text-xs text-muted-foreground mt-0.5">
              不是每句话都占：只有结算判定「这一幕收尾了」那一轮才算一格，
              闲聊几句不收尾就是 0 格。模拟器和角色养成这类「今天安排什么」的玩法
              需要它，否则玩家能在一个时段里聊到天荒地老。不勾就是原来那样，
              自由打字永远不动时间。
            </p>
          </div>
        </label>
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
        // 模拟器里这些按钮就是玩家的主界面（见 SimHome），不是聊天框旁边的快捷路
        title={blockTitle('actions', playStyle)}
        desc={playStyle === 'sim'
          ? '玩家的主界面就是这些按钮。填了「分栏」的会在主页上分栏摆开，点一次数字精确变化，不经过 AI。'
          : undefined}
        // 套动作套装时一键补建缺的数值。数值表在这一层，动作区够不着
        onAddStats={(stats, relations) => {
          if (stats.length) set('stat_defs', [...(form.stat_defs || []), ...stats])
          if (relations.length) set('relation_stat_defs', [...(form.relation_stat_defs || []), ...relations])
        }}
      />
    ),
    items: (
      <ItemSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        assistContext={assistContext}
      />
    ),
    skills: (
      <SkillSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        relationDefs={form.relation_stat_defs || []}
        npcs={npcs}
        slotNames={form.time_slots || []}
        assistContext={assistContext}
      />
    ),
    // 任务没有条件编辑器——「接不接得下」是剧情说了算，不是数值卡的，
    // 所以不用像技能那样把 relationDefs/npcs/slotNames 一路传进去
    tasks: (
      <TaskSection
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
    protagonist: (
      <ProtagonistSection
        moduleId={moduleId}
        npcs={npcs}
        form={form}
        set={set}
        assistContext={assistContext}
      />
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
    generation: (
      <Section title="生成参数" desc="分别选择 8 类 AI 功能的模型，并调整生成长度、上下文和温度。" icon={Settings2}>
        <GenerationParams form={form} set={set} />
      </Section>
    ),
    npcs: (
      <NpcSection
        moduleId={moduleId}
        statDefs={form.stat_defs || []}
        rankStat={form.rank_stat || ''}
        checkOff={form.check_mode === 'never'}
        relationDefs={form.relation_stat_defs || []}
        slotNames={form.time_slots || []}
        assistContext={assistContext}
        genre={form.genre}
        imageConfig={form.image_config || {}}
      />
    ),
    difficulty: (
      <Section title="判定" desc="默认整个关掉。想要骰子味道的模组再打开，成功率由你锁定。" icon={Dices} accent={ACCENT.save}>
        <DifficultySettings form={form} set={set} />
      </Section>
    ),
  }

  const worldPanel = (
    <Section title="这是个什么世界" desc="每轮都会注入，是整个模组的底色。" icon={Globe2} accent={ACCENT.map}>
      <div className="space-y-5">
        <PlayStyleField value={playStyle} onChange={v => set('play_style', v)} />
        <GenreField form={form} set={set} />
        <Field label="世界观" multiline value={form.worldview} onChange={v => set('worldview', v)} placeholder="时代、地理、势力、超自然规则、当下的危机……" hint="写世界本身长什么样。具体的地点、人物和秘密放到世界书词条里。" assist={{ moduleId, field: 'worldview', context: assistContext }} />
        <div className="border-t border-border/60 pt-5 space-y-5">
          <div className="flex items-center gap-2 text-sm font-medium"><Clapperboard className="w-4 h-4 text-primary" />故事从哪开始</div>
          <Field label="开场旁白" multiline value={form.opening_scene} onChange={v => set('opening_scene', v)} placeholder="玩家睁开眼看到的第一幕……" assist={{ moduleId, field: 'opening_scene', context: assistContext }} />
          <OpeningLocationSelect moduleId={moduleId} label="主角起始地点" value={form.default_location || ''} onChange={value => set('default_location', value)} />
          <OpeningCast
            moduleId={moduleId} npcs={npcs} start={form.default_location || ''}
            firstSlot={(form.time_slots || [])[0] || ''}
            selected={form.opening_npc_ids || []} placements={form.opening_npc_locations || {}}
            onChange={(ids, placements) => setForm(prev => prev ? {
              ...prev, opening_npc_ids: ids, opening_npc_locations: placements,
            } : prev)}
          />
        </div>
      </div>
    </Section>
  )
  const narrationPanel = (
    <Section title="叙事风格" desc="通过 GM 指令、叙事样例和写作规则控制叙事风格。" icon={ScrollText}>
      <div className="space-y-5">
        <div>
          <Field label="GM 指令" multiline value={form.system_instruction} onChange={v => set('system_instruction', v)} placeholder="语气、血腥程度、是否描写 NPC 的内心……" assist={{ moduleId, field: 'system_instruction', context: assistContext }} />
          <InstructionPresets
            current={form.system_instruction || ''}
            onPick={async text => {
              const existing = (form.system_instruction || '').trim()
              // 空文本 = 取消/清空，那本来就是明确的意图，不要再问一遍
              if (text.trim() && existing && existing !== text.trim()
                  && !await confirmDialog({
                    title: '覆盖已经写好的 GM 指令？',
                    detail: '上面输入框里的内容会被这条常用指令替换掉。',
                    confirmText: '覆盖',
                  })) return
              set('system_instruction', text)
            }}
          />
        </div>
        <Field label="叙事样例" multiline value={form.narration_sample} onChange={v => set('narration_sample', v)} placeholder="贴一两段你想要的旁白，定下腔调。" assist={{ moduleId, field: 'narration_sample', context: assistContext }} />
        <RulesSection
          selected={form.enabled_rule_ids || []}
          onChange={ids => set('enabled_rule_ids', ids)}
        />
        <details className="border rounded-lg bg-background/40">
          <summary className="px-3 py-2 text-xs text-muted-foreground cursor-pointer select-none">自己的备注</summary>
          <div className="px-3 pb-3 pt-1"><Field label="模组介绍" multiline value={form.creator_note} onChange={v => set('creator_note', v)} placeholder="这个模组是做什么的、灵感来源、自己的备注……" hint="AI 不会看到这段内容。" /></div>
        </details>
      </div>
    </Section>
  )
  /** 面板顺序按玩法类别来（见 stylePresets.STYLE_BLOCKS）。
   *  以前这里是一张硬编码的表，三个类别看到的是同一个顺序，而那张按类别排的表
   *  挂在一段 `&& false` 的死分支里——两者只能留一个，留的是能按类别变的那张。
   *  node 为空的块自动不占一格——现在没有这种块了，留着是给以后按条件藏的块兜底，
   *  也让「只往 STYLE_BLOCKS 里加名字」这件事不会因为少写一个判断就直接崩 */
  const panelItems = STYLE_BLOCKS[playStyle]
    .map(name => ({
      id: name,
      title: blockTitle(name, playStyle),
      node: name === 'world' ? worldPanel : name === 'narration' ? narrationPanel : blocks[name],
    }))
    .filter(panel => !!panel.node)
  const activeId = panelItems.some(panel => panel.id === activePanel) ? activePanel : panelItems[0].id
  const activeIndex = Math.max(0, panelItems.findIndex(panel => panel.id === activeId))
  const active = panelItems[activeIndex]
  const goToPanel = (id: string, direction?: number) => {
    const nextIndex = panelItems.findIndex(panel => panel.id === id)
    if (nextIndex < 0 || nextIndex === activeIndex) return
    setPanelDirection(direction ?? (nextIndex > activeIndex ? 1 : -1))
    setActivePanel(id)
  }

  return (
    <div className="mode-game min-h-screen bg-background relative">
      <header className="sticky top-0 z-20 border-b border-border/50 bg-background/80 backdrop-blur-md px-6 py-3.5 flex items-center gap-3">
        <button onClick={() => navigate('/game')} className="p-2 rounded-md hover:bg-muted" title="返回游戏列表">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Dices className="w-5 h-5 text-violet-500" />
        <h1 className="font-bold text-lg truncate">{form.name || '模组'}</h1>
        <span className="text-[11px] px-2 py-0.5 rounded-full shrink-0 bg-primary/10 text-primary">
          {styleLabel(playStyle)}
        </span>
        <button
          onClick={() => setGuideOpen(true)}
          title="想让谁在什么条件下登场、想让一个地点等到条件满足才开，照这两套配方填就行"
          className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 border
            hover:bg-muted transition-colors shrink-0"
        >
          <BookOpen className="w-4 h-4" /> 条件触发指南
        </button>
        <div className="ml-auto flex items-center gap-3">
          {/* 只有从游玩界面点进来的时候才有。从列表进来的那份没有「这一局」可回，
              画出来就是一颗点不出结果的按钮。
              和左边那个箭头是两件事：箭头是退出去选模组，这颗是回去接着玩 */}
          {backToPlay !== null && (
            <button
              onClick={() => navigate(`/game/play/${backToPlay}`)}
              title="回到刚才那一局，停在你离开时那一级"
              className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 border
                hover:bg-muted transition-colors"
            >
              <MessageSquare className="w-4 h-4" /> 回到对话
            </button>
          )}
          <button
            onClick={() => setWizardOpen(true)}
            title="对话式构思：AI 帮你把角色、地点、道具、数值一步步定出来，回填到这份表单"
            className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
          >
            <Wand2 className="w-4 h-4" /> 构思向导
          </button>
          <button
            onClick={() => setImageOpen(true)}
            title="NPC 立绘用哪份 ComfyUI 工作流、什么画风"
            className="flex items-center gap-1.5 text-sm rounded-lg px-3 py-1.5 border
              hover:bg-muted transition-colors"
          >
            <ImagePlus className="w-4 h-4" /> 出图设置
          </button>
          <SaveBadge
            state={autosave.state}
            blocked="模组名还空着，先不存"
            onRetry={autosave.flush}
          />
          <ThemePicker />
        </div>
      </header>

      <AssistModelBall form={form} set={set} />

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
              <WizardPanel key={`${moduleId}-${playStyle}`} moduleId={moduleId} playStyle={playStyle} onApply={applyWizard} />
            </div>
          </div>
        </div>
      )}

      {imageOpen && (
        <div className="fixed inset-0 z-40 flex justify-end" onClick={() => setImageOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="relative w-full max-w-md bg-background border-l shadow-2xl flex flex-col h-full"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0">
              <span className="text-sm font-medium flex items-center gap-1.5">
                <ImagePlus className="w-4 h-4 text-primary" /> 出图设置
              </span>
              <button onClick={() => setImageOpen(false)} className="p-1.5 rounded-md hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              <ImageSettingsDrawer form={form} set={set} />
            </div>
          </div>
        </div>
      )}

      {/* 条件触发指南。不自动弹、不打断，只在你点那颗按钮时出现——
          docs/RPG数值驱动改造.md 里记着「不弹窗、不打断」这条偏好，抽屉 + 显式点击
          是对它的兼容做法。
          和上面两个抽屉一样挂在 <main> 的兄弟位、留在 .mode-game 里面：portal 挪到
          document.body 上会把这套 --rpg-* 变量全丢掉，抽屉会变成没配色的白板 */}
      {guideOpen && (
        <div className="fixed inset-0 z-40 flex justify-end" onClick={() => setGuideOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div
            className="relative w-full max-w-md bg-background border-l shadow-2xl flex flex-col h-full"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0">
              <span className="text-sm font-medium flex items-center gap-1.5">
                <BookOpen className="w-4 h-4 text-primary" /> 条件触发指南
              </span>
              <button onClick={() => setGuideOpen(false)} className="p-1.5 rounded-md hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3.5">
              <TriggerGuide />
            </div>
          </div>
        </div>
      )}

      <main className="relative z-10 max-w-[1440px] mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-5">
        <div className="grid gap-4 lg:grid-cols-2 items-stretch">
          <div className="min-h-[220px]"><CoverHeader form={form} set={set} /></div>
          {module && <div className="min-h-[220px] [&>section]:h-full"><PlaySection module={module} /></div>}
        </div>

        <nav aria-label="模组面板导航" className="sticky top-[4.25rem] z-10 -mx-1 overflow-x-auto rounded-xl border border-border/70 bg-background/90 p-1.5 backdrop-blur-md">
          <div className="flex min-w-max gap-1">
            {panelItems.map((panel, index) => (
              <button key={panel.id} type="button" onClick={() => goToPanel(panel.id)} className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${activeId === panel.id ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}>
                <span className="mr-1 text-[10px] opacity-70">{index + 1}</span>{panel.title}
              </button>
            ))}
          </div>
        </nav>

        <section aria-live="polite" className="relative overflow-hidden rounded-xl">
          <motion.div
            className="mb-2 flex h-6 items-center justify-center rounded-lg text-muted-foreground/50 touch-none cursor-ew-resize select-none"
            drag="x"
            dragConstraints={{ left: 0, right: 0 }}
            dragElastic={0.2}
            onDragEnd={(_, info) => {
              if (info.offset.x < -90 && activeIndex < panelItems.length - 1) goToPanel(panelItems[activeIndex + 1].id, 1)
              if (info.offset.x > 90 && activeIndex > 0) goToPanel(panelItems[activeIndex - 1].id, -1)
            }}
            whileDrag={{ scale: 1.03, color: 'hsl(var(--primary))' }}
            aria-label="拖动此处切换面板"
            title="拖动此处切换面板"
          >
            <span className="h-1 w-12 rounded-full bg-current" />
          </motion.div>
          <AnimatePresence initial={false} mode="wait" custom={panelDirection}>
            <motion.div
              key={active.id}
              custom={panelDirection}
              initial={{ opacity: 0, x: panelDirection * 80 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: panelDirection * -80 }}
              transition={{ type: 'spring', stiffness: 360, damping: 32, mass: 0.7 }}
              className="select-text"
            >
              {active.node}
            </motion.div>
          </AnimatePresence>
          <div className="mt-4 flex items-center justify-between gap-3">
            <button type="button" disabled={activeIndex === 0} onClick={() => goToPanel(panelItems[activeIndex - 1].id, -1)} className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40">
              <ChevronLeft className="h-4 w-4" />上一个
            </button>
            <span className="text-xs text-muted-foreground">{activeIndex + 1} / {panelItems.length}</span>
            <button type="button" disabled={activeIndex === panelItems.length - 1} onClick={() => goToPanel(panelItems[activeIndex + 1].id, 1)} className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-40">
              下一个<ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </section>

      </main>
    </div>
  )
}

function OpeningLocationSelect({ moduleId, label, value, onChange, showLabel = true, emptyLabel = '未设置起始地点' }: {
  moduleId: number
  label: string
  value: string
  onChange: (value: string) => void
  showLabel?: boolean
  emptyLabel?: string
}) {
  const { data: locations = [], isLoading, isError } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId),
  })
  const names = [...new Set(locations.map(place => place.name).filter(name => name.trim()))]

  return (
    <div>
      <label className="block">
        <span className={showLabel ? 'text-xs font-medium mb-1.5 block' : 'sr-only'}>{label}</span>
        <select value={value} onChange={event => onChange(event.target.value)} disabled={isLoading || isError} className={INPUT}>
          <option value="">{isLoading ? '加载地点中…' : emptyLabel}</option>
          {value && !names.includes(value) && <option value={value}>{value}（当前配置）</option>}
          {names.map(name => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      {isError ? (
        <p className="text-xs text-muted-foreground mt-1.5">地点加载失败，请刷新页面重试。</p>
      ) : !isLoading && names.length === 0 ? (
        <p className="text-xs text-muted-foreground mt-1.5">请先在「地点」面板添加地点，再回来选择。</p>
      ) : null}
    </div>
  )
}

function OpeningCast({ moduleId, npcs, start, firstSlot, selected, placements, onChange }: {
  moduleId: number
  npcs: RpgNpc[]
  start: string
  firstSlot: string
  selected: number[]
  placements: Record<string, string>
  onChange: (ids: number[], placements: Record<string, string>) => void
}) {
  const cast = npcs.filter(n => (n.role || 'npc') !== 'protagonist')
  const mode = (id: number) => Object.prototype.hasOwnProperty.call(placements, String(id))
    ? 'custom' : selected.includes(id) ? 'player' : 'routine'
  const openingPlace = (npc: RpgNpc) => mode(npc.id) === 'custom'
    ? placements[String(npc.id)].trim() || npcPlace(npc, firstSlot)
    : mode(npc.id) === 'player' && start.trim() ? start.trim() : npcPlace(npc, firstSlot)
  const present = cast.filter(npc => !!start.trim() && norm(openingPlace(npc)) === norm(start))
  const changeMode = (npc: RpgNpc, nextMode: string) => {
    const nextPlacements = { ...placements }
    delete nextPlacements[String(npc.id)]
    if (nextMode === 'custom') nextPlacements[String(npc.id)] = openingPlace(npc)
    const nextSelected = selected.filter(identity => identity !== npc.id)
    if (nextMode === 'player') nextSelected.push(npc.id)
    onChange(nextSelected, nextPlacements)
  }

  return (
    <div>
      <div className="text-xs font-medium mb-1.5">NPC 开场位置</div>
      {cast.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          还没有角色卡。在「角色」里加了人，这里就能分别安排开场地点。
        </p>
      ) : (
        <div className="space-y-2">
          {cast.map(npc => (
            <div key={npc.id} className="border rounded-lg p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <label htmlFor={`opening-mode-${npc.id}`} className="text-sm font-medium mr-auto">{npc.name}</label>
                <select
                  id={`opening-mode-${npc.id}`} value={mode(npc.id)}
                  onChange={event => changeMode(npc, event.target.value)}
                  className="border rounded-lg px-2 py-1.5 text-xs bg-background/60"
                >
                  <option value="routine">按作息 / 常驻地点</option>
                  <option value="player">与主角同地点</option>
                  <option value="custom">指定地点</option>
                </select>
              </div>
              {mode(npc.id) === 'custom' && (
                <OpeningLocationSelect
                  moduleId={moduleId} label={`${npc.name}的开场地点`} showLabel={false}
                  emptyLabel="未指定，按作息 / 常驻地点"
                  value={placements[String(npc.id)]}
                  onChange={value => onChange(selected.filter(identity => identity !== npc.id), {
                    ...placements, [String(npc.id)]: value,
                  })}
                />
              )}
              <p className="text-xs text-muted-foreground">
                开场：{openingPlace(npc) || '未设置'}；常驻：{npc.location || '未设置'}
                {mode(npc.id) === 'custom' && !placements[String(npc.id)].trim() && '（指定地点未填写，暂按日常安排）'}
                {mode(npc.id) === 'player' && !start.trim() && '（请填写主角起始地点，暂按日常安排）'}
              </p>
            </div>
          ))}
        </div>
      )}
      {!!start.trim() && (
        <p className="text-xs text-muted-foreground mt-1.5">
          开场与主角同处「{start}」：{present.length ? present.map(npc => npc.name).join('、') : '无'}。
        </p>
      )}
      <p className="text-xs text-muted-foreground mt-1.5">
        每个人的开场地点可以不同，常驻地点和作息表保持原样。选择「按作息 / 常驻地点」可取消特殊安排。
        只影响新开局，不会移动已有存档中的人物，也不会自动设为跟随。
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
            onClick={() => navigate(`/game/play/${sess.id}`)}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault(); navigate(`/game/play/${sess.id}`)
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
          onCreated={sess => navigate(`/game/play/${sess.id}`)}
        />
      )}
    </Section>
  )
}

// ── 通用外壳 ──────────────────────────────────────────────────────────────

/** 表单内部的折叠块 */
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
    <div className={`${PANEL} h-full backdrop-blur-sm p-4 flex items-center gap-3`}>
      <button
        onClick={() => fileRef.current?.click()}
        disabled={busy}
        className="w-16 h-16 rounded-xl shrink-0 flex items-center justify-center overflow-hidden
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
        <label className="text-base font-semibold tracking-tight mb-2 block">模组名字</label>
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

// ── 主角 ──────────────────────────────────────────────────────────────────

/**
 * 「玩家在这个世界里是谁」。
 *
 * **这里没有新字段。** 名字和出身与动机改的就是「角色卡」里那张标成「主角模板」
 * 的卡（`role = 'protagonist'`），开局背包还是 `module.default_inventory`。
 * 单独摆一格是因为这两摊东西说的是同一件事，而它们原来隔着大半个页面：主角卡
 * 混在一列 NPC 中间，开局背包在倒数第几个面板——作者要凑出「玩家开局是谁、
 * 身上有什么」得来回翻。
 *
 * 主角卡还没建的时候不自动建：填了名字点「保存」才落库，同 NpcSection 里新增
 * 角色那一路（新建的卡还没 id，自动保存无处可写）。
 */
function ProtagonistSection({
  moduleId, npcs, form, set, assistContext,
}: {
  moduleId: number
  npcs: RpgNpc[]
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
  assistContext: () => Record<string, string>
}) {
  const qc = useQueryClient()
  const card = protagonistCard(npcs)
  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })

  // 还没建卡时这两格是本地的，点「保存」才落库；建过之后一律以卡为准，
  // 免得两份状态各自漂
  const [draftName, setDraftName] = useState('')
  const [draftDesc, setDraftDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  // 换卡（或第一次读出来）时灌一次。不能每次 npcs 变了就灌：自动保存成功后
  // 会 invalidate 这份查询，那一灌会把作者正在敲的字盖回上一次存下来的值
  const hydrated = useRef<number | null>(null)
  useEffect(() => {
    if (card && hydrated.current !== card.id) {
      hydrated.current = card.id
      setName(card.name)
      setDesc(card.description)
    }
  }, [card])

  const autosave = useFormAutosave(
    card && name.trim() ? { id: card.id, body: { name: name.trim(), description: desc } } : null,
    !!card,
    async ({ id, body }) => { await rpgApi.npcs.update(id, body); refresh() },
  )

  const create = async () => {
    if (!draftName.trim() || saving) return
    setSaving(true)
    try {
      await rpgApi.npcs.create(moduleId, {
        name: draftName.trim(), role: 'protagonist', description: draftDesc,
        sort_order: npcs.length + 1,
      })
      refresh()
      setDraftName(''); setDraftDesc('')
    } catch {
      toast.error('保存主角设定失败')
    } finally { setSaving(false) }
  }

  // 锁定拿不出值来就不给开：后端建局时也是「没有卡就当没锁」，界面上先说清楚，
  // 免得作者勾了一个什么都不做的开关
  const lockable = !!card && !!card.name.trim()

  return (
    <Section
      title="主角"
      desc="玩家在这个世界里是谁，以及开局身上带着什么。名字和出身改的就是「角色卡」里那张主角模板。"
      icon={UserRound}
      accent={ACCENT.cast}
    >
      <div className="space-y-6">
        {card ? (
          <div className="space-y-5">
            <div>
              <label className="text-sm font-medium mb-2 block">名字</label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="例：阿隼"
                className={INPUT}
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-2 block">出身与动机</label>
              <textarea
                value={desc}
                onChange={e => setDesc(e.target.value)}
                placeholder="他从哪来、会点什么、为什么非要蹚这趟浑水……"
                className={`${INPUT} resize-y min-h-[8rem] leading-relaxed`}
              />
              <Assist
                moduleId={moduleId}
                field="npc_description"
                context={assistContext}
                value={desc}
                onApply={setDesc}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                GM 每轮都看得到这段。开局时它会填进弹窗那一栏，玩家还能自己改（除非下面锁上）。
              </p>
            </div>
            {/* 拼进 char_desc 的是「简介 + 性格」两栏（后端 protagonist_identity
                是同一个拼法）。性格那栏只在角色卡编辑器里，这儿不重复摆一遍，
                但写了东西就得说一句——不然作者会以为上面这一格就是全部 */}
            {!!card.persona.trim() && (
              <p className="text-xs text-muted-foreground">
                这张卡的「性格」栏还写着一段，开局时会跟在上面这段后面一起给 GM。
                要改去「角色卡」里那张主角模板。
              </p>
            )}
            <div className="flex items-center gap-3">
              <SaveBadge
                state={autosave.state}
                blocked="主角名字还空着，先不存"
                onRetry={autosave.flush}
              />
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              还没定主角。填上名字就会在「角色卡」里建一张标着「主角模板」的卡——
              它不登场，只用来定玩家扮演谁。留空也能玩，那样每次开局玩家自己填。
            </p>
            <input
              value={draftName}
              onChange={e => setDraftName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') void create() }}
              placeholder="名字，例：阿隼"
              className={INPUT}
            />
            <textarea
              value={draftDesc}
              onChange={e => setDraftDesc(e.target.value)}
              placeholder="出身与动机：他从哪来、会点什么、为什么非要蹚这趟浑水……"
              className={`${INPUT} resize-y min-h-[6rem] leading-relaxed`}
            />
            <button
              onClick={create}
              disabled={!draftName.trim() || saving}
              className="text-sm px-4 py-2 rounded-lg flex items-center gap-1.5
                bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              保存主角设定
            </button>
          </div>
        )}

        <div className="border-t border-border/60 pt-5">
          <div className="flex items-center gap-2 text-sm font-medium mb-3">
            <Backpack className="w-4 h-4 text-primary" />开局时的背包
          </div>
          <StartingInventory form={form} set={set} />
        </div>

        <div className="border-t border-border/60 pt-5">
          <label className={`flex items-start gap-2.5 ${lockable ? 'cursor-pointer' : 'opacity-60'}`}>
            <input
              type="checkbox"
              checked={!!form.lock_protagonist}
              disabled={!lockable}
              onChange={e => set('lock_protagonist', e.target.checked)}
              className="mt-0.5 accent-[hsl(var(--primary))]"
            />
            <div>
              <span className="text-sm">锁定主角设定</span>
              <p className="text-xs text-muted-foreground mt-0.5">
                {lockable
                  ? '开局时名字和出身按上面这份定死，玩家看得到但改不动。主角是固定角色的剧本用这个；想让玩家自己捏人就别勾。数值和时段那两栏照旧可以改。'
                  : '先在上面把主角定出来，才有「定死的那一份」可锁。'}
              </p>
            </div>
          </label>
        </div>
      </div>
    </Section>
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
  const defs = (form.stat_defs || []).filter(d => (d.name || '').trim())
  const rank = (form.rank_stat || '').trim()
  // 指向已删或改名的数值项。后端到这儿是安静降级成「无对抗」的，玩家看不出
  // 任何异常——只有这行红字能告诉作者他的等级制其实根本没生效
  const dangling = rank !== '' && !defs.some(d => d.name === rank)
  const perLevel = Number(form.rank_per_level) || 0
  // 阶梯预览按「普通」档算：base + 等级差 × 每级百分点 + 整体偏移，两头夹 5/95。
  // 不给预览作者不可能发现 15/级在普通档的可用量程只有 −3…+2，九阶天梯撞平了
  const ladder = [0, -1, -2, -3].map(diff => ({
    diff,
    rate: Math.max(5, Math.min(95, table.medium + diff * perLevel + form.difficulty_bias)),
  }))

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
            {/* 「-10 更硬核」写在下面那行提示里，负号必须打得进去 */}
            <NumInput
              value={form.difficulty_bias}
              onChange={n => set('difficulty_bias', n ?? 0)}
              clamp={n => Math.max(-30, Math.min(30, n))}
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

          <div className="pt-1 border-t">
            <label className="text-xs font-medium mb-1.5 block">跟人对上的时候比什么</label>
            <div className="flex gap-1.5">
              <button
                onClick={() => set('rank_stat', '')}
                className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                  rank === ''
                    ? 'bg-primary/15 text-primary border-primary/40'
                    : 'hover:bg-muted text-muted-foreground'
                }`}
              >
                数值制
              </button>
              <button
                // 切过去得先落一个具体项，否则「等级制」这个选中态存不住
                onClick={() => set('rank_stat', rank || defs[0]?.name || '')}
                className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                  rank !== ''
                    ? 'bg-primary/15 text-primary border-primary/40'
                    : 'hover:bg-muted text-muted-foreground'
                }`}
                disabled={defs.length === 0}
              >
                等级制
              </button>
            </div>
            <p className="text-xs text-muted-foreground mt-1.5">
              {rank === ''
                ? '比 AI 挑中的那一项：玩家用剑术砍人就比双方的剑术，每点 4%。对手卡上没填那一项就照旧对基准 10 算。'
                : '不管这一轮做的是什么，跟人正面对上时一律比下面这一项。适合修仙、军阶这种「境界压一切」的设定。'}
            </p>
            {defs.length === 0 && (
              <p className="text-xs text-muted-foreground mt-1">先在「数值」里加一项，才能选等级制。</p>
            )}

            {rank !== '' && (
              <div className="mt-3 space-y-3">
                <div className="flex gap-3">
                  <div className="flex-1 min-w-0">
                    <label className="text-xs font-medium mb-1.5 block">等级项</label>
                    <select
                      value={dangling ? '' : rank}
                      onChange={e => set('rank_stat', e.target.value)}
                      className={INPUT}
                    >
                      {dangling && <option value="">{rank}（已不存在）</option>}
                      {defs.map(d => (
                        <option key={d.name} value={d.name}>{d.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="w-32">
                    <label className="text-xs font-medium mb-1.5 block">每级百分点</label>
                    <input
                      type="number" min={1} max={50}
                      value={form.rank_per_level}
                      onChange={e => set('rank_per_level', Math.max(1, Math.min(50, Number(e.target.value) || 1)))}
                      className={INPUT}
                    />
                  </div>
                </div>

                {dangling ? (
                  <p className="text-xs text-rose-600 dark:text-rose-400">
                    「{rank}」在「数值」里已经找不到了，对抗不会生效（判定照常跑，只是等级差被当成 0）。重选一项。
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    普通档下的手感：
                    {ladder.map(({ diff, rate }) => (
                      <span key={diff}>
                        {diff === 0 ? '同级' : `低 ${-diff} 级`} {rate}%
                        {diff === -3 ? '' : ' / '}
                      </span>
                    ))}
                    。险胜档恒定再多 20 个百分点，所以撞到 5% 底板也还有约四分之一能把事情推下去。
                    撞到两头就再拉不开差距了——量程不够就把每级百分点调小。
                  </p>
                )}

                <p className="text-xs text-muted-foreground">
                  对手的数值填在角色卡的「能力数值」里，不填的人照旧按基准算。升级一轮最多 1 级。
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── 生成参数 ──────────────────────────────────────────────────────────────

/**
 * 悬浮球：不滚回「生成参数」也能换掉「AI 生成 / AI 优化」用的模型。
 *
 * 改的就是 `model_ref` 那一个字段，和下面 GenerationParams 里的「叙事模型」是**同一个值**
 * ——后端 rpg_assist 走 get_agent_client("writer", module.model_ref)，编辑器帮写和游玩时
 * 写旁白共用一个模型。所以球里必须写明这一点，否则作者会以为这是个独立设置，
 * 回头发现叙事模型跟着变了当成 bug。
 *
 * 不 createPortal：--rpg-* 那套颜色变量定在外面的 .mode-game 上，portal 出去就取不到了。
 */
function AssistModelBall({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const [open, setOpen] = useState(false)
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  const current = models.find(m => String(m.id) === modelSelectValue(models, form.model_ref))

  return (
    <div className="fixed bottom-6 right-6 z-30">
      {open && (
        <div className={`${PANEL} absolute bottom-14 right-0 w-72 p-3 shadow-xl bg-card`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-primary" /> AI 帮写用的模型
            </span>
            <button onClick={() => setOpen(false)} className="p-1 rounded-md hover:bg-muted">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <select
            value={modelSelectValue(models, form.model_ref)}
            onChange={e => set('model_ref', e.target.value)}
            className={INPUT}
          >
            <option value="">跟随默认</option>
            {groupModelsByProvider(models).map(g => (
              <optgroup key={g.provider} label={g.provider}>
                {g.items.map(m => (
                  <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <p className="text-xs text-muted-foreground mt-2">
            就是「生成参数」里的叙事模型，改这儿等于改那儿。游玩时写旁白也用它。
          </p>
        </div>
      )}
      <button
        onClick={() => setOpen(v => !v)}
        title={`AI 帮写用的模型：${current?.display_name || current?.model_id || '跟随默认'}`}
        className="w-11 h-11 rounded-full bg-primary text-primary-foreground shadow-lg
          flex items-center justify-center hover:scale-105 transition-transform"
      >
        <Sparkles className="w-5 h-5" />
      </button>
    </div>
  )
}

function GenerationParams({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  // 按供应商分组，同小说那边。同一个模型名在两家都有的时候，不写供应商就是
  // 两条一模一样的选项
  const groups = groupModelsByProvider(models)
  const options = groups.map(g => (
    <optgroup key={g.provider} label={g.provider}>
      {g.items.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
    </optgroup>
  ))
  // 向量检索那一格要的是模型库里标了 embedding 的那拨，和上面这份互斥
  const embeddingGroups = groupModelsByProvider(models, 'embedding')
  // 一个嵌入模型都没注册时下拉是空的，那和「这功能坏了」长得一模一样，说清楚
  const embeddingOptions = embeddingGroups.length > 0
    ? embeddingGroups.map(g => (
      <optgroup key={g.provider} label={g.provider}>
        {g.items.map(m => <option key={m.id} value={String(m.id)}>{m.display_name || m.model_id}</option>)}
      </optgroup>
    ))
    : <option disabled>模型库里还没有嵌入模型，先去「设置 → 模型库」添加</option>
  // 负温度 = 整个参数不发给供应商，llm_client 里 `if temperature >= 0` 已有这个约定
  const tempOff = form.temperature < 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {GAMEPLAY_MODEL_FIELDS.map(({ key, label, empty, hint }) => (
          <div key={key}>
            <label className="text-xs font-medium mb-1 block">{label}</label>
            <select
              value={modelSelectValue(models, form[key])}
              onChange={event => set(key, event.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
            >
              <option value="">{empty}</option>
              {options}
            </select>
            <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>
          </div>
        ))}
      </div>
      <details className="border rounded-lg bg-background/40">
        <summary className="px-3 py-2 text-xs text-muted-foreground cursor-pointer">默认 / 立绘 / 向量模型</summary>
        <div className="px-3 pb-3 grid grid-cols-1 sm:grid-cols-2 gap-4">
          {EXTRA_MODEL_FIELDS.map(({ key, label, empty, hint }) => (
            <div key={key}>
              <label className="text-xs font-medium mb-1 block">{label}</label>
              <select
                value={modelSelectValue(models, form[key])}
                onChange={event => set(key, event.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60"
              >
                <option value="">{empty}</option>
                {isEmbeddingField(key) ? embeddingOptions : options}
              </select>
              <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>
            </div>
          ))}
        </div>
      </details>

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
          <p className="text-xs text-muted-foreground mt-1.5">
            每个角色各自留这么多轮，更早的压成她自己那份梗概。
          </p>
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

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium mb-1 block">设定总闸</label>
          <input
            type="number" min={2000} max={200000} step={500}
            value={form.context_budget}
            onChange={e => set('context_budget', Math.max(1, Number(e.target.value) || 21500))}
            className={INPUT}
          />
          {/* 这个数只管 system 那一大段（世界观、角色卡、回忆……），不含对话
              历史，所以它和模型的上下文窗口不是一回事，别照着窗口填满 */}
          <p className="text-xs text-muted-foreground mt-1.5">
            tokens。世界观、角色、回忆这些块按比例分这个数，21500 是原来的额度。
          </p>
        </div>
      </div>
    </div>
  )
}

// ── 世界书 ────────────────────────────────────────────────────────────────

interface EntryForm {
  title: string
  keywords: string
  content: string
  constant: boolean
  depth: number
  once: boolean
  trigger_condition: RpgCondition
}

const EMPTY_ENTRY: EntryForm = {
  title: '', keywords: '', content: '', constant: false, depth: 0, once: false,
  trigger_condition: {},
}

/** 一条词条实际在干的三件事之一。
 *
 *  **纯前端的填表模式，不落库**：三种都是 (constant, keywords, trigger_condition)
 *  的组合，加一个 kind 列就等于把同一件事记两遍，两边还会对不上。它只决定
 *  「新建时先问什么、空栏折不折起来」。
 */
type EntryKind = 'lore' | 'rule' | 'event'

const ENTRY_KINDS: { kind: EntryKind; label: string; desc: string; preset: Partial<EntryForm> }[] = [
  {
    kind: 'lore',
    label: '补充设定',
    desc: '提到某个词，才把这段递给 AI。不提到就不占 token。',
    preset: { constant: false },
  },
  {
    kind: 'rule',
    label: '一直生效的规则',
    desc: '每轮都递，不看关键词。代价是一直占 token。',
    preset: { constant: true },
  },
  {
    kind: 'event',
    label: '条件到了才发生的事',
    desc: '好感≥50 → 她开始主动找你。条件不满足时一个字都不发。',
    preset: { constant: true },
  },
]

/** 一条已有的词条算哪一类。**只用来决定空栏折不折起来**，不改任何数据。
 *
 *  有条件的一律算事件，哪怕它同时带着关键词——那种词条（提到地窖「且」第 3 天
 *  之后）两头的性质都有，按事件展开能让作者看见条件那一栏。 */
function entryKindOf(entry: { constant: boolean; trigger_condition?: RpgCondition }): EntryKind {
  if (Object.keys(entry.trigger_condition || {}).length > 0) return 'event'
  return entry.constant ? 'rule' : 'lore'
}

/** 插入深度的人话版。作者真正用得上的只有这三档，其余留给下面那个数字框 */
const DEPTH_CHOICES: { value: number; label: string }[] = [
  { value: 0, label: '放在开场设定里' },
  { value: 1, label: '贴在我这句话前面' },
  { value: 2, label: '再往前一条' },
]

/** 常用 GM 指令：把当下输入框里那段存起来，换个模组也能取用。
 *  照酒馆 TavernCard 的 InstructionPresets。存的是文本副本，之后各模组独立不联动。 */
function InstructionPresets({
  current, onPick,
}: {
  current: string
  onPick: (text: string) => void
}) {
  const qc = useQueryClient()
  const { data: presets = [] } = useQuery({
    queryKey: ['rpg-instruction-presets'],
    queryFn: rpgApi.instructionPresets.list,
  })
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')

  const save = async () => {
    const trimmed = name.trim()
    if (!trimmed || !current.trim()) return
    try {
      await rpgApi.instructionPresets.create({ name: trimmed, content: current.trim() })
      qc.invalidateQueries({ queryKey: ['rpg-instruction-presets'] })
      setName('')
      setNaming(false)
      toast.success('已存为常用指令')
    } catch {
      toast.error('保存常用指令失败')
    }
  }

  return (
    <div className="mt-2.5 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground mr-1">常用指令</span>
        {presets.map(p => {
          const active = p.content.trim() === current.trim() && !!current.trim()
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => (active ? onPick('') : onPick(p.content))}
              title={active ? `点一下取消：\n\n${p.content}` : p.content}
              className={`inline-flex items-center rounded-full border text-xs px-2.5 py-1
                max-w-[12rem] truncate hover:bg-primary/15 ${
                active
                  ? 'border-primary/60 bg-primary/15 text-primary'
                  : 'border-primary/25 bg-primary/[0.06]'
              }`}
            >
              {active && <Check className="w-3 h-3 inline mr-1 -mt-0.5" />}
              {p.name}
            </button>
          )
        })}
        {presets.length === 0 && (
          <span className="text-xs text-muted-foreground">还没存过</span>
        )}
        {current.trim() && (
          <button
            type="button"
            onClick={() => onPick('')}
            title="清空上面的 GM 指令输入框（不影响已存的常用指令）"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border
              text-muted-foreground hover:bg-muted"
          >
            <Eraser className="w-3 h-3" /> 清空
          </button>
        )}
        {!naming && (
          <button
            type="button"
            onClick={() => setNaming(true)}
            disabled={!current.trim()}
            title={current.trim() ? '把上面这段存起来' : '先写点内容再存'}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-dashed
              border-primary/30 text-muted-foreground hover:bg-primary/5 disabled:opacity-40"
          >
            <BookmarkPlus className="w-3 h-3" /> 存为常用
          </button>
        )}
      </div>
      {naming && (
        <div className="flex gap-2">
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') save() }}
            placeholder="给这段指令起个名字，如：克苏鲁腔"
            autoFocus
            className="flex-1 border rounded-lg px-3 py-1.5 text-xs bg-background/60
              focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
          <button
            type="button"
            onClick={save}
            disabled={!name.trim()}
            className="text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground
              hover:opacity-90 disabled:opacity-40"
          >
            保存
          </button>
          <button
            type="button"
            onClick={() => { setNaming(false); setName('') }}
            className="text-xs px-3 py-1.5 border rounded-lg hover:bg-muted"
          >
            取消
          </button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        点一条填进上面的输入框，再点亮着的那条就取消。存的是当时的文本副本，之后改这个模组不会影响别的模组。
        <Link to="/game/settings" className="text-primary hover:underline ml-1">去游戏设定改名或删除</Link>
      </p>
    </div>
  )
}

/** 写作规则勾选器。库在游戏设定页管理，这里只勾选哪几条注入这个模组。
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
    <div className="border-t border-border/60 pt-5 space-y-3">
      <h3 className="text-sm font-medium">写作规则</h3>
      <p className="text-xs text-muted-foreground">管住叙事的用词用语。默认不启用，勾上的规则会原样拼进 GM 的系统提示词。</p>
      {rules.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          还没有写作规则。
          <Link to="/game/settings" className="text-primary hover:underline ml-1">去游戏设定写一条</Link>
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
            <Link to="/game/settings" className="text-primary hover:underline">去游戏设定管理规则</Link>
          </p>
        </>
      )}
    </div>
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
  // 新建时先选这个，选完才出表单；编辑已有的直接按它的形状推
  const [kind, setKind] = useState<EntryKind>('lore')
  const [picking, setPicking] = useState(false)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-world-book', moduleId] })
  const reset = () => {
    setForm(EMPTY_ENTRY); setEditingId(null); setShowForm(false); setPicking(false)
  }

  const startEdit = (entry: RpgWorldEntry) => {
    // 换一条之前先把上一条欠着的那一次存掉。它自带 id，所以哪怕请求是在
    // 表单已经换人之后才发出去的，也不会写到新那一条身上
    void autosave.flush()
    setEditingId(entry.id)
    setKind(entryKindOf(entry))
    setForm({
      title: entry.title || '',
      keywords: entry.keywords, content: entry.content, constant: entry.constant,
      depth: entry.depth, once: !!entry.once,
      trigger_condition: entry.trigger_condition || {},
    })
    setPicking(false)
    setShowForm(true)
  }

  /** 选完「这条是干什么的」，按预设开一张空表 */
  const startAdd = (picked: EntryKind) => {
    setKind(picked)
    setForm({
      ...EMPTY_ENTRY,
      ...(ENTRY_KINDS.find(k => k.kind === picked)?.preset || {}),
    })
    setEditingId(null)
    setPicking(false)
    setShowForm(true)
  }

  /** 必填栏空着就整份不发。存一条既没关键词又没内容的词条进去，等于在模组里
   *  埋一个永远不触发、列表上还看不出毛病的废物 */
  const valid = form.constant || !!form.keywords.trim()
  const canSave = valid && !!form.content.trim()

  /** 改哪一格就存哪一格。新建的还没有 id，整份等「添加」一起提交 */
  const autosave = useFormAutosave(
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

  const renderForm = () => {
    // 哪些栏要露出来。**任何已经有值的栏一律显示**——推断出的类型只决定空栏
    // 折不折起来。一条「关键词 + 条件」的词条会被推断成事件，藏掉关键词栏的话
    // 这一栏是自动保存的，作者改一下别的就把关键词悄悄清了（同 PlaceSelect 那个坑）
    const showKeywords = kind === 'lore' || !!form.keywords.trim()
    const showCondition = kind === 'event' || Object.keys(form.trigger_condition).length > 0
    const showConstant = kind !== 'event' || form.constant !== true
    const kindLabel = ENTRY_KINDS.find(k => k.kind === kind)?.label || ''

    return (
        <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {editingId ? '编辑词条' : `新增 · ${kindLabel}`}
            </span>
            <button onClick={close} className="p-1 rounded hover:bg-muted"><X className="w-4 h-4" /></button>
          </div>
          <input
            value={form.title}
            onChange={e => setForm({ ...form, title: e.target.value })}
            placeholder="名字（只给你自己看，比如：她开始主动找你）"
            className={INPUT}
          />
          {showKeywords && (
            <input
              value={form.keywords}
              onChange={e => setForm({ ...form, keywords: e.target.value })}
              disabled={form.constant}
              placeholder={form.constant ? '常驻词条不看关键词' : '关键词（逗号或顿号分隔，如：地窖，锈锁）'}
              className={`${INPUT} disabled:opacity-50`}
            />
          )}
          <textarea
            value={form.content}
            onChange={e => setForm({ ...form, content: e.target.value })}
            placeholder={kind === 'event' ? '条件到了之后，要让 AI 知道发生了什么' : '要注入的设定内容'}
            className={`${INPUT} resize-y min-h-[6rem]`}
          />
          {showConstant && (
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
          )}
          {showCondition && (
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
          )}
          {showCondition && (
            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={form.once}
                onChange={e => setForm({ ...form, once: e.target.checked })}
                className="mt-0.5 accent-[hsl(var(--primary))]"
              />
              <div>
                <span className="text-sm">只触发一次</span>
                <p className="text-xs text-muted-foreground mt-0.5">
                  「她终于肯叫你名字了」这种只该发生一次的勾上。不勾的话条件一直满足，
                  这段话就每轮都递过去，AI 会让她每轮重演一次「终于」。
                  想让它重来只能读档回到那之前。
                </p>
              </div>
            </label>
          )}
          <Fold title="高级">
            <label className="text-xs font-medium mb-1 block">这段话贴在哪儿</label>
            {DEPTH_CHOICES.some(c => c.value === form.depth) ? (
              <select
                value={form.depth}
                onChange={e => setForm({ ...form, depth: Number(e.target.value) })}
                className={`${INPUT} w-56`}
              >
                {DEPTH_CHOICES.map(c => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </select>
            ) : (
              // 老词条填过 3 以上的值。**不能塞进上面那个 select**：value 对不上
              // 任何 option 会渲染成空白行，作者随手一改就把原值覆盖没了
              <input
                type="number" min={0} max={20}
                value={form.depth}
                onChange={e => setForm({ ...form, depth: Math.max(0, Number(e.target.value) || 0) })}
                className={`${INPUT} w-24`}
              />
            )}
            <p className="text-xs text-muted-foreground mt-1.5">
              离当前对话越近，模型越不会忽略它。拿不准就放开场设定里。
            </p>
          </Fold>
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
    )
  }

  const renderEntry = (entry: RpgWorldEntry) => {
    // 既不常驻又没关键词 = 谁都唤不醒它。原先只淡淡写一句「（没有关键词）」，
    // 看不出这条是死的
    const dead = !entry.constant && !entry.keywords.trim()
    return (
      <div key={entry.id} className="space-y-2">
      <div className={`border rounded-lg px-3 py-2 ${entry.enabled ? '' : 'opacity-60'}`}>
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            {/* 有名字就让名字打头，剩下那些徽章退到第二行。没名字的老词条
                第一行还是徽章，和以前一模一样 */}
            {entry.title && <p className="text-sm font-medium truncate">{entry.title}</p>}
            <div className={`flex flex-wrap items-center gap-1.5 ${entry.title ? 'mt-1' : ''}`}>
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
              {entry.once && (
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                  一次性
                </span>
              )}
              {entry.keywords
                // 分隔符必须与后端保持一致，否则这里显示成两个词、实际却当成一个来匹配
                ? entry.keywords.split(/[,，、;；\n]+/).filter(Boolean).map((kw, i) => (
                    <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-primary/10 text-primary">
                      {kw}
                    </span>
                  ))
                : dead && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-destructive/10 text-destructive">
                      这条永远不会触发
                    </span>
                  )}
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
      {showForm && editingId === entry.id && renderForm()}
      </div>
    )
  }

  const events = entries.filter(e => entryKindOf(e) === 'event')
  const lore = entries.filter(e => entryKindOf(e) !== 'event')
  const split = lore.length > 0 && events.length > 0

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
        {/* 只有两类都非空才分段。词条少的模组照旧是一条大列表，界面不变 */}
        {split && <p className="text-xs font-medium text-muted-foreground px-1">设定词条</p>}
        {lore.map(renderEntry)}
        {split && <p className="text-xs font-medium text-muted-foreground px-1 pt-2">触发事件</p>}
        {events.map(renderEntry)}

        {showForm && editingId === null && renderForm()}
        {picking && (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">这条是干什么的？</span>
              <button onClick={() => setPicking(false)} className="p-1 rounded hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            {ENTRY_KINDS.map(k => (
              <button
                key={k.kind}
                onClick={() => startAdd(k.kind)}
                className="w-full text-left border rounded-lg px-3 py-2 hover:bg-muted"
              >
                <span className="text-sm">{k.label}</span>
                <p className="text-xs text-muted-foreground mt-0.5">{k.desc}</p>
              </button>
            ))}
          </div>
        )}
        {!showForm && !picking && (
          <AddRow onClick={() => setPicking(true)}>添加词条</AddRow>
        )}
      </div>
    </Section>
  )
}

// ── NPC ───────────────────────────────────────────────────────────────────

interface NpcForm {
  name: string
  role: RpgNpc['role']
  age: string
  description: string
  persona: string
  appearance: string
  location: string
  slot_locations: Record<string, string>
  random_movement_slots: string[]
  random_movement_places: string[]
  keywords: string
  ai_scheduled: boolean
  random_movement: boolean
  profile_sections: Record<string, string>
  dialogue_examples: { user: string; assistant: string }[]
  initial_state: Record<string, number | boolean>
  relation_enabled: boolean
  relation_stat_names: string[]
  /** 稀疏：只给要正面对上的人填，键是玩家那张表里的项名 */
  ability_stats: Record<string, number>
}

const EMPTY_NPC: NpcForm = {
  name: '', role: 'npc', age: '', description: '', persona: '', appearance: '',
  location: '', slot_locations: {}, keywords: '', ai_scheduled: false,
  random_movement: false,
  random_movement_slots: [],
  random_movement_places: [],
  profile_sections: {}, dialogue_examples: [], initial_state: {},
  relation_enabled: false, relation_stat_names: [],
  ability_stats: {},
}

// 后端拿 key 当标签直接拼进提示词，所以这里存的就是中文。
// 外貌单独一栏，不重复放进档案（每轮都注入，见 _one_npc）——向导早期版本照酒馆
// 那套发了英文键，后端读出来的时候会归一到这三个键上（normalize_profile_sections）
const PROFILE_KEYS: Array<[string, string]> = [
  ['背景故事', '出身、成长经历、重要事件、当前身份、人生转折……'],
  ['能力特长', '会什么、擅长什么、弱点和限制……'],
  ['关系网络', '和别的角色什么关系、有什么矛盾、藏着什么……'],
]

/**
 * 从地点表里挑一个地名。
 *
 * 地点表里没有的旧值要**自己补一条 option**：`<select>` 的 value 对不上任何
 * option 时渲染成一个空白行（presetLib 里已经踩过一次），作者看着像「没填」，
 * 随手改一下就把原来那个名字覆盖没了——而这一栏是自动保存的，没有撤销。
 */
function PlaceSelect({ value, onChange, names, empty }: {
  value: string
  onChange: (v: string) => void
  names: string[]
  empty: string
}) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)} className={INPUT}>
      <option value="">{empty}</option>
      {names.map(n => <option key={n} value={n}>{n}</option>)}
      {!!value && !names.includes(value) && (
        <option value={value}>{value}（地点表里没有这个地方）</option>
      )}
    </select>
  )
}

function NpcSection({
  moduleId, statDefs, rankStat, checkOff, relationDefs, slotNames, assistContext, genre, imageConfig,
}: {
  moduleId: number
  /** 玩家那张表的数值项。这儿只为了「能力数值」那一栏：填的就是同名的项 */
  statDefs: RpgStatDef[]
  /** 模组的等级项。非空 = 等级制，对上人的时候一律比这一项 */
  rankStat: string
  /** 模组整个关了判定。那就没有对抗，这一栏填了也不会被用到，说明里要讲清 */
  checkOff: boolean
  relationDefs: RpgStatDef[]
  /** 模组的时段表。空 = 这个模组没有时钟，作息表那一栏整个不出现 */
  slotNames: string[]
  /** 模组层面的参考（模组名/题材/类别/世界观），「帮我写」要用 */
  assistContext: () => Record<string, string>
  /** 下面两样只给立绘拼提示词用：题材现读主字段，画风读出图设置 */
  genre: string
  imageConfig: RpgImageConfig
}) {
  const qc = useQueryClient()
  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', moduleId],
    queryFn: () => rpgApi.npcs.list(moduleId),
  })
  // 「在哪儿」是拿名字跟地点表比对的（后端 npc_place → here_npcs 走 norm 后
  // 字符串相等），所以这一栏只能从地点表里挑，手打一个字不一样就永远不在场。
  // 查询键和 LocationSection 一模一样，react-query 会复用同一份，不多发请求
  const { data: locations = [] } = useQuery({
    queryKey: ['rpg-locations', moduleId],
    queryFn: () => rpgApi.locations.list(moduleId),
  })
  const placeNames = locations.map(l => l.name).filter(Boolean)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<NpcForm>(EMPTY_NPC)

  const refresh = () => qc.invalidateQueries({ queryKey: ['rpg-npcs', moduleId] })
  const reset = () => { setForm(EMPTY_NPC); setEditingId(null); setShowForm(false) }

  // 立绘不进 form：生成/上传接口自己落库，而 autosave 会 PATCH 整份 form，
  // 两边都写 avatar_url 就会互相盖。所以直接读列表里那条最新的
  const editingNpc = editingId === null ? null : npcs.find(n => n.id === editingId) || null

  const startEdit = (npc: RpgNpc) => {
    // 换一张卡之前先把上一张欠着的那一次存掉。它自带 id，所以哪怕请求是在
    // 表单已经换人之后才发出去的，也不会写到新那张身上
    void autosave.flush()
    setEditingId(npc.id)
    setForm({
      name: npc.name, role: npc.role, age: npc.age || '',
      description: npc.description,
      persona: npc.persona, appearance: npc.appearance,
      location: npc.location, slot_locations: npc.slot_locations || {},
      random_movement_slots: npc.random_movement_slots || [],
      random_movement_places: npc.random_movement_places || [],
      keywords: npc.keywords,
      ai_scheduled: npc.ai_scheduled,
      random_movement: npc.random_movement ?? false,
      profile_sections: npc.profile_sections || {},
      dialogue_examples: npc.dialogue_examples || [],
      initial_state: npc.initial_state || {},
      relation_enabled: npc.relation_enabled ?? false,
      relation_stat_names: npc.relation_stat_names || [],
      ability_stats: npc.ability_stats || {},
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
  const autosave = useFormAutosave(
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
    年龄: form.age,
    这个人是谁: form.description,
    性格: form.persona,
    外貌: form.appearance,
  })

  const setExample = (i: number, patch: Partial<{ user: string; assistant: string }>) =>
    setForm(f => ({
      ...f,
      dialogue_examples: f.dialogue_examples.map((ex, j) => (j === i ? { ...ex, ...patch } : ex)),
    }))

  const activeRelationNames = form.relation_stat_names.length
    ? new Set(form.relation_stat_names)
    : new Set(relationDefs.map(def => def.name))
  const activeRelationDefs = relationDefs.filter(def => activeRelationNames.has(def.name))

  // 等级制下只有等级项参与对抗，别的项填了也不进公式，那就别摊一屏输入框
  const abilityDefs = (rankStat
    ? statDefs.filter(def => def.name === rankStat)
    : statDefs.filter(def => def.for_check)
  ).filter(def => (def.name || '').trim())

  /** 清空必须 delete 这个键：稀疏语义下写 0 是把人设成「凡人」，不是没填 */
  const setAbility = (name: string, raw: string) => setForm(f => {
    const next = { ...f.ability_stats }
    if (raw.trim() === '') delete next[name]
    else next[name] = Number(raw) || 0
    return { ...f, ability_stats: next }
  })

  /** 随机移动范围里还对得上的那几个。全部对不上 = 她不会移动（后端 pool 为空） */
  const allowedRandomPlaces = form.random_movement_places.filter(n => placeNames.includes(n))

  const placeHint = !form.ai_scheduled ? ''
    : form.random_movement
      ? (placeNames.length === 0 ? '随机移动需要至少一个地点，请先去「地点」里添加。'
        : form.random_movement_places.length > 0 && allowedRandomPlaces.length === 0
          ? '随机移动范围里的地点都不在地点表里了（改名或删掉了），她不会移动。改一下上面那排勾选。'
          : '')
    : slotNames.length === 0
      ? '这个模组没设时段（右边「时段」那一格是空的），她不会换地方——调度只替她写「在做什么」。'
      : !Object.values(form.slot_locations).some(v => (v || '').trim())
        ? (form.location
            ? `作息表空着，她每个时段都在常驻地（${form.location}），不会自己走开。想让她某个时段待在别处，填上面的作息表；在对话里直接叫她过去也行。`
            : '常驻地点和作息表都空着，她哪儿都算不上「在场」——侧栏里不会出现这个人。把作息表每一格都填上就行（早 大礼堂、中 图书馆、晚 公共休息室），常驻地点空着没关系：它只是某一格留空时的替补。嫌早/中/晚太粗，就去右边「时段」里多写几格。')
        : ''

  const renderForm = () => (
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

          {/* 生成接口要按 id 落库，新建的角色还没 id，先存下来再回来加 */}
          {editingNpc
            ? <NpcAvatarField
                npc={editingNpc} onChanged={refresh} genre={genre} imageConfig={imageConfig}
                // 背景用这个人常驻地点的描述。locations 上面已经查过了，不多发请求。
                // 地点为空时不查：否则会跟某个名字也是空的地点撞上
                place={editingNpc.location.trim()
                  ? locations.find(l => l.name.trim() === editingNpc.location.trim())
                  : undefined}
              />
            : <p className="text-xs text-muted-foreground">立绘要先把角色添加进去才能加。</p>}

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-medium mb-1.5 block">名字</label>
              <input
                value={form.name}
                onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="例：阿隼"
                className={INPUT}
              />
            </div>
            <div>
              <label className="text-xs font-medium mb-1.5 block">常驻地点</label>
              <PlaceSelect
                value={form.location}
                onChange={v => setForm(f => ({ ...f, location: v }))}
                names={placeNames}
                empty="不设常驻地点"
              />
              {placeNames.length === 0 && (
                <p className="text-xs text-muted-foreground mt-1">
                  还没建地点，先去「地点」那一格加几个。
                </p>
              )}
            </div>
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
                    <PlaceSelect
                      value={form.slot_locations[name] || ''}
                      onChange={v => setForm(f => ({
                        ...f, slot_locations: { ...f.slot_locations, [name]: v },
                      }))}
                      names={placeNames}
                      empty="留空 = 用常驻地点"
                    />
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                {form.ai_scheduled && form.random_movement
                  ? '随机移动已启用，常驻地点和作息表都可以留空。填写的地点仅用于初始位置和未调度时的回退。'
                  : '填了就在这个时段待在填的地方，玩家要找他得去那儿；留空就一直在常驻地点。没有固定落脚点的人（学生、行商）把每一格都填上就行，常驻地点空着没关系。要让某个人某个时段「谁也找不到」，填一个玩家不去的地方就行。'}
              </p>
            </div>
          )}

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
              {form.ai_scheduled && (
                <div className="mt-2 ml-6 space-y-1.5">
                  <label className="text-xs font-medium block">移动方式</label>
                  <select
                    value={form.random_movement ? 'random' : 'schedule'}
                    onChange={e => setForm(f => ({ ...f, random_movement: e.target.value === 'random' }))}
                    className={INPUT}
                  >
                    <option value="schedule">按作息表 / 常驻地点</option>
                    <option value="random">随机移动</option>
                  </select>
                  {form.random_movement && (
                    <>
                    {slotNames.length > 0 && (
                      <div className="space-y-1.5">
                        <label className="text-xs font-medium block">随机移动时段</label>
                        <div className="flex flex-wrap gap-x-3 gap-y-1">
                          {slotNames.map(name => (
                            <label key={name} className="flex items-center gap-1 text-xs">
                              <input
                                type="checkbox"
                                checked={form.random_movement_slots.includes(name)}
                                onChange={event => setForm(f => ({
                                  ...f,
                                  random_movement_slots: event.target.checked
                                    ? [...f.random_movement_slots, name]
                                    : f.random_movement_slots.filter(slot => slot !== name),
                                }))}
                                className="accent-primary"
                              />
                              {name}
                            </label>
                          ))}
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          只在勾选的时段随机移动；不勾选表示所有时段都可随机移动，其他时段按作息表或常驻地点。
                        </p>
                      </div>
                    )}
                    {/* 随机移动的地点范围。语义和上面那排时段勾选框一致：不勾 = 不限制。
                        孤儿名字（地点改名/删了）单独显出来，否则作者不知道自己少了一格 */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium block">随机移动范围</label>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {placeNames.map(name => (
                          <label key={name} className="flex items-center gap-1 text-xs">
                            <input
                              type="checkbox"
                              checked={form.random_movement_places.includes(name)}
                              onChange={event => setForm(f => ({
                                ...f,
                                random_movement_places: event.target.checked
                                  ? [...f.random_movement_places, name]
                                  : f.random_movement_places.filter(place => place !== name),
                              }))}
                              className="accent-primary"
                            />
                            {name}
                          </label>
                        ))}
                        {form.random_movement_places
                          .filter(name => !placeNames.includes(name))
                          .map(name => (
                            <label
                              key={name}
                              className="flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400"
                            >
                              <input
                                type="checkbox"
                                checked
                                onChange={() => setForm(f => ({
                                  ...f,
                                  random_movement_places: f.random_movement_places
                                    .filter(place => place !== name),
                                }))}
                                className="accent-primary"
                              />
                              {name}（地点表里没有这个地方）
                            </label>
                          ))}
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        只在勾选的地点之间随机移动；不勾选表示可以去任何地点。
                        只勾一个地点等于把她钉在那儿——她会一直待在那里不动。
                      </p>
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">
                      每轮结束时，闲置角色会从允许的地点中随机选择去处，再由 AI 记录活动。
                      无需填写常驻地点或作息表，也不需要设置时段；在场、被提到或跟随你的角色不会随机移动。
                    </p>
                    </>
                  )}
                </div>
              )}
              {placeHint && (
                <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1.5 ml-6 leading-relaxed">
                  {placeHint}
                </p>
              )}
            </div>
          )}

          <div>
            <label className="text-xs font-medium mb-1.5 block">年龄（选填）</label>
            <input
              value={form.age}
              onChange={e => setForm({ ...form, age: e.target.value })}
              placeholder="例：十七、三百余岁、看不出年纪"
              className={INPUT}
            />
            <p className="text-xs text-muted-foreground mt-1.5">随外貌一起每轮注入。留空就不出现，模型会自己编一个。</p>
          </div>

          <div>
            <label className="text-xs font-medium mb-1.5 block">身份：一句话他是谁</label>
            <textarea
              value={form.description}
              onChange={e => setForm({ ...form, description: e.target.value })}
              placeholder="身份、和玩家什么关系……"
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
            <label className="text-xs font-medium mb-1.5 block">性格与说话方式</label>
            <textarea
              value={form.persona}
              onChange={e => setForm({ ...form, persona: e.target.value })}
              placeholder="他想要什么、怕什么、开口是什么调子……"
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
            <label className="text-xs font-medium mb-1.5 block">外貌（选填）</label>
            <textarea
              value={form.appearance}
              onChange={e => setForm({ ...form, appearance: e.target.value })}
              placeholder="身形、穿着、让人记住的那一处……"
              className={`${INPUT} resize-y min-h-[4rem]`}
            />
            <Assist
              moduleId={moduleId}
              field="npc_appearance"
              context={npcContext}
              value={form.appearance}
              onApply={v => setForm(f => ({ ...f, appearance: v }))}
            />
            <p className="text-xs text-muted-foreground mt-1.5">在场、或者这一轮被提到，就整段注入。写具体点，模型靠它认人。</p>
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
            <div className="rounded-lg border border-border/60 p-3 space-y-2">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.relation_enabled}
                  onChange={e => setForm({ ...form, relation_enabled: e.target.checked })}
                  className="mt-0.5 accent-primary"
                />
                <span>
                  <span className="text-xs font-medium">跟踪这个角色的关系数值</span>
                  <span className="block text-[11px] text-muted-foreground mt-0.5">
                    关闭后只保留角色设定和近期状态，不显示好感、信任等数值。
                  </span>
                </span>
              </label>
              {form.relation_enabled && (
                <div className="pl-6 grid grid-cols-2 gap-1.5">
                  {relationDefs.map(def => {
                    const checked = activeRelationNames.has(def.name)
                    return (
                      <label key={def.name} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={e => {
                            const next = new Set(activeRelationNames)
                            if (e.target.checked) next.add(def.name)
                            else next.delete(def.name)
                            const all = relationDefs.map(item => item.name)
                            setForm({
                              ...form,
                              relation_enabled: next.size > 0,
                              relation_stat_names: next.size === all.length ? [] : Array.from(next),
                            })
                          }}
                          className="accent-primary"
                        />
                        {def.name}
                      </label>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {form.role === 'npc' && form.relation_enabled && activeRelationDefs.length > 0 && (
            <Fold title="关系数值的起点（选填）">
              <div className="grid grid-cols-2 gap-2">
                {activeRelationDefs.map(def => (
                  <div key={def.name} className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground shrink-0">{def.name}</span>
                    {/* 关系数值的初始值常是负的（敌对阵营从 -30 起） */}
                    <NumInput
                      value={Number(form.initial_state[def.name] ?? def.initial)}
                      onChange={n => setForm({
                        ...form,
                        initial_state: { ...form.initial_state, [def.name]: n ?? 0 },
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

          {/* 门卫只看 role：能力数值填的是玩家那张表里的项，跟关系数值表无关，
              所以不能照抄上面两块的 relationDefs.length > 0 */}
          {form.role === 'npc' && abilityDefs.length > 0 && (
            <Fold title="能力数值（选填）">
              <div className="grid grid-cols-2 gap-2">
                {abilityDefs.map(def => {
                  const filled = form.ability_stats[def.name]
                  // 没填 at 的行（作者刚点「添加一档」）后端会跳过，这儿也一样
                  const tiers = (def.tiers || [])
                    .filter(t => typeof t?.at === 'number')
                    .map(t => ({ at: t.at as number, label: t.label }))
                    .sort((a, b) => a.at - b.at)
                  const isRank = def.name === rankStat
                  return (
                    <div key={def.name} className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground shrink-0">{def.name}</span>
                      {isRank && tiers.length > 0 ? (
                        <select
                          value={filled === undefined ? '' : String(filled)}
                          onChange={e => setAbility(def.name, e.target.value)}
                          className={INPUT}
                        >
                          <option value="">没填</option>
                          {tiers.map(t => (
                            <option key={t.at} value={String(t.at)}>
                              {t.label || t.at}（{t.at}）
                            </option>
                          ))}
                          {/* 档表改过之后落下的旧值：不补一条 option 就渲染成空白行，
                              作者看着像「没填」，随手一动就把原值盖掉了 */}
                          {filled !== undefined && !tiers.some(t => t.at === filled) && (
                            <option value={String(filled)}>{filled}（档表里没有这一档）</option>
                          )}
                        </select>
                      ) : (
                        <input
                          type="number"
                          value={filled === undefined ? '' : String(filled)}
                          onChange={e => setAbility(def.name, e.target.value)}
                          placeholder="没填"
                          className={INPUT}
                        />
                      )}
                    </div>
                  )
                })}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                {checkOff
                  ? '这个模组关了判定，填了也用不上——想要对抗先去「判定」里打开。'
                  : rankStat
                    ? `只有「${rankStat}」参与对抗：玩家跟他正面对上时比这一项，差一级就差一档成功率。别的项填了只是给你自己看。`
                    : '玩家跟他正面对上、而 AI 挑中的正是这里填过的那一项时，比的就是双方这一项。'}
                {' '}留空的项按基准算，等于不占优势也不吃亏——0 是「凡人」，和留空不是一回事。
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                这一栏是作者设定的「他有多强」，不随存档走：你把 BOSS 从 5 改成 8，老存档下一轮就变难。
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
  )

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
          <div key={npc.id} className="space-y-2">
          <div className="border rounded-lg px-3 py-2 flex items-start gap-3">
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
                    {npc.random_movement ? 'AI 调度 · 随机移动' : 'AI 调度'}
                  </span>
                )}
                {npc.relation_enabled && (
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-700 dark:text-sky-300">
                    关系数值
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
          {showForm && editingId === npc.id && renderForm()}
          </div>
          )
        })}

        {showForm && editingId === null && renderForm()}
        {!showForm && (
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
                    initial_state: n.initial_state,
                    relation_enabled: Object.keys(n.initial_state || {}).length > 0,
                    sort_order: npcs.length + 1,
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
