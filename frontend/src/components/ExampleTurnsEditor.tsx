import { Plus, Trash2, Sparkles } from 'lucide-react'
import type { ExampleTurn } from '@/api/client'

interface Props {
  value: ExampleTurn[]
  onChange: (v: ExampleTurn[]) => void
}

const TEMPLATE: ExampleTurn = {
  user: '写作方向：写主角初入门派、被长老当众考验的一场戏，约 500 字，突出紧张感与人物心理。',
  assistant: '（在此粘贴一段你满意的范文片段，模型会模仿其叙事节奏、用词与文风。把上面的「写作方向」换成与这段范文对应的任务描述，效果最好。）',
}

export default function ExampleTurnsEditor({ value, onChange }: Props) {
  const update = (i: number, patch: Partial<ExampleTurn>) => {
    onChange(value.map((ex, idx) => (idx === i ? { ...ex, ...patch } : ex)))
  }
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i))
  const addEmpty = () => onChange([...value, { user: '', assistant: '' }])
  const addTemplate = () => onChange([...value, { ...TEMPLATE }])

  return (
    <div className="mt-4 border-t pt-4">
      <div className="flex items-center justify-between mb-2">
        <label className="text-sm font-medium">示例轮（few-shot，可空）</label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={addTemplate}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5" /> 插入模板示例
          </button>
          <button
            type="button"
            onClick={addEmpty}
            className="flex items-center gap-1 text-xs text-primary hover:opacity-75 transition-opacity"
          >
            <Plus className="w-3.5 h-3.5" /> 添加示例
          </button>
        </div>
      </div>

      {value.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          以「输入 → 期望输出」成对提供范例，生成时作为真实对话轮注入，比写在提示词里更能稳定文风。留空则不注入。
        </p>
      ) : (
        <div className="space-y-3">
          {value.map((ex, i) => (
            <div key={i} className="border rounded-lg p-3 bg-muted/30">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-muted-foreground">示例 {i + 1}</span>
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="p-1 rounded hover:bg-muted text-muted-foreground hover:text-destructive transition-colors"
                  title="删除此示例"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
              <label className="block text-xs text-muted-foreground mb-1">输入（用户）</label>
              <textarea
                value={ex.user}
                onChange={e => update(i, { user: e.target.value })}
                placeholder="示例的写作方向 / 任务描述..."
                className="w-full border rounded-md px-2.5 py-1.5 text-sm bg-background resize-y min-h-[3rem] focus:outline-none focus:ring-1 focus:ring-ring mb-2"
              />
              <label className="block text-xs text-muted-foreground mb-1">输出（范文）</label>
              <textarea
                value={ex.assistant}
                onChange={e => update(i, { assistant: e.target.value })}
                placeholder="期望模型模仿的范文片段..."
                className="w-full border rounded-md px-2.5 py-1.5 text-sm bg-background resize-y min-h-[5rem] focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
