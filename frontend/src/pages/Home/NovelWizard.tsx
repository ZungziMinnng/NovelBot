import { useState, useMemo, useEffect, type MutableRefObject } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, ChevronRight, ChevronLeft, ChevronDown, Loader2 } from 'lucide-react'
import { novelsApi, volumesApi, modelLibraryApi, modelSelectValue, type BrainstormExtract } from '@/api/client'
import { ROLE_OPTIONS } from '@/constants/roles'
import { PERSONALITY_GROUPS } from '@/constants/personality'
import { WRITING_STYLES } from '@/constants/writingStyles'
import { useSettingsStore } from '@/store/settingsStore'
import { useAuthStore } from '@/store/authStore'
import type { FormSnapshot } from './ApplyExtractModal'

interface Props {
  onCancel: () => void
  onComplete: (novelId: number) => void
  onBuild: (novelId: number) => void
  /** 同步当前9个文本字段，供diff预览显示「会被换成什么」*/
  snapshotRef?: MutableRefObject<FormSnapshot>
  /** 注册一个函数供右侧调用，把勾选的字段合并进表单 */
  applyRef?: MutableRefObject<((picked: Partial<BrainstormExtract>) => void) | null>
}

const GENRES = [
  '玄幻', '仙侠', '都市', '科幻',
  '历史', '言情', '悬疑', '武侠',
  '奇幻', '末世', '游戏', '军事',
  '古代权谋',
]
const STYLES = WRITING_STYLES
const LENGTHS = ['超短篇（< 10万字）', '短篇（10-50万字）', '中篇（50-150万字）', '长篇（> 150万字）']
const LENGTH_VALUES = ['超短篇', '短篇', '中篇', '长篇']
const WIZARD_ROLE_OPTIONS = ['主角', ...ROLE_OPTIONS.filter(role => role !== '主角')]

const CHAPTER_RANGES: Record<string, { min: number; max: number; default: number }> = {
  '超短篇': { min: 10, max: 100, default: 30 },
  '短篇': { min: 30, max: 500, default: 100 },
  '中篇': { min: 100, max: 1500, default: 300 },
  '长篇': { min: 200, max: 5000, default: 500 },
}

const TAG_GROUPS: { key: string; label: string; options: string[] }[] = [
  {
    key: 'tropes', label: '叙事套路',
    options: ['系统流', '升级流', '无敌流', '种田流', '练功流', '技术流', '宠物流', '鉴宝流', '自播流', '经营流', '建设流', '领主流', '签到流', '抽奖流', '模拟器流'],
  },
  {
    key: 'situation', label: '角色处境',
    options: ['重生', '穿越', '夺舍', '快穿', '女扮男装', '扮猪吃虎', '废柴逆袭', '天才', '退隐强者', '赘婿', '孤儿', '皇族'],
  },
  {
    key: 'theme', label: '题材方向',
    options: ['宫斗', '探险', '末日求生', '星际', '盗墓', '航海', '校园', '职场', '电竞', '美食', '医术', '娱乐圈', '体育', '音乐'],
  },
  {
    key: 'pacing', label: '节奏风格',
    options: ['慢热', '快节奏', '日常', '群像', '单女主', '后宫', '争霸', '复仇', '阴谋', '轻松', '暗黑', '治愈', '搞笑', '虐心'],
  },
  {
    key: 'cheat', label: '金手指类型',
    options: ['系统', '空间', '重生记忆', '功法传承', '异能', '血脉', '神器', '时间回溯', '读心', '鉴定'],
  },
]

const NSFW_TAG_GROUPS: { key: string; label: string; options: string[] }[] = [
  {
    key: 'nsfw_genre', label: '成人类型',
    options: ['纯爱', '后宫', '百合', '耽美', 'NTR', '调教', '人妻', '触手', '异种', '催眠', '女尊'],
  },
  {
    key: 'nsfw_element', label: '情色元素',
    options: ['女仆', '制服诱惑', '温泉', '校园禁忌', '师徒禁恋', '异世奴隶', '魅魔', '身体改造', '精神控制', '时间停止'],
  },
]

