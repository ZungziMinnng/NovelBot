import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BookOpen, Beer, Dices, ArrowUpRight, LogOut, Settings, Library, Flame, Package } from 'lucide-react'
import { authApi } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import StyleLibraryModal from '@/components/StyleLibrary/StyleLibraryModal'
import { useAuthStore } from '@/store/authStore'

// 每张卡的强调色只给一个 HSL 三元组，经 --mode 变量传下去。
// 小说跟主题主色走；酒馆粉、游戏紫和 index.css 的 .mode-tavern / .mode-game 是同一个值，
// 进了模式页颜色对得上
const MODES = [
  {
    key: 'novel',
    label: '小说',
    desc: '长篇连载创作',
    detail: '大纲、角色、世界观与逐章生成，适合有明确故事线的长篇。',
    features: ['分卷大纲', '角色状态追踪', '逐章生成与审校'],
    icon: BookOpen,
    path: '/novels',
    hsl: 'var(--primary)',
    fg: 'var(--primary-foreground)',
  },
  {
    key: 'tavern',
    label: '酒馆',
    desc: '角色扮演对话',
    detail: '建一张角色卡，配上世界书词条，然后逐轮跟角色互动。',
    features: ['角色卡与世界书', '一卡多线剧情', '自定义玩家身份'],
    icon: Beer,
    path: '/tavern',
    hsl: '330 81% 60%',
    fg: '0 0% 100%',
  },
  {
    key: 'game',
    label: '游戏',
    desc: '互动游戏模组',
    detail: '模拟器、角色养成和探索冒险，共用状态、行动和存档系统。',
    features: ['属性与判定', '状态逐轮推进', '存档回溯'],
    icon: Dices,
    path: '/game',
    hsl: '258 90% 66%',
    fg: '0 0% 100%',
  },
] as const

const HEADLINE = ['今天想写', '点什么？']

// 右侧那张稿纸上逐行「写出来」的示例正文
const DRAFT_LINES = [
  '雨落了一整夜，城南的灯一盏也没灭。',
  '她把信折好，压在砚台底下，',
  '像是压住一句说不出口的话。',
  '门外有人叩了三下——',
]

// 光斑跟着指针走。直接写 CSS 变量，不走 React state，移动时不重渲染
function trackPointer(e: React.PointerEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect()
  e.currentTarget.style.setProperty('--px', `${e.clientX - r.left}px`)
  e.currentTarget.style.setProperty('--py', `${e.clientY - r.top}px`)
}

const iconBtn =
  'inline-flex items-center justify-center w-9 h-9 rounded-full text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] active:scale-95 transition-[color,background-color,transform] duration-150'

