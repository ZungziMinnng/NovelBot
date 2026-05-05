import { useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import {
  chaptersApi, charactersApi, generationApi, worldEntitiesApi,
  streamChapterGeneration,
} from '@/api/client'
import type { SSEMessage, AgentDoneData, TotalUsageData, OriginalDraftData, NewCharactersData, NewEntitiesData, LlmCallData } from '@/api/client'
import { type AgentLogEntry } from '@/components/AgentLog/AgentLog'
import { useGenerationStore } from '@/store/generationStore'
import { useEditorStore } from '@/store/editorStore'
import { useDevLogStore } from '@/store/devLogStore'
import { useQueryClient } from '@tanstack/react-query'

export interface GenerationStreamState {
  newCharCandidates: Array<{ name: string; role: string; description: string }>
  newEntityCandidates: Array<{ name: string; type: string; description: string }>
  selectedCharIndices: Set<number>
  selectedEntityIndices: Set<number>
  addingChars: boolean
  addingEntities: boolean
  isLoadingSuggestions: boolean
}

export interface GenerationStreamActions {
  handleGenerate: () => void
  handleAbortOrGenerate: () => void
  handleFetchSuggestions: () => Promise<void>
  toggleCharSelection: (i: number) => void
  toggleEntitySelection: (i: number) => void
  handleAddNewChars: () => Promise<void>
  handleAddNewEntities: () => Promise<void>
  setNewCharCandidates: (v: Array<{ name: string; role: string; description: string }>) => void
  setNewEntityCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
}

export function useGenerationStream(
  novelId: number,
  selectedChapterNum: number,
  instruction: string,
  targetWords: number,
  novelTitle: string,
) {
  const qc = useQueryClient()
  const setChapterSuggestions = useEditorStore((s) => s.setChapterSuggestions)

  // ── Discovery state ──────────────────────────────────────────────────────
  const [newCharCandidates, setNewCharCandidates] = useState<Array<{ name: string; role: string; description: string }>>([])
  const [newEntityCandidates, setNewEntityCandidates] = useState<Array<{ name: string; type: string; description: string }>>([])
  const [selectedCharIndices, setSelectedCharIndices] = useState<Set<number>>(new Set())
  const [selectedEntityIndices, setSelectedEntityIndices] = useState<Set<number>>(new Set())
  const [addingChars, setAddingChars] = useState(false)
  const [addingEntities, setAddingEntities] = useState(false)
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState(false)

  const isCurrentlyGenerating = useGenerationStore((s) =>
    s.isGenerating && s.novelId === novelId && s.chapterNum === selectedChapterNum,
  )

  // ── Plot Suggestions ─────────────────────────────────────────────────────
  const handleFetchSuggestions = useCallback(async () => {
    setIsLoadingSuggestions(true)
    setChapterSuggestions(novelId, selectedChapterNum, [])
    try {
      const suggestions = await generationApi.plotSuggestions(novelId, selectedChapterNum)
      setChapterSuggestions(novelId, selectedChapterNum, suggestions)
    } catch (e) {
      console.error('Failed to fetch suggestions:', e)
    } finally {
      setIsLoadingSuggestions(false)
    }
  }, [novelId, selectedChapterNum, setChapterSuggestions])

  // ── Generate ─────────────────────────────────────────────────────────────
  const handleGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating) return

    gs.startGeneration(novelId, novelTitle, selectedChapterNum)
    setChapterSuggestions(novelId, selectedChapterNum, [])
    setNewCharCandidates([])
    setNewEntityCandidates([])

    let entryCounter = 0
    const runningEntryIds: Map<string, string> = new Map()

    const ctrl = streamChapterGeneration(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        volume: 1,
        instruction,
        target_words: targetWords,
      },
      (msg: SSEMessage) => {
        const s = useGenerationStore.getState()
        switch (msg.event) {
          case 'stage':
            s.setAgentStage(msg.data as string)
            break
          case 'token':
            s.appendToken(msg.data as string)
            break
          case 'agent_start': {
            const d = msg.data as { agent: string; label: string }
            const entryId = `${d.agent}-${entryCounter++}`
            const entry: AgentLogEntry = {
              id: entryId,
              agent: d.agent,
              label: d.label,
              status: 'running',
              inputTokens: 0,
              outputTokens: 0,
            }
            runningEntryIds.set(d.agent, entryId)
            s.addLogEntry(entry)
            break
          }
          case 'agent_done': {
            const d = msg.data as AgentDoneData
            const entryId = runningEntryIds.get(d.agent)
            if (entryId) {
              s.updateLogEntry(entryId, {
                status: 'done',
                inputTokens: d.input_tokens,
                outputTokens: d.output_tokens,
                passed: d.passed,
              })
            }
            break
          }
          case 'total_usage': {
            const d = msg.data as TotalUsageData
            s.setTotalTokens(d.input_tokens, d.output_tokens)
            break
          }
          case 'done':
            s.setAgentStage('done')
            qc.invalidateQueries({ queryKey: ['chapters', novelId] })
            qc.invalidateQueries({ queryKey: ['characters', novelId] })
            break
          case 'original_draft': {
            const d = msg.data as OriginalDraftData
            s.setOriginalDraft(d.text)
            break
          }
          case 'new_characters': {
            const d = msg.data as NewCharactersData
            if (d.candidates?.length) {
              setNewCharCandidates(d.candidates)
              setSelectedCharIndices(new Set(d.candidates.map((_, i) => i)))
            }
            break
          }
          case 'new_entities': {
            const d = msg.data as NewEntitiesData
            if (d.candidates?.length) {
              setNewEntityCandidates(d.candidates)
              setSelectedEntityIndices(new Set(d.candidates.map((_, i) => i)))
            }
            break
          }
          case 'plot_suggestions': {
            const d = msg.data as { suggestions: string[] }
            if (d.suggestions?.length) setChapterSuggestions(novelId, selectedChapterNum, d.suggestions)
            break
          }
          case 'llm_call': {
            const d = msg.data as LlmCallData
            useDevLogStore.getState().addEntry({
              type: 'llm_call',
              agent: d.agent,
              model: d.model,
              llmStatus: d.status,
              inputTokens: d.input_tokens,
              outputTokens: d.output_tokens,
              durationMs: d.duration_ms,
              payload: d.payload,
            })
            break
          }
          case 'warning': {
            s.setWarning(String(msg.data))
            toast(String(msg.data), { icon: '⚠️' })
            break
          }
          case 'error':
            s.setError(String(msg.data))
            break
        }
      },
      () => {
        useGenerationStore.getState().finishGeneration()
      },
    )

    useGenerationStore.getState().setAbortController(ctrl)
  }, [novelId, selectedChapterNum, instruction, targetWords, novelTitle, qc, setChapterSuggestions])

  // ── Abort / Generate ─────────────────────────────────────────────────────
  const handleAbortOrGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating && gs.novelId === novelId && gs.chapterNum === selectedChapterNum) {
      gs.abortGeneration()
      return
    }
    handleGenerate()
  }, [novelId, selectedChapterNum, handleGenerate])

  // ── Discovery: Character ─────────────────────────────────────────────────
  const toggleCharSelection = useCallback((i: number) => {
    setSelectedCharIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewChars = useCallback(async () => {
    if (!selectedCharIndices.size || addingChars) return
    setAddingChars(true)
    try {
      for (const i of selectedCharIndices) {
        await charactersApi.create({ ...newCharCandidates[i], novel_id: novelId })
      }
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      const remaining = newCharCandidates.filter((_, i) => !selectedCharIndices.has(i))
      setNewCharCandidates(remaining)
      setSelectedCharIndices(new Set())
    } finally {
      setAddingChars(false)
    }
  }, [newCharCandidates, selectedCharIndices, addingChars, novelId, qc])

  // ── Discovery: Entity ────────────────────────────────────────────────────
  const toggleEntitySelection = useCallback((i: number) => {
    setSelectedEntityIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewEntities = useCallback(async () => {
    if (!selectedEntityIndices.size || addingEntities) return
    setAddingEntities(true)
    try {
      for (const i of selectedEntityIndices) {
        const e = newEntityCandidates[i]
        await worldEntitiesApi.create({
          novel_id: novelId,
          type: e.type as 'item' | 'system',
          name: e.name,
          description: e.description,
        })
      }
      qc.invalidateQueries({ queryKey: ['world-entities', novelId] })
      const remaining = newEntityCandidates.filter((_, i) => !selectedEntityIndices.has(i))
      setNewEntityCandidates(remaining)
      setSelectedEntityIndices(new Set())
    } finally {
      setAddingEntities(false)
    }
  }, [newEntityCandidates, selectedEntityIndices, addingEntities, novelId, qc])

  return {
    // state
    newCharCandidates,
    newEntityCandidates,
    selectedCharIndices,
    selectedEntityIndices,
    addingChars,
    addingEntities,
    isLoadingSuggestions,
    isCurrentlyGenerating,
    // actions
    handleGenerate,
    handleAbortOrGenerate,
    handleFetchSuggestions,
    toggleCharSelection,
    toggleEntitySelection,
    handleAddNewChars,
    handleAddNewEntities,
    setNewCharCandidates,
    setNewEntityCandidates,
  }
}
