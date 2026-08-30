import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import type { WriterPreset, ExampleTurn } from '@/api/client'
import ExampleTurnsEditor from '@/components/ExampleTurnsEditor'

interface Props {
  preset: WriterPreset | null  // null = create mode
  onSave: (data: { name: string; prompt: string; examples: ExampleTurn[] }) => void
  onClose: () => void
}

export default function PresetModal({ preset, onSave, onClose }: Props) {
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [examples, setExamples] = useState<ExampleTurn[]>([])

  useEffect(() => {
    if (preset) {
      setName(preset.name)
      setPrompt(preset.prompt)
      setExamples(preset.examples || [])
    }
  }, [preset])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    onSave({ name: name.trim(), prompt, examples })
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50">
      <div
        className="fixed inset-4 bg-card border rounded-xl shadow-lg flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center gap-4 px-5 py-3 border-b shrink-0">
          <h3 className="font-semibold text-lg shrink-0">{preset ? '编辑预设' : '新建预设'}</h3>
          <input
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="预设名称，例如：玄幻修仙风格"
            className="flex-1 max-w-md px-3 py-1.5 text-sm border rounded-lg bg-background focus:outline-none focus:ring-2 focus:ring-primary/50"
            autoFocus
          />
          <button onClick={onClose} className="ml-auto p-1 rounded-md hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 flex flex-col min-h-0">
          <div className="flex-1 flex min-h-0">
            <div className="w-[45%] flex flex-col min-h-0 p-5">
              <label className="block text-sm font-medium mb-1 shrink-0">提示词内容</label>
              <textarea
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                placeholder="输入 Writer 系统提示词..."
                className="flex-1 w-full px-3 py-2 border rounded-lg bg-background resize-none focus:outline-none focus:ring-2 focus:ring-primary/50 font-mono text-sm leading-relaxed"
              />
            </div>
            <div className="w-px bg-border shrink-0" />
            <div className="w-[55%] min-h-0 overflow-y-auto p-5">
              <ExampleTurnsEditor value={examples} onChange={setExamples} />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 px-5 py-3 border-t shrink-0">
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
