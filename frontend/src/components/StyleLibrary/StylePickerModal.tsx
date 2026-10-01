import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import toast from 'react-hot-toast'
import {
  defaultPick,
  styleProfilesApi,
  type StyleAdaptMode,
  type StyleAdaptResult,
  type StyleProfile,
} from '@/api/styleProfiles'
import StyleModelSelect, { useStyleModel } from './StyleModelSelect'

const TITLES: Record<StyleAdaptMode, string> = {
  novel: '从文风库取示例',
  tavern: '从文风库取说话样例',
  rpg_narration: '从文风库取叙事示例',
  rpg_npc: '从文风库取对话示例',
}

const PREVIEW_LEN = 120

interface Props {
  mode: StyleAdaptMode
  targetName?: string
  nameOptions?: string[] // 这边已有的角色名，填名字对照时给候选
  onApply: (r: StyleAdaptResult & { styleDesc?: string }) => void
  onClose: () => void
}

export default function StylePickerModal({ mode, targetName, nameOptions, onApply, onClose }: Props) {
  const [profiles, setProfiles] = useState<StyleProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [profileId, setProfileId] = useState<number | null>(null)
  const [character, setCharacter] = useState('')
  // 只存用户亲手改过的格子；清空也算改过（存 ''），预填不会再冒回来
  const [nameEdits, setNameEdits] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<number[]>([])
  const [expanded, setExpanded] = useState<number[]>([])
  const [withStyleDesc, setWithStyleDesc] = useState(false)
  const [converting, setConverting] = useState(false)
  const [result, setResult] = useState<StyleAdaptResult | null>(null)
  const [model, setModel] = useStyleModel()

  const needsCharacter = mode === 'tavern' || mode === 'rpg_npc'
  const isNarration = mode === 'rpg_narration'
  const profile = profiles.find(p => p.id === profileId) || null
  const scenes = profile?.scenes || []
  // 叙事示例、以及小说模式下已有玩家输入的段，后端直接拼，不调模型
  const needsModel =
    !isNarration && !(mode === 'novel' && selected.every(i => (scenes[i]?.input || '').trim()))

  useEffect(() => {
    let alive = true
    styleProfilesApi
      .list()
      .then(list => {
        if (!alive) return
        setProfiles(list)
        if (list.length > 0) setProfileId(list[0].id)
      })
      .catch((err: any) => toast.error(err?.response?.data?.detail || '加载文风库失败'))
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    // 换文风后候选段落整个变了，角色和名字对照都得重来
    setCharacter('')
    setNameEdits({})
    setExpanded([])
  }, [profileId])

  const characterOptions = useMemo(() => {
    if (!profile) return []
    const set = new Set<string>()
    for (const c of profile.characters || []) if (c.name) set.add(c.name)
    for (const s of profile.scenes || []) for (const sp of s.speakers || []) if (sp) set.add(sp)
    return [...set]
  }, [profile])

  // 选中段落里出现的人：不给他们配名字，示例里就留着导入时起的中性名
  const involved = useMemo(() => {
    if (!profile) return []
    const texts = selected.map(i => `${scenes[i]?.text || ''}\n${scenes[i]?.input || ''}`)
    return characterOptions.filter(name => texts.some(t => t.includes(name)))
  }, [profile, scenes, selected, characterOptions])

  const roleOf = (name: string) => profile?.characters?.find(c => c.name === name)?.role || ''

  // 预填：叙事示例的主角、说话样例选中的那个人，默认换成 targetName
  const nameMap = useMemo(() => {
    const merged: Record<string, string> = {}
    if (targetName) {
      const lead = isNarration
        ? profile?.characters?.find(c => c.role === '主角')?.name
        : needsCharacter ? character : ''
      if (lead) merged[lead] = targetName
    }
    return { ...merged, ...nameEdits }
  }, [targetName, isNarration, needsCharacter, character, profile, nameEdits])

  const candidateIndexes = useMemo(() => {
    if (!profile) return []
    const all = (profile.scenes || []).map((_, i) => i)
    // 叙事示例的玩家一侧是导入时反推的，没有的段取不了
    if (isNarration) return all.filter(i => (profile.scenes[i].input || '').trim())
    if (!needsCharacter) return all
    if (!character) return []
    return (profile.scenes || [])
      .map((s, i) => (s.speakers?.includes(character) ? i : -1))
      .filter(i => i >= 0)
  }, [profile, isNarration, needsCharacter, character])

  useEffect(() => {
    if (!profile) {
      setSelected([])
      return
    }
    setSelected(defaultPick(profile.scenes || [], candidateIndexes))
  }, [profile, candidateIndexes])

  function toggleScene(index: number) {
    setSelected(prev => (prev.includes(index) ? prev.filter(i => i !== index) : [...prev, index]))
  }

  function toggleExpand(index: number) {
    setExpanded(prev => (prev.includes(index) ? prev.filter(i => i !== index) : [...prev, index]))
  }

  async function handleConvert() {
    if (!profile || selected.length === 0 || converting) return
    setConverting(true)
    try {
      const res = await styleProfilesApi.adapt(profile.id, {
        mode,
        scene_indexes: selected,
        character: needsCharacter ? character : '',
        // 只发这次选中段落里出现的人，空的就是不换
        name_map: Object.fromEntries(
          involved.map(n => [n, (nameMap[n] || '').trim()]).filter(([, v]) => v),
        ),
        model,
      })
      setResult(res)
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || '转换失败，请重试')
    } finally {
      setConverting(false)
    }
  }

  function handleApply() {
    if (!result) return
    onApply({ ...result, styleDesc: withStyleDesc ? profile?.style_desc : undefined })
    onClose()
  }

  const userLabel = mode === 'novel' ? '指令' : isNarration ? '玩家' : '对方'
  const assistantLabel = mode === 'novel' ? '正文' : isNarration ? '叙事' : '角色'
  const footHint =
    mode === 'rpg_narration' || mode === 'rpg_npc'
      ? '填入后会随编辑面板自动保存'
      : '填入后记得点页面上的保存'

  let body: ReactNode
  if (loading) {
    body = <p className="text-sm text-muted-foreground">加载中…</p>
  } else if (profiles.length === 0) {
    body = <p className="text-sm text-muted-foreground">文风库是空的，先去首页导入一本 txt。</p>
  } else if (result) {
    body = (
      <div className="space-y-4">
        {result.examples && result.examples.length > 0 && (
          <div className="space-y-4">
            {result.examples.map((ex, i) => (
              <div key={i} className="border rounded-lg overflow-hidden">
                <div className="px-3 py-2 border-b bg-muted/30">
                  <div className="inline-block px-1.5 py-0.5 rounded bg-muted text-[11px] text-muted-foreground mb-1">
                    {userLabel}
                  </div>
                  <div className="text-sm whitespace-pre-wrap break-words">{ex.user}</div>
                </div>
                <div className="px-3 py-2">
                  <div className="inline-block px-1.5 py-0.5 rounded bg-muted text-[11px] text-muted-foreground mb-1">
                    {assistantLabel}
                  </div>
                  <div className="text-sm whitespace-pre-wrap break-words">{ex.assistant}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  } else {
    body = (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <label className="text-sm shrink-0">文风</label>
          <select
            value={profileId ?? ''}
            onChange={e => setProfileId(Number(e.target.value))}
            className="flex-1 max-w-sm px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            {profiles.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {needsCharacter && (
          <>
            <div className="flex items-center gap-3">
              <label className="text-sm shrink-0">原书角色</label>
              <select
                value={character}
                onChange={e => setCharacter(e.target.value)}
                className="flex-1 max-w-sm px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="">选择角色…</option>
                {characterOptions.map(c => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <p className="text-xs text-muted-foreground">
              学这个角色的说话方式，名字按下面的对照替换。只列出这个角色开口说过话的段落。
            </p>
          </>
        )}

        {needsCharacter && !character ? (
          <p className="text-sm text-muted-foreground">先选一个角色。</p>
        ) : candidateIndexes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {isNarration
              ? '这个文风的段落还没有玩家输入（旧版导入的）。重新导入这本书就会生成。'
              : '没有匹配的段落。'}
          </p>
        ) : (
          <>
            <div className="text-sm text-muted-foreground">
              已选 {selected.length} 段，{needsModel ? '每段会调用一次模型' : '直接取用，不调模型'}
            </div>
            <div className="space-y-3">
              {candidateIndexes.map(i => {
                const scene = scenes[i]
                const isOpen = expanded.includes(i)
                const tooLong = scene.text.length > PREVIEW_LEN
                return (
                  <div
                    key={i}
                    onClick={() => toggleScene(i)}
                    className="flex items-start gap-3 border rounded-lg p-3 cursor-pointer hover:bg-muted/50 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(i)}
                      onChange={() => {}}
                      className="mt-1 pointer-events-none"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="px-1.5 py-0.5 rounded bg-muted text-[11px]">
                          {scene.scene_type}
                        </span>
                        {scene.summary && (
                          <span className="text-sm font-medium">{scene.summary}</span>
                        )}
                        {scene.speakers.length > 0 && (
                          <span className="text-xs text-muted-foreground">
                            说话：{scene.speakers.join('、')}
                          </span>
                        )}
                      </div>
                      {isNarration && (
                        <div className="mt-1 text-xs text-muted-foreground">玩家：{scene.input}</div>
                      )}
                      <div className="mt-1 text-sm whitespace-pre-wrap break-words">
                        {isOpen || !tooLong ? scene.text : scene.text.slice(0, PREVIEW_LEN) + '…'}
                      </div>
                      {tooLong && (
                        <button
                          type="button"
                          onClick={e => {
                            e.stopPropagation()
                            toggleExpand(i)
                          }}
                          className="mt-1 text-xs text-primary hover:underline"
                        >
                          {isOpen ? '收起' : '展开'}
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}

        {involved.length > 0 && (
          <div className="space-y-2 border-t pt-4">
            <div className="text-sm">示例里的人名</div>
            <p className="text-xs text-muted-foreground">
              这些是导入时起的名字。对应到你这边的角色，示例里就换成真名；留空就保持原样。
            </p>
            {involved.map(name => (
              <div key={name} className="flex items-center gap-3">
                <span className="text-sm shrink-0 w-32 truncate">
                  {name}
                  {roleOf(name) && <span className="text-xs text-muted-foreground">（{roleOf(name)}）</span>}
                </span>
                <span className="text-xs text-muted-foreground">→</span>
                <input
                  list="style-name-options"
                  value={nameMap[name] || ''}
                  onChange={e => setNameEdits(prev => ({ ...prev, [name]: e.target.value }))}
                  placeholder="不换就留空"
                  className="flex-1 max-w-sm px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
              </div>
            ))}
            <datalist id="style-name-options">
              {(nameOptions || []).map(n => (
                <option key={n} value={n} />
              ))}
            </datalist>
          </div>
        )}

        {mode === 'novel' && (
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={withStyleDesc}
              onChange={e => setWithStyleDesc(e.target.checked)}
            />
            同时把文风说明填进 Writer 提示词
          </label>
        )}
      </div>
    )
  }

  let footer: ReactNode
  if (result) {
    footer = (
      <div className="flex items-start gap-2">
        <button
          type="button"
          onClick={() => setResult(null)}
          className="px-4 py-2 rounded-lg border hover:bg-muted transition-colors"
        >
          重新选
        </button>
        <div className="ml-auto text-right">
          <button
            type="button"
            onClick={handleApply}
            className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
          >
            填入
          </button>
          <div className="mt-1 text-[11px] text-muted-foreground">{footHint}</div>
        </div>
      </div>
    )
  } else {
    footer = (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onClose}
          className="px-4 py-2 rounded-lg border hover:bg-muted transition-colors"
        >
          取消
        </button>
        <button
          type="button"
          onClick={() => void handleConvert()}
          disabled={converting || !profile || selected.length === 0}
          className="ml-auto px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
        >
          {converting ? '转换中…' : needsModel ? '转换' : '预览'}
        </button>
      </div>
    )
  }

  // 挂到 body：游戏编辑面板里有 transform 容器，fixed 会被困住
  return createPortal(
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-card border rounded-xl shadow-lg w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div className="flex items-center gap-3 px-5 py-3 border-b shrink-0">
          <h3 className="font-semibold text-lg">{TITLES[mode]}</h3>
          {!isNarration && <StyleModelSelect value={model} onChange={setModel} />}
          <button
            onClick={onClose}
            className="ml-auto p-1 rounded-md hover:bg-muted transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-5">{body}</div>

        <div className="px-5 py-3 border-t shrink-0">{footer}</div>
      </div>
    </div>,
    document.body,
  )
}
