import { useState, useRef, useCallback, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check, ChevronDown, ChevronRight, Layers, Pencil, Trash2,
  Plus, X, Loader2,
} from 'lucide-react'
import { chaptersApi, volumesApi, type Chapter, type Novel, type Volume } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  novelId: number
  novel: Novel | undefined
  chapters: Chapter[]
  selectedChapterNum: number
  isGenerating: boolean
  generatingNovelId: number | null
  generatingChapterNum: number | null
  onSelectChapter: (num: number) => void
  onNewChapter: () => void
}

export default function ProjectTab({
  novelId,
  novel,
  chapters,
  selectedChapterNum,
  isGenerating,
  generatingNovelId,
  generatingChapterNum,
  onSelectChapter,
  onNewChapter,
}: Props) {
  const qc = useQueryClient()

  const { data: volumes = [] } = useQuery({
    queryKey: ['volumes', novelId],
    queryFn: () => volumesApi.list(novelId),
  })

  // Multi-select mode
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const lastClickedIdx = useRef<number | null>(null)

  // Collapsed volumes
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())

  // Create volume modal
  const [showCreate, setShowCreate] = useState(false)
  const [createForm, setCreateForm] = useState({ title: '', description: '' })
  const [saving, setSaving] = useState(false)

  // Edit volume
  const [editingVol, setEditingVol] = useState<Volume | null>(null)
  const [editForm, setEditForm] = useState({ title: '', description: '' })

  // Move to existing volume
  const [showMoveMenu, setShowMoveMenu] = useState(false)

  const totalWords = useMemo(() => chapters.reduce((sum, c) => sum + (c.word_count || 0), 0), [chapters])
  const totalTokens = useMemo(() => Math.round(totalWords * 1.5), [totalWords])

  const volumeNumSet = new Set(volumes.map(v => v.number))
  const volumeMap = new Map(volumes.map(v => [v.number, v]))

  // Group chapters: all Volume records are shown, even before any chapters exist.
  // Chapters whose volume number has no matching Volume record go to "unassigned" (key = -1).
  const UNASSIGNED = -1
  const byVol = new Map<number, Chapter[]>()
  for (const ch of chapters) {
    const key = volumeNumSet.has(ch.volume) ? ch.volume : UNASSIGNED
    const arr = byVol.get(key) || []
    arr.push(ch)
    byVol.set(key, arr)
  }

  const groups: { volNum: number; vol: Volume | undefined; chapters: Chapter[] }[] = []
  // Real volumes first, sorted by number, including empty generated outline volumes.
  for (const vol of [...volumes].sort((a, b) => a.number - b.number)) {
    groups.push({ volNum: vol.number, vol, chapters: byVol.get(vol.number) || [] })
  }
  // Unassigned last
  if (byVol.has(UNASSIGNED)) {
    groups.push({ volNum: UNASSIGNED, vol: undefined, chapters: byVol.get(UNASSIGNED)! })
  }

  const hasVolumes = volumes.length > 0

  // Flat ordered list of all chapter ids for shift-click range selection
  const flatChapterIds = chapters.map(c => c.id)

  const handleSelect = useCallback((id: number, shiftKey: boolean) => {
    const currentIdx = flatChapterIds.indexOf(id)
    setSelected(prev => {
      const next = new Set(prev)
      if (shiftKey && lastClickedIdx.current !== null) {
        const from = Math.min(lastClickedIdx.current, currentIdx)
        const to = Math.max(lastClickedIdx.current, currentIdx)
        for (let i = from; i <= to; i++) {
          next.add(flatChapterIds[i])
        }
      } else {
        if (next.has(id)) next.delete(id)
        else next.add(id)
      }
      return next
    })
    lastClickedIdx.current = currentIdx
  }, [flatChapterIds])

  const toggleCollapse = (volNum: number) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(volNum)) next.delete(volNum)
      else next.add(volNum)
      return next
    })
  }

  const exitSelectMode = () => {
    setSelectMode(false)
    setSelected(new Set())
    setShowMoveMenu(false)
    lastClickedIdx.current = null
  }

  const handleCreateVolume = async () => {
    if (!createForm.title.trim()) return
    setSaving(true)
    try {
      // Pick a volume number that doesn't collide with any existing chapter.volume or Volume.number
      const maxInChapters = chapters.length > 0 ? Math.max(...chapters.map(c => c.volume)) : 0
      const maxInVolumes = volumes.length > 0 ? Math.max(...volumes.map(v => v.number)) : 0
      const newNum = Math.max(maxInChapters, maxInVolumes) + 1
      await volumesApi.create({ novel_id: novelId, number: newNum, title: createForm.title, description: createForm.description })
      if (selected.size > 0) {
        await chaptersApi.batchVolume([...selected], newNum)
        qc.invalidateQueries({ queryKey: ['chapters', novelId] })
      }
      qc.invalidateQueries({ queryKey: ['volumes', novelId] })
      setShowCreate(false)
      setCreateForm({ title: '', description: '' })
      exitSelectMode()
      toast.success('分卷已创建')
    } finally { setSaving(false) }
  }

  const handleMoveToVolume = async (volNum: number) => {
    if (selected.size === 0) return
    await chaptersApi.batchVolume([...selected], volNum)
    qc.invalidateQueries({ queryKey: ['chapters', novelId] })
    setShowMoveMenu(false)
    exitSelectMode()
    toast.success('章节已移动')
  }

  const handleEditVolume = async () => {
    if (!editingVol || !editForm.title.trim()) return
    setSaving(true)
    try {
      await volumesApi.update(editingVol.id, editForm)
      qc.invalidateQueries({ queryKey: ['volumes', novelId] })
      setEditingVol(null)
      toast.success('已保存')
    } finally { setSaving(false) }
  }

  const handleDeleteVolume = async (vol: Volume) => {
    if (!confirm(`确认删除「${vol.title}」？章节不会被删除。`)) return
    await volumesApi.delete(vol.id)
    qc.invalidateQueries({ queryKey: ['volumes', novelId] })
    toast.success('分卷已删除')
  }

  const renderChapter = (c: Chapter) => {
    const isActive = c.number === selectedChapterNum
    const isGen = isGenerating && generatingNovelId === c.novel_id && generatingChapterNum === c.number
    return (
      <div key={c.id} className="flex items-center gap-1">
        {selectMode && (
          <input
            type="checkbox"
            checked={selected.has(c.id)}
            onChange={(e) => handleSelect(c.id, e.nativeEvent instanceof MouseEvent && (e.nativeEvent as MouseEvent).shiftKey)}
            className="shrink-0 rounded border-gray-300 text-primary focus:ring-primary/50 h-3.5 w-3.5"
          />
        )}
        <button
          onClick={(e) => {
            if (selectMode) {
              handleSelect(c.id, e.shiftKey)
            } else {
              onSelectChapter(c.number)
            }
          }}
          className={`flex-1 text-left px-2.5 py-1.5 rounded-md text-sm transition-colors ${
            isActive && !selectMode
              ? 'bg-primary text-primary-foreground'
              : selected.has(c.id)
                ? 'bg-primary/10'
                : 'hover:bg-muted'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="truncate">第{c.number}章</span>
            {isGen
              ? <span className="w-2 h-2 rounded-full bg-primary animate-pulse shrink-0" />
              : c.status === 'confirmed'
                ? <Check className="w-3 h-3 shrink-0 opacity-70" />
                : null}
          </div>
          {c.title && c.title !== `第${c.number}章` && (
            <p className={`text-xs truncate mt-0.5 ${isActive && !selectMode ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
              {c.title}
            </p>
          )}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      {novel && (
        <div className="px-3 py-2.5 border-b flex items-center justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{novel.title}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {chapters.length} 章 · {volumes.length > 0 ? `${volumes.length} 卷` : `第${novel.current_volume || 1}卷`}
            </p>
            {totalWords > 0 && (
              <p className="text-[11px] text-muted-foreground/70 mt-0.5">
                {totalWords.toLocaleString()} 字 · ~{totalTokens.toLocaleString()} tokens
              </p>
            )}
          </div>
          <button
            onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}
            className={`shrink-0 p-1 rounded transition-colors ${selectMode ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-foreground hover:bg-muted'}`}
            title="分卷管理"
          >
            <Layers className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Chapter list */}
      <div className="overflow-y-auto flex-1 p-2 space-y-0.5">
        {hasVolumes ? (
          groups.map(({ volNum, vol, chapters: chs }) => (
            <div key={volNum}>
              {/* Volume header */}
              {vol ? (
                <div className="group flex items-center gap-1 px-1 py-1.5 rounded-md hover:bg-muted/50 cursor-pointer"
                  onClick={() => toggleCollapse(volNum)}>
                  {collapsed.has(volNum)
                    ? <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
                    : <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
                  }
                  <div className="flex-1 min-w-0">
                    <span className="text-xs font-medium truncate block">{vol.title}</span>
                    {vol.description && (
                      <span className="text-[10px] text-muted-foreground truncate block">{vol.description}</span>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground shrink-0">{chs.length}章</span>
                  <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); setEditForm({ title: vol.title, description: vol.description }); setEditingVol(vol) }}
                      className="p-0.5 hover:text-foreground text-muted-foreground">
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); handleDeleteVolume(vol) }}
                      className="p-0.5 hover:text-destructive text-muted-foreground">
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              ) : (
                <div className="px-1 py-1.5 flex items-center gap-1 cursor-pointer" onClick={() => toggleCollapse(UNASSIGNED)}>
                  {collapsed.has(UNASSIGNED)
                    ? <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />
                    : <ChevronDown className="w-3 h-3 text-muted-foreground shrink-0" />
                  }
                  <span className="text-xs text-muted-foreground">未分卷</span>
                  <span className="text-[10px] text-muted-foreground ml-auto">{chs.length}章</span>
                </div>
              )}
              {/* Chapters in this volume */}
              {!collapsed.has(volNum) && (
                <div className="ml-2 space-y-0.5">
                  {chs.length > 0 ? chs.map(renderChapter) : (
                    <div className="px-2.5 py-1.5 text-xs text-muted-foreground">
                      暂无章节
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        ) : (
          chapters.map(renderChapter)
        )}

        <button
          onClick={onNewChapter}
          className="w-full text-left px-2.5 py-2 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors border border-dashed mt-2"
        >
          + 新章节
        </button>
      </div>

      {/* Select mode action bar */}
      {selectMode && (
        <div className="px-2 py-2 border-t space-y-1.5 shrink-0 bg-muted/30">
          <div className="flex items-center justify-between px-1">
            <span className="text-[10px] text-muted-foreground">已选 {selected.size} 章</span>
            <button onClick={exitSelectMode} className="text-[10px] text-muted-foreground hover:text-foreground">
              <X className="w-3 h-3" />
            </button>
          </div>
          <div className="flex gap-1.5">
            <button
              onClick={() => setShowCreate(true)}
              disabled={selected.size === 0}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] bg-primary text-primary-foreground rounded-md disabled:opacity-50"
            >
              <Plus className="w-3 h-3" /> 新建分卷
            </button>
            {volumes.length > 0 && (
              <div className="relative flex-1">
                <button
                  onClick={() => setShowMoveMenu(!showMoveMenu)}
                  disabled={selected.size === 0}
                  className="w-full flex items-center justify-center gap-1 py-1.5 text-[11px] border rounded-md hover:bg-muted disabled:opacity-50"
                >
                  移入已有卷 <ChevronDown className="w-3 h-3" />
                </button>
                {showMoveMenu && (
                  <div className="absolute bottom-full mb-1 left-0 right-0 bg-background border rounded-lg shadow-lg z-10 max-h-40 overflow-y-auto">
                    {volumes.map(v => (
                      <button key={v.id} onClick={() => handleMoveToVolume(v.number)}
                        className="w-full text-left px-3 py-1.5 text-xs hover:bg-muted truncate">
                        {v.title}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Create volume modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={e => e.stopPropagation()}>
            <h3 className="font-medium text-sm">新建分卷</h3>
            <input
              value={createForm.title}
              onChange={e => setCreateForm({ ...createForm, title: e.target.value })}
              placeholder="卷名称，如：第一卷 初来乍到"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <textarea
              value={createForm.description}
              onChange={e => setCreateForm({ ...createForm, description: e.target.value })}
              placeholder="简要描述（可选）"
              rows={3}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
            />
            {selected.size > 0 && (
              <p className="text-xs text-muted-foreground">将 {selected.size} 个已选章节移入此卷</p>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleCreateVolume} disabled={saving || !createForm.title.trim()}
                className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '创建'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit volume modal */}
      {editingVol && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setEditingVol(null)}>
          <div className="bg-background rounded-xl p-5 w-80 space-y-3 shadow-lg" onClick={e => e.stopPropagation()}>
            <h3 className="font-medium text-sm">编辑分卷</h3>
            <input
              value={editForm.title}
              onChange={e => setEditForm({ ...editForm, title: e.target.value })}
              placeholder="卷名称"
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background"
              autoFocus
            />
            <textarea
              value={editForm.description}
              onChange={e => setEditForm({ ...editForm, description: e.target.value })}
              placeholder="简要描述（可选）"
              rows={3}
              className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setEditingVol(null)} className="px-3 py-1.5 text-sm rounded-lg hover:bg-muted">取消</button>
              <button onClick={handleEditVolume} disabled={saving || !editForm.title.trim()}
                className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg disabled:opacity-50">
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
