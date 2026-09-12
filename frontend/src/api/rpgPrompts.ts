import { api } from './client'

export interface RpgPrompt {
  name: string
  label: string
  description: string
  variables: Record<string, string>
  content: string
  default_content: string
  customized: boolean
}

export const rpgPromptsApi = {
  list: () => api.get<RpgPrompt[]>('/rpg/prompts/').then(response => response.data),
  update: (name: string, content: string) =>
    api.put<RpgPrompt>(`/rpg/prompts/${encodeURIComponent(name)}`, { content }).then(response => response.data),
  reset: (name: string) =>
    api.delete<RpgPrompt>(`/rpg/prompts/${encodeURIComponent(name)}`).then(response => response.data),
}
