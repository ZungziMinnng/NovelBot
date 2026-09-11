import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, Sparkles, X } from 'lucide-react'
import { rpgApi, type RpgModule, type RpgSession } from '@/api/client'
import { INPUT } from './rpgUi'

/** 开局：角色属于这一局而不是模组，所以每次开局都重填一遍。
 *  数值起点从模组的定义拷过来，模组里有主角卡的话名字和出身也预填好。
 */
export default function CharacterForm({
  module, onClose, onCreated,
}: {
  module: RpgModule
  onClose: () => void
  onCreated: (session: RpgSession) => void
}) {
  // 「隐藏」的是幕后计数器，不该让玩家在建局界面调
  const defs = (module.stat_defs || []).filter(d => d.name && d.display !== '隐藏')

  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [stats, setStats] = useState<Record<string, number>>(
    Object.fromEntries(defs.map(d => [d.name, d.initial])),
  )
  const [creating, setCreating] = useState(false)

  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', module.id],
    queryFn: () => rpgApi.npcs.list(module.id),
  })
  const template = npcs.find(n => n.role === 'protagonist')

  const usePreset = () => {
    if (!template) return
    setName(template.name)
    setDesc([template.description, template.persona].filter(Boolean).join('\n\n'))
  }

  const submit = async () => {
    const charName = name.trim()
    if (!charName || creating) return
    setCreating(true)
    try {
      onCreated(await rpgApi.sessions.create(module.id, {
        char_name: charName,
        char_desc: desc.trim(),
        stats,
      }))
    } catch {
      toast.error('开局失败')
      setCreating(false)
    }
  }

  // 挂到 body：调用点在页面 main 里，而 main 是 relative z-10、页头是 sticky z-20，
  // 留在原地的话整个弹窗会被页头压住，z-50 出不了 main 这个层叠上下文
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-2xl border border-primary/25 bg-card shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-card border-b px-6 py-4 flex items-center gap-2">
          <div className="flex-1 min-w-0">
            <p className="font-semibold">你是谁？</p>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">即将进入「{module.name}」</p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-muted shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          {template && (
            <button
              onClick={usePreset}
              className="w-full flex items-center justify-center gap-1.5 text-xs py-2 rounded-lg
                bg-primary/10 text-primary ring-1 ring-primary/30 hover:bg-primary/20"
            >
              <Sparkles className="w-3.5 h-3.5" /> 套用主角卡「{template.name}」
            </button>
          )}

          <div>
            <label className="block text-sm font-medium mb-1.5">名字</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submit() }}
              placeholder="例：阿隼"
              autoFocus
              className={INPUT}
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">出身与动机</label>
            <textarea
              value={desc}
              onChange={e => setDesc(e.target.value)}
              rows={3}
              placeholder="你从哪来、会点什么、为什么非要蹚这趟浑水……"
              className={INPUT}
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              GM 每轮都看得到这段，写得越具体，世界对你的反应越贴。
            </p>
          </div>

          {defs.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1.5">起始数值</label>
              <div className="grid grid-cols-2 gap-3">
                {defs.map(def => (
                  <div key={def.name} className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground shrink-0">{def.name}</span>
                    <input
                      type="number"
                      value={stats[def.name] ?? def.initial}
                      onChange={e => setStats(prev => ({ ...prev, [def.name]: Number(e.target.value) || 0 }))}
                      className={INPUT}
                    />
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-1.5">
                默认就是模组定的起点，想开个高难度局就自己往下调。
              </p>
            </div>
          )}
        </div>

        <div className="sticky bottom-0 bg-card border-t px-6 py-4 flex justify-end gap-2">
          <button onClick={onClose} className="text-sm px-4 py-2 rounded-lg border hover:bg-muted">
            取消
          </button>
          <button
            onClick={submit}
            disabled={!name.trim() || creating}
            className="text-sm px-5 py-2 rounded-lg flex items-center gap-1.5
              bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-40"
          >
            {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            出发
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