export default function NovelWizard({ onCancel, onComplete, onBuild, snapshotRef, applyRef }: Props) {
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
  const defaultFastModel = useAuthStore((s) => s.user?.default_fast_model || '')
  const { data: modelLibrary = [] } = useQuery({
    queryKey: ['model-library'],
    queryFn: modelLibraryApi.list,
  })
  const buildModelOptions = useMemo(
    () => modelLibrary.filter(m => m.model_type !== 'embedding'),
    [modelLibrary],
  )
  const allTagGroups = useMemo(
    () => nsfwMode ? [...TAG_GROUPS, ...NSFW_TAG_GROUPS] : TAG_GROUPS,
    [nsfwMode],
  )
  const [step, setStep] = useState(1)
  const [loading, setLoading] = useState(false)
  const [novelId, setNovelId] = useState<number | null>(null)

  // Step 1 fields
  const [title, setTitle] = useState('')
  const [premise, setPremise] = useState('')
  const [plotDesign, setPlotDesign] = useState('')
  // 构建模型默认带出「设置」里配置的默认构建模型（default_fast_model），可在向导内改
  const [buildModel, setBuildModel] = useState(defaultFastModel)
  const [genre, setGenre] = useState('玄幻')
  const [style, setStyle] = useState('严肃厚重')
  const [tags, setTags] = useState<Record<string, string[]>>({
    tropes: [], situation: [], theme: [], pacing: [], cheat: [],
  })
  const [cheatCustom, setCheatCustom] = useState('')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const [rawSetting, setRawSetting] = useState('')
  const [rawRules, setRawRules] = useState('')

  // Step 2 fields
  const [length, setLength] = useState(1)
  const [estimatedChapters, setEstimatedChapters] = useState(30)
  const [enableVolumeSplit, setEnableVolumeSplit] = useState(false)
  const [skipOutline, setSkipOutline] = useState(false)

  // Step 3 fields：开写前要定下来的收尾方向
  const [ending, setEnding] = useState('')
  const [protagonistArc, setProtagonistArc] = useState('')
  // 每张牌带一个解锁卷号，序列化成 "第N卷 | 内容" 存 Volume.endgame_cards
  const [endgameCards, setEndgameCards] = useState([
    { volume: 3, text: '' }, { volume: 5, text: '' },
  ])
  const [tierCount, setTierCount] = useState(0)
  const [wordsPerTier, setWordsPerTier] = useState(0)

  // Step 4 fields。personality/appearance/speech_style 留空则整栏交给 AI 生成
  const [characters, setCharacters] = useState([
    { name: '', role: '主角', age: '', description: '', personality: '', appearance: '', speech_style: '' }
  ])
  // 展开性格标签面板的角色下标，同时只开一个
  const [tagPanelIndex, setTagPanelIndex] = useState<number | null>(null)

  // Track submissions
  const [charactersSubmitted, setCharactersSubmitted] = useState(false)

  const toggleTag = (groupKey: string, tag: string) => {
    setTags(prev => {
      const arr = prev[groupKey] || []
      return {
        ...prev,
        [groupKey]: arr.includes(tag) ? arr.filter(t => t !== tag) : [...arr, tag],
      }
    })
  }

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const buildTags = () => {
    const finalTags = { ...tags }
    if (cheatCustom.trim()) {
      finalTags.cheat = [...(finalTags.cheat || []), cheatCustom.trim()]
    }
    const nonEmpty: Record<string, string[]> = {}
    for (const [k, v] of Object.entries(finalTags)) {
      if (v.length > 0) nonEmpty[k] = v
    }
    return nonEmpty
  }

  const ensureNovel = async (): Promise<number> => {
    if (novelId) return novelId
    const novel = await novelsApi.create({
      title: title || `《${premise.slice(0, 10) || '新建小说'}》`,
      premise: premise || '',
      plot_design: plotDesign || '',
      genre,
      target_length: LENGTH_VALUES[length],
      writing_style: style,
      fast_model: buildModel || '',
      tags: buildTags(),
    })
    setNovelId(novel.id)
    return novel.id
  }

  const chapterRange = useMemo(() => CHAPTER_RANGES[LENGTH_VALUES[length]], [length])

  // 全书目标字数按每章 3000 估，和后端体检 outlines.WORDS_PER_CHAPTER 一致
  const targetWords = estimatedChapters * 3000
  const capacity = tierCount * wordsPerTier
  const capacityShort = tierCount > 0 && wordsPerTier > 0 && capacity < targetWords

  const serializeCards = () =>
    endgameCards
      .filter(c => c.text.trim())
      .map(c => `第${c.volume}卷 | ${c.text.trim()}`)
      .join('\n')

  /** 把结局字段写进 Novel，把库存写进第 1 卷（不存在则建） */
  const saveEndingFields = async (id: number) => {
    await novelsApi.update(id, { ending: ending.trim(), protagonist_arc: protagonistArc.trim() })
    const cards = serializeCards()
    if (!cards && !tierCount && !wordsPerTier) return
    const volumes = await volumesApi.list(id)
    const first = volumes.find(v => v.number === 1)
    const payload = {
      endgame_cards: cards,
      tier_count: tierCount,
      words_per_tier: wordsPerTier,
    }
    if (first) {
      await volumesApi.update(first.id, payload)
    } else {
      await volumesApi.create({ novel_id: id, number: 1, title: '第1卷', ...payload })
    }
  }

  const handleStep1 = async () => {
    setLoading(true)
    try {
      await ensureNovel()
      setStep(2)
    } finally {
      setLoading(false)
    }
  }

  const handleStep2 = async () => {
    setLoading(true)
    try {
      const id = await ensureNovel()
      await novelsApi.update(id, {
        target_length: LENGTH_VALUES[length],
        estimated_chapters: estimatedChapters,
        enable_volume_split: enableVolumeSplit,
        skip_outline: skipOutline,
      })
      setStep(3)
    } finally {
      setLoading(false)
    }
  }

  const handleStep3 = async () => {
    setLoading(true)
    try {
      const id = await ensureNovel()
      await saveEndingFields(id)
      setStep(4)
    } finally {
      setLoading(false)
    }
  }

  const handleStep4 = async () => {
    const validChars = characters.filter(c => c.name.trim())
    if (validChars.length === 0) {
      await handleBuild()
      return
    }
    setLoading(true)
    try {
      const id = await ensureNovel()
      await novelsApi.wizardCharacters(id, validChars)
      setCharactersSubmitted(true)
      await handleBuildInner(id)
    } finally {
      setLoading(false)
    }
  }

  const handleBuildInner = async (id: number) => {
    if (rawSetting.trim() || rawRules.trim()) {
      await novelsApi.update(id, {
        core_setting: rawSetting.trim(),
        world_rules_seed: rawRules.trim(),
      })
    }
    onBuild(id)
  }

  const handleBuild = async () => {
    setLoading(true)
    try {
      const id = await ensureNovel()
      if (step >= 2) {
        await novelsApi.update(id, {
          target_length: LENGTH_VALUES[length],
          estimated_chapters: estimatedChapters,
          enable_volume_split: enableVolumeSplit,
          skip_outline: skipOutline,
        })
      }
      // 结局要在大纲生成之前落库，否则这次构建的大纲还是不知道往哪收
      if (step >= 3) {
        await saveEndingFields(id)
      }
      const validChars = characters.filter(c => c.name.trim())
      if (!charactersSubmitted && validChars.length > 0) {
        await novelsApi.wizardCharacters(id, validChars)
        setCharactersSubmitted(true)
      }
      await handleBuildInner(id)
    } finally {
      setLoading(false)
    }
  }

  const handleSkip = async () => {
    setLoading(true)
    try {
      const id = await ensureNovel()
      const updates: Record<string, unknown> = {}
      if (step >= 1 && (rawSetting.trim() || rawRules.trim())) {
        updates.core_setting = rawSetting.trim()
        updates.world_rules_seed = rawRules.trim()
      }
      if (step >= 2) {
        updates.target_length = LENGTH_VALUES[length]
        updates.estimated_chapters = estimatedChapters
        updates.enable_volume_split = enableVolumeSplit
        updates.skip_outline = skipOutline
      }
      if (Object.keys(updates).length > 0) {
        await novelsApi.update(id, updates)
      }
      if (step >= 3) {
        await saveEndingFields(id)
      }
      onComplete(id)
    } finally {
      setLoading(false)
    }
  }

  const addCharacter = () =>
    setCharacters([...characters, { name: '', role: '配角', age: '', description: '', personality: '', appearance: '', speech_style: '' }])

  const updateChar = (i: number, k: string, v: string) =>
    setCharacters(characters.map((c, idx) => idx === i ? { ...c, [k]: v } : c))

  /** 点标签往性格栏追加，已经有了就移除。用「、」分隔与角色卡里的写法一致 */
  const toggleTrait = (i: number, trait: string) =>
    setCharacters(characters.map((c, idx) => {
      if (idx !== i) return c
      const traits = c.personality.split(/[、,，]/).map(t => t.trim()).filter(Boolean)
      const next = traits.includes(trait)
        ? traits.filter(t => t !== trait)
        : [...traits, trait]
      return { ...c, personality: next.join('、') }
    }))

  const hasTrait = (personality: string, trait: string) =>
    personality.split(/[、,，]/).map(t => t.trim()).includes(trait)

  const totalTagsSelected = Object.values(tags).reduce((s, a) => s + a.length, 0) + (cheatCustom.trim() ? 1 : 0)

  // 同步快照：只9个文本字段，供diff预览显示「会被换成什么」。写ref不提状态，避免每敲一个字都重渲染对话面板
  useEffect(() => {
    if (!snapshotRef) return
    snapshotRef.current = {
      title,
      genre,
      writing_style: style,
      premise,
      plot_design: plotDesign,
      core_setting: rawSetting,
      world_rules_seed: rawRules,
      ending,
      protagonist_arc: protagonistArc,
    }
  })

  // 注册apply函数：把勾选的字段合并进表单state。用函数式setState避免stale closure
  useEffect(() => {
    if (!applyRef) return
    applyRef.current = (picked: Partial<BrainstormExtract>) => {
      if (picked.title) setTitle(picked.title)
      if (picked.genre) setGenre(picked.genre)
      if (picked.writing_style) setStyle(picked.writing_style)
      if (picked.premise) setPremise(picked.premise)
      if (picked.plot_design) setPlotDesign(picked.plot_design)
      if (picked.core_setting) setRawSetting(picked.core_setting)
      if (picked.world_rules_seed) setRawRules(picked.world_rules_seed)
      if (picked.ending) setEnding(picked.ending)
      if (picked.protagonist_arc) setProtagonistArc(picked.protagonist_arc)
      if (picked.endgame_cards) {
        setEndgameCards(prev => [...prev, ...picked.endgame_cards!])
      }
      if (picked.characters) {
        setCharacters(prev => {
          const next = [...prev]
          for (const c of picked.characters!) {
            const idx = next.findIndex(x => x.name === c.name)
            // 抽取只给四个基本字段，同名时保留作者已填的性格/外貌/语言风格
            if (idx >= 0) {
              next[idx] = { ...next[idx], ...c }
            } else {
              next.push({ ...c, personality: '', appearance: '', speech_style: '' })
            }
          }
          return next
        })
      }
    }
  })

  return (
    <div className="flex flex-col h-full min-w-0">
      <div className="px-5 py-3 border-b shrink-0">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-bold shrink-0">新建小说</h2>
          <div className="flex items-center gap-1.5 min-w-0">
            <label className="text-xs text-muted-foreground shrink-0">构建模型</label>
            <select
              value={modelSelectValue(buildModelOptions, buildModel)}
              onChange={e => setBuildModel(e.target.value)}
              title="留空使用全局默认"
              className="text-xs border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-ring max-w-[200px]"
            >
              <option value="">全局默认</option>
              {buildModelOptions.map(m => (
                <option key={m.id} value={String(m.id)}>
                  [{m.provider}] {m.display_name || m.model_id}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex items-center gap-1 mt-1.5">
          {[1,2,3,4].map(s => (
            <button
              key={s}
              onClick={() => s <= step && setStep(s)}
              className={`h-1 w-8 rounded-full transition-colors ${s <= step ? 'bg-primary' : 'bg-border'}`}
            />
          ))}
          <span className="text-xs text-muted-foreground ml-2">{step}/4</span>
        </div>
      </div>

      <div className="px-5 py-5 overflow-y-auto flex-1">
        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1 block">小说名称</label>
              <input
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="留空则AI自动取名"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">创作方向 <span className="text-muted-foreground font-normal">（选填）</span></label>
              <textarea
                value={premise}
                onChange={e => setPremise(e.target.value)}
                placeholder="简要描述你想写的故事方向或核心创意..."
                className="w-full border rounded-lg p-3 text-sm resize-none h-20 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">剧情设计 <span className="text-muted-foreground font-normal">（选填）</span></label>
              <textarea
                value={plotDesign}
                onChange={e => setPlotDesign(e.target.value)}
                placeholder="核心情节/走向/转折点，AI 大纲和角色设计将以此为主线依据..."
                className="w-full border rounded-lg p-3 text-sm resize-none h-20 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">小说类型</label>
              <div className="grid grid-cols-4 gap-2">
                {GENRES.map(g => (
                  <button key={g} onClick={() => setGenre(g)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${genre === g ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                    {g}
                  </button>
                ))}
                <button onClick={() => { if (GENRES.includes(genre)) setGenre('') }}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${!GENRES.includes(genre) ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                  自定义
                </button>
              </div>
              {!GENRES.includes(genre) && (
                <input
                  value={genre}
                  onChange={e => setGenre(e.target.value)}
                  placeholder="输入自定义类型..."
                  className="mt-2 w-full border rounded-lg p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              )}
            </div>

            <div>
              <label className="text-sm font-medium mb-2 block">写作风格</label>
              <div className="flex flex-wrap gap-2">
                {STYLES.map(s => (
                  <button key={s} onClick={() => setStyle(s)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${style === s ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                    {s}
                  </button>
                ))}
                <button onClick={() => { if (STYLES.includes(style)) setStyle('') }}
                  className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${!STYLES.includes(style) ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                  自定义
                </button>
              </div>
              {!STYLES.includes(style) && (
                <input
                  value={style}
                  onChange={e => setStyle(e.target.value)}
                  placeholder="输入自定义风格..."
                  className="mt-2 w-full border rounded-lg p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              )}
            </div>

            {/* 世界观设定 */}
            <div className="border-t pt-4">
              <p className="text-sm text-muted-foreground mb-3">描述你的世界观，AI 将自动扩展为完整设定文档。</p>
              <div className="space-y-3">
                <div>
                  <label className="text-sm font-medium mb-1 block">时代背景 <span className="text-muted-foreground font-normal">（选填）</span></label>
                  <textarea
                    value={rawSetting}
                    onChange={e => setRawSetting(e.target.value)}
                    placeholder="例：架空古代，类似明朝中期，无魔法体系..."
                    className="w-full border rounded-lg p-3 text-sm resize-none h-20 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium mb-1 block">核心规则/特殊设定 <span className="text-muted-foreground font-normal">（选填）</span></label>
                  <textarea
                    value={rawRules}
                    onChange={e => setRawRules(e.target.value)}
                    placeholder="例：皇权衰弱，三大世家把持朝政..."
                    className="w-full border rounded-lg p-3 text-sm resize-none h-16 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
              </div>
            </div>

            {/* 标签 */}
            <div className="border-t pt-4">
              <div className="flex items-center justify-between mb-3">
                <label className="text-sm font-medium">标签设定 <span className="text-muted-foreground font-normal">（选填）</span></label>
                {totalTagsSelected > 0 && (
                  <span className="text-xs text-muted-foreground">已选 {totalTagsSelected} 个</span>
                )}
              </div>
              <div className="space-y-1">
                {allTagGroups.map(group => {
                  const expanded = expandedGroups.has(group.key)
                  const selected = tags[group.key] || []
                  return (
                    <div key={group.key} className="border rounded-lg">
                      <button
                        onClick={() => toggleGroup(group.key)}
                        className="w-full flex items-center justify-between px-3 py-2 text-sm hover:bg-muted/50 transition-colors"
                      >
                        <span className="font-medium">
                          {group.label}
                          {selected.length > 0 && (
                            <span className="text-muted-foreground font-normal ml-2">({selected.join('、')})</span>
                          )}
                        </span>
                        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${expanded ? 'rotate-180' : ''}`} />
                      </button>
                      {expanded && (
                        <div className="px-3 pb-3">
                          <div className="flex flex-wrap gap-1.5">
                            {group.options.map(opt => (
                              <button key={opt} onClick={() => toggleTag(group.key, opt)}
                                className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${selected.includes(opt) ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                                {opt}
                              </button>
                            ))}
                          </div>
                          {group.key === 'cheat' && (
                            <input
                              value={cheatCustom}
                              onChange={e => setCheatCustom(e.target.value)}
                              placeholder="自定义金手指..."
                              className="mt-2 w-full border rounded-md p-2 text-xs bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                            />
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <p className="text-sm text-muted-foreground">设置小说规模，AI 将据此规划大纲结构。</p>

            <div>
              <label className="text-sm font-medium mb-2 block">目标长度</label>
              <div className="flex gap-2">
                {LENGTHS.map((l, i) => (
                  <button key={l} onClick={() => {
                    setLength(i)
                    setEstimatedChapters(CHAPTER_RANGES[LENGTH_VALUES[i]].default)
                  }}
                    className={`flex-1 px-3 py-1.5 rounded-full text-sm border transition-colors ${length === i ? 'bg-primary text-primary-foreground border-primary' : 'hover:border-primary'}`}>
                    {l}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium">预估章节数</label>
                <span className="text-sm font-bold text-primary">{estimatedChapters} 章</span>
              </div>
              <input
                type="range"
                min={chapterRange.min}
                max={chapterRange.max}
                step={chapterRange.max <= 50 ? 1 : 5}
                value={estimatedChapters}
                onChange={e => setEstimatedChapters(Number(e.target.value))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
              <div className="flex justify-between text-xs text-muted-foreground mt-1">
                <span>{chapterRange.min} 章</span>
                <span>{chapterRange.max} 章</span>
              </div>
            </div>

            <div className="border-t pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <label className="text-sm font-medium block">自动分卷</label>
                  <p className="text-xs text-muted-foreground mt-0.5">开启后系统将根据大纲和设定自动分卷</p>
                </div>
                <button
                  onClick={() => setEnableVolumeSplit(!enableVolumeSplit)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${enableVolumeSplit ? 'bg-primary' : 'bg-muted'}`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${enableVolumeSplit ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
              <div className="flex items-center justify-between mt-4">
                <div>
                  <label className="text-sm font-medium block">跳过大纲生成</label>
                  <p className="text-xs text-muted-foreground mt-0.5">开启后 AI 构建仅生成世界观设定，不生成章节大纲</p>
                </div>
                <button
                  onClick={() => setSkipOutline(!skipOutline)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${skipOutline ? 'bg-primary' : 'bg-muted'}`}
                >
                  <span className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${skipOutline ? 'translate-x-6' : 'translate-x-1'}`} />
                </button>
              </div>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-5">
            <p className="text-sm text-muted-foreground">
              这一步定的是「往哪收」。不填也能往下走，但大纲会不知道故事要去哪，
              写到中后段容易出现无牌可打。
            </p>

            <div>
              <label className="text-sm font-medium mb-1 block">
                结局一句话 <span className="text-muted-foreground font-normal">（主角最后走到哪、跟谁、什么状态）</span>
              </label>
              <textarea
                value={ending}
                onChange={e => setEnding(e.target.value)}
                placeholder="主角登顶大道，与旧友决裂，独自守着一座空城..."
                rows={2}
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-none"
              />
            </div>

            <div>
              <label className="text-sm font-medium mb-1 block">
                主角起点 → 终点 <span className="text-muted-foreground font-normal">（身份地位怎么变）</span>
              </label>
              <input
                value={protagonistArc}
                onChange={e => setProtagonistArc(e.target.value)}
                placeholder="外门杂役 → 一宗之主"
                className="w-full border rounded-lg p-3 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>

            <div>
              <label className="text-sm font-medium mb-1 block">留到后面才揭的牌</label>
              <p className="text-xs text-muted-foreground mb-2">
                宿敌真身、主角身世、世界真相这类只能用一次的料。标上最早能揭的卷号，
                之前的卷只埋线索。建议留 2 张以上。
              </p>
              <div className="space-y-2">
                {endgameCards.map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className="flex items-center gap-1 shrink-0">
                      <span className="text-xs text-muted-foreground">第</span>
                      <input
                        type="number" min={1} value={c.volume}
                        onChange={e => setEndgameCards(endgameCards.map((x, idx) =>
                          idx === i ? { ...x, volume: Math.max(1, Number(e.target.value)) } : x))}
                        className="w-14 border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                      <span className="text-xs text-muted-foreground">卷揭</span>
                    </div>
                    <input
                      value={c.text}
                      onChange={e => setEndgameCards(endgameCards.map((x, idx) =>
                        idx === i ? { ...x, text: e.target.value } : x))}
                      placeholder={i === 0 ? '师父其实是灭门仇人' : '主角是上一代魔尊转世'}
                      className="flex-1 border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                    {endgameCards.length > 1 && (
                      <button
                        onClick={() => setEndgameCards(endgameCards.filter((_, idx) => idx !== i))}
                        className="text-muted-foreground hover:text-destructive px-1 shrink-0"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <button
                onClick={() => setEndgameCards([...endgameCards, { volume: endgameCards.length + 3, text: '' }])}
                className="mt-2 w-full border border-dashed rounded-lg py-2 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors"
              >
                + 再留一张牌
              </button>
            </div>

            <div>
              <label className="text-sm font-medium mb-1 block">实力体系够不够撑满全书</label>
              <p className="text-xs text-muted-foreground mb-2">
                一共几档（练气→筑基→…算几档）、每档大概写多少字。填完当场算给你看。
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">一共几档</label>
                  <input
                    type="number" min={0} value={tierCount}
                    onChange={e => setTierCount(Math.max(0, Number(e.target.value)))}
                    className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">每档写多少字</label>
                  <input
                    type="number" min={0} step={10000} value={wordsPerTier}
                    onChange={e => setWordsPerTier(Math.max(0, Number(e.target.value)))}
                    className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>
              </div>
              {tierCount > 0 && wordsPerTier > 0 && (
                <div className={`mt-2 text-xs rounded-md p-2 ${
                  capacityShort
                    ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400'
                    : 'bg-muted text-muted-foreground'
                }`}>
                  {tierCount} 档 × {wordsPerTier} 字 = {capacity} 字，
                  全书目标约 {targetWords} 字（{estimatedChapters} 章 × 3000）。
                  {capacityShort
                    ? `还差 ${targetWords - capacity} 字，写到一半实力就顶天了。要么加档位，要么每档多写。`
                    : '够用。'}
                </div>
              )}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">添加主要角色，AI 将自动生成完整角色卡。</p>
            {characters.map((c, i) => (
              <div key={i} className="border rounded-lg p-4 space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">姓名 *</label>
                    <input value={c.name} onChange={e => updateChar(i, 'name', e.target.value)}
                      className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">定位</label>
                    <select
                      value={WIZARD_ROLE_OPTIONS.includes(c.role) ? c.role : '__custom__'}
                      onChange={e => {
                        updateChar(i, 'role', e.target.value === '__custom__' ? '' : e.target.value)
                      }}
                      className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      {WIZARD_ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                      <option value="__custom__">自定义...</option>
                    </select>
                    {!WIZARD_ROLE_OPTIONS.includes(c.role) && (
                      <input
                        value={c.role}
                        onChange={e => updateChar(i, 'role', e.target.value)}
                        className="mt-2 w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                        placeholder="输入角色定位"
                      />
                    )}
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground mb-1 block">年龄</label>
                    <input value={c.age} onChange={e => updateChar(i, 'age', e.target.value)}
                      placeholder="25" className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                  </div>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">一句话描述</label>
                  <input value={c.description} onChange={e => updateChar(i, 'description', e.target.value)}
                    placeholder="外表平庸内心坚韧..."
                    className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-xs text-muted-foreground">性格</label>
                    <button
                      type="button"
                      onClick={() => setTagPanelIndex(tagPanelIndex === i ? null : i)}
                      className="flex items-center gap-0.5 text-xs text-muted-foreground hover:text-primary transition-colors"
                    >
                      标签速填
                      <ChevronDown className={`w-3 h-3 transition-transform ${tagPanelIndex === i ? 'rotate-180' : ''}`} />
                    </button>
                  </div>
                  {tagPanelIndex === i && (
                    <div className="mb-2 border rounded-md p-2.5 space-y-2 bg-muted/30">
                      {PERSONALITY_GROUPS.map(g => (
                        <div key={g.label}>
                          <div className="text-xs text-muted-foreground mb-1">{g.label}</div>
                          <div className="flex flex-wrap gap-1">
                            {g.options.map(t => (
                              <button
                                key={t}
                                type="button"
                                onClick={() => toggleTrait(i, t)}
                                className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                                  hasTrait(c.personality, t)
                                    ? 'border-primary bg-primary/10 text-primary'
                                    : 'text-muted-foreground hover:border-primary hover:text-foreground'
                                }`}
                              >
                                {t}
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <textarea value={c.personality} onChange={e => updateChar(i, 'personality', e.target.value)}
                    placeholder="留空由 AI 生成。填了就是硬要求，AI 会据此扩写"
                    className="w-full border rounded-md p-2 text-sm resize-none h-16 bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                </div>

                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">外貌</label>
                  <textarea value={c.appearance} onChange={e => updateChar(i, 'appearance', e.target.value)}
                    placeholder="留空由 AI 生成。五官、发型发色、身材、穿搭"
                    className="w-full border rounded-md p-2 text-sm resize-none h-16 bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                </div>

                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">语言风格</label>
                  <input value={c.speech_style} onChange={e => updateChar(i, 'speech_style', e.target.value)}
                    placeholder="留空由 AI 生成。说话习惯、口头禅、语气"
                    className="w-full border rounded-md p-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
                </div>
              </div>
            ))}
            <button onClick={addCharacter} className="w-full border border-dashed rounded-lg py-2 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors">
              + 添加角色
            </button>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between px-5 py-4 border-t shrink-0 flex-wrap gap-2">
        <button
          onClick={() => step > 1 ? setStep(step - 1) : onCancel()}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          {step === 1 ? '取消' : '上一步'}
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSkip}
            disabled={loading}
            className="text-sm text-muted-foreground hover:text-foreground disabled:opacity-40 transition-colors px-3 py-2"
          >
            跳过，快速创建
          </button>
          {(step === 2 || step === 3) && (
            <button
              onClick={handleBuild}
              disabled={loading}
              className="flex items-center gap-2 border border-primary text-primary px-4 py-2 rounded-lg hover:bg-primary/10 disabled:opacity-50 transition-colors font-medium text-sm"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              AI 自动构建
            </button>
          )}
          {step < 4 && (
            <button
              onClick={() => {
                if (step === 1) handleStep1()
                else if (step === 2) handleStep2()
                else if (step === 3) handleStep3()
              }}
              disabled={loading}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2 rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium text-sm"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              下一步
              {!loading && <ChevronRight className="w-4 h-4" />}
            </button>
          )}
          {step === 4 && (
            <button
              onClick={handleStep4}
              disabled={loading}
              className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2 rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium text-sm"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              AI 自动构建
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
