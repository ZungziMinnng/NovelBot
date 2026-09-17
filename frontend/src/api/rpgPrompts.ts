import { createUserPromptsApi, type UserPrompt } from './userPrompts'

export type RpgPrompt = UserPrompt

export const rpgPromptsApi = createUserPromptsApi('/rpg/prompts')
