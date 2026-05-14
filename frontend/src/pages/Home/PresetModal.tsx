import { useState, useEffect, useRef, useCallback } from 'react'
import { X } from 'lucide-react'
import type { WriterPreset } from '@/api/client'

interface Props {
  preset: WriterPreset | null  // null = create mode
  onSave: (data: { name: string; prompt: string }) => void
  onClose: () => void
}

const MIN_W = 480
const MIN_H = 400

export default function PresetModal({ preset, onSave, onClose }: Props) {
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState({ w: 768, h: 600 })
  const dragging = useRef<{ edge: string; startX: number; startY: number; startW: number; startH: number } | null>(null)

  useEffect(() => {
    if (preset) {
      setName(preset.name)
      setPrompt(preset.prompt)
    }
  }, [preset])

  const onMouseMove = useCallback((e: MouseEvent) => {
    const d = dragging.current
    if (!d) return
    const dx = e.clientX - d.startX
    const dy = e.clientY - d.startY
    setSize(prev => {
      let w = prev.w, h = prev.h
      if (d.edge.includes('e')) w = Math.max(MIN_W, d.startW + dx * 2)
      if (d.edge.includes('w')) w = Math.max(MIN_W, d.startW - dx * 2)
      if (d.edge.includes('s')) h = Math.max(MIN_H, d.startH + dy * 2)
      if (d.edge.includes('n')) h = Math.max(MIN_H, d.startH - dy * 2)
      return { w, h }
    })
  }, [])

  const onMouseUp = useCallback(() => {
    dragging.current = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  useEffect(() => {
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [onMouseMove, onMouseUp])

  const startDrag = (edge: string) => (e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = { edge, startX: e.clientX, startY: e.clientY, startW: size.w, startH: size.h }
    document.body.style.userSelect = 'none'
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    onSave({ name: name.trim(), prompt })
  }

  const edgeClass = 'absolute z-10'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className="bg-card border rounded-xl shadow-lg flex flex-col relative"
        style={{ width: size.w, height: size.h, maxWidth: '95vw', maxHeight: '95vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Resize handles */}
        <div onMouseDown={startDrag('n')}  className={`${edgeClass} top-0 left-2 right-2 h-1.5 cursor-n-resize`} />
        <div onMouseDown={startDrag('s')}  className={`${edgeClass} bottom-0 left-2 right-2 h-1.5 cursor-s-resize`} />
        <div onMouseDown={startDrag('w')}  className={`${edgeClass} left-0 top-2 bottom-2 w-1.5 cursor-w-resize`} />
        <div onMouseDown={startDrag('e')}  className={`${edgeClass} right-0 top-2 bottom-2 w-1.5 cursor-e-resize`} />
        <div onMouseDown={startDrag('nw')} className={`${edgeClass} top-0 left-0 w-3 h-3 cursor-nw-resize`} />
        <div onMouseDown={startDrag('ne')} className={`${edgeClass} top-0 right-0 w-3 h-3 cursor-ne-resize`} />
        <div onMouseDown={startDrag('sw')} className={`${edgeClass} bottom-0 left-0 w-3 h-3 cursor-sw-resize`} />
        <div onMouseDown={startDrag('se')} className={`${edgeClass} bottom-0 right-0 w-3 h-3 cursor-se-resize`} />

        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h3 className="font-semibold text-lg">{preset ? '编辑预设' : '新建预设'}</h3>
          <button onClick={onClose} className="p-1 rounded-md hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 flex flex-col min-h-0">
          <div className="px-5 pt-4 pb-2 shrink-0">
            <label className="block text-sm font-medium mb-1">预设名称</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="例如：玄幻修仙风格"
              className="w-full px-3 py-2 border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
              autoFocus
            />
          </div>
          <div className="flex-1 flex flex-col min-h-0 px-5 pb-4 pt-2">
            <label className="block text-sm font-medium mb-1 shrink-0">提示词内容</label>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="输入 Writer 系统提示词..."
              className="w-full flex-1 min-h-0 px-3 py-2 border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
            />
          </div>

          <div className="flex items-center justify-end gap-2 px-5 py-4 border-t shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg border hover:bg-muted transition-colors"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={!name.trim()}
              className="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              保存
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
