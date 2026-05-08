import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface ChatSettings {
  systemPrompt: string
  model: string
  temperature: number
  maxTokens: number
  contextRounds: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

const DEFAULT_SETTINGS: ChatSettings = {
  systemPrompt: '',
  model: '',
  temperature: 0.85,
  maxTokens: 4096,
  contextRounds: 20,
}

const EMPTY_MESSAGES: ChatMessage[] = []

interface ChatStore {
  settings: Record<number, ChatSettings>
  messages: Record<number, ChatMessage[]>
  updateSettings: (novelId: number, partial: Partial<ChatSettings>) => void
  resetSettings: (novelId: number) => void
  appendMessage: (novelId: number, message: ChatMessage) => void
  updateLastAssistant: (novelId: number, updater: (content: string) => string) => void
  clearMessages: (novelId: number) => void
}

export const useChatStore = create<ChatStore>()(
  persist(
    (set) => ({
      settings: {},
      messages: {},

      updateSettings: (novelId, partial) =>
        set((s) => ({
          settings: {
            ...s.settings,
            [novelId]: { ...DEFAULT_SETTINGS, ...(s.settings[novelId] || {}), ...partial },
          },
        })),

      resetSettings: (novelId) =>
        set((s) => {
          const { [novelId]: _, ...rest } = s.settings
          return { settings: rest }
        }),

      appendMessage: (novelId, message) =>
        set((s) => ({
          messages: { ...s.messages, [novelId]: [...(s.messages[novelId] || []), message] },
        })),

      updateLastAssistant: (novelId, updater) =>
        set((s) => {
          const msgs = s.messages[novelId] || []
          if (msgs.length === 0) return s
          const last = msgs[msgs.length - 1]
          if (last.role !== 'assistant') return s
          const updated = [...msgs]
          updated[updated.length - 1] = { ...last, content: updater(last.content) }
          return { messages: { ...s.messages, [novelId]: updated } }
        }),

      clearMessages: (novelId) =>
        set((s) => {
          const { [novelId]: _, ...rest } = s.messages
          return { messages: rest }
        }),
    }),
    { name: 'novelbot-chat-settings' }
  )
)

/** 获取指定小说的对话设置（稳定引用，不在 store 内部创建新对象） */
export function getChatSettings(state: ChatStore, novelId: number): ChatSettings {
  return state.settings[novelId] ?? DEFAULT_SETTINGS
}

/** 获取指定小说的对话消息（稳定引用） */
export function getChatMessages(state: ChatStore, novelId: number): ChatMessage[] {
  return state.messages[novelId] ?? EMPTY_MESSAGES
}
