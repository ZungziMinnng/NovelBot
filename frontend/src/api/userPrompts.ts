import { api } from './client'

/** 每用户提示词覆盖。RPG 和酒馆两侧的接口形状一致，只差 URL 前缀。 */
export interface UserPrompt {
  name: string
  label: string
  description: string
  variables: Record<string, string>
  content: string
  default_content: string
  customized: boolean
}

export interface UserPromptsApi {
  list: () => Promise<UserPrompt[]>
  update: (name: string, content: string) => Promise<UserPrompt>
  reset: (name: string) => Promise<UserPrompt>
}

export function createUserPromptsApi(basePath: string): UserPromptsApi {
  return {
    list: () => api.get<UserPrompt[]>(`${basePath}/`).then(response => response.data),
    update: (name: string, content: string) =>
      api.put<UserPrompt>(`${basePath}/${encodeURIComponent(name)}`, { content }).then(response => response.data),
    reset: (name: string) =>
      api.delete<UserPrompt>(`${basePath}/${encodeURIComponent(name)}`).then(response => response.data),
  }
}