export default function Landing() {
  const navigate = useNavigate()
  const authUser = useAuthStore((s) => s.user)
  const [libraryOpen, setLibraryOpen] = useState(false)

  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {}
    useAuthStore.getState().clear()
    navigate('/login', { replace: true })
  }, [navigate])

  let charIndex = 0

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background grain">
      {/* 背景：稿纸格 + 两团慢慢漂的主色光 */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="manuscript-grid absolute inset-x-0 top-0 h-[900px]" />
        <div className="aurora absolute -top-40 left-[8%] h-[520px] w-[520px] rounded-full bg-primary/20 blur-[120px]" />
        <div
          className="aurora absolute top-24 right-[-10%] h-[440px] w-[440px] rounded-full bg-[hsl(330_81%_60%/0.12)] blur-[120px]"
          style={{ animationDelay: '-9s' }}
        />
      </div>

      <header data-bare className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
        <Link to="/" className="group flex items-center gap-2.5 rounded-lg select-none" aria-label="NovelBot 首页">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-foreground text-background shadow-md transition-transform duration-300 ease-out-expo group-hover:-rotate-6">
            <BookOpen className="h-4 w-4" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">NovelBot</span>
        </Link>
        <nav className="flex items-center gap-1" aria-label="账户与设置">
          {authUser && (
            <button
              onClick={() => navigate('/account')}
              className="mr-1 flex items-center gap-2 rounded-full py-1 pl-1 pr-3 text-sm text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground transition-colors"
              title="用户设置"
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-primary/15 text-xs font-semibold uppercase text-primary">
                {authUser.username.slice(0, 1)}
              </span>
              <span className="hidden max-w-[8rem] truncate sm:inline">{authUser.username}</span>
            </button>
          )}
          <ThemePicker />
          <button onClick={() => navigate('/settings')} className={iconBtn} title="设置" aria-label="设置">
            <Settings className="h-[18px] w-[18px]" />
          </button>
          <button onClick={handleLogout} className={iconBtn} title="登出" aria-label="登出">
            <LogOut className="h-4 w-4" />
          </button>
        </nav>
      </header>

      <main className="relative z-10 mx-auto max-w-6xl px-5 pb-20 sm:px-8">
        {/* ---------- 主视觉 ---------- */}
        <section className="grid items-center gap-12 pb-14 pt-10 sm:pt-16 lg:grid-cols-[1.15fr_0.85fr] lg:pb-20 lg:pt-20">
          <div>
            <p
              className="reveal mb-6 inline-flex items-center gap-2 rounded-full border border-foreground/10 bg-card/70 px-3 py-1 text-xs font-medium text-muted-foreground shadow-sm backdrop-blur"
              style={{ '--i': 0 } as React.CSSProperties}
            >
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
              </span>
              AI 创作工作台
            </p>

            <h1 className="font-display text-[clamp(2.75rem,8vw,5.25rem)] font-bold leading-[1.08] tracking-tight">
              {HEADLINE.map((line, li) => (
                <span key={line} className="block">
                  {[...line].map((ch) => (
                    <span key={charIndex} className="ink-char" style={{ '--i': charIndex++ } as React.CSSProperties}>
                      {ch}
                    </span>
                  ))}
                  {li === HEADLINE.length - 1 && <span aria-hidden className="caret" />}
                </span>
              ))}
            </h1>

            <p
              className="reveal mt-6 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg"
              style={{ '--i': 5 } as React.CSSProperties}
            >
              长篇连载、角色对话、互动游戏。三种模式各自独立，共用模型配置与规则广场。
            </p>
          </div>

          {/* 稿纸：示意「AI 在写」，纯装饰，窄屏不占位置 */}
          <div aria-hidden className="reveal relative hidden lg:block" style={{ '--i': 4 } as React.CSSProperties}>
            <div className="absolute inset-0 translate-x-4 translate-y-4 rotate-3 rounded-2xl border border-foreground/10 bg-card/50" />
            <div className="relative -rotate-1 rounded-2xl border border-foreground/10 bg-card p-7 shadow-2xl transition-transform duration-700 ease-out-expo hover:rotate-0">
              <div className="mb-5 flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-display text-base font-semibold text-foreground">第一章 · 夜雨</span>
                <span className="tabular-nums">1,284 字</span>
              </div>
              <div className="space-y-3 font-display text-[15px] leading-[2.1] text-foreground/85">
                {DRAFT_LINES.map((t, i) => (
                  <p
                    key={t}
                    className="reveal border-b border-dashed border-foreground/10"
                    style={{ '--i': 8 + i * 3 } as React.CSSProperties}
                  >
                    {t}
                    {i === DRAFT_LINES.length - 1 && <span className="caret" />}
                  </p>
                ))}
              </div>
              <div className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="rounded-full bg-primary/10 px-2 py-0.5 font-medium text-primary">续写中</span>
                <span>伏笔 3 · 角色 5 · 时间线 第 2 日</span>
              </div>
            </div>
          </div>
        </section>

        {/* ---------- 模式 ---------- */}
        <section aria-labelledby="modes-title">
          <div className="reveal mb-6 flex items-center gap-4" style={{ '--i': 6 } as React.CSSProperties}>
            <h2 id="modes-title" className="text-sm font-medium text-muted-foreground">
              选一种开始
            </h2>
            <span className="h-px flex-1 bg-gradient-to-r from-border to-transparent" />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 lg:gap-5">
            {MODES.map((mode, i) => {
              const Icon = mode.icon
              return (
                <Link
                  key={mode.key}
                  to={mode.path}
                  onPointerMove={trackPointer}
                  style={{ '--mode': mode.hsl, '--mode-fg': mode.fg, '--i': 7 + i } as React.CSSProperties}
                  className={`reveal group relative flex min-h-[20rem] flex-col overflow-hidden rounded-2xl border border-foreground/10 bg-card p-6 shadow-sm transition-[transform,box-shadow,border-color] duration-500 ease-out-expo hover:-translate-y-1 hover:border-[hsl(var(--mode)/0.45)] hover:shadow-xl active:translate-y-0 active:scale-[0.99] sm:p-7 ${i === MODES.length - 1 ? 'sm:col-span-2 lg:col-span-1' : ''}`}
                >
                  {/* 指针光斑 */}
                  <span
                    aria-hidden
                    className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
                    style={{
                      background:
                        'radial-gradient(420px circle at var(--px, 50%) var(--py, 0%), hsl(var(--mode) / 0.12), transparent 60%)',
                    }}
                  />
                  {/* 顶边一条模式色，悬停时从左展开 */}
                  <span
                    aria-hidden
                    className="absolute inset-x-0 top-0 h-[3px] origin-left scale-x-[0.18] bg-[hsl(var(--mode))] transition-transform duration-700 ease-out-expo group-hover:scale-x-100"
                  />

                  <div className="relative flex items-start justify-between">
                    <span className="grid h-12 w-12 place-items-center rounded-xl bg-[hsl(var(--mode)/0.12)] text-[hsl(var(--mode))] ring-1 ring-inset ring-[hsl(var(--mode)/0.2)] transition-transform duration-500 ease-out-expo group-hover:scale-110 group-hover:-rotate-6">
                      <Icon className="h-6 w-6" />
                    </span>
                    <span className="font-mono text-xs tabular-nums text-muted-foreground/70">0{i + 1}</span>
                  </div>

                  <div className="relative mt-8">
                    <h3 className="font-display text-[1.75rem] font-bold leading-none">{mode.label}</h3>
                    <p className="mt-2 text-sm font-medium text-[hsl(var(--mode))]">{mode.desc}</p>
                  </div>

                  <p className="relative mt-4 text-sm leading-relaxed text-muted-foreground">{mode.detail}</p>

                  <div className="relative mt-auto flex items-end justify-between gap-3 pt-6">
                    <ul className="flex flex-wrap gap-1.5" aria-label={`${mode.label}模式功能`}>
                      {mode.features.map((f) => (
                        <li
                          key={f}
                          className="rounded-full border border-foreground/10 bg-background/60 px-2.5 py-1 text-xs text-foreground/75"
                        >
                          {f}
                        </li>
                      ))}
                    </ul>
                    <span
                      aria-hidden
                      className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-foreground/10 text-muted-foreground transition-all duration-500 ease-out-expo group-hover:rotate-45 group-hover:border-transparent group-hover:bg-[hsl(var(--mode))] group-hover:text-[hsl(var(--mode-fg))]"
                    >
                      <ArrowUpRight className="h-4 w-4" />
                    </span>
                  </div>
                </Link>
              )
            })}
          </div>

          {/* 文风库三种模式共用，所以入口放首页，各模式里只有「从文风库取用」 */}
          <button
            onClick={() => setLibraryOpen(true)}
            onPointerMove={trackPointer}
            style={{ '--mode': 'var(--primary)', '--i': 10 } as React.CSSProperties}
            className="reveal group relative mt-4 flex w-full items-center gap-4 overflow-hidden rounded-2xl border border-foreground/10 bg-card px-5 py-5 text-left shadow-sm transition-[transform,box-shadow,border-color] duration-500 ease-out-expo hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg active:translate-y-0 active:scale-[0.995] sm:px-7 lg:mt-5"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
              style={{
                background:
                  'radial-gradient(360px circle at var(--px, 50%) var(--py, 50%), hsl(var(--primary) / 0.1), transparent 60%)',
              }}
            />
            <span className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <Library className="h-5 w-5" />
            </span>
            <span className="relative min-w-0 flex-1">
              <span className="block font-semibold">文风库</span>
              <span className="mt-0.5 block text-sm text-muted-foreground">
                导入一本 txt，提炼文风和原文片段，小说、酒馆、游戏都能取来当示例
              </span>
            </span>
            <span
              aria-hidden
              className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full border border-foreground/10 text-muted-foreground transition-all duration-500 ease-out-expo group-hover:rotate-45 group-hover:border-transparent group-hover:bg-primary group-hover:text-primary-foreground"
            >
              <ArrowUpRight className="h-4 w-4" />
            </span>
          </button>

          <Link
            to="/forge"
            onPointerMove={trackPointer}
            style={{ '--mode': 'var(--primary)', '--i': 11 } as React.CSSProperties}
            className="reveal group relative mt-4 flex w-full items-center gap-4 overflow-hidden rounded-2xl border border-foreground/10 bg-card px-5 py-5 text-left shadow-sm transition-[transform,box-shadow,border-color] duration-500 ease-out-expo hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg active:translate-y-0 active:scale-[0.995] sm:px-7"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
              style={{
                background:
                  'radial-gradient(360px circle at var(--px, 50%) var(--py, 50%), hsl(var(--primary) / 0.1), transparent 60%)',
              }}
            />
            <span className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <Flame className="h-5 w-5" />
            </span>
            <span className="relative min-w-0 flex-1">
              <span className="block font-semibold">熔炉</span>
              <span className="mt-0.5 block text-sm text-muted-foreground">
                挑几个酒馆、小说、模组里的角色，调好比例，让 AI 炼成一个新角色
              </span>
            </span>
            <span
              aria-hidden
              className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full border border-foreground/10 text-muted-foreground transition-all duration-500 ease-out-expo group-hover:rotate-45 group-hover:border-transparent group-hover:bg-primary group-hover:text-primary-foreground"
            >
              <ArrowUpRight className="h-4 w-4" />
            </span>
          </Link>

          <Link
            to="/lore"
            onPointerMove={trackPointer}
            style={{ '--mode': 'var(--primary)', '--i': 12 } as React.CSSProperties}
            className="reveal group relative mt-4 flex w-full items-center gap-4 overflow-hidden rounded-2xl border border-foreground/10 bg-card px-5 py-5 text-left shadow-sm transition-[transform,box-shadow,border-color] duration-500 ease-out-expo hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg active:translate-y-0 active:scale-[0.995] sm:px-7"
          >
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
              style={{
                background:
                  'radial-gradient(360px circle at var(--px, 50%) var(--py, 50%), hsl(var(--primary) / 0.1), transparent 60%)',
              }}
            />
            <span className="relative grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <Package className="h-5 w-5" />
            </span>
            <span className="relative min-w-0 flex-1">
              <span className="block font-semibold">设定库</span>
              <span className="mt-0.5 block text-sm text-muted-foreground">
                收纳道具、技能、规则，可融合出新设定，再导出到小说、酒馆、游戏
              </span>
            </span>
            <span
              aria-hidden
              className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full border border-foreground/10 text-muted-foreground transition-all duration-500 ease-out-expo group-hover:rotate-45 group-hover:border-transparent group-hover:bg-primary group-hover:text-primary-foreground"
            >
              <ArrowUpRight className="h-4 w-4" />
            </span>
          </Link>
        </section>
      </main>

      <footer className="relative z-10 mx-auto flex max-w-6xl items-center justify-between border-t border-foreground/[0.06] px-5 py-6 text-xs text-muted-foreground sm:px-8">
        <span>NovelBot</span>
        <Link to="/about" className="rounded hover:text-foreground transition-colors">
          关于
        </Link>
      </footer>

      {libraryOpen && <StyleLibraryModal onClose={() => setLibraryOpen(false)} />}
    </div>
  )
}
