import { useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { BookOpen, Beer, Dices, ChevronRight, LogOut, Settings } from 'lucide-react'
import { authApi } from '@/api/client'
import ThemePicker from '@/components/ThemePicker/ThemePicker'
import Silk from '@/components/Silk/Silk'
import SpotlightCard from '@/components/SpotlightCard/SpotlightCard'
import { useSettingsStore } from '@/store/settingsStore'
import { useAuthStore } from '@/store/authStore'

// 每张卡一套强调色。Tailwind 要靠静态字符串扫描，所以类名必须写全，
// 不能拼 `bg-${color}-500` 那种模板串，否则生产构建里会被清掉
const MODES = [
  {
    key: 'novel',
    label: '小说',
    desc: '长篇连载创作',
    detail: '大纲、角色、世界观与逐章生成，适合有明确故事线的长篇。',
    features: ['分卷大纲', '角色状态追踪', '逐章生成与审校'],
    icon: BookOpen,
    path: '/novels',
    bar: 'bg-sky-500',
    iconWrap: 'bg-sky-500/15 text-sky-400',
    glow: 'rgba(56, 189, 248, 0.10)',
    hoverBorder: 'hover:border-sky-500/60',
    dot: 'bg-sky-400',
  },
  {
    key: 'tavern',
    label: '酒馆',
    desc: '角色扮演对话',
    detail: '建一张角色卡，配上世界书词条，然后逐轮跟角色互动。',
    features: ['角色卡与世界书', '一卡多线剧情', '自定义玩家身份'],
    icon: Beer,
    path: '/tavern',
    bar: 'bg-pink-500',
    iconWrap: 'bg-pink-500/15 text-pink-400',
    glow: 'rgba(236, 72, 153, 0.14)',
    hoverBorder: 'hover:border-pink-500/60',
    dot: 'bg-pink-400',
  },
  {
    key: 'rpg',
    label: 'RPG',
    desc: '文字冒险',
    detail: '带状态与判定的回合制叙事，你出招、AI 接着往下讲。',
    features: ['属性与判定', '状态逐轮推进', '存档回溯'],
    icon: Dices,
    path: null,
    bar: 'bg-violet-500',
    iconWrap: 'bg-violet-500/15 text-violet-400',
    glow: 'rgba(167, 139, 250, 0.10)',
    hoverBorder: 'hover:border-violet-500/60',
    dot: 'bg-violet-400',
  },
] as const

export default function Landing() {
  const navigate = useNavigate()
  const nsfwMode = useSettingsStore((s) => s.nsfwMode)
  const authUser = useAuthStore((s) => s.user)

  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {}
    useAuthStore.getState().clear()
    navigate('/login', { replace: true })
  }, [navigate])

  const silkColor = useMemo(() => {
    if (nsfwMode) return '#4A1942'
    const style = getComputedStyle(document.documentElement)
    const h = style.getPropertyValue('--primary').trim().split(' ')[0] || '220'
    const hue = parseFloat(h)
    const r = Math.round(128 + 40 * Math.cos((hue * Math.PI) / 180))
    const g = Math.round(128 + 40 * Math.cos(((hue - 120) * Math.PI) / 180))
    const b = Math.round(128 + 40 * Math.cos(((hue - 240) * Math.PI) / 180))
    return `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`
  }, [nsfwMode])

  return (
    <div className="min-h-screen bg-background relative">
      <div className="fixed inset-0 z-0 opacity-20 pointer-events-none">
        <Silk speed={3} scale={1} color={silkColor} noiseIntensity={1.2} rotation={0} className="w-full h-full" />
      </div>

      <header className="relative z-10 border-b border-border/50 backdrop-blur-sm px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2 select-none">
          <BookOpen className="w-6 h-6 text-primary" />
          <h1 className="text-xl font-bold">NovelBot</h1>
        </div>
        <div className="flex items-center gap-1">
          {authUser && (
            <button
              onClick={() => navigate('/account')}
              className="text-sm text-muted-foreground mr-2 px-2 py-1 rounded-md hover:bg-muted hover:text-foreground transition-colors"
              title="用户设置"
            >
              {authUser.username}
            </button>
          )}
          <ThemePicker />
          <button
            onClick={() => navigate('/settings')}
            className="p-2 rounded-md hover:bg-muted transition-colors"
            title="设置"
          >
            <Settings className="w-5 h-5" />
          </button>
          <button
            onClick={handleLogout}
            className="p-2 rounded-md hover:bg-muted transition-colors"
            title="登出"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="relative z-10 max-w-5xl mx-auto px-6 py-16">
        <div className="mb-10">
          <h2 className="text-2xl font-bold mb-1.5">今天想写点什么？</h2>
          <p className="text-sm text-muted-foreground">三种模式各自独立，共用模型配置与规则广场</p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {MODES.map((mode) => {
            const { key, label, desc, detail, features, icon: Icon, path } = mode
            const available = path !== null
            return (
              <SpotlightCard
                key={key}
                spotlightColor={mode.glow}
                className={`rounded-xl border bg-card/60 backdrop-blur-sm transition-colors ${
                  available ? mode.hoverBorder : 'opacity-70'
                }`}
              >
                {/* 左侧色条：参考图里区分卡片类型的主要手段 */}
                <div className={`absolute left-0 top-0 bottom-0 w-1 ${mode.bar}`} />
                <button
                  onClick={() => {
                    if (available) navigate(path)
                    else toast(`${label}模式还在开发中`, { icon: '🚧', duration: 2000 })
                  }}
                  className="w-full text-left pl-7 pr-6 py-7 flex flex-col gap-4 min-h-[19rem]"
                >
                  <div className="flex items-start justify-between">
                    <div className={`p-3 rounded-xl ${mode.iconWrap}`}>
                      <Icon className="w-7 h-7" />
                    </div>
                    {available ? (
                      <ChevronRight className="w-4 h-4 text-muted-foreground mt-1" />
                    ) : (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground mt-1">
                        开发中
                      </span>
                    )}
                  </div>

                  <div>
                    <p className="text-lg font-semibold">{label}</p>
                    <p className="text-xs text-muted-foreground mt-1">{desc}</p>
                  </div>

                  <p className="text-xs text-muted-foreground leading-relaxed">{detail}</p>

                  <ul className="mt-auto space-y-2 pt-2">
                    {features.map((f) => (
                      <li key={f} className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className={`w-1.5 h-1.5 rounded-full ${mode.dot} shrink-0`} />
                        {f}
                      </li>
                    ))}
                  </ul>
                </button>
              </SpotlightCard>
            )
          })}
        </div>
      </main>
    </div>
  )
}
