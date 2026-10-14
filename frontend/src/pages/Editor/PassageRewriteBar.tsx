import { useState } from 'react'
import toast from 'react-hot-toast'
import { Check, Loader2, RotateCcw, Wand2, X } from 'lucide-react'
import { passageApi, type PassageMode } from '@/api/client'

// 前后文只是给模型看衔接用，后端还会再截一次；这里先截掉，免得整章正文都发过去
const BEFORE_SEND = 3000
const AFTER_SEND = 1600
const MAX_SELECTED = 8000

const MODES: Array<{ mode: PassageMode; label: string; title: string }> = [
  { mode: 'rewrite', label: '改写', title: '意思不变，换个写法' },
  { mode: 'expand', label: '扩写', title: '补细节、动作、感官，篇幅约 1.8 倍' },
  { mode: 'condense', label: '缩写', title: '删水分，篇幅约 6 成' },
]

export interface TextRange { start: number; end: number }

interface Props {
  novelId: number
  editContent: string
  selection: TextRange
  /** 替换完成后把新文字写回编辑框，并选中替换进去的那段 */
  onApply: (next: string, range: TextRange) => void
}

/** 手动编辑时，选中一段文字后出现：只改这一段，前后文作参考 */
export default function PassageRewriteBar({ novelId, editContent, selection, onApply }: Props) {
  const [instruction, setInstruction] = useState('')
  const [loading, setLoading] = useState<PassageMode | null>(null)
  // 发请求那一刻的选区和原文，结果回来时编辑框可能已经变了
  const [result, setResult] = useState<{ text: string; mode: PassageMode; range: TextRange; original: string } | null>(null)

  const selLen = selection.end - selection.start
  const run = async (mode: PassageMode, range: TextRange = selection) => {
    const original = editContent.slice(range.start, range.end)
    if (!original.trim()) return
    if (original.length > MAX_SELECTED) {
      toast.error(`一次最多选 ${MAX_SELECTED} 字`)
      return
    }
    setLoading(mode)
    try {
      const { text } = await passageApi.rewrite({
        novel_id: novelId,
        mode,
        selected: original,
        before: editContent.slice(Math.max(0, range.start - BEFORE_SEND), range.start),
        after: editContent.slice(range.end, range.end + AFTER_SEND),
        instruction: instruction.trim(),
      })
      setResult({ text, mode, range, original })
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || '生成失败')
    } finally { setLoading(null) }
  }

  const accept = () => {
    if (!result) return
    let { start, end } = result.range
    // 等结果的时候作者可能改了别处，原位置对不上就按原文找一次
    if (editContent.slice(start, end) !== result.original) {
      const at = editContent.indexOf(result.original)
      if (at < 0) {
        toast.error('原来选的那段已经被改动，没法替换了')
        return
      }
      start = at
      end = at + result.original.length
    }
    onApply(editContent.slice(0, start) + result.text + editContent.slice(end), { start, end: start + result.text.length })
    setResult(null)
  }

  if (result) {
    return (
      <div className="border-b bg-muted/30 px-4 py-2 shrink-0 space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <Wand2 className="w-3.5 h-3.5 text-primary" />
          <span className="font-medium">{MODES.find(m => m.mode === result.mode)?.label}结果</span>
          <span className="text-muted-foreground tabular-nums">{result.original.length} → {result.text.length} 字</span>
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => run(result.mode, result.range)}
              disabled={!!loading}
              className="flex items-center gap-1 px-2.5 py-1 border rounded-md hover:bg-muted disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />} 再来一次
            </button>
            <button onClick={() => setResult(null)} className="flex items-center gap-1 px-2.5 py-1 border rounded-md hover:bg-muted">
              <X className="w-3 h-3" /> 不要
            </button>
            <button onClick={accept} className="flex items-center gap-1 px-3 py-1 bg-primary text-primary-foreground rounded-full hover:opacity-95">
              <Check className="w-3 h-3" /> 替换
            </button>
          </div>
        </div>
        <div className="max-h-56 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap novel-content font-serif bg-background border rounded-md px-3 py-2">
          {result.text}
        </div>
      </div>
    )
  }

  if (selLen <= 0) return null

  return (
    <div className="border-b bg-muted/30 px-4 py-1.5 shrink-0 flex items-center gap-2 text-xs">
      <Wand2 className="w-3.5 h-3.5 text-muted-foreground" />
      <span className="text-muted-foreground tabular-nums">已选 {selLen} 字</span>
      {MODES.map(m => (
        <button
          key={m.mode}
          // mousedown 时阻止默认，免得点按钮把编辑框里的选区弄丢
          onMouseDown={e => e.preventDefault()}
          onClick={() => run(m.mode)}
          disabled={!!loading}
          title={m.title}
          className="flex items-center gap-1 px-2.5 py-1 border rounded-md bg-background hover:bg-muted disabled:opacity-50"
        >
          {loading === m.mode && <Loader2 className="w-3 h-3 animate-spin" />}
          {m.label}
        </button>
      ))}
      <input
        value={instruction}
        onChange={e => setInstruction(e.target.value)}
        maxLength={500}
        placeholder="额外要求（可不填），比如：语气再冷一点"
        aria-label="选段改写的额外要求"
        className="flex-1 min-w-0 bg-background border rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </div>
  )
}
