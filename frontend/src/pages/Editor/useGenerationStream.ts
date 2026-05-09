import { useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import {
  chaptersApi, charactersApi, generationApi, worldEntitiesApi, locationsApi, techniquesApi,
  streamChapterGeneration, streamChapterRewrite,
} from '@/api/client'
import type { SSEMessage, AgentDoneData, TotalUsageData, OriginalDraftData, NewCharactersData, NewEntitiesData, NewLocationsData, NewTechniquesData, LlmCallData, ContextStepData } from '@/api/client'
import { type AgentLogEntry } from '@/components/AgentLog/AgentLog'
import { useGenerationStore } from '@/store/generationStore'
import { useEditorStore } from '@/store/editorStore'
import { useDevLogStore } from '@/store/devLogStore'
import { useQueryClient } from '@tanstack/react-query'

export interface GenerationStreamState {
  newCharCandidates: Array<{ name: string; role: string; description: string }>
  newEntityCandidates: Array<{ name: string; type: string; description: string }>
  newLocationCandidates: Array<{ name: string; type: string; description: string; parent_name: string }>
  newTechCandidates: Array<{ name: string; type: string; description: string }>
  selectedCharIndices: Set<number>
  selectedEntityIndices: Set<number>
  selectedLocationIndices: Set<number>
  selectedTechIndices: Set<number>
  addingChars: boolean
  addingEntities: boolean
  addingLocations: boolean
  addingTechs: boolean
  isLoadingSuggestions: boolean
  isDiscovering: boolean
}

export interface GenerationStreamActions {
  handleGenerate: () => void
  handleAbortOrGenerate: () => void
  handleFetchSuggestions: () => Promise<void>
  handleDiscover: (chapterId: number) => Promise<void>
  toggleCharSelection: (i: number) => void
  toggleEntitySelection: (i: number) => void
  toggleTechSelection: (i: number) => void
  handleAddNewChars: () => Promise<void>
  handleAddNewEntities: () => Promise<void>
  toggleLocationSelection: (i: number) => void
  handleAddNewLocations: () => Promise<void>
  handleAddNewTechs: () => Promise<void>
  setNewCharCandidates: (v: Array<{ name: string; role: string; description: string }>) => void
  setNewEntityCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
  setNewLocationCandidates: (v: Array<{ name: string; type: string; description: string; parent_name: string }>) => void
  setNewTechCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
}

export function useGenerationStream(
  novelId: number,
  selectedChapterNum: number,
  selectedVolume: number,
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
  const [newLocationCandidates, setNewLocationCandidates] = useState<Array<{ name: string; type: string; description: string; parent_name: string }>>([])
  const [selectedEntityIndices, setSelectedEntityIndices] = useState<Set<number>>(new Set())
  const [selectedLocationIndices, setSelectedLocationIndices] = useState<Set<number>>(new Set())
  const [addingChars, setAddingChars] = useState(false)
  const [addingEntities, setAddingEntities] = useState(false)
  const [addingLocations, setAddingLocations] = useState(false)
  const [newTechCandidates, setNewTechCandidates] = useState<Array<{ name: string; type: string; description: string }>>([])
  const [selectedTechIndices, setSelectedTechIndices] = useState<Set<number>>(new Set())
  const [addingTechs, setAddingTechs] = useState(false)
  const [isLoadingSuggestions, setIsLoadingSuggestions] = useState(false)
  const [isDiscovering, setIsDiscovering] = useState(false)

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

  // ── Discover (manual re-discovery) ───────────────────────────────────────
  const handleDiscover = useCallback(async (chapterId: number) => {
    setIsDiscovering(true)
    setNewCharCandidates([])
    setNewEntityCandidates([])
    setNewLocationCandidates([])
    setNewTechCandidates([])
    try {
      const result = await chaptersApi.discover(chapterId)
      if (result.characters?.length) {
        setNewCharCandidates(result.characters)
        setSelectedCharIndices(new Set(result.characters.map((_, i) => i)))
      }
      if (result.entities?.length) {
        setNewEntityCandidates(result.entities)
        setSelectedEntityIndices(new Set(result.entities.map((_, i) => i)))
      }
      if (result.locations?.length) {
        setNewLocationCandidates(result.locations)
        setSelectedLocationIndices(new Set(result.locations.map((_, i) => i)))
      }
      if (result.techniques?.length) {
        setNewTechCandidates(result.techniques)
        setSelectedTechIndices(new Set(result.techniques.map((_, i) => i)))
      }
      const total = (result.characters?.length || 0) + (result.entities?.length || 0) +
        (result.locations?.length || 0) + (result.techniques?.length || 0)
      if (total === 0) toast('未发现新的角色、道具、地点或功法', { icon: 'ℹ️' })
    } catch (e) {
      console.error('Discover failed:', e)
      toast.error('发现失败')
    } finally {
      setIsDiscovering(false)
    }
  }, [novelId])

  // ── Generate ─────────────────────────────────────────────────────────────
  const handleGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating) return

    gs.startGeneration(novelId, novelTitle, selectedChapterNum)
    setChapterSuggestions(novelId, selectedChapterNum, [])
    setNewCharCandidates([])
    setNewEntityCandidates([])
    setNewLocationCandidates([])
    setNewTechCandidates([])

    let entryCounter = 0
    const runningEntryIds: Map<string, string> = new Map()

    const ctrl = streamChapterGeneration(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        volume: selectedVolume,
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
          case 'new_locations': {
            const d = msg.data as NewLocationsData
            if (d.candidates?.length) {
              setNewLocationCandidates(d.candidates)
              setSelectedLocationIndices(new Set(d.candidates.map((_, i) => i)))
            }
            break
          }
          case 'new_techniques': {
            const d = msg.data as NewTechniquesData
            if (d.candidates?.length) {
              setNewTechCandidates(d.candidates)
              setSelectedTechIndices(new Set(d.candidates.map((_, i) => i)))
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
          case 'context_step': {
            const d = msg.data as ContextStepData
            s.addContextStep(d)
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
  }, [novelId, selectedChapterNum, selectedVolume, instruction, targetWords, novelTitle, qc, setChapterSuggestions])

  // ── Abort / Generate ─────────────────────────────────────────────────────
  const handleAbortOrGenerate = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating && gs.novelId === novelId && gs.chapterNum === selectedChapterNum) {
      gs.abortGeneration()
      return
    }
    handleGenerate()
  }, [novelId, selectedChapterNum, handleGenerate])

  // ── Rewrite ─────────────────────────────────────────────────────────────
  const handleRewrite = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating) return

    const annotations = useEditorStore.getState().getAnnotations(novelId, selectedChapterNum)
    if (!annotations.length) return

    gs.startGeneration(novelId, novelTitle, selectedChapterNum)

    let entryCounter = 0
    const runningEntryIds: Map<string, string> = new Map()

    const ctrl = streamChapterRewrite(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        annotations: annotations.map(a => ({ paragraph: a.paragraph, text: a.text })),
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
            useEditorStore.getState().clearAnnotations(novelId, selectedChapterNum)
            break
          case 'original_draft': {
            const d = msg.data as OriginalDraftData
            s.setOriginalDraft(d.text)
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
          case 'context_step': {
            const d = msg.data as ContextStepData
            s.addContextStep(d)
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
  }, [novelId, selectedChapterNum, targetWords, novelTitle, qc])

  const handleRewriteOrAbort = useCallback(() => {
    const gs = useGenerationStore.getState()
    if (gs.isGenerating && gs.novelId === novelId && gs.chapterNum === selectedChapterNum) {
      gs.abortGeneration()
      return
    }
    handleRewrite()
  }, [novelId, selectedChapterNum, handleRewrite])

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

  // ── Discovery: Location ───────────────────────────────────────────────────
  const toggleLocationSelection = useCallback((i: number) => {
    setSelectedLocationIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewLocations = useCallback(async () => {
    if (!selectedLocationIndices.size || addingLocations) return
    setAddingLocations(true)
    try {
      const existingLocations = await locationsApi.list(novelId)
      const nameToId = new Map(existingLocations.map(l => [l.name, l.id]))
      for (const i of selectedLocationIndices) {
        const loc = newLocationCandidates[i]
        const parentId = loc.parent_name ? (nameToId.get(loc.parent_name) ?? null) : null
        await locationsApi.create({
          novel_id: novelId,
          name: loc.name,
          type: loc.type,
          description: loc.description,
          parent_id: parentId,
        })
      }
      qc.invalidateQueries({ queryKey: ['locations', novelId] })
      const remaining = newLocationCandidates.filter((_, i) => !selectedLocationIndices.has(i))
      setNewLocationCandidates(remaining)
      setSelectedLocationIndices(new Set())
    } finally {
      setAddingLocations(false)
    }
  }, [newLocationCandidates, selectedLocationIndices, addingLocations, novelId, qc])

  // ── Discovery: Technique ──────────────────────────────────────────────────
  const toggleTechSelection = useCallback((i: number) => {
    setSelectedTechIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewTechs = useCallback(async () => {
    if (!selectedTechIndices.size || addingTechs) return
    setAddingTechs(true)
    try {
      for (const i of selectedTechIndices) {
        const t = newTechCandidates[i]
        await techniquesApi.create({
          novel_id: novelId,
          name: t.name,
          type: t.type,
          description: t.description,
        })
      }
      qc.invalidateQueries({ queryKey: ['techniques', novelId] })
      const remaining = newTechCandidates.filter((_, i) => !selectedTechIndices.has(i))
      setNewTechCandidates(remaining)
      setSelectedTechIndices(new Set())
    } finally {
      setAddingTechs(false)
    }
  }, [newTechCandidates, selectedTechIndices, addingTechs, novelId, qc])

  return {
    // state
    newCharCandidates,
    newEntityCandidates,
    newLocationCandidates,
    newTechCandidates,
    selectedCharIndices,
    selectedEntityIndices,
    selectedLocationIndices,
    selectedTechIndices,
    addingChars,
    addingEntities,
    addingLocations,
    addingTechs,
    isLoadingSuggestions,
    isDiscovering,
    isCurrentlyGenerating,
    // actions
    handleGenerate,
    handleAbortOrGenerate,
    handleRewrite,
    handleRewriteOrAbort,
    handleFetchSuggestions,
    handleDiscover,
    toggleCharSelection,
    toggleEntitySelection,
    toggleLocationSelection,
    toggleTechSelection,
    handleAddNewChars,
    handleAddNewEntities,
    handleAddNewLocations,
    handleAddNewTechs,
    setNewCharCandidates,
    setNewEntityCandidates,
    setNewLocationCandidates,
    setNewTechCandidates,
  }
}
