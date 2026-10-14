import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { ChevronDown, Lightbulb, Plus, Trash2 } from 'lucide-react'
import { memosApi, type Memo, type MemoScope } from '@/api/client'
import { confirmDialog } from '@/components/ConfirmDialog/ConfirmDialog'
import AutoTextarea from '@/components/AutoTextarea'

const FIELD = 'w-full rounded-xl border border-foreground/10 bg-background px-3 py-2 text-sm leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/30'

function formatTime(iso: string): string {
  // 后端存的是 UTC 且不带时区后缀
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * 主页备忘录：脑子里冒出来的点子随手记一笔。只给自己看，不进任何提示词。
 * 不用 portal、颜色全走主题变量，所以放进游戏主页也跟着 .mode-game 变色。
 */
export default function MemoBoard({ scope }: { scope: MemoScope }) {
  const qc = useQueryClient()
  const key = ['memos', scope]
  const foldKey = `memo_folded_${scope}`
  const [folded, setFolded] = useState(() => localStorage.getItem(foldKey) === '1')
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null)
  const { data: memos = [] } = useQuery({ queryKey: key, queryFn: () => memosApi.list(scope) })

  const toggleFold = () => {
    setFolded(f => {
      localStorage.setItem(foldKey, f ? '0' : '1')
      return !f
    })
  }

  const add = async () => {
    if (!draft.trim() || saving) return
    setSaving(true)
    try {
      await memosApi.create(scope, draft)
      setDraft('')
      qc.invalidateQueries({ queryKey: key })
    } catch {
      toast.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  const saveEdit = async (memo: Memo) => {
    if (!editing) return
    const text = editing.text.trim()
    setEditing(null)
    if (!text || text === memo.content) return
    try {
      await memosApi.update(memo.id, text)
      qc.invalidateQueries({ queryKey: key })
    } catch {
      toast.error('保存失败')
    }
  }

  const remove = async (memo: Memo) => {
    const ok = await confirmDialog({ title: '删掉这条备忘？', detail: memo.content.slice(0, 80), confirmText: '删除', danger: true })
    if (!ok) return
    try {
      await memosApi.delete(memo.id)
      qc.invalidateQueries({ queryKey: key })
    } catch {
      toast.error('删除失败')
    }
  }

  return (
    <section className="reveal rounded-2xl border border-foreground/10 bg-card shadow-sm">
      <button
        onClick={toggleFold}
        aria-expanded={!folded}
        className="w-full flex items-center gap-2 px-4 sm:px-5 py-3 text-left"
      >
        <Lightbulb className="w-4 h-4 text-primary" />
        <span className="font-medium text-sm">备忘录</span>
        {memos.length > 0 && <span className="text-xs text-muted-foreground tabular-nums">{memos.length} 条</span>}
        <span className="ml-auto text-xs text-muted-foreground hidden sm:inline">只给自己看，不会发给 AI</span>
        <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${folded ? '-rotate-90' : ''}`} />
      </button>

      {!folded && (
        <div className="px-4 sm:px-5 pb-4 space-y-3">
          <div className="flex items-end gap-2">
            <AutoTextarea
              minRows={2}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); add() }
              }}
              placeholder="想到什么记一笔…（Ctrl+Enter 保存）"
              aria-label="新备忘"
              className={FIELD}
            />
            <button
              onClick={add}
              disabled={!draft.trim() || saving}
              className="shrink-0 flex items-center gap-1 rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-95 disabled:opacity-40"
            >
              <Plus className="w-4 h-4" /> 记下
            </button>
          </div>

          {memos.length > 0 && (
            <ul className="grid gap-2 sm:grid-cols-2 max-h-[26rem] overflow-y-auto pr-1">
              {memos.map(memo => (
                <li key={memo.id} className="group rounded-xl border border-foreground/[0.08] bg-background/60 px-3 py-2.5">
                  {editing?.id === memo.id ? (
                    <AutoTextarea
                      autoFocus
                      minRows={2}
                      value={editing.text}
                      onChange={e => setEditing({ id: memo.id, text: e.target.value })}
                      onBlur={() => saveEdit(memo)}
                      onKeyDown={e => {
                        if (e.key === 'Escape') setEditing(null)
                        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); saveEdit(memo) }
                      }}
                      aria-label="编辑备忘"
                      className={FIELD}
                    />
                  ) : (
                    <p
                      onDoubleClick={() => setEditing({ id: memo.id, text: memo.content })}
                      title="双击修改"
                      className="text-sm leading-relaxed whitespace-pre-wrap break-words cursor-text"
                    >
                      {memo.content}
                    </p>
                  )}
                  <div className="mt-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span className="tabular-nums">{formatTime(memo.updated_at)}</span>
                    <button
                      onClick={() => remove(memo)}
                      className="p-1 rounded-md opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-destructive hover:bg-destructive/10 transition"
                      title="删除"
                      aria-label="删除备忘"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
