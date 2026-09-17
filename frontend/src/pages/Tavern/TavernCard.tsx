import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Loader2, Plus, Trash2, Beer, BookMarked, Play, X,
  UserRound, Clapperboard, Settings2, ChevronDown, ImagePlus, ScrollText,
  MessagesSquare, Pin, BookmarkPlus, Eraser, Check, Sparkles,
} from 'lucide-react'
import {
  tavernApi, modelLibraryApi, modelSelectValue, type ModelEntry, type TavernAssistField, type TavernCard as Card, type TavernWorldEntry,
} from '@/api/client'
import AutoTextarea from '@/components/AutoTextarea'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import ExampleTurnsEditor from '@/components/ExampleTurnsEditor'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import CardAvatar from './CardAvatar'
import CardMultiSelect from './CardMultiSelect'
import TavernParamFields from './TavernParams'

type FieldKey = 'name' | 'creator_note' | 'personality' | 'opening_scene' | 'system_instruction' | 'description'

interface FieldDef {
  key: FieldKey
  label: string
  required?: boolean
  multiline?: boolean
  placeholder: string
  hint: string
  /** 挂 AI 辅助按钮。creator_note 只能生成，其余空则生成、有内容则优化 */
  assist?: TavernAssistField
}

// 六个字段按"这是谁 / 故事从哪开始 / 怎么演"分三组，比竖着排六个框好找
const SECTIONS: Array<{
  id: string
  title: string
  desc: string
  icon: typeof UserRound
  fields: FieldDef[]
}> = [
  {
    id: 'who',
    title: '这是谁',
    desc: '角色的身份与性格，AI 靠这部分保持前后一致。',
    icon: UserRound,
    fields: [
      {
        key: 'name', label: '角色名字', required: true,
        placeholder: '例：林越',
        hint: '其他文本里可以用 {{char}} 指代这个名字，用 {{user}} 指代玩家。',
      },
      {
        key: 'personality', label: '角色性格', multiline: true, assist: 'personality',
        placeholder: '基本特质、情感表现、人际关系、价值观、行为模式、优点和缺点、成长潜力……',
        hint: '复杂而有矛盾的性格往往更有深度和真实感，尽量避免完美无缺或过于单一的描述。',
      },
    ],
  },
  {
    id: 'scene',
    title: '故事从哪开始',
    desc: '开新故事线时，这段会作为角色的第一句话。',
    icon: Clapperboard,
    fields: [
      {
        key: 'opening_scene', label: '开场环境', multiline: true, assist: 'opening_scene',
        placeholder: '物理环境、氛围、时间、在场的其他人、角色所处位置、与玩家的情感联系……',
        hint: '场景应与背景故事和后续对话保持一致。',
      },
    ],
  },
  {
    id: 'meta',
    title: '你自己的备注',
    desc: '只给你看的一栏，方便在列表里认卡。',
    icon: ScrollText,
    fields: [
      {
        key: 'creator_note', label: '角色卡介绍', multiline: true, assist: 'creator_note',
        placeholder: '这张卡是干什么的、灵感来源、你自己的备注……',
        hint: 'AI 不会看到这段内容，只在列表页给你自己认卡用。',
      },
    ],
  },
]

const ADVANCED_FIELD: FieldDef = {
  key: 'system_instruction', label: '系统指令', multiline: true,
  placeholder: '语言风格、知识范围、行为模式、情感表达、互动规则、特殊能力或限制、角色立场……',
  hint: '要清晰、具体，避免过于笼统。这段紧跟在内置的扮演底稿之后，写在这里的要求可以覆盖它。'
    + '「保持角色、不跳出设定、不替玩家发言」底稿已经写了，不用重复。',
}

const EMPTY: Partial<Card> & { name: string } = {
  name: '', creator_note: '', personality: '', opening_scene: '',
  system_instruction: '', description: '', dialogue_examples: [],
  enabled_rule_ids: [], avatar_url: '', linked_book_card_ids: [],
  context_turns: 20, temperature: 0.9, max_tokens: 2048, reply_length: 0,
  scan_depth: 3,
  summary_model_ref: '',
  profile_sections: { appearance: '', background: '', abilities: '', relationships: '' },
}

