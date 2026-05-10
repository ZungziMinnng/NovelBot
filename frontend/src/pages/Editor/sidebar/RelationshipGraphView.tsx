import { useEffect, useRef, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Users, Check, X } from 'lucide-react'
import { charactersApi, type RelationshipNode, type RelationshipEdge, type Character } from '@/api/client'
import toast from 'react-hot-toast'
import { getRoleFill } from '@/constants/roles'
import {
  forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide,
  type SimulationNodeDatum, type SimulationLinkDatum,
} from 'd3-force'

interface Props {
  novelId: number
  focusCharacterId?: number
  onSelectCharacter?: (id: number, name: string) => void
}

type SimNode = RelationshipNode & SimulationNodeDatum
type SimLink = SimulationLinkDatum<SimNode> & { labels: RelationshipEdge['labels']; index?: number }


export default function RelationshipGraphView({ novelId, focusCharacterId, onSelectCharacter }: Props) {
  const qc = useQueryClient()
  const { data: graph, isLoading } = useQuery({
    queryKey: ['relationship-graph', novelId],
    queryFn: () => charactersApi.relationshipGraph(novelId),
  })
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })

  const containerRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ width: 400, height: 500 })
  const [nodes, setNodes] = useState<SimNode[]>([])
  const [links, setLinks] = useState<SimLink[]>([])
  const [hoveredEdge, setHoveredEdge] = useState<number | null>(null)
  const [hoveredNode, setHoveredNode] = useState<number | null>(null)
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null)
  const dragRef = useRef<{ nodeId: number; startX: number; startY: number } | null>(null)

  // Edge editing state
  const [editingEdge, setEditingEdge] = useState<number | null>(null)
  const [editLabels, setEditLabels] = useState<Array<{ from: string; desc: string; type?: 'initial' | 'current' }>>([])
  const [savingEdge, setSavingEdge] = useState(false)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) setDims({ width, height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!graph || !graph.nodes.length) {
      setNodes([])
      setLinks([])
      return
    }

    let filteredEdges = graph.edges
    let filteredNodeIds: Set<number>

    if (focusCharacterId) {
      filteredEdges = graph.edges.filter(
        (e) => e.source === focusCharacterId || e.target === focusCharacterId,
      )
      filteredNodeIds = new Set<number>()
      filteredNodeIds.add(focusCharacterId)
      for (const e of filteredEdges) {
        filteredNodeIds.add(e.source)
        filteredNodeIds.add(e.target)
      }
    } else {
      const hasEdges = filteredEdges.length > 0
      filteredNodeIds = new Set<number>()
      if (hasEdges) {
        for (const e of filteredEdges) {
          filteredNodeIds.add(e.source)
          filteredNodeIds.add(e.target)
        }
      } else {
        for (const n of graph.nodes) filteredNodeIds.add(n.id)
      }
    }

    const filteredNodes = graph.nodes.filter((n) => filteredNodeIds.has(n.id))
    const simNodes: SimNode[] = filteredNodes.map((n) => ({ ...n }))
    const nodeMap = new Map(simNodes.map((n) => [n.id, n]))

    const simLinks: SimLink[] = filteredEdges
      .filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
      .map((e) => ({
        source: nodeMap.get(e.source)!,
        target: nodeMap.get(e.target)!,
        labels: e.labels,
      }))

    if (simRef.current) simRef.current.stop()

    const sim = forceSimulation(simNodes)
      .force('link', forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance(100))
      .force('charge', forceManyBody().strength(-200))
      .force('center', forceCenter(dims.width / 2, dims.height / 2))
      .force('collide', forceCollide(35))
      .on('tick', () => {
        setNodes([...simNodes])
        setLinks([...simLinks])
      })

    simRef.current = sim
    return () => { sim.stop() }
  }, [graph, dims.width, dims.height, focusCharacterId])

  const handleMouseDown = useCallback((e: React.MouseEvent, nodeId: number) => {
    e.stopPropagation()
    const node = nodes.find((n) => n.id === nodeId)
    if (!node) return
    dragRef.current = { nodeId, startX: e.clientX, startY: e.clientY }

    const sim = simRef.current
    if (sim) {
      node.fx = node.x
      node.fy = node.y
      sim.alphaTarget(0.3).restart()
    }

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return
      const svg = containerRef.current?.querySelector('svg')
      if (!svg) return
      const rect = svg.getBoundingClientRect()
      node.fx = ev.clientX - rect.left
      node.fy = ev.clientY - rect.top
    }

    const onUp = () => {
      dragRef.current = null
      node.fx = null
      node.fy = null
      if (sim) sim.alphaTarget(0)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [nodes])

  // Edge editing
  const handleEdgeClick = useCallback((idx: number, link: SimLink) => {
    setEditingEdge(idx)
    setEditLabels(link.labels.map((l) => ({ ...l })))
  }, [])

  const handleSaveEdge = useCallback(async () => {
    if (editingEdge === null) return
    const link = links[editingEdge]
    if (!link) return
    setSavingEdge(true)
    try {
      const sourceNode = link.source as SimNode
      const targetNode = link.target as SimNode

      for (const label of editLabels) {
        const fromChar = characters.find((c) => c.name === label.from)
        if (!fromChar) continue
        const otherName = fromChar.id === sourceNode.id ? targetNode.name : sourceNode.name
        const oldState = fromChar.current_state || {}
        const relKey = label.type === 'initial' ? 'initial_relationships' : 'relationship_changes'
        const oldRels = (oldState[relKey] || {}) as Record<string, string>
        const newRels = { ...oldRels, [otherName]: label.desc }
        await charactersApi.update(fromChar.id, {
          current_state: { ...oldState, [relKey]: newRels },
        } as Partial<Character>)
      }

      qc.invalidateQueries({ queryKey: ['relationship-graph', novelId] })
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
      setEditingEdge(null)
      toast.success('关系已更新')
    } catch {
      toast.error('保存失败')
    } finally {
      setSavingEdge(false)
    }
  }, [editingEdge, links, editLabels, characters, novelId, qc])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        加载关系数据...
      </div>
    )
  }

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3 px-6">
        <Users className="w-8 h-8 opacity-30" />
        <p className="text-xs text-center">暂无角色数据。创建角色并确认章节后，关系网将自动生成。</p>
      </div>
    )
  }

  if (nodes.length === 0 && links.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground gap-3 px-6">
        <Users className="w-8 h-8 opacity-30" />
        <p className="text-xs text-center">
          {focusCharacterId ? '该角色暂无关系数据。' : '角色尚无关系数据。确认章节后，记忆 Agent 会自动提取角色间的关系。'}
        </p>
      </div>
    )
  }

  return (
    <div ref={containerRef} className="w-full h-full overflow-hidden relative">
      <svg width={dims.width} height={dims.height} className="select-none"
        onClick={() => { if (editingEdge !== null) setEditingEdge(null) }}>
        {/* Edges */}
        {links.map((link, i) => {
          const s = link.source as SimNode
          const t = link.target as SimNode
          if (s.x == null || t.x == null) return null
          const label = link.labels.map((l) => {
            const prefix = l.type === 'initial' ? '初始：' : l.type === 'current' ? '当前：' : ''
            return `${prefix}${l.desc}`
          }).join(' / ')
          const mx = (s.x + t.x) / 2
          const my = (s.y! + t.y!) / 2
          const isHovered = hoveredEdge === i
          const isEditing = editingEdge === i
          return (
            <g key={`e-${i}`}>
              <line
                x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                stroke={isEditing ? 'hsl(var(--primary))' : isHovered ? 'hsl(var(--primary))' : 'hsl(var(--border))'}
                strokeWidth={isEditing ? 2.5 : isHovered ? 2 : 1}
                className="transition-all"
              />
              <line
                x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                stroke="transparent"
                strokeWidth={12}
                onMouseEnter={() => setHoveredEdge(i)}
                onMouseLeave={() => setHoveredEdge(null)}
                onClick={(e) => { e.stopPropagation(); handleEdgeClick(i, link) }}
                className="cursor-pointer"
              />
              {isHovered && !isEditing && (
                <text
                  x={mx} y={my - 6}
                  textAnchor="middle"
                  className="text-[10px] fill-foreground pointer-events-none"
                >
                  {label}
                </text>
              )}
            </g>
          )
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          if (node.x == null || node.y == null) return null
          const fill = getRoleFill(node.role)
          const isHovered = hoveredNode === node.id
          const isFocus = focusCharacterId === node.id
          const r = isFocus ? 22 : isHovered ? 20 : 18
          return (
            <g
              key={`n-${node.id}`}
              transform={`translate(${node.x},${node.y})`}
              onMouseDown={(e) => handleMouseDown(e, node.id)}
              onMouseEnter={() => setHoveredNode(node.id)}
              onMouseLeave={() => setHoveredNode(null)}
              onClick={() => onSelectCharacter?.(node.id, node.name)}
              className="cursor-pointer"
            >
              <circle
                r={r}
                fill={fill}
                opacity={0.85}
                stroke={isFocus ? 'hsl(var(--primary))' : isHovered ? 'hsl(var(--foreground))' : 'none'}
                strokeWidth={isFocus ? 3 : 2}
                className="transition-all"
              />
              <text
                textAnchor="middle"
                dominantBaseline="central"
                className="text-[11px] fill-white font-bold pointer-events-none select-none"
              >
                {node.name.length <= 2 ? node.name : node.name.slice(0, 2)}
              </text>
              <text
                y={28}
                textAnchor="middle"
                className="text-[10px] fill-muted-foreground pointer-events-none select-none"
              >
                {node.name}
              </text>
              {isHovered && (
                <text
                  y={-26}
                  textAnchor="middle"
                  className="text-[10px] fill-foreground pointer-events-none"
                >
                  {node.role}
                </text>
              )}
            </g>
          )
        })}
      </svg>

      {/* Edge edit popover */}
      {editingEdge !== null && links[editingEdge] && (() => {
        const link = links[editingEdge]
        const s = link.source as SimNode
        const t = link.target as SimNode
        if (s.x == null || t.x == null) return null
        const px = (s.x + t.x) / 2
        const py = (s.y! + t.y!) / 2
        return (
          <div
            className="absolute bg-background border rounded-lg shadow-lg p-3 space-y-2 z-10"
            style={{ left: px - 100, top: py + 10, width: 200 }}
            onClick={(e) => e.stopPropagation()}
          >
            {editLabels.map((label, li) => (
              <div key={li} className="space-y-1">
                <p className="text-[10px] text-muted-foreground">
                  {label.from} →
                  {label.type && <span className="ml-1 text-[9px] opacity-60">({label.type === 'initial' ? '初始' : '当前'})</span>}
                </p>
                <input
                  value={label.desc}
                  onChange={(e) => setEditLabels((prev) => prev.map((l, j) => j === li ? { ...l, desc: e.target.value } : l))}
                  className="w-full text-xs border rounded px-2 py-1 bg-background focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
            ))}
            <div className="flex justify-end gap-1.5 pt-1">
              <button onClick={() => setEditingEdge(null)}
                className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted">
                <X className="w-3.5 h-3.5" />
              </button>
              <button onClick={handleSaveEdge} disabled={savingEdge}
                className="p-1 text-primary hover:bg-primary/10 rounded disabled:opacity-50">
                {savingEdge ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
