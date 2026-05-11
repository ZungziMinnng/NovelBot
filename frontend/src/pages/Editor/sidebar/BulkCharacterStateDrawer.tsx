import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { charactersApi, type Character } from '@/api/client'
import toast from 'react-hot-toast'

interface Props {
  novelId: number
  offsetLeft: number
  onClose: () => void
}

export default function BulkCharacterStateDrawer({ novelId, offsetLeft, onClose }: Props) {
  const qc = useQueryClient()
  const { data: characters = [] } = useQuery({
    queryKey: ['characters', novelId],
    queryFn: () => charactersApi.list(novelId),
  })
  const [keyName, setKeyName] = useState('')
  const [defaultValue, setDefaultValue] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [saving, setSaving] = useState(false)

  const trimmedKey = keyName.trim()
  const affectedCount = characters.filter((c) => {
    const state = c.current_state || {}
    return overwrite || !(trimmedKey in state)
  }).length

  const handleApply = async () => {
    if (!trimmedKey || saving) return
    setSaving(true)
    try {
      const updatedCharacters: Character[] = []
      for (const character of characters) {
        const currentState = { ...(character.current_state || {}) }
        if (!overwrite && trimmedKey in currentState) {
          updatedCharacters.push(character)
          continue
        }
        currentState[trimmedKey] = defaultValue
        const updated = await charactersApi.update(character.id, { current_state: currentState } as Partial<Character>)
        updatedCharacters.push(updated)
      }
      qc.setQueryData<Character[]>(['characters', novelId], (old = []) =>
        old.map((character) => updatedCharacters.find((updated) => updated.id === character.id) || character),
      )
      await qc.invalidateQueries({ queryKey: ['characters', novelId] })
      toast.success(`已为 ${affectedCount} 个角色添加状态词条`)
      onClose()
    } catch {
      toast.error('批量添加失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-y-0 z-40 w-[360px] border-r bg-background shadow-xl flex flex-col" style={{ left: offsetLeft }}>
      <div className="flex items-center gap-2 px-4 py-3 border-b shrink-0">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold">批量添加角色状态词条</h3>
          <p className="text-xs text-muted-foreground mt-0.5">为当前所有角色的 current_state 添加新字段。</p>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-muted">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div>
          <label className="text-xs font-medium mb-1.5 block">词条名</label>
          <input
            value={keyName}
            onChange={(e) => setKeyName(e.target.value)}
            placeholder="例如：等级、境界、阵营状态"
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background focus:outline-none focus:ring-1 focus:ring-ring"
            autoFocus
          />
        </div>

        <div>
          <label className="text-xs font-medium mb-1.5 block">默认值</label>
          <textarea
            value={defaultValue}
            onChange={(e) => setDefaultValue(e.target.value)}
            placeholder="可留空。留空也会写入字段并在角色当前状态中显示。"
            rows={4}
            className="w-full border rounded-lg px-3 py-2 text-sm bg-background resize-y focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        <label className="flex items-start gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
            className="mt-0.5"
          />
          <span>如果角色已有同名词条，覆盖原值</span>
        </label>

        <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground space-y-1">
          <p>当前角色数：{characters.length}</p>
          <p>将写入：{trimmedKey ? affectedCount : 0} 个角色</p>
          <p>空值会被保留，用于后续手动填写或批量推断。</p>
        </div>
      </div>

      <div className="border-t p-3 flex justify-end gap-2 shrink-0">
        <button onClick={onClose} className="px-3 py-1.5 text-sm border rounded-lg hover:bg-muted">
          取消
        </button>
        <button
          onClick={handleApply}
          disabled={!trimmedKey || saving || characters.length === 0}
          className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5"
        >
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          添加词条
        </button>
      </div>
    </div>
  )
}