export default function TavernCard() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const isNew = !id || id === 'new'
  const cardId = isNew ? 0 : Number(id)

  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)

  const { data: card } = useQuery({
    queryKey: ['tavern-card', cardId],
    queryFn: () => tavernApi.cards.get(cardId),
    enabled: !isNew,
  })

  useEffect(() => {
    if (card) setForm(card)
  }, [card])

  const set = <K extends keyof Card>(key: K, value: Card[K]) =>
    setForm(prev => ({ ...prev, [key]: value }))

  const handleSave = async () => {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      if (isNew) {
        const created = await tavernApi.cards.create({ ...form, name: form.name.trim() })
        qc.invalidateQueries({ queryKey: ['tavern-cards'] })
        // 用户的预期是"创建角色后才有世界书"，所以建完就跳到详情态
        navigate(`/tavern/card/${created.id}`, { replace: true })
      } else {
        await tavernApi.cards.update(cardId, { ...form, name: form.name.trim() })
        qc.invalidateQueries({ queryKey: ['tavern-card', cardId] })
        qc.invalidateQueries({ queryKey: ['tavern-cards'] })
        toast.success('已保存')
      }
    } catch {
      toast.error('保存角色卡失败')
    } finally { setSaving(false) }
  }

  return (
    <div className="mode-tavern min-h-screen bg-background relative">
      <header className="sticky top-0 z-20 border-b border-border/50 bg-background/80 backdrop-blur-md px-6 py-3.5 flex items-center gap-3">
        <button onClick={() => navigate('/tavern')} className="p-2 rounded-md hover:bg-muted" title="返回角色卡列表">
          <ArrowLeft className="w-4 h-4" />
        </button>
        <Beer className="w-5 h-5 text-pink-500" />
        <h1 className="font-bold text-lg truncate">{isNew ? '捏一个新角色' : form.name || '角色卡'}</h1>
        <div className="ml-auto flex items-center gap-3">
          <ThemePicker />
          <button
            onClick={handleSave}
            disabled={!form.name.trim() || saving}
            className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5 transition-colors
              bg-primary text-primary-foreground hover:opacity-90
              disabled:opacity-40"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {isNew ? '创建' : '保存'}
          </button>
        </div>
      </header>

      <main className="relative z-10 max-w-[1440px] mx-auto px-8 py-12 space-y-8">
        <IdentityHeader
          name={form.name}
          avatarUrl={form.avatar_url || ''}
          cardId={cardId}
          isNew={isNew}
          onAvatarChange={url => set('avatar_url', url)}
        />

        {/* 宽屏分两栏：左边是"这个人是谁"，右边是参数与数据。
            窄屏（<1280px）自动落回单列，顺序和以前一样 */}
        <div className="grid gap-8 xl:grid-cols-2 items-start">
          <div className="space-y-8">
            {SECTIONS.slice(0, 1).map(section => (
              <Section key={section.id} title={section.title} desc={section.desc} icon={section.icon}>
                <div className="space-y-5">
                  {section.fields.map(f => (
                    <FieldInput key={f.key} field={f} form={form} set={set} />
                  ))}
                </div>
              </Section>
            ))}

            <Section title="角色详细设定" desc="分别填写后，AI 会按板块注入提示词，更容易保持设定清晰。" icon={ScrollText}>
              <ProfileSections form={form} set={set} />
            </Section>

            {SECTIONS.slice(1).map(section => (
              <Section key={section.id} title={section.title} desc={section.desc} icon={section.icon}>
                <div className="space-y-5">
                  {section.fields.map(f => (
                    <FieldInput key={f.key} field={f} form={form} set={set} />
                  ))}
                </div>
              </Section>
            ))}

            <Section
              title="他怎么说话"
              desc="给两三组问答样例，角色的腔调会立刻贴上去。"
              icon={MessagesSquare}
            >
              <ExampleTurnsEditor
                variant="dialogue"
                value={form.dialogue_examples || []}
                onChange={v => set('dialogue_examples', v)}
              />
            </Section>
          </div>

          <div className="space-y-8">
            <Collapsible title="进阶：系统指令与生成参数" icon={Settings2}>
              <div className="space-y-6">
                <div>
                  <FieldInput field={ADVANCED_FIELD} form={form} set={set} />
                  <InstructionPresets
                    current={form.system_instruction || ''}
                    onPick={async text => {
                      const existing = (form.system_instruction || '').trim()
                      // 空文本 = 取消/清空，那本来就是明确的意图，不要再问一遍
                      if (text.trim() && existing && existing !== text.trim()
                          && !await confirmDialog({
                            title: '覆盖已经写好的系统指令？',
                            detail: '上面输入框里的内容会被这条常用指令替换掉。',
                            confirmText: '覆盖',
                          })) return
                      set('system_instruction', text)
                    }}
                  />
                </div>
                <GenerationSettings form={form} set={set} />
                <RulesSection
                  selected={form.enabled_rule_ids || []}
                  onChange={ids => set('enabled_rule_ids', ids)}
                />
              </div>
            </Collapsible>

            {isNew ? (
              <p className="text-xs text-muted-foreground border-t pt-6">
                创建角色卡之后，这里会出现世界书和故事线。
              </p>
            ) : (
              <>
                <WorldBookSection
                  cardId={cardId}
                  scanDepth={form.scan_depth ?? 3}
                  onScanDepthChange={v => set('scan_depth', v)}
                  linkedIds={form.linked_book_card_ids || []}
                  onLinkedChange={ids => set('linked_book_card_ids', ids)}
                />
                <SessionsSection cardId={cardId} />
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

// ── 通用外壳 ────────────────────────────────────────────────────────────────

function Section({
  title, desc, icon: Icon, children,
}: {
  title: string
  desc?: string
  icon: typeof UserRound
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl border bg-card/50 backdrop-blur-sm p-6">
      <div className="flex items-start gap-3 mb-5">
        <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0">
          <Icon className="w-4 h-4" />
        </div>
        <div>
          <h2 className="font-semibold text-sm">{title}</h2>
          {desc && <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>}
        </div>
      </div>
      {children}
    </section>
  )
}

function Collapsible({
  title, icon: Icon, children,
}: {
  title: string
  icon: typeof UserRound
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-xl border bg-card/50 backdrop-blur-sm">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full px-6 py-4 flex items-center gap-3 text-left"
      >
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

function FieldInput({
  field, form, set,
}: {
  field: FieldDef
  form: Partial<Card> & { name: string }
  set: <K extends keyof Card>(key: K, value: Card[K]) => void
}) {
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const current = (form[field.key] as string) || ''
  // creator_note 是按性格+描述推导出来的，没有"优化原文"的语义
  const isGenerate = field.assist === 'creator_note' || !current.trim()

  const runAssist = async () => {
    if (!field.assist) return
    setBusy(true)
    try {
      const { text } = await tavernApi.cards.assist({
        field: field.assist,
        name: form.name,
        personality: form.personality || '',
        description: form.description || '',
        profile_sections: form.profile_sections || {},
        opening_scene: form.opening_scene || '',
      })
      if (!text.trim()) {
        toast.error('AI 没返回内容，再试一次')
        return
      }
      setDraft(text)
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || (isGenerate ? 'AI 生成失败' : 'AI 优化失败'))
    } finally { setBusy(false) }
  }

  return (
    <div>
      <label className="text-sm font-medium mb-2 flex items-center gap-2">
        <span>
          {field.label}
          {field.required
            ? <span className="text-pink-500 ml-1">*</span>
            : <span className="text-muted-foreground font-normal text-xs ml-1">（选填）</span>}
        </span>
        {field.assist && (
          <button
            type="button"
            onClick={runAssist}
            disabled={busy}
            className="ml-auto flex items-center gap-1 text-xs font-normal px-2 py-1 rounded-md
              text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
          >
            {busy
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Sparkles className="w-3 h-3" />}
            {isGenerate ? 'AI 生成' : 'AI 优化'}
          </button>
        )}
      </label>
      {field.multiline ? (
        <textarea
          value={(form[field.key] as string) || ''}
          onChange={e => set(field.key, e.target.value)}
          placeholder={field.placeholder}
          className="w-full border rounded-lg px-4 py-3 text-sm bg-background/60 resize-y min-h-[12rem]
            focus:outline-none focus:ring-1 focus:ring-pink-500/50 leading-relaxed"
        />
      ) : (
        <input
          value={(form[field.key] as string) || ''}
          onChange={e => set(field.key, e.target.value)}
          placeholder={field.placeholder}
          className="w-full border rounded-lg px-4 py-2.5 text-sm bg-background/60
            focus:outline-none focus:ring-1 focus:ring-pink-500/50"
        />
      )}
      {draft !== null && (
        <AssistDraft
          original={current}
          draft={draft}
          onDiscard={() => setDraft(null)}
          onApply={text => { set(field.key, text as Card[FieldKey]); setDraft(null) }}
          onRetry={runAssist}
          retrying={busy}
        />
      )}
      <p className="text-xs text-muted-foreground mt-1.5">{field.hint}</p>
    </div>
  )
}

function ProfileSections({ form, set }: { form: Partial<Card> & { name: string }; set: <K extends keyof Card>(key: K, value: Card[K]) => void }) {
  const sections = [
    ['appearance', '外貌身材', '身高体型、五官、发色、服饰、气质、身体特征……'],
    ['background', '背景故事', '出身、成长经历、重要事件、当前身份、人生转折……'],
    ['abilities', '能力特长', '战斗、职业、知识、特殊能力、弱点和限制……'],
    ['relationships', '关系网络', '与其他角色的关系、矛盾、依赖、秘密和当前状态……'],
  ] as const
  const values = form.profile_sections || {}
  return <div className="grid gap-7">{sections.map(([key, label, placeholder]) => (
    <div key={key}>
      <label className="text-sm font-medium mb-2 block">{label}</label>
      <textarea
        value={values[key] || ''}
        onChange={event => set('profile_sections', { ...values, [key]: event.target.value })}
        placeholder={placeholder}
        className="w-full border rounded-lg px-4 py-4 text-sm bg-background/60 resize-y min-h-[18rem] focus:outline-none focus:ring-1 focus:ring-pink-500/50 leading-relaxed"
      />
    </div>
  ))}</div>
}

/** AI 结果就地展开在输入框下面，确认后才替换原文。
 *
 * 不用浮层：这是"对着原文挑一段"的活，盖住原文反而碍事，
 * 而且每个栏位一个浮层会互相压住页面上别的东西。
 */
function AssistDraft({
  original, draft, onDiscard, onApply, onRetry, retrying,
}: {
  original: string
  draft: string
  onDiscard: () => void
  onApply: (text: string) => void
  onRetry: () => void
  retrying: boolean
}) {
  const [text, setText] = useState(draft)

  // 重新生成后不收起，把新结果换进来
  useEffect(() => { setText(draft) }, [draft])

  return (
    <div className="mt-2 rounded-lg border border-pink-500/30 bg-pink-500/[0.04] overflow-hidden">
      <div className="px-3 py-2 flex items-center gap-1.5 border-b border-pink-500/20">
        <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="text-xs font-medium text-primary">AI 写的版本</span>
        <span className="text-xs text-muted-foreground">
          {original.trim() ? '确认后替换上面的内容' : '确认后填进上面的输入框'}
        </span>
        <button
          onClick={onDiscard}
          className="ml-auto p-1 rounded-md hover:bg-pink-500/10 text-muted-foreground"
          title="丢弃这版"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="p-3">
        <AutoTextarea
          value={text}
          onChange={e => setText(e.target.value)}
          className="w-full border rounded-lg px-3 py-2.5 text-sm bg-background/60 leading-relaxed
            focus:outline-none focus:ring-1 focus:ring-pink-500/50"
          minRows={5}
        />
        <div className="mt-2 flex gap-2 justify-end">
          <button
            onClick={onRetry}
            disabled={retrying}
            className="text-xs px-2.5 py-1.5 rounded-md text-muted-foreground hover:bg-muted
              transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {retrying && <Loader2 className="w-3 h-3 animate-spin" />}
            重新生成
          </button>
          <button
            onClick={() => onApply(text)}
            disabled={!text.trim()}
            className="text-xs px-3 py-1.5 rounded-md transition-colors
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {original.trim() ? '替换原文' : '用这段'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 顶部身份区（头像 + 名字预览）──────────────────────────────────────────

function IdentityHeader({
  name, avatarUrl, cardId, isNew, onAvatarChange,
}: {
  name: string
  avatarUrl: string
  cardId: number
  isNew: boolean
  onAvatarChange: (url: string) => void
}) {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const pick = async (file: File | undefined) => {
    if (!file) return
    setUploading(true)
    try {
      const updated = await tavernApi.cards.uploadAvatar(cardId, file)
      onAvatarChange(updated.avatar_url)
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
    } catch {
      toast.error('上传头像失败')
    } finally { setUploading(false) }
  }

  const remove = async () => {
    try {
      await tavernApi.cards.deleteAvatar(cardId)
      onAvatarChange('')
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
    } catch {
      toast.error('删除头像失败')
    }
  }

  return (
    <div className="rounded-xl border bg-card/50 backdrop-blur-sm p-6 flex items-center gap-5">
      <div className="relative shrink-0">
        <CardAvatar name={name || '?'} url={avatarUrl} size="lg" />
        {uploading && (
          <div className="absolute inset-0 rounded-xl bg-black/50 flex items-center justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-white" />
          </div>
        )}
      </div>
      <div className="min-w-0">
        <p className="text-xl font-bold truncate">{name || '还没起名字'}</p>
        {isNew ? (
          <p className="text-xs text-muted-foreground mt-1.5">创建之后可以上传头像。</p>
        ) : (
          <div className="flex items-center gap-3 mt-2">
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif"
              className="hidden"
              onChange={e => { pick(e.target.files?.[0]); e.target.value = '' }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border hover:bg-muted disabled:opacity-50"
            >
              <ImagePlus className="w-3.5 h-3.5" /> {avatarUrl ? '换头像' : '上传头像'}
            </button>
            {avatarUrl && (
              <button onClick={remove} className="text-xs text-muted-foreground hover:text-foreground">
                移除
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── 生成参数 / 规则 ────────────────────────────────────────────────────────

function GenerationSettings({
  form, set,
}: {
  form: Partial<Card> & { name: string }
  set: <K extends keyof Card>(key: K, value: Card[K]) => void
}) {
  return (
    <div>
      <h3 className="text-sm font-medium mb-3">生成参数</h3>
      <TavernParamFields
        value={form}
        onChange={patch => {
          for (const [k, v] of Object.entries(patch)) set(k as keyof Card, v as never)
        }}
      />
      <SummaryModelSelect form={form} set={set} />
      <p className="text-xs text-muted-foreground mt-3">对话页右上角也能随时调这几项，改完立即生效。</p>
    </div>
  )
}

function SummaryModelSelect({ form, set }: { form: Partial<Card> & { name: string }; set: <K extends keyof Card>(key: K, value: Card[K]) => void }) {
  const { data: models = [] } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  return <div className="mt-5">
    <label className="text-xs font-medium mb-1 block">上下文总结模型</label>
    <select value={modelSelectValue(models, form.summary_model_ref || '')} onChange={event => set('summary_model_ref', event.target.value)} className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60">
      <option value="">跟随对话模型（默认）</option>
      {models.filter((model: ModelEntry) => model.model_type !== 'embedding').map((model: ModelEntry) => <option key={model.id} value={String(model.id)}>{model.display_name || model.model_id}</option>)}
    </select>
    <p className="text-xs text-muted-foreground mt-1.5">上下文超过保留轮数时，用这个模型压缩早期对话；留空则使用当前对话模型。</p>
  </div>
}

/** 常用系统指令：存起来给别的卡复用。存的是当下输入框里的文本，之后各卡独立不联动 */
function InstructionPresets({
  current, onPick,
}: {
  current: string
  onPick: (text: string) => void
}) {
  const qc = useQueryClient()
  const { data: presets = [] } = useQuery({
    queryKey: ['tavern-instruction-presets'],
    queryFn: tavernApi.instructionPresets.list,
  })
  const [naming, setNaming] = useState(false)
  const [name, setName] = useState('')

  const refresh = () => qc.invalidateQueries({ queryKey: ['tavern-instruction-presets'] })

  const save = async () => {
    const trimmed = name.trim()
    if (!trimmed || !current.trim()) return
    try {
      await tavernApi.instructionPresets.create({ name: trimmed, content: current.trim() })
      refresh()
      setName('')
      setNaming(false)
      toast.success('已存为常用指令')
    } catch {
      toast.error('保存常用指令失败')
    }
  }

  return (
    <div className="mt-3 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground mr-1">常用指令</span>
        {presets.map(p => {
          const active = p.content.trim() === current.trim() && !!current.trim()
          return (
          <button
            key={p.id}
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
            onClick={() => onPick('')}
            title="清空上面的系统指令输入框（不影响已存的常用指令）"
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border
              text-muted-foreground hover:bg-muted"
          >
            <Eraser className="w-3 h-3" /> 清空
          </button>
        )}
        {!naming && (
          <button
            onClick={() => setNaming(true)}
            disabled={!current.trim()}
            title={current.trim() ? '把上面这段存起来' : '先写点内容再存'}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-dashed
              border-pink-500/30 text-muted-foreground hover:bg-pink-500/5 disabled:opacity-40"
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
            placeholder="给这段指令起个名字，如：市井口吻"
            autoFocus
            className="flex-1 border rounded-lg px-3 py-1.5 text-xs bg-background/60
              focus:outline-none focus:ring-1 focus:ring-pink-500/50"
          />
          <button
            onClick={save}
            disabled={!name.trim()}
            className="text-xs px-3 py-1.5 rounded-lg bg-primary text-primary-foreground
              hover:opacity-90 disabled:opacity-40"
          >
            保存
          </button>
          <button
            onClick={() => { setNaming(false); setName('') }}
            className="text-xs px-3 py-1.5 border rounded-lg hover:bg-muted"
          >
            取消
          </button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        点一条填进上面的输入框，再点亮着的那条就取消。存的是当时的文本副本，之后改这张卡不会影响其他卡。
        <Link to="/tavern/settings" className="text-pink-500 hover:underline ml-1">去酒馆设定改名或删除</Link>
      </p>
    </div>
  )
}

function RulesSection({
  selected, onChange,
}: {
  selected: number[]
  onChange: (ids: number[]) => void
}) {
  const { data: rules = [] } = useQuery({
    queryKey: ['tavern-rules'],
    queryFn: tavernApi.rules.list,
  })

  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])

  return (
    <div>
      <h3 className="text-sm font-medium mb-1">写作规则</h3>
      <p className="text-xs text-muted-foreground mb-3">
        默认不启用。勾上的规则会原样拼进这张卡的系统提示词。
        <Link to="/tavern/settings" className="text-pink-500 hover:underline ml-1">去酒馆设定管理</Link>
      </p>
      {rules.length === 0 ? (
        <p className="text-xs text-muted-foreground">还没有酒馆规则，先去酒馆设定里写一条。</p>
      ) : (
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
                className="mt-0.5 accent-pink-500"
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
      )}
    </div>
  )
}

// ── 世界书 ────────────────────────────────────────────────────────────────

interface EntryForm {
  keywords: string
  content: string
  constant: boolean
  depth: number
}

const EMPTY_ENTRY: EntryForm = { keywords: '', content: '', constant: false, depth: 0 }

function WorldBookSection({
  cardId, scanDepth, onScanDepthChange, linkedIds, onLinkedChange,
}: {
  cardId: number
  scanDepth: number
  onScanDepthChange: (v: number) => void
  linkedIds: number[]
  onLinkedChange: (ids: number[]) => void
}) {
  const qc = useQueryClient()
  const { data: entries = [] } = useQuery({
    queryKey: ['tavern-world-book', cardId],
    queryFn: () => tavernApi.worldEntries.list(cardId),
  })

  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<EntryForm>(EMPTY_ENTRY)

  const refresh = () => qc.invalidateQueries({ queryKey: ['tavern-world-book', cardId] })

  const reset = () => {
    setForm(EMPTY_ENTRY)
    setEditingId(null)
    setShowForm(false)
  }

  const startEdit = (entry: TavernWorldEntry) => {
    setEditingId(entry.id)
    setForm({
      keywords: entry.keywords, content: entry.content,
      constant: entry.constant, depth: entry.depth,
    })
    setShowForm(true)
  }

  const submit = async () => {
    // 常驻词条每轮都注入，不需要关键词
    if ((!form.constant && !form.keywords.trim()) || !form.content.trim()) return
    try {
      if (editingId) {
        await tavernApi.worldEntries.update(editingId, form)
      } else {
        await tavernApi.worldEntries.create(cardId, { ...form, sort_order: entries.length + 1 })
      }
      refresh()
      reset()
    } catch {
      toast.error('保存词条失败')
    }
  }

  const toggle = async (entry: TavernWorldEntry) => {
    try {
      await tavernApi.worldEntries.update(entry.id, { enabled: !entry.enabled })
      refresh()
    } catch {
      toast.error('切换词条状态失败')
    }
  }

  const remove = async (entry: TavernWorldEntry) => {
    if (!await confirmDialog({
      title: '确认删除这条世界书词条？',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.worldEntries.delete(entry.id)
      refresh()
    } catch {
      toast.error('删除词条失败')
    }
  }

  return (
    <Section
      title="世界书"
      desc="对话中出现关键词时，词条内容会注入这一轮上下文；不命中就不占 token。也可以设成常驻，或指定插入位置。"
      icon={BookMarked}
    >
      <div className="mb-4 pb-4 border-b flex items-center gap-2 flex-wrap">
        <label className="text-xs font-medium">关键词扫描范围</label>
        <input
          type="number" min={1} max={20}
          value={scanDepth}
          onChange={e => onScanDepthChange(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
          className="w-16 border rounded-lg px-2 py-1 text-sm bg-background/60
            focus:outline-none focus:ring-1 focus:ring-pink-500/50"
        />
        <span className="text-xs text-muted-foreground">
          条消息
          {scanDepth <= 1
            ? '：只看你刚发的这句'
            : `：你这句 + 往回 ${scanDepth - 1} 条`}
        </span>
        <p className="text-xs text-muted-foreground w-full">
          调大了角色自己的回复也会参与匹配，同一条词条容易连着触发好几轮。
          想让某条设定一直在，用「常驻」比调大这个稳。
        </p>
      </div>

      <div className="mb-4 pb-4 border-b">
        <p className="text-xs font-medium mb-1">也使用这些角色的世界书</p>
        <p className="text-xs text-muted-foreground mb-2.5">
          勾上之后，这张卡对话时会连着那些卡的词条一起匹配。
          共用一套设定时，把词条都写在其中一张卡上，其他卡勾过来就行，不用复制几份。
        </p>
        <CardMultiSelect
          selected={linkedIds}
          onChange={onLinkedChange}
          excludeId={cardId}
          empty="只有这一张角色卡，没有别人的世界书可以引用。"
        />
      </div>

      <div className="space-y-2">
        {entries.map(entry => (
          <div key={entry.id} className={`border rounded-lg px-3 py-2 ${entry.enabled ? '' : 'opacity-60'}`}>
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  {entry.constant && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 flex items-center gap-1">
                      <Pin className="w-2.5 h-2.5" /> 常驻
                    </span>
                  )}
                  {entry.keywords
                    // 分隔符必须与后端 tavern_context._KEYWORD_SEP 一致，
                    // 否则这里显示成两个词、实际却当成一个来匹配
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
                <p className="text-xs text-muted-foreground mt-1.5 whitespace-pre-wrap line-clamp-3">
                  {entry.content}
                </p>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button onClick={() => toggle(entry)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                  {entry.enabled ? '停用' : '启用'}
                </button>
                <button onClick={() => startEdit(entry)} className="text-xs px-2 py-1 rounded border hover:bg-muted">
                  编辑
                </button>
                <button
                  onClick={() => remove(entry)}
                  className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
                  title="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
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
            <div>
              <input
                value={form.keywords}
                onChange={e => setForm({ ...form, keywords: e.target.value })}
                disabled={form.constant}
                placeholder={form.constant ? '常驻词条不看关键词' : '关键词（逗号或顿号分隔，如：黑塔，旧盟约）'}
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50 disabled:opacity-50"
              />
            </div>
            <textarea
              value={form.content}
              onChange={e => setForm({ ...form, content: e.target.value })}
              placeholder="要注入的设定内容"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 resize-y min-h-[6rem] focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />

            <label className="flex items-start gap-2.5 cursor-pointer">
              <input
                type="checkbox"
                checked={form.constant}
                onChange={e => setForm({ ...form, constant: e.target.checked })}
                className="mt-0.5 accent-pink-500"
              />
              <div>
                <span className="text-sm">常驻</span>
                <p className="text-xs text-muted-foreground mt-0.5">
                  不看关键词，每轮都注入。适合放世界观底色这类必须一直在的设定，代价是一直占 token。
                </p>
              </div>
            </label>

            <div>
              <label className="text-xs font-medium mb-1 block">插入深度</label>
              <input
                type="number" min={0} max={20}
                value={form.depth}
                onChange={e => setForm({ ...form, depth: Math.max(0, Number(e.target.value) || 0) })}
                className="w-24 border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                0 = 放在系统提示词里。填 1 会贴在你这一条发言前面，2 是再往前一条，以此类推。
                离当前对话越近模型越不会忽略，适合放「别忘了你是谁」这种提醒。
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
          <button
            onClick={() => setShowForm(true)}
            className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
              border-pink-500/30 rounded-lg text-muted-foreground hover:bg-pink-500/5"
          >
            <Plus className="w-3.5 h-3.5" /> 添加词条
          </button>
        )}
      </div>
    </Section>
  )
}

// ── 故事线 ────────────────────────────────────────────────────────────────

function SessionsSection({ cardId }: { cardId: number }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { data: sessions = [] } = useQuery({
    queryKey: ['tavern-sessions', cardId],
    queryFn: () => tavernApi.sessions.list(cardId),
  })

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState('')
  const [personaName, setPersonaName] = useState('')
  const [personaDesc, setPersonaDesc] = useState('')
  const [creating, setCreating] = useState(false)

  const create = async () => {
    setCreating(true)
    try {
      const sess = await tavernApi.sessions.create(cardId, {
        title: title.trim(), persona_name: personaName.trim(), persona_desc: personaDesc.trim(),
      })
      qc.invalidateQueries({ queryKey: ['tavern-sessions', cardId] })
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
      navigate(`/tavern/chat/${sess.id}`)
    } catch {
      toast.error('创建故事线失败')
    } finally { setCreating(false) }
  }

  const remove = async (id: number) => {
    if (!await confirmDialog({
      title: '确认删除这条故事线？',
      detail: '全部对话记录会一起删掉，不可恢复。角色卡本身保留。',
      confirmText: '删除',
      danger: true,
    })) return
    try {
      await tavernApi.sessions.delete(id)
      qc.invalidateQueries({ queryKey: ['tavern-sessions', cardId] })
      qc.invalidateQueries({ queryKey: ['tavern-cards'] })
    } catch {
      toast.error('删除故事线失败')
    }
  }

  return (
    <Section
      title="故事线"
      desc="同一张卡可以开多条故事线，各自独立的对话记录和玩家身份。"
      icon={Play}
    >
      <div className="space-y-2">
        {sessions.map(sess => (
          <div key={sess.id} className="border rounded-lg px-3 py-2.5 flex items-center gap-3 hover:border-pink-500/40 transition-colors">
            <div className="flex-1 min-w-0">
              <p className="text-sm truncate">
                {sess.title || new Date(sess.created_at).toLocaleString()}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {sess.message_count} 条消息
                {sess.persona_name && ` · 玩家：${sess.persona_name}`}
                {sess.summary && ' · 已生成剧情梗概'}
              </p>
            </div>
            <button
              onClick={() => navigate(`/tavern/chat/${sess.id}`)}
              className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg shrink-0
                bg-primary text-primary-foreground hover:opacity-90"
            >
              <Play className="w-3 h-3" /> 继续
            </button>
            <button
              onClick={() => remove(sess.id)}
              className="p-1.5 rounded hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30 shrink-0"
              title="删除"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        {showForm ? (
          <div className="border rounded-lg p-3 bg-muted/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">新故事线</span>
              <button onClick={() => setShowForm(false)} className="p-1 rounded hover:bg-muted">
                <X className="w-4 h-4" />
              </button>
            </div>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="故事线名称（选填）"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
            <div>
              <input
                value={personaName}
                onChange={e => setPersonaName(e.target.value)}
                placeholder="你的名字（选填）"
                className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
              />
              <p className="text-xs text-muted-foreground mt-1.5">留空时 {'{{user}}'} 会替换成 user。</p>
            </div>
            <AutoTextarea
              minRows={3}
              value={personaDesc}
              onChange={e => setPersonaDesc(e.target.value)}
              placeholder="你扮演的人是谁（选填）：身份、外貌、与角色的关系……"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50"
            />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowForm(false)} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
                取消
              </button>
              <button
                onClick={create}
                disabled={creating}
                className="text-sm px-4 py-1.5 rounded-lg flex items-center gap-1.5
                  bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                开始
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setShowForm(true)}
            className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
              border-pink-500/30 rounded-lg text-muted-foreground hover:bg-pink-500/5"
          >
            <Plus className="w-3.5 h-3.5" /> 新故事线
          </button>
        )}
      </div>
    </Section>
  )
}
