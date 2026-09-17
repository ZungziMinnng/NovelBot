import { createUserPromptsApi, type UserPrompt } from './userPrompts'

export type TavernPrompt = UserPrompt

export const tavernPromptsApi = createUserPromptsApi('/tavern/prompts')
