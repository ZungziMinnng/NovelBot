import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { X, Loader2, Copy, Wand2 } from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  character: Character
  novelId: number
  onClose: () => void
}

export default function CharacterPromptDrawer({ character, novelId, onClose }: Props) {
  const qc = useQueryClient()
  const sheet = character.full_sheet || {}

  const [sdResult, setSdResult] = useState(String(sheet.sd_prompt || ''))
  const [sdLoading, setSdLoading] = useState(false)
  const [naturalResult, setNaturalResult] = useState(String(sheet.natural_prompt || ''))
  const [naturalLoading, setNaturalLoading] = useState(false)

  const saveToSheet = async (key: string, value: string) => {
    try {
      await charactersApi.update(character.id, {
        full_sheet: { ...sheet, [key]: value },
      } as Partial<Character>)
      qc.invalidateQueries({ queryKey: ['characters', novelId] })
    } catch {
      // 静默失败，结果已显示在 UI
    }
  }

  const handleGenerate = async (style: 'sd_tags' | 'natural_zh') => {
    const setLoading = style === 'sd_tags' ? setSdLoading : setNaturalLoading
    const setResult = style === 'sd_tags' ? setSdResult : setNaturalResult
    const sheetKey = style === 'sd_tags' ? 'sd_prompt' : 'natural_prompt'
    setLoading(true)
    try {
      const { prompt } = await charactersApi.generateImagePrompt(character.id, style)
      setResult(prompt)
      await saveToSheet(sheetKey, prompt)
    } catch {
      toast.error('生成失败')
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = async (text: string) => {
    await navigator.clipboard.writeText(text)
    toast.success('已复制')
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-[400px] bg-background border-l shadow-2xl z-50 flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b shrink-0">
          <h2 className="text-sm font-semibold truncate">生成提示词 — {character.name}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* SD Tags Section */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-medium">SD 标签提示词</h3>
              <p className="text-xs text-muted-foreground mt-0.5">适用于 Illustrious / 光辉系列模型，英文标签格式</p>
            </div>
            <button
              onClick={() => handleGenerate('sd_tags')}
              disabled={sdLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {sdLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {sdLoading ? '生成中...' : sdResult ? '重新生成 SD 标签' : '生成 SD 标签'}
            </button>
            {sdResult && (
              <div className="relative">
                <textarea
                  readOnly
                  value={sdResult}
                  rows={6}
                  className="w-full text-xs border rounded-lg p-3 bg-muted/30 resize-y focus:outline-none"
                />
                <button
                  onClick={() => handleCopy(sdResult)}
                  className="absolute top-2 right-2 p-1.5 rounded-md bg-background border hover:bg-muted transition-colors"
                  title="复制"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>

          {/* Natural Chinese Section */}
          <div className="space-y-3">
            <div>
              <h3 className="text-sm font-medium">自然语言提示词</h3>
              <p className="text-xs text-muted-foreground mt-0.5">适用于 Image Turbo 等模型，中文自然语言描述</p>
            </div>
            <button
              onClick={() => handleGenerate('natural_zh')}
              disabled={naturalLoading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {naturalLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {naturalLoading ? '生成中...' : naturalResult ? '重新生成自然语言描述' : '生成自然语言描述'}
            </button>
            {naturalResult && (
              <div className="relative">
                <textarea
                  readOnly
                  value={naturalResult}
                  rows={6}
                  className="w-full text-xs border rounded-lg p-3 bg-muted/30 resize-y focus:outline-none"
                />
                <button
                  onClick={() => handleCopy(naturalResult)}
                  className="absolute top-2 right-2 p-1.5 rounded-md bg-background border hover:bg-muted transition-colors"
                  title="复制"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
