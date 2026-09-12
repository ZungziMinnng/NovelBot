import { useEffect, useRef, useState } from 'react'
import type { Dices } from 'lucide-react'
import { Plus, Trash2 } from 'lucide-react'

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

/** 板块色。变量定在 index.css 的 .mode-rpg 里，18 套主题下是同一个身份——
 *  换个主题就找不到道具在哪的话，这套辨识度就白做了。
 *  不传 accent 的板块跟主题主色走（RPG 下是紫） */
export const ACCENT = {
  cast: 'var(--rpg-cast)',
  bag: 'var(--rpg-bag)',
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
  label, value, onChange, placeholder, hint, multiline,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  multiline?: boolean
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
      {hint && <p className="text-xs text-muted-foreground mt-1.5">{hint}</p>}
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
