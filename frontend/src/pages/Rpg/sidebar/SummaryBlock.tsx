import { useState } from 'react'
import { Loader2, Pencil } from 'lucide-react'

/**
 * 一格长期记忆，能看也能改。
 *
 * 玩家自己那格（你亲身经历的）和每个角色那格长得一样、改法也一样，所以收在
 * 这一个组件里，两处各传各的 slot。
 *
 * **为什么要能改**：这段话是旧剧情压出来的，每轮都注入，而且会喂给下一次
 * 压缩——错一句（「你已经答应嫁给他」）会自己往后长，一路带到局终。没有这个
 * 口子只能读档，把这之后玩的全扔掉。同角色卡上那几条近况的补救。
 *
 * **不给「重新生成」按钮**：重压要拿原文，而原文正是被这段话顶掉的那些——
 * 指针已经越过去了。真要重来得先回滚指针，那是另一件事。
 *
 * 没有自动保存：这一格不是表单，是一段会改变模型记忆的话，落笔要由玩家点一下
 * 确认。改坏了 Esc 就退回原样
 */
/** 玩家自己那格的键。和后端 rpg_context.PLAYER_SLOT 是同一个字符串，
 *  别的格子用角色 id 的字符串 */
export const PLAYER_SLOT = 'player'

export default function SummaryBlock({
  title, hint, empty, text, onSave,
}: {
  title: string
  /** 标题下那句小字，解释这段话是干什么的 */
  hint: string
  /** 还没压缩过时显示的话 */
  empty: string
  text: string
  onSave: (next: string) => Promise<void>
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (draft === null) return
    setSaving(true)
    try {
      await onSave(draft.trim())
      setDraft(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    // 和角色卡上「这一局记下的」同一条竖线：都是模型边玩边写的东西，
    // 玩家得一眼看出它不是模组作者写的设定
    <div className="border-l-2 border-primary/40 pl-3">
      <div className="flex items-center gap-1.5">
        <p className="text-xs font-medium text-muted-foreground flex-1">{title}</p>
        {draft === null ? (
          <button
            onClick={() => setDraft(text)}
            title="改这段记忆"
            className="p-0.5 rounded text-muted-foreground/60 hover:bg-muted hover:text-foreground"
          >
            <Pencil className="w-3 h-3" />
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <button
              onClick={save}
              disabled={saving}
              className="text-[11px] px-2 py-0.5 rounded bg-primary text-primary-foreground
                hover:opacity-90 disabled:opacity-50"
            >
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : '保存'}
            </button>
            <button
              onClick={() => setDraft(null)}
              className="text-[11px] px-2 py-0.5 rounded border text-muted-foreground hover:bg-muted"
            >
              取消
            </button>
          </div>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground/70 mb-2">{hint}</p>
      {draft === null ? (
        <p className="text-sm leading-relaxed whitespace-pre-wrap">
          {text || <span className="text-xs text-muted-foreground italic">{empty}</span>}
        </p>
      ) : (
        <textarea
          value={draft}
          rows={8}
          autoFocus
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') setDraft(null) }}
          placeholder="清空就是把这段记忆丢掉：被压掉的那些原文不会回来"
          className="w-full text-sm leading-relaxed rounded-lg border bg-background px-2 py-1.5
            resize-y focus:outline-none focus:ring-1 focus:ring-primary/40"
        />
      )}
    </div>
  )
}
