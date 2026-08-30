import { useState, useCallback } from 'react'
import toast from 'react-hot-toast'
import {
  chaptersApi, charactersApi, worldEntitiesApi, locationsApi, techniquesApi, factionsApi,
  storyThreadsApi, streamChapterGeneration, streamChapterRewrite,
} from '@/api/client'
import type { SSEMessage, AgentDoneData, TotalUsageData, OriginalDraftData, NewCharactersData, NewEntitiesData, NewLocationsData, NewTechniquesData, NewFactionsData, NewThreadsData, ThreadResolutionsData, LlmCallData, ContextStepData, Character } from '@/api/client'
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
  newFactionCandidates: Array<{ name: string; type: string; description: string }>
  selectedCharIndices: Set<number>
  selectedEntityIndices: Set<number>
  selectedLocationIndices: Set<number>
  selectedTechIndices: Set<number>
  selectedFactionIndices: Set<number>
  addingChars: boolean
  addingEntities: boolean
  addingLocations: boolean
  addingTechs: boolean
  addingFactions: boolean
  isDiscovering: boolean
}

export interface GenerationStreamActions {
  handleGenerate: () => void
  handleAbortOrGenerate: () => void
  handleDiscover: (chapterId: number) => Promise<void>
  toggleCharSelection: (i: number) => void
  toggleEntitySelection: (i: number) => void
  toggleTechSelection: (i: number) => void
  handleAddNewChars: () => Promise<void>
  handleAddNewEntities: () => Promise<void>
  toggleLocationSelection: (i: number) => void
  handleAddNewLocations: () => Promise<void>
  handleAddNewTechs: () => Promise<void>
  toggleFactionSelection: (i: number) => void
  handleAddNewFactions: () => Promise<void>
  setNewCharCandidates: (v: Array<{ name: string; role: string; description: string }>) => void
  setNewEntityCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
  setNewLocationCandidates: (v: Array<{ name: string; type: string; description: string; parent_name: string }>) => void
  setNewTechCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
  setNewFactionCandidates: (v: Array<{ name: string; type: string; description: string }>) => void
}

