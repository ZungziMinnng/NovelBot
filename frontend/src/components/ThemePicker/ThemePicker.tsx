import { useState, useRef, useEffect } from 'react'
import { Palette, Check } from 'lucide-react'
import { useSettingsStore } from '@/store/settingsStore'
import { THEMES } from '@/lib/themes'

export default function ThemePicker({ size = 'md' }: { size?: 'sm' | 'md' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const theme = useSettingsStore((s) => s.theme)
  const setTheme = useSettingsStore((s) => s.setTheme)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4'
  const btnPad = size === 'sm' ? 'p-1.5' : 'p-2'

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`${btnPad} rounded-md hover:bg-muted transition-colors`}
        title="切换主题"
      >
        <Palette className={iconSize} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-card border rounded-xl shadow-lg p-3 w-[280px]">
          <p className="text-xs text-muted-foreground mb-2 px-1">选择主题</p>
          <div className="grid grid-cols-2 gap-0.5 max-h-[400px] overflow-y-auto">
            {THEMES.filter(t => t.id !== 'nsfw').map(t => (
              <button
                key={t.id}
                onClick={() => { setTheme(t.id); setOpen(false) }}
                className={`flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs transition-colors text-left ${
                  theme === t.id ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted text-foreground'
                }`}
              >
                <span
                  className="w-3.5 h-3.5 rounded-full shrink-0 border border-foreground/10"
                  style={{ backgroundColor: t.accentColor }}
                />
                <span className="flex-1 truncate">{t.label}</span>
                {theme === t.id && <Check className="w-3 h-3 shrink-0" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
