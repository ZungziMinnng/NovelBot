import { useState, useMemo } from 'react'
import { X, ChevronRight, ChevronLeft, ChevronDown, Loader2 } from 'lucide-react'
import { novelsApi } from '@/api/client'
import { ROLE_OPTIONS } from '@/constants/roles'
import { useSettingsStore } from '@/store/settingsStore'

interface Props {
  onClose: () => void
  onComplete: (novelId: number) => void
  onBuild: (novelId: number) => void
}

const GENRES = [
  '玄幻', '仙侠', '都市', '科幻',
  '历史', '言情', '悬疑', '武侠',
  '奇幻', '末世', '游戏', '军事',
  '古代权谋',
]
const STYLES = ['严肃厚重', '轻快幽默', '悬念紧张', '细腻文艺', '热血激昂']
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

export default function NovelWizard({ onClose, onComplete, onBuild }: Props) {
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
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

  // Step 3 fields
  const [characters, setCharacters] = useState([
    { name: '', role: '主角', age: '', description: '' }
  ])

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
      genre,
      target_length: LENGTH_VALUES[length],
      writing_style: style,
      tags: buildTags(),
    })
    setNovelId(novel.id)
    return novel.id
  }

  const chapterRange = useMemo(() => CHAPTER_RANGES[LENGTH_VALUES[length]], [length])

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
      const coreSetting = [rawSetting.trim(), rawRules.trim()].filter(Boolean).join('\n\n')
      await novelsApi.update(id, { core_setting: coreSetting })
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
        updates.core_setting = [rawSetting.trim(), rawRules.trim()].filter(Boolean).join('\n\n')
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
      onComplete(id)
    } finally {
      setLoading(false)
    }
  }

  const addCharacter = () =>
    setCharacters([...characters, { name: '', role: '配角', age: '', description: '' }])

  const updateChar = (i: number, k: string, v: string) =>
    setCharacters(characters.map((c, idx) => idx === i ? { ...c, [k]: v } : c))

  const totalTagsSelected = Object.values(tags).reduce((s, a) => s + a.length, 0) + (cheatCustom.trim() ? 1 : 0)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-card rounded-2xl w-full max-w-2xl shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b shrink-0">
          <div>
            <h2 className="font-bold text-lg">新建小说</h2>
            <div className="flex items-center gap-1 mt-1">
              {[1,2,3].map(s => (
                <button
                  key={s}
                  onClick={() => s <= step && setStep(s)}
                  className={`h-1 w-8 rounded-full transition-colors ${s <= step ? 'bg-primary' : 'bg-border'}`}
                />
              ))}
              <span className="text-xs text-muted-foreground ml-2">{step}/3</span>
            </div>
          </div>
          <button onClick={onClose} className="p-2 rounded-md hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 overflow-y-auto flex-1">
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
                </div>
              ))}
              <button onClick={addCharacter} className="w-full border border-dashed rounded-lg py-2 text-sm text-muted-foreground hover:border-primary hover:text-primary transition-colors">
                + 添加角色
              </button>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between p-6 border-t shrink-0">
          <button
            onClick={() => step > 1 ? setStep(step - 1) : onClose()}
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
            {step === 2 && (
              <button
                onClick={handleBuild}
                disabled={loading}
                className="flex items-center gap-2 border border-primary text-primary px-4 py-2 rounded-lg hover:bg-primary/10 disabled:opacity-50 transition-colors font-medium text-sm"
              >
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                AI 自动构建
              </button>
            )}
            {step < 3 && (
              <button
                onClick={() => {
                  if (step === 1) handleStep1()
                  else if (step === 2) handleStep2()
                }}
                disabled={loading}
                className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2 rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity font-medium text-sm"
              >
                {loading && <Loader2 className="w-4 h-4 animate-spin" />}
                下一步
                {!loading && <ChevronRight className="w-4 h-4" />}
              </button>
            )}
            {step === 3 && (
              <button
                onClick={handleStep3}
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
    </div>
  )
}
