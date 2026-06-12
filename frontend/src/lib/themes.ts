export interface ThemeDefinition {
  id: string
  label: string
  base: 'dark' | 'light'
  accentColor: string
}

export const THEMES: ThemeDefinition[] = [
  { id: 'dark',            label: '深色模式',  base: 'dark',  accentColor: '#3B82F6' },
  { id: 'light',           label: '浅色模式',  base: 'light', accentColor: '#F59E0B' },
  { id: 'eye-care',        label: '护眼模式',  base: 'light', accentColor: '#D4A574' },
  { id: 'midnight-purple', label: '午夜紫',    base: 'dark',  accentColor: '#8B5CF6' },
  { id: 'dark-pro',        label: '暗色系',    base: 'dark',  accentColor: '#6B7280' },
  { id: 'monokai',         label: 'Monokai',  base: 'dark',  accentColor: '#A6E22E' },
  { id: 'rose',            label: '玫瑰粉',    base: 'light', accentColor: '#F472B6' },
  { id: 'lava',            label: '熔岩橙',    base: 'dark',  accentColor: '#F97316' },
  { id: 'iron-man',        label: '钢铁侠',    base: 'dark',  accentColor: '#EF4444' },
  { id: 'cyber',           label: '机械觉醒',  base: 'dark',  accentColor: '#06B6D4' },
  { id: 'pandora',         label: '潘多拉',    base: 'dark',  accentColor: '#10B981' },
  { id: 'dark-knight',     label: '暗夜骑士',  base: 'dark',  accentColor: '#1E293B' },
  { id: 'force',           label: '原力觉醒',  base: 'dark',  accentColor: '#3B82F6' },
  { id: 'trader',          label: '交易员',    base: 'dark',  accentColor: '#22C55E' },
  { id: 'sky-blue',        label: '天际蓝',    base: 'light', accentColor: '#38BDF8' },
  { id: 'dream-purple',    label: '梦幻紫',    base: 'light', accentColor: '#A78BFA' },
  { id: 'elegant-gray',    label: '淡雅灰',    base: 'light', accentColor: '#9CA3AF' },
  { id: 'nsfw',            label: '创作自由',  base: 'dark',  accentColor: '#C026D3' },
]

export function getThemeById(id: string): ThemeDefinition {
  return THEMES.find(t => t.id === id) ?? THEMES[0]
}
