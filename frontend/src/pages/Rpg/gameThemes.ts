import type { RpgUiTheme } from '@/api/client'

/** 游玩界面主题。样式在 index.css 的 `.mode-game[data-game-theme=…]`，
 *  这里只放选择器要显示的名字和色块。色块是浅色底下的近似值，仅作预览。 */
export const GAME_THEMES: Array<{
  key: RpgUiTheme
  label: string
  hint: string
  swatch: [string, string]
}> = [
  { key: '', label: '跟随全站', hint: '不套游戏主题，用你在全站选的那一套。', swatch: ['#e5e7eb', '#8b5cf6'] },
  { key: 'xuanhuan', label: '玄幻', hint: '宣纸墨青配朱砂金，宋体，云纹底，页眉带菱形金线。', swatch: ['#2f5d62', '#b8893a'] },
  { key: 'modern', label: '现代', hint: '冷灰白底配靛蓝，无衬线，细点阵底，硬朗小圆角。', swatch: ['#eef1f5', '#4f46e5'] },
  { key: 'fantasy', label: '魔幻', hint: '羊皮纸与深紫夜色配烫金，衬线体，星辰符环底，页眉带微光。', swatch: ['#3b2a63', '#d4a24c'] },
]

/** 写进 data-game-theme 的值；空串返回 undefined，让属性整个不出现 */
export const gameThemeAttr = (key: string | undefined | null) => key || undefined
