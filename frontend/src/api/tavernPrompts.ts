import { api } from './client'

export interface TavernPrompt {
  name: string
  label: string
  description: string
  variables: Record<string, string>
  content: string
  default_content: string
  customized: boolean
}

export const tavernPromptsApi = {
  list: () => api.get<TavernPrompt[]>('/tavern/prompts/').then(response => response.data),
  update: (name: string, content: string) =>
    api.put<TavernPrompt>(`/tavern/prompts/${encodeURIComponent(name)}`, { content }).then(response => response.data),
  reset: (name: string) =>
    api.delete<TavernPrompt>(`/tavern/prompts/${encodeURIComponent(name)}`).then(response => response.data),
}