export function useGenerationStream(
  novelId: number,
  selectedChapterNum: number,
  selectedVolume: number,
  instruction: string,
  targetWords: number,
  novelTitle: string,
  rewriteModel: string = '',
  resetRewriteModel?: () => void,
  pov: string = '',
) {
  const qc = useQueryClient()
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
  const [newFactionCandidates, setNewFactionCandidates] = useState<Array<{ name: string; type: string; description: string }>>([])
  const [selectedFactionIndices, setSelectedFactionIndices] = useState<Set<number>>(new Set())
  const [addingFactions, setAddingFactions] = useState(false)
  const [isDiscovering, setIsDiscovering] = useState(false)
  const [reviewCharacters, setReviewCharacters] = useState<Character[]>([])
  const [newThreads, setNewThreads] = useState<NewThreadsData['threads']>([])
  const [selectedThreadIndices, setSelectedThreadIndices] = useState<Set<number>>(new Set())
  const [addingThreads, setAddingThreads] = useState(false)
  const [threadResolutions, setThreadResolutions] = useState<ThreadResolutionsData['resolutions']>([])

  const isCurrentlyGenerating = useGenerationStore((s) =>
    s.isGenerating && s.novelId === novelId && s.chapterNum === selectedChapterNum,
  )

  // ── Discover (manual re-discovery) ───────────────────────────────────────
  const handleDiscover = useCallback(async (chapterId: number) => {
    setIsDiscovering(true)
    setNewCharCandidates([])
    setNewEntityCandidates([])
    setNewLocationCandidates([])
    setNewTechCandidates([])
    setNewFactionCandidates([])
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
      if (result.factions?.length) {
        setNewFactionCandidates(result.factions)
        setSelectedFactionIndices(new Set(result.factions.map((_, i) => i)))
      }
      const total = (result.characters?.length || 0) + (result.entities?.length || 0) +
        (result.locations?.length || 0) + (result.techniques?.length || 0) + (result.factions?.length || 0)
      if (total === 0) toast('未发现新的角色、道具、地点、功法或势力', { icon: 'ℹ️' })
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
    setNewCharCandidates([])
    setNewEntityCandidates([])
    setNewLocationCandidates([])
    setNewTechCandidates([])
    setNewFactionCandidates([])
    setNewThreads([])
    setThreadResolutions([])

    let entryCounter = 0
    const runningEntryIds: Map<string, string> = new Map()

    const ctrl = streamChapterGeneration(
      {
        novel_id: novelId,
        chapter_number: selectedChapterNum,
        volume: selectedVolume,
        instruction,
        target_words: targetWords,
        pov: pov || undefined,
      },
      (msg: SSEMessage) => {
        const s = useGenerationStore.getState()
        switch (msg.event) {
          case 'stage':
            {
              const stage = msg.data as string
              s.setAgentStage(stage)
              if (stage.startsWith('revising_')) {
                s.clearStreamingText()
              }
            }
            break
          case 'token':
            s.appendToken(msg.data as string)
            break
          case 'agent_start': {
            const d = msg.data as { agent: string; label: string; model?: string }
            const entryId = `${d.agent}-${entryCounter++}`
            const entry: AgentLogEntry = {
              id: entryId,
              agent: d.agent,
              label: d.label,
              model: d.model,
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
                ...(d.label ? { label: d.label } : {}),
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
            qc.invalidateQueries({ queryKey: ['novel', novelId] })
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
          case 'new_factions': {
            const d = msg.data as NewFactionsData
            if (d.candidates?.length) {
              setNewFactionCandidates(d.candidates)
              setSelectedFactionIndices(new Set(d.candidates.map((_, i) => i)))
            }
            break
          }
          case 'new_threads': {
            const d = msg.data as NewThreadsData
            if (d.threads?.length) {
              setNewThreads(d.threads)
              setSelectedThreadIndices(new Set(d.threads.map((_, i) => i)))
            }
            break
          }
          case 'thread_resolutions': {
            const d = msg.data as ThreadResolutionsData
            if (d.resolutions?.length) {
              setThreadResolutions(d.resolutions)
            }
            break
          }
          case 'critic_issues': {
            const d = msg.data as { issues_text: string }
            const criticEntryId = runningEntryIds.get('critic')
            if (criticEntryId && d.issues_text) {
              s.updateLogEntry(criticEntryId, { issues: d.issues_text })
            }
            break
          }
          case 'review_result': {
            const d = msg.data as { issues?: Array<{ type: string; severity: string; chapters: number[]; description: string }> }
            if (d.issues?.length) {
              s.setWarning(`剧情细节审查发现 ${d.issues.length} 个问题，正在尝试修订`)
              const detailEntryId = runningEntryIds.get('detail_review')
              if (detailEntryId) {
                s.updateLogEntry(detailEntryId, { issues: d.issues })
              }
            }
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
          case 'llm_request': {
            const payload = msg.data as Record<string, unknown>
            useDevLogStore.getState().addEntry({
              type: 'llm_call',
              agent: 'writer',
              model: String(payload.model || ''),
              llmStatus: 'ok',
              inputTokens: 0,
              outputTokens: 0,
              durationMs: 0,
              payload,
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
  }, [novelId, selectedChapterNum, selectedVolume, instruction, targetWords, novelTitle, pov, qc])

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
        rewrite_model: rewriteModel || undefined,
      },
      (msg: SSEMessage) => {
        const s = useGenerationStore.getState()
        switch (msg.event) {
          case 'stage':
            {
              const stage = msg.data as string
              s.setAgentStage(stage)
              if (stage.startsWith('revising_')) {
                s.clearStreamingText()
              }
            }
            break
          case 'token':
            s.appendToken(msg.data as string)
            break
          case 'agent_start': {
            const d = msg.data as { agent: string; label: string; model?: string }
            const entryId = `${d.agent}-${entryCounter++}`
            const entry: AgentLogEntry = {
              id: entryId,
              agent: d.agent,
              label: d.label,
              model: d.model,
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
                ...(d.label ? { label: d.label } : {}),
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
            qc.invalidateQueries({ queryKey: ['novel', novelId] })
            useEditorStore.getState().clearAnnotations(novelId, selectedChapterNum)
            break
          case 'original_draft': {
            const d = msg.data as OriginalDraftData
            s.setOriginalDraft(d.text)
            break
          }
          case 'critic_issues': {
            const d = msg.data as { issues_text: string }
            const criticEntryId = runningEntryIds.get('critic')
            if (criticEntryId && d.issues_text) {
              s.updateLogEntry(criticEntryId, { issues: d.issues_text })
            }
            break
          }
          case 'review_result': {
            const d = msg.data as { issues?: Array<{ type: string; severity: string; chapters: number[]; description: string }> }
            if (d.issues?.length) {
              s.setWarning(`剧情细节审查发现 ${d.issues.length} 个问题，正在尝试修订`)
              const detailEntryId = runningEntryIds.get('detail_review')
              if (detailEntryId) {
                s.updateLogEntry(detailEntryId, { issues: d.issues })
              }
            }
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
          case 'llm_request': {
            const payload = msg.data as Record<string, unknown>
            useDevLogStore.getState().addEntry({
              type: 'llm_call',
              agent: 'writer',
              model: String(payload.model || ''),
              llmStatus: 'ok',
              inputTokens: 0,
              outputTokens: 0,
              durationMs: 0,
              payload,
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
        resetRewriteModel?.()
      },
    )

    useGenerationStore.getState().setAbortController(ctrl)
  }, [novelId, selectedChapterNum, targetWords, novelTitle, qc, rewriteModel, resetRewriteModel])

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
    const created: Character[] = []
    try {
      for (const i of selectedCharIndices) {
        const char = await charactersApi.create({ ...newCharCandidates[i], novel_id: novelId })
        created.push(char)
      }
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      const remaining = newCharCandidates.filter((_, i) => !selectedCharIndices.has(i))
      setNewCharCandidates(remaining)
      setSelectedCharIndices(new Set())

      // 创建接口已在后端生成过角色卡（full_sheet），直接进入审阅弹窗
      if (created.length > 0) {
        setReviewCharacters(created)
      }
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

  // ── Discovery: Faction ────────────────────────────────────────────────────
  const toggleFactionSelection = useCallback((i: number) => {
    setSelectedFactionIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewFactions = useCallback(async () => {
    if (!selectedFactionIndices.size || addingFactions) return
    setAddingFactions(true)
    try {
      for (const i of selectedFactionIndices) {
        const f = newFactionCandidates[i]
        await factionsApi.create({
          novel_id: novelId,
          name: f.name,
          type: f.type,
          description: f.description,
        })
      }
      qc.invalidateQueries({ queryKey: ['factions', novelId] })
      const remaining = newFactionCandidates.filter((_, i) => !selectedFactionIndices.has(i))
      setNewFactionCandidates(remaining)
      setSelectedFactionIndices(new Set())
    } finally {
      setAddingFactions(false)
    }
  }, [newFactionCandidates, selectedFactionIndices, addingFactions, novelId, qc])

  // ── Discovery: 伏笔/秘密 ──────────────────────────────────────────────────
  // 候选留在发现面板里，作者可以先读完正文再决定收哪几条，不像弹窗那样关掉就没了。
  const toggleThreadSelection = useCallback((i: number) => {
    setSelectedThreadIndices(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }, [])

  const handleAddNewThreads = useCallback(async () => {
    if (!selectedThreadIndices.size || addingThreads) return
    setAddingThreads(true)
    try {
      for (const i of selectedThreadIndices) {
        const t = newThreads[i]
        await storyThreadsApi.create({
          novel_id: novelId,
          kind: t.kind,
          title: t.title,
          content: t.content,
          importance: t.importance,
          known_by: t.known_by ?? [],
          related_entities: t.related_entities ?? [],
          source_chapter: t.source_chapter ?? 0,
          source: 'auto',
        })
      }
      qc.invalidateQueries({ queryKey: ['story-threads', novelId] })
      toast.success(`已添加 ${selectedThreadIndices.size} 条`)
      setNewThreads(newThreads.filter((_, i) => !selectedThreadIndices.has(i)))
      setSelectedThreadIndices(new Set())
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '添加失败')
    } finally {
      setAddingThreads(false)
    }
  }, [newThreads, selectedThreadIndices, addingThreads, novelId, qc])

  return {
    // state
    newCharCandidates,
    newEntityCandidates,
    newLocationCandidates,
    newTechCandidates,
    newFactionCandidates,
    selectedCharIndices,
    selectedEntityIndices,
    selectedLocationIndices,
    selectedTechIndices,
    selectedFactionIndices,
    addingChars,
    addingEntities,
    addingLocations,
    addingTechs,
    addingFactions,
    isDiscovering,
    isCurrentlyGenerating,
    // actions
    handleGenerate,
    handleAbortOrGenerate,
    handleRewrite,
    handleRewriteOrAbort,
    handleDiscover,
    toggleCharSelection,
    toggleEntitySelection,
    toggleLocationSelection,
    toggleTechSelection,
    toggleFactionSelection,
    handleAddNewChars,
    handleAddNewEntities,
    handleAddNewLocations,
    handleAddNewTechs,
    handleAddNewFactions,
    reviewCharacters,
    setReviewCharacters,
    newThreads,
    setNewThreads,
    selectedThreadIndices,
    addingThreads,
    toggleThreadSelection,
    handleAddNewThreads,
    threadResolutions,
    setThreadResolutions,
    setNewCharCandidates,
    setNewEntityCandidates,
    setNewLocationCandidates,
    setNewTechCandidates,
    setNewFactionCandidates,
  }
}
