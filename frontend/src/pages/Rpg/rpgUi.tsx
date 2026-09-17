import { useEffect, useRef, useState } from 'react'
import type { Dices } from 'lucide-react'
import { Loader2, Plus, Sparkles, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { rpgApi, type RpgAssistField } from '@/api/client'

export const INPUT = 'w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-primary/50'

/** 逗号分隔的一行文本 ↔ 字符串数组。中英文逗号、顿号、分号都认 */
export const splitList = (text: string) =>
  text.split(/[,，、;；]+/).map(s => s.trim()).filter(Boolean)

/**
 * 「一串名字」的输入框：时段表、剧情标记、道具都是这个形状。
 *
 * 必须自己存一份原始文本，不能写成 value={list.join('，')} + onChange={splitList}：
 * 那样每敲一个字都要走一遍 join → split → join，**刚敲下的那个逗号会在往返里被吃掉**，
 * 结果就是逗号根本打不进去（时段表因此只能存成一个格子叫「早中晚」）。
 */
export function CommaInput({
  value, onChange, placeholder, className, disabled,
}: {
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  className?: string
  disabled?: boolean
}) {
  const [text, setText] = useState(() => value.join('，'))
  // 上一次「我们自己发出去的」数组长什么样。只有外面传进来的值跟它不一样时，
  // 才说明是别人改的（比如切换到另一条词条），这时才覆盖输入框里的字
  const emitted = useRef(value.join('，'))

  useEffect(() => {
    const joined = value.join('，')
    if (joined !== emitted.current) {
      emitted.current = joined
      setText(joined)
    }
  }, [value])

  return (
    <input
      value={text}
      onChange={e => {
        setText(e.target.value)
        const next = splitList(e.target.value)
        emitted.current = next.join('，')
        onChange(next)
      }}
      placeholder={placeholder}
      className={className ?? INPUT}
      disabled={disabled}
    />
  )
}

/** 面板的公共壳。侧栏那四张重复的 rounded-xl border bg-card/70 p-3 也用它 */
export const PANEL = 'rpg-panel rounded-xl border bg-card/70'

/** 板块色。变量定在 index.css 的 .mode-game 里，18 套主题下是同一个身份——
 *  换个主题就找不到道具在哪的话，这套辨识度就白做了。
 *  不传 accent 的板块跟主题主色走（游戏下是紫） */
export const ACCENT = {
  cast: 'var(--rpg-cast)',
  bag: 'var(--rpg-bag)',
  skill: 'var(--rpg-skill)',
  task: 'var(--rpg-task)',
  save: 'var(--rpg-save)',
  map: 'var(--rpg-map)',
} as const

/** 一块面板。accent 决定页眉和左边那道色条的颜色，不传就是主题主色。
 *
 *  左侧那条 1px 色条是**板块辨识度**的主力手法，仓库里本来就有——
 *  见 Landing.tsx 顶部那段（注释自己写着「参考图里区分卡片类型的主要手段」），
 *  只是从没在别处用过。 */
export function Section({
  title, desc, icon: Icon, children, accent,
}: {
  title: string
  desc?: string
  icon: typeof Dices
  children: React.ReactNode
  /** 板块强调色的 HSL 三元组，如 '38 92% 50%'。默认跟主题主色走 */
  accent?: string
}) {
  const color = accent ? `hsl(${accent})` : 'hsl(var(--primary))'
  const tint = accent ? `hsl(${accent} / 0.14)` : 'hsl(var(--primary) / 0.14)'
  return (
    <section
      className={`${PANEL} relative overflow-hidden backdrop-blur-sm`}
      style={{ '--rpg-accent': accent || 'var(--primary)' } as React.CSSProperties}
    >
      <span className="absolute left-0 top-0 bottom-0 w-1" style={{ background: color }} />
      <div className="rpg-head px-6 py-4 border-b border-border/60">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg shrink-0" style={{ background: tint, color }}>
            <Icon className="w-4 h-4" />
          </div>
          <div>
            {/* 提到 text-base：原来和正文一样是 text-sm，标题认不出来 */}
            <h2 className="font-semibold text-base tracking-tight">{title}</h2>
            {desc && <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>}
          </div>
        </div>
      </div>
      <div className="p-6">{children}</div>
    </section>
  )
}

export function Field({
  label, value, onChange, placeholder, hint, multiline, assist,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  multiline?: boolean
  /** 传了就在输入框下面出「AI 生成 / AI 优化」。栏位名见后端 FIELD_SPECS */
  assist?: AssistTarget
}) {
  return (
    <div>
      <label className="text-sm font-medium mb-2 block">{label}</label>
      {multiline ? (
        <textarea
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`${INPUT} resize-y min-h-[10rem] leading-relaxed`}
        />
      ) : (
        <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} className={INPUT} />
      )}
      {assist && <Assist {...assist} value={value} onApply={onChange} />}
      {hint && <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>}
    </div>
  )
}

