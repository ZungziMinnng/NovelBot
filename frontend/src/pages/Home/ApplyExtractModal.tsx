import { useState } from 'react'
import { Check, X } from 'lucide-react'
import type { BrainstormExtract } from '@/api/client'

/** 表单当前值，用于并排显示"会被换成什么"。只读、不回写 */
export interface FormSnapshot {
  title: string
  genre: string
  writing_style: string
  premise: string
  plot_design: string
  core_setting: string
  world_rules_seed: string
  ending: string
  protagonist_arc: string
}

export type TextKey = keyof FormSnapshot

export const LABELS: Record<TextKey, string> = {
  title: '小说名称',
  genre: '题材',
  writing_style: '写作风格',
  premise: '创作方向',
  plot_design: '剧情设计',
  core_setting: '时代背景',
  world_rules_seed: '核心规则',
  ending: '结局一句话',
  protagonist_arc: '主角起点→终点',
}

export const TEXT_KEYS = Object.keys(LABELS) as TextKey[]

interface Props {
  extract: BrainstormExtract
  current: FormSnapshot
  onCancel: () => void
  /** 只带用户勾了的字段 */
  onApply: (picked: Partial<BrainstormExtract>) => void
}

export default function ApplyExtractModal({ extract, current, onCancel, onApply }: Props) {
  const changed = TEXT_KEYS.filter(k => extract[k] && extract[k] !== current[k])
  const hasCards = extract.endgame_cards.length > 0
  const hasChars = extract.characters.length > 0

  const [picked, setPicked] = useState<Set<string>>(
    () => new Set<string>([...changed, ...(hasCards ? ['endgame_cards'] : []), ...(hasChars ? ['characters'] : [])]),
  )

  const toggle = (key: string) =>
    setPicked(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })

  const nothing = changed.length === 0 && !hasCards && !hasChars

  const apply = () => {
    const out: Partial<BrainstormExtract> = {}
    for (const k of changed) {
      if (picked.has(k)) out[k] = extract[k]
    }
    if (hasCards && picked.has('endgame_cards')) out.endgame_cards = extract.endgame_cards
    if (hasChars && picked.has('characters')) out.characters = extract.characters
    onApply(out)
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onCancel}>
      <div
        className="bg-background rounded-xl border shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b flex items-center justify-between shrink-0">
          <div className="min-w-0">
            <h3 className="font-medium">把聊定的内容填进表单</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              勾掉不想要的。只有勾上的会覆盖左边对应栏位。
            </p>
          </div>
          <button onClick={onCancel} className="p-1.5 rounded-md hover:bg-muted shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {nothing && (
            <p className="text-sm text-muted-foreground py-6 text-center">
              没从对话里抽到能填的内容。多聊几轮，把书名、金手指、开局这些聊具体些再试。
            </p>
          )}

          {changed.map(k => (
            <label
              key={k}
              className={`block border rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                picked.has(k) ? 'border-primary/50 bg-primary/5' : 'opacity-60'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={picked.has(k)}
                  onChange={() => toggle(k)}
                  className="accent-primary"
                />
                <span className="text-sm font-medium">{LABELS[k]}</span>
              </div>
              {current[k] && (
                <p className="text-xs text-muted-foreground mt-1.5 line-clamp-2 whitespace-pre-wrap line-through decoration-muted-foreground/40">
                  {current[k]}
                </p>
              )}
              <p className="text-sm mt-1 whitespace-pre-wrap">{extract[k]}</p>
            </label>
          ))}

          {hasCards && (
            <label
              className={`block border rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                picked.has('endgame_cards') ? 'border-primary/50 bg-primary/5' : 'opacity-60'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={picked.has('endgame_cards')}
                  onChange={() => toggle('endgame_cards')}
                  className="accent-primary"
                />
                <span className="text-sm font-medium">留到后面揭的牌（追加 {extract.endgame_cards.length} 张）</span>
              </div>
              <ul className="text-sm mt-1 space-y-0.5">
                {extract.endgame_cards.map((c, i) => (
                  <li key={i} className="text-muted-foreground">
                    <span className="text-foreground">第{c.volume}卷</span>｜{c.text}
                  </li>
                ))}
              </ul>
            </label>
          )}

          {hasChars && (
            <label
              className={`block border rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                picked.has('characters') ? 'border-primary/50 bg-primary/5' : 'opacity-60'
              }`}
            >
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={picked.has('characters')}
                  onChange={() => toggle('characters')}
                  className="accent-primary"
                />
                <span className="text-sm font-medium">角色（{extract.characters.length} 个，同名的会被更新）</span>
              </div>
              <ul className="text-sm mt-1 space-y-1">
                {extract.characters.map((c, i) => (
                  <li key={i}>
                    <span className="font-medium">{c.name}</span>
                    <span className="text-muted-foreground">
                      （{c.role}{c.age ? `，${c.age}岁` : ''}）{c.description}
                    </span>
                  </li>
                ))}
              </ul>
            </label>
          )}
        </div>

        <div className="px-5 py-3 border-t flex justify-end gap-2 shrink-0">
          <button onClick={onCancel} className="text-sm px-3 py-1.5 border rounded-lg hover:bg-muted">
            取消
          </button>
          <button
            onClick={apply}
            disabled={picked.size === 0}
            className="flex items-center gap-1 text-sm px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            <Check className="w-3.5 h-3.5" />
            填进表单（{picked.size}）
          </button>
        </div>
      </div>
    </div>
  )
}
