import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { Trash2, Upload, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import {
  DEFAULT_CATEGORIES,
  PRESET_CATEGORIES,
  styleProfilesApi,
  type StyleCharacter,
  type StyleProfile,
  type StyleProfilePreview,
  type StyleScene,
  type StyleStats,
} from '@/api/styleProfiles'
import StyleModelSelect, { useStyleModel } from './StyleModelSelect'

// 旧版导入是模型从固定几类里选的，老文风里还存着这些值
const LEGACY_SCENE_TYPES = ['描写', '心理', '过渡', '其他']
const MAX_CATEGORY_LEN = 20
const EXCERPTS_PER_CATEGORY = 5

interface Props {
  onClose: () => void
}

// 段落没有后端 id，列表 key 只能自己造；uid 是纯前端的东西，提交前必须剥掉
type EditScene = StyleScene & { uid: string }

let uidSeed = 0
const nextUid = () => `scene-${++uidSeed}`

const toEditScenes = (scenes: StyleScene[]): EditScene[] =>
  (scenes || []).map(s => ({ ...s, uid: nextUid() }))

const stripScenes = (scenes: EditScene[]): StyleScene[] =>
  scenes.map(({ summary, scene_type, text, speakers, input }) => ({ summary, scene_type, text, speakers, input }))

const errText = (err: any, fallback: string) => err?.response?.data?.detail || fallback

function SceneCard({
  scene,
  onChange,
  onRemove,
}: {
  scene: EditScene
  onChange: (patch: Partial<StyleScene>) => void
  onRemove: () => void
}) {
  // 说话人先存本地字符串：直接绑数组的话，刚敲下的逗号会被 join 抹掉，第二个名字就打不出来
  const [speakersText, setSpeakersText] = useState(scene.speakers.join(', '))
  // 带上当前值：自定义类别不在列表里，不带就显示成别的
  const typeOptions = [...new Set([...PRESET_CATEGORIES, ...LEGACY_SCENE_TYPES, scene.scene_type])]

  return (
    <div className="border rounded-lg p-3 space-y-2">
      <input
        type="text"
        value={scene.summary || ''}
        onChange={e => onChange({ summary: e.target.value })}
        placeholder="这段写的是什么场景"
        className="w-full px-2 py-1 text-sm font-medium border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
      />
      <div className="flex items-center gap-2">
        <select
          value={scene.scene_type}
          onChange={e => onChange({ scene_type: e.target.value })}
          className="px-2 py-1 text-xs border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          {typeOptions.map(t => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={speakersText}
          onChange={e => {
            setSpeakersText(e.target.value)
            onChange({
              speakers: e.target.value.split(/[,，]/).map(s => s.trim()).filter(Boolean),
            })
          }}
          placeholder="开口说话的人，逗号分隔"
          title="开口说话的人（酒馆/NPC 取用时按这里筛段落）"
          className="flex-1 min-w-0 px-2 py-1 text-xs border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
        />
        <button
          type="button"
          onClick={onRemove}
          title="删掉这一段"
          className="p-1 rounded-md hover:bg-muted transition-colors shrink-0"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>
      <input
        type="text"
        value={scene.input || ''}
        onChange={e => onChange({ input: e.target.value })}
        placeholder="玩家输入：主角在这段里做了什么、说了什么（游戏叙事示例用）"
        title="取到游戏里时，这句当玩家输入，下面的原文当 GM 的回复"
        className="w-full px-2 py-1 text-xs border rounded-md bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
      />
      <textarea
        value={scene.text}
        onChange={e => onChange({ text: e.target.value })}
        rows={4}
        className="w-full px-2 py-1.5 text-sm border rounded-lg bg-background resize-y focus:outline-none focus:ring-2 focus:ring-primary/50"
      />
    </div>
  )
}

export default function StyleLibraryModal({ onClose }: Props) {
  const [profiles, setProfiles] = useState<StyleProfile[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [isDraft, setIsDraft] = useState(false)
  const [name, setName] = useState('')
  const [styleDesc, setStyleDesc] = useState('')
  const [stats, setStats] = useState<StyleStats>({})
  const [characters, setCharacters] = useState<StyleCharacter[]>([])
  const [scenes, setScenes] = useState<EditScene[]>([])
  const [dirty, setDirty] = useState(false)
  const [importing, setImporting] = useState(false)
  const [saving, setSaving] = useState(false)
  // 选完文件先停在「选类别」这一步
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  // 勾选在弹窗里一直留着：连着导几本不用重勾
  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES)
  const [categoryInput, setCategoryInput] = useState('')
  const [importedCategories, setImportedCategories] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const [model, setModel] = useStyleModel()
  const customCategories = categories.filter(c => !PRESET_CATEGORIES.includes(c))

  const editing = isDraft || selectedId !== null

  useEffect(() => {
    let alive = true
    styleProfilesApi
      .list()
      .then(list => {
        if (alive) setProfiles(list)
      })
      .catch(err => toast.error(errText(err, '加载文风库失败')))
      .finally(() => {
        if (alive) setListLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  function applyData(data: {
    name: string
    style_desc: string
    stats?: StyleStats
    characters?: StyleCharacter[]
    scenes?: StyleScene[]
  }) {
    setName(data.name)
    setStyleDesc(data.style_desc)
    setStats(data.stats || {})
    setCharacters(data.characters || [])
    setScenes(toEditScenes(data.scenes || []))
  }

  function openProfile(p: StyleProfile) {
    setSelectedId(p.id)
    setIsDraft(false)
    applyData(p)
    setDirty(false)
    setImportedCategories([])
    setPendingFile(null)
  }

  function openDraft(preview: StyleProfilePreview) {
    setSelectedId(null)
    setIsDraft(true)
    applyData(preview)
    setDirty(false)
  }

  function clearEditing() {
    setSelectedId(null)
    setIsDraft(false)
    setName('')
    setStyleDesc('')
    setStats({})
    setCharacters([])
    setScenes([])
    setDirty(false)
    setImportedCategories([])
  }

  async function confirmDiscard(): Promise<boolean> {
    // 草稿本来就是没落库的东西，没动过也算「有内容会丢」
    if (!dirty && !isDraft) return true
    return confirmDialog({
      title: '还有没保存的内容',
      detail: '离开的话这些内容就没了。',
      confirmText: '丢弃',
      danger: true,
    })
  }

  async function handleClose() {
    if (!(await confirmDiscard())) return
    onClose()
  }

  async function handleSelect(p: StyleProfile) {
    if (!isDraft && p.id === selectedId) return
    if (!(await confirmDiscard())) return
    openProfile(p)
  }

  async function handleImportClick() {
    if (importing) return
    if (!(await confirmDiscard())) return
    fileRef.current?.click()
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // 清掉才能再选同一个文件
    if (file) setPendingFile(file)
  }

  function toggleCategory(name: string) {
    setCategories(prev => (prev.includes(name) ? prev.filter(c => c !== name) : [...prev, name]))
  }

  function addCategory() {
    const name = categoryInput.trim().slice(0, MAX_CATEGORY_LEN)
    setCategoryInput('')
    if (name && !categories.includes(name)) setCategories(prev => [...prev, name])
  }

  async function handleStartImport() {
    if (!pendingFile || importing || categories.length === 0) return
    const used = [...categories] // 跑的时候还能改勾选，先记下这次用的
    setImporting(true)
    try {
      const preview = await styleProfilesApi.importTxt(pendingFile, used, model)
      setPendingFile(null)
      openDraft(preview)
      setImportedCategories(used)
    } catch (err) {
      toast.error(errText(err, '导入失败，检查一下是不是小说正文'))
    } finally {
      setImporting(false)
    }
  }

  async function handleSave() {
    if (!name.trim() || saving) return
    setSaving(true)
    try {
      if (isDraft) {
        const created = await styleProfilesApi.create({
          name: name.trim(),
          style_desc: styleDesc,
          stats,
          characters,
          scenes: stripScenes(scenes),
        })
        setProfiles(prev => [created, ...prev])
        openProfile(created)
        toast.success('已存进文风库')
      } else if (selectedId !== null) {
        const updated = await styleProfilesApi.update(selectedId, {
          name: name.trim(),
          style_desc: styleDesc,
          characters,
          scenes: stripScenes(scenes),
        })
        // 刚改的排到最前，和后端按 updated_at 排序一致
        setProfiles(prev => [updated, ...prev.filter(p => p.id !== updated.id)])
        openProfile(updated)
        toast.success('已保存')
      }
    } catch (err) {
      toast.error(errText(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (selectedId === null) return
    const ok = await confirmDialog({
      title: '删掉这个文风？',
      detail: '已经填进小说/酒馆/游戏里的示例不受影响，但文风库里这份删了不能恢复。',
      confirmText: '删除',
      danger: true,
    })
    if (!ok) return
    try {
      await styleProfilesApi.delete(selectedId)
      setProfiles(prev => prev.filter(p => p.id !== selectedId))
      clearEditing()
      toast.success('已删除')
    } catch (err) {
      toast.error(errText(err, '删除失败'))
    }
  }

  function patchScene(uid: string, patch: Partial<StyleScene>) {
    setScenes(prev => prev.map(s => (s.uid === uid ? { ...s, ...patch } : s)))
    setDirty(true)
  }

  function removeScene(uid: string) {
    setScenes(prev => prev.filter(s => s.uid !== uid))
    setDirty(true)
  }

  function removeCharacter(index: number) {
    setCharacters(prev => prev.filter((_, i) => i !== index))
    setDirty(true)
  }

  const statParts: string[] = []
  if (stats.avg_sentence_len != null) statParts.push(`平均句长 ${stats.avg_sentence_len} 字`)
  if (stats.dialogue_ratio != null) statParts.push(`对话占比 ${Math.round(stats.dialogue_ratio * 100)}%`)
  if (stats.avg_para_len != null) statParts.push(`平均段长 ${stats.avg_para_len} 字`)
  if (stats.person) statParts.push(stats.person)
  const statsLine = statParts.join(' · ')

  // 某类没凑够就明说，免得以为是漏了
  const shortfallText = importedCategories
    .map(c => ({ name: c, count: scenes.filter(s => s.scene_type === c).length }))
    .filter(x => x.count < EXCERPTS_PER_CATEGORY)
    .map(x => (x.count === 0 ? `${x.name}：没找到` : `${x.name}：只找到 ${x.count} 段`))
    .join('；')

  return (
    <div className="fixed inset-0 z-50 bg-black/50">
      <div className="fixed inset-4 bg-card border rounded-xl shadow-lg flex flex-col">
        <div className="flex items-center gap-4 px-5 py-3 border-b shrink-0">
          <h3 className="font-semibold text-lg shrink-0">文风库</h3>
          <StyleModelSelect value={model} onChange={setModel} />
          <button
            onClick={() => void handleClose()}
            className="ml-auto p-1 rounded-md hover:bg-muted transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 flex min-h-0">
          <aside className="w-64 shrink-0 border-r flex flex-col min-h-0">
            <div className="p-3 border-b shrink-0">
              <button
                type="button"
                onClick={() => void handleImportClick()}
                disabled={importing}
                className="w-full px-3 py-2 rounded-lg border text-sm inline-flex items-center justify-center gap-1.5 hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Upload className="w-4 h-4" />
                导入 txt
              </button>
              {importing && (
                <p className="mt-2 text-xs text-muted-foreground leading-relaxed">
                  正在全书查找并摘取，可能要几分钟…
                </p>
              )}
              <input
                ref={fileRef}
                type="file"
                accept=".txt,text/plain"
                className="hidden"
                onChange={e => void handleFileChange(e)}
              />
            </div>

            <div className="flex-1 overflow-y-auto p-2">
              {listLoading ? (
                <p className="px-2 py-3 text-xs text-muted-foreground">加载中…</p>
              ) : profiles.length === 0 ? (
                <p className="px-2 py-3 text-xs text-muted-foreground">还没导入过任何 txt。</p>
              ) : (
                profiles.map(p => {
                  const active = !isDraft && selectedId === p.id
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => void handleSelect(p)}
                      className={`w-full text-left px-3 py-2 rounded-lg mb-1 transition-colors ${
                        active ? 'bg-muted' : 'hover:bg-muted'
                      }`}
                    >
                      <div className="text-sm font-medium truncate">{p.name}</div>
                      <div className="text-xs text-muted-foreground">{p.scenes?.length ?? 0} 段</div>
                    </button>
                  )
                })
              )}
            </div>
          </aside>

          <main className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto p-5">
              {pendingFile ? (
                <div className="max-w-xl space-y-5">
                  <div>
                    <h4 className="text-sm font-medium mb-1">选择要提取的内容</h4>
                    <p className="text-xs text-muted-foreground break-all">{pendingFile.name}</p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {PRESET_CATEGORIES.map(c => (
                      <label
                        key={c}
                        className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border text-sm cursor-pointer hover:bg-muted transition-colors"
                      >
                        <input
                          type="checkbox"
                          checked={categories.includes(c)}
                          onChange={() => toggleCategory(c)}
                        />
                        {c}
                      </label>
                    ))}
                    {customCategories.map(c => (
                      <span
                        key={c}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-primary/40 bg-primary/5 text-sm"
                      >
                        {c}
                        <button
                          type="button"
                          onClick={() => toggleCategory(c)}
                          title="删掉这一类"
                          className="p-0.5 rounded hover:bg-muted transition-colors"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={categoryInput}
                        maxLength={MAX_CATEGORY_LEN}
                        onChange={e => setCategoryInput(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            addCategory()
                          }
                        }}
                        placeholder="自己加一类"
                        className="flex-1 min-w-0 px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                      />
                      <button
                        type="button"
                        onClick={addCategory}
                        disabled={!categoryInput.trim()}
                        className="px-3 py-1.5 rounded-lg border text-sm hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        添加
                      </button>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      例如「吃饭场景」「初次见面」，写得越具体越准。
                    </p>
                  </div>

                  <p className="text-xs text-muted-foreground leading-relaxed">
                    每类约 {EXCERPTS_PER_CATEGORY} 段，只截相关的那几句原文。类别越多越慢。
                  </p>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setPendingFile(null)}
                      disabled={importing}
                      className="px-4 py-2 rounded-lg border text-sm hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      取消
                    </button>
                    <button
                      type="button"
                      onClick={() => fileRef.current?.click()}
                      disabled={importing}
                      className="px-4 py-2 rounded-lg border text-sm hover:bg-muted transition-colors disabled:opacity-50"
                    >
                      换文件
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleStartImport()}
                      disabled={categories.length === 0 || importing}
                      className="ml-auto px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {importing ? '提取中…' : '开始提取'}
                    </button>
                  </div>
                </div>
              ) : !editing ? (
                <div className="h-full flex items-center justify-center">
                  <p className="max-w-sm text-center text-sm text-muted-foreground leading-relaxed">
                    {profiles.length > 0
                      ? '从左边选一个文风查看或修改，或者再导入一本 txt。'
                      : '还没有文风。导入一本 txt，会自动抽几十段原文、写出文风说明，之后在小说、酒馆、游戏里都能取用。'}
                  </p>
                </div>
              ) : (
                <div className="space-y-5">
                  {isDraft && (
                    <div className="rounded-lg border border-primary/40 bg-primary/5 px-3 py-2 text-sm leading-relaxed">
                      这是预览，还没存进文风库。检查一下原书的人名地名有没有漏换，再点保存。
                    </div>
                  )}

                  <div>
                    <label className="block text-sm font-medium mb-1">名称</label>
                    <input
                      type="text"
                      value={name}
                      onChange={e => {
                        setName(e.target.value)
                        setDirty(true)
                      }}
                      className="w-full max-w-md px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>

                  {statsLine && <div className="text-sm text-muted-foreground">{statsLine}</div>}

                  <div>
                    <label className="block text-sm font-medium mb-1">文风说明</label>
                    <textarea
                      value={styleDesc}
                      onChange={e => {
                        setStyleDesc(e.target.value)
                        setDirty(true)
                      }}
                      rows={5}
                      placeholder="这本书的文风特点…"
                      className="w-full px-3 py-2 text-sm border rounded-lg bg-background resize-y focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>

                  <div>
                    <div className="text-sm font-medium mb-2">原书角色</div>
                    {characters.length === 0 ? (
                      <p className="text-xs text-muted-foreground">没有识别到角色。</p>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {characters.map((c, i) => (
                          <span
                            key={`${c.name}-${i}`}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md border text-xs"
                          >
                            {c.name}
                            {c.role ? ` · ${c.role}` : ''}
                            <button
                              type="button"
                              onClick={() => removeCharacter(i)}
                              title="删掉这个角色"
                              className="p-0.5 rounded hover:bg-muted transition-colors"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="text-sm font-medium mb-2">候选段落（{scenes.length} 段）</div>
                    {shortfallText && (
                      <p className="mb-2 text-xs text-amber-600 leading-relaxed">{shortfallText}</p>
                    )}
                    <div className="space-y-3">
                      {scenes.map(s => (
                        <SceneCard
                          key={s.uid}
                          scene={s}
                          onChange={patch => patchScene(s.uid, patch)}
                          onRemove={() => removeScene(s.uid)}
                        />
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>

            {editing && !pendingFile && (
              <div className="flex items-center gap-2 px-5 py-3 border-t shrink-0">
                {isDraft ? (
                  <>
                    <button
                      type="button"
                      onClick={clearEditing}
                      className="px-4 py-2 rounded-lg border hover:bg-muted transition-colors"
                    >
                      放弃
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSave()}
                      disabled={!name.trim() || saving}
                      className="ml-auto px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
                    >
                      保存到文风库
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void handleDelete()}
                      className="px-4 py-2 rounded-lg border hover:bg-muted transition-colors"
                    >
                      删除
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSave()}
                      disabled={!name.trim() || saving}
                      className="ml-auto px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
                    >
                      保存修改
                    </button>
                  </>
                )}
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  )
}
