/** 生成参数的四个输入框。角色卡编辑页和对话页的浮层共用一份，免得两边说法不一致。 */

export interface TavernParams {
  reply_length: number
  temperature: number
  max_tokens: number
  context_turns: number
}

interface Props {
  value: Partial<TavernParams>
  onChange: (patch: Partial<TavernParams>) => void
  /** 对话页用：失焦即存。角色卡页留空，跟着页面顶部的保存按钮走 */
  onCommit?: () => void
}

const LENGTH_PRESETS = [
  { label: '不限', value: 0 },
  { label: '简短', value: 80 },
  { label: '适中', value: 200 },
  { label: '详细', value: 400 },
]

export default function TavernParamFields({ value, onChange, onCommit }: Props) {
  const replyLength = value.reply_length ?? 0
  // 负温度 = 整个参数不发给供应商，llm_client 里 `if temperature >= 0` 已有这个约定
  const tempOff = (value.temperature ?? 0.9) < 0
  const input = 'w-full border rounded-lg px-3 py-2 text-sm bg-background/60 focus:outline-none focus:ring-1 focus:ring-pink-500/50'

  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs font-medium mb-1.5 block">回复长度</label>
        <div className="flex gap-1.5 mb-2">
          {LENGTH_PRESETS.map(p => (
            <button
              key={p.value}
              onClick={() => { onChange({ reply_length: p.value }); onCommit?.() }}
              className={`text-xs px-2.5 py-1 rounded-lg border transition-colors ${
                replyLength === p.value
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'hover:bg-muted text-muted-foreground'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number" min={0} max={2000} step={20}
            value={replyLength}
            onChange={e => onChange({ reply_length: Math.max(0, Number(e.target.value) || 0) })}
            onBlur={onCommit}
            className={`${input} w-28`}
          />
          <span className="text-xs text-muted-foreground">字，0 = 不作要求</span>
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          写进提示词的软要求，模型会自己收尾。跟下面的「单次上限」不是一回事——那个是硬截断，会切在句子中间。
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs font-medium mb-1 block">温度</label>
          <input
            type="number" min={0} max={2} step={0.05}
            value={tempOff ? '' : (value.temperature ?? 0.9)}
            disabled={tempOff}
            onChange={e => onChange({ temperature: Number(e.target.value) })}
            onBlur={onCommit}
            className={`${input} disabled:opacity-40`}
          />
          <label className="flex items-center gap-1.5 mt-1.5 cursor-pointer">
            <input
              type="checkbox"
              checked={tempOff}
              onChange={e => {
                onChange({ temperature: e.target.checked ? -1 : 0.9 })
                onCommit?.()
              }}
              className="accent-pink-500"
            />
            <span className="text-xs text-muted-foreground">不传</span>
          </label>
          <p className="text-xs text-muted-foreground mt-1">
            高了更放得开。Claude 的推理模型等不接受这个参数，勾「不传」就整个不发。
          </p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">单次上限</label>
          <input
            type="number" min={256} max={32768} step={256}
            value={value.max_tokens ?? 2048}
            onChange={e => onChange({ max_tokens: Number(e.target.value) })}
            onBlur={onCommit}
            className={input}
          />
          <p className="text-xs text-muted-foreground mt-1.5">tokens，安全网。</p>
        </div>
        <div>
          <label className="text-xs font-medium mb-1 block">上下文轮数</label>
          <input
            type="number" min={1} max={100}
            value={value.context_turns ?? 20}
            onChange={e => onChange({ context_turns: Number(e.target.value) })}
            onBlur={onCommit}
            className={input}
          />
          <p className="text-xs text-muted-foreground mt-1.5">更早的会压成梗概。</p>
        </div>
      </div>
    </div>
  )
}
