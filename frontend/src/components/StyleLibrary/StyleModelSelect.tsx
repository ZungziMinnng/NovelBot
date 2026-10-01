import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { groupModelsByProvider, modelLibraryApi, modelSelectValue } from '@/api/client'

// 导入分析和取用转换共用一个选择，记在本机：选一次两边都生效
const STORAGE_KEY = 'styleLibraryModel'

export function useStyleModel() {
  const [model, setModelState] = useState(() => localStorage.getItem(STORAGE_KEY) || '')
  const setModel = useCallback((v: string) => {
    setModelState(v)
    if (v) localStorage.setItem(STORAGE_KEY, v)
    else localStorage.removeItem(STORAGE_KEY)
  }, [])
  return [model, setModel] as const
}

export default function StyleModelSelect({ value, onChange }: {
  value: string
  onChange: (v: string) => void
}) {
  const { data: models, isSuccess } = useQuery({ queryKey: ['model-library'], queryFn: modelLibraryApi.list })
  const list = models || []
  const shown = modelSelectValue(list, value)
  // 记住的模型已经被删了：清回默认，否则请求会带着失效的 id 被后端拒掉
  useEffect(() => {
    if (isSuccess && value && !shown) onChange('')
  }, [isSuccess, value, shown, onChange])
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className="shrink-0">分析用模型</span>
      <select
        value={shown}
        onChange={e => onChange(e.target.value)}
        className="min-w-0 max-w-[14rem] px-2 py-1 text-xs border rounded-md bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
      >
        <option value="">默认快速模型</option>
        {groupModelsByProvider(list).map(g => (
          <optgroup key={g.provider} label={g.provider}>
            {g.items.map(m => (
              <option key={m.id} value={String(m.id)}>
                {m.display_name || m.model_id}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  )
}
