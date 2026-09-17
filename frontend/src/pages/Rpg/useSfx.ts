import { useSyncExternalStore } from 'react'

export type SfxKey = 'dice' | 'stat-up' | 'stat-down' | 'turn' | 'enter' | 'npc'

interface SfxSettings {
  enabled: boolean
  volume: number
}

const SFX_KEYS: readonly SfxKey[] = ['dice', 'stat-up', 'stat-down', 'turn', 'enter', 'npc']

const SFX_DIR = '/sfx'
const STORAGE_KEY = 'novelbot.rpg.sfx'
const DEFAULT_SETTINGS: SfxSettings = { enabled: false, volume: 0.5 }

/** 同 key 的静默窗：60ms 够盖住一次点击里的重复触发，又短到不会被听成吞音 */
const THROTTLE_MS = 60

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

/**
 * 这份数据会被旧版本写过、被用户手改过，所以逐字段校验而不是整体断言。
 * 任何一段读不出来都回落到默认值——音效是这个项目里最不重要的一环，
 * 不值得为了它让页面挂掉或者弹提示。
 */
function loadSettings(): SfxSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_SETTINGS
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return DEFAULT_SETTINGS
    const record = parsed as Record<string, unknown>
    return {
      enabled: typeof record.enabled === 'boolean' ? record.enabled : DEFAULT_SETTINGS.enabled,
      volume:
        typeof record.volume === 'number' && Number.isFinite(record.volume)
          ? clamp01(record.volume)
          : DEFAULT_SETTINGS.volume,
    }
  } catch {
    return DEFAULT_SETTINGS
  }
}

let settings: SfxSettings = loadSettings()

const subscribers = new Set<() => void>()

function getSnapshot(): SfxSettings {
  return settings
}

function subscribe(onChange: () => void): () => void {
  subscribers.add(onChange)
  return () => {
    subscribers.delete(onChange)
  }
}

function persist(): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // 隐私模式、配额满都会抛。存不下就只在本次会话生效，不值得打断玩家
  }
}

function commit(next: SfxSettings): void {
  settings = next
  persist()
  subscribers.forEach(notify => notify())
}

const GESTURE_EVENTS = ['pointerdown', 'keydown'] as const

/**
 * 这个模块是点进 RPG 页才 import 的，那一次点击其实已经算交互了，
 * 再傻等一次 pointerdown 会白丢一整个回合的音效
 */
function alreadyActivated(): boolean {
  const activation = (navigator as Navigator & { userActivation?: { hasBeenActive?: boolean } })
    .userActivation
  return activation?.hasBeenActive === true
}

let unlocked = alreadyActivated()

function unlock(): void {
  unlocked = true
  // 解锁后就地拆掉，别让两个监听器跟着页面活到关服
  GESTURE_EVENTS.forEach(type => window.removeEventListener(type, unlock))
}

if (!unlocked) {
  GESTURE_EVENTS.forEach(type => window.addEventListener(type, unlock))
}

/** 一个 key 常驻一个元素：重播时直接盖掉上一遍，也不用自己管元素回收 */
const pool = new Map<SfxKey, HTMLAudioElement>()
/** 加载失败的 key 记这儿，之后连元素都不再建——否则每回合都要刷一串 404 */
const missing = new Set<SfxKey>()
const lastAt = new Map<SfxKey, number>()

function elementFor(key: SfxKey): HTMLAudioElement | null {
  if (missing.has(key)) return null
  const cached = pool.get(key)
  if (cached) return cached

  const el = new Audio(`${SFX_DIR}/${key}.ogg`)
  el.preload = 'auto'
  el.volume = settings.volume
  el.addEventListener('error', () => {
    missing.add(key)
    pool.delete(key)
  }, { once: true })

  pool.set(key, el)
  return el
}

function preloadAll(): void {
  SFX_KEYS.forEach(key => { elementFor(key) })
}

// 上次是开着的话，这次进来就该是热的；关着的时候一个字节都不下
if (settings.enabled) preloadAll()

/**
 * 命令式播放。用 <audio> 而不是 Web Audio：这层只要「放个文件、调个音量」，
 * 上 AudioContext 就得自己管解码和恢复时机，收益为零。
 */
export function playSfx(key: SfxKey): void {
  if (!settings.enabled) return
  // 交互之前直接丢，不排队：迟到几秒的音效比没有音效更让人困惑
  if (!unlocked) return
  if (missing.has(key)) return

  const now = performance.now()
  if (now - (lastAt.get(key) ?? 0) < THROTTLE_MS) return
  lastAt.set(key, now)

  const el = elementFor(key)
  if (!el) return

  el.volume = settings.volume
  try {
    // 重播要盖掉上一遍，而不是接在它尾巴后面
    el.currentTime = 0
  } catch {
    // 元数据还没到时 currentTime 不可写，直接 play 也是从头放
  }
  void el.play().catch(() => {
    // 文件缺失、解码失败、浏览器仍然拒绝，都会 reject。
    // 玩家只该听到「没有声音」，不该在控制台看到一坨红字
  })
}

function setEnabled(next: boolean): void {
  if (next === settings.enabled) return
  commit({ ...settings, enabled: next })
  if (next) preloadAll()
}

function setVolume(next: number): void {
  const clamped = Number.isFinite(next) ? clamp01(next) : settings.volume
  if (clamped === settings.volume) return
  commit({ ...settings, volume: clamped })
}

/** 状态挂在模块级 store 上，多个组件同时用才听得见彼此改的开关 */
export function useSfxSettings(): {
  enabled: boolean
  volume: number
  setEnabled: (next: boolean) => void
  setVolume: (next: number) => void
} {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot)
  return {
    enabled: snapshot.enabled,
    volume: snapshot.volume,
    setEnabled,
    setVolume,
  }
}