// ── 帮我写 ────────────────────────────────────────────────────────────────

export interface AssistTarget {
  moduleId: number
  /** 后端 agents/rpg_assist.py 的 FIELD_SPECS 里的键 */
  field: RpgAssistField
  /** {展示名: 文本}，作为参考喂给模型。写成函数是为了拿点击那一刻的表单值，
   *  而不是渲染那一刻的——作者常常是边写世界观边点旁边这个按钮 */
  context?: () => Record<string, string>
}

/**
 * 一个「帮我写」按钮加它的草稿区。放在输入框**下面**而不是标签行里：
 * 角色卡、地点、道具那几栏是裸 textarea，压根没有标签行可以塞。
 *
 * 生成的东西不直接写回输入框 —— 作者点「用这段」才写。AI 不该悄悄改掉人家
 * 已经写好的设定。点了「用这段」这一栏就进表单、随后自动存进库，跟作者自己
 * 敲进去的字完全一样（要反悔就再改回去，或者重新生成一次）。
 */
export function Assist({
  moduleId, field, context, value, onApply,
}: AssistTarget & { value: string; onApply: (text: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
  const isGenerate = !value.trim()

  const run = async () => {
    setBusy(true)
    try {
      const { text } = await rpgApi.modules.assist(moduleId, {
        field, content: value, context: context?.() ?? {},
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
    <div className="mt-1.5">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md
          text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
      >
        {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
        {isGenerate ? 'AI 生成' : 'AI 优化'}
      </button>
      {draft !== null && (
        <AssistDraft
          original={value}
          draft={draft}
          retrying={busy}
          onRetry={run}
          onDiscard={() => setDraft(null)}
          onApply={text => { onApply(text); setDraft(null) }}
        />
      )}
    </div>
  )
}

/** AI 结果就地展开，可改、可重试，确认后才替换原文。
 *
 *  不直接 import 酒馆那个（`TavernCard.tsx`）：它把 `border-pink-500/30`、
 *  `bg-pink-500/[0.04]` 写死了，在游戏的紫色和另外 17 套主题下是一块粉斑。
 *  这里跟主题主色走。 */
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

  // 重新生成之后不收起，把新结果换进来
  useEffect(() => { setText(draft) }, [draft])

  return (
    <div className={`${PANEL} mt-2 overflow-hidden`} style={{ borderColor: 'hsl(var(--primary) / 0.3)' }}>
      <div
        className="px-3 py-2 flex items-center gap-1.5 border-b"
        style={{ borderColor: 'hsl(var(--primary) / 0.2)', background: 'hsl(var(--primary) / 0.06)' }}
      >
        <Sparkles className="w-3.5 h-3.5 text-primary shrink-0" />
        <span className="text-xs font-medium text-primary">AI 写的版本</span>
        <span className="text-xs text-muted-foreground">
          {original.trim() ? '确认后替换上面的内容' : '确认后填进上面的输入框'}
        </span>
        <button
          onClick={onDiscard}
          className="ml-auto p-1 rounded-md hover:bg-primary/10 text-muted-foreground"
          title="丢弃这版"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <div className="p-3">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          className={`${INPUT} resize-y min-h-[8rem] leading-relaxed`}
        />
        <div className="mt-2 flex gap-2 justify-end">
          <button
            onClick={onRetry}
            disabled={retrying}
            className="text-xs px-2.5 py-1.5 rounded-md text-muted-foreground hover:bg-muted
              flex items-center gap-1.5 disabled:opacity-50"
          >
            {retrying && <Loader2 className="w-3 h-3 animate-spin" />}
            重新生成
          </button>
          <button
            onClick={() => onApply(text)}
            disabled={!text.trim()}
            className="text-xs px-3 py-1.5 rounded-md
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {original.trim() ? '替换原文' : '用这段'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AddRow({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-center gap-1 px-3 py-2 text-xs border border-dashed
        border-primary/30 rounded-lg text-muted-foreground hover:bg-primary/5"
    >
      <Plus className="w-3.5 h-3.5" /> {children}
    </button>
  )
}

export function DeleteButton({ onClick, title = '删除' }: { onClick: () => void; title?: string }) {
  return (
    <button
      onClick={onClick}
      // 双基底写：原来那个 hover:bg-red-50 是浅色主题的写死值，
      // 在 18 套深色主题下是一块发光的粉斑
      className="p-1.5 rounded shrink-0 text-muted-foreground
        hover:bg-rose-500/15 hover:text-rose-700 dark:hover:text-rose-300"
      title={title}
    >
      <Trash2 className="w-3.5 h-3.5" />
    </button>
  )
}
