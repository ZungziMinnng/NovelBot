export const ROLE_OPTIONS = ['男主', '女主', '配角', '盟友', '朋友', '反派']

const ROLE_COLORS: Record<string, string> = {
  男主: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  女主: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',
  主角: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  反派: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  配角: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  盟友: 'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
  朋友: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
}

const EXTRA_PALETTE = [
  'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  'bg-lime-100 text-lime-700 dark:bg-lime-900/40 dark:text-lime-300',
  'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-900/40 dark:text-fuchsia-300',
]

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function getRoleColor(role: string): string {
  if (ROLE_COLORS[role]) return ROLE_COLORS[role]
  return EXTRA_PALETTE[hashCode(role) % EXTRA_PALETTE.length]
}

const ROLE_FILL: Record<string, string> = {
  男主: '#f59e0b',
  主角: '#f59e0b',
  女主: '#ec4899',
  反派: '#ef4444',
  配角: '#6b7280',
  盟友: '#14b8a6',
  朋友: '#3b82f6',
}

const EXTRA_FILL_PALETTE = [
  '#8b5cf6', '#06b6d4', '#f97316', '#84cc16',
  '#f43f5e', '#6366f1', '#10b981', '#d946ef',
]

export function getRoleFill(role: string): string {
  if (ROLE_FILL[role]) return ROLE_FILL[role]
  return EXTRA_FILL_PALETTE[hashCode(role) % EXTRA_FILL_PALETTE.length]
}
