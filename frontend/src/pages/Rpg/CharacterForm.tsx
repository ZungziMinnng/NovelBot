import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Loader2, Lock, X } from 'lucide-react'
import { rpgApi, type RpgModule, type RpgSession } from '@/api/client'
import { INPUT, NumInput, splitList } from './rpgUi'
import { protagonistCard, protagonistDesc } from './protagonist'

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
  // 时段表预填模组那一份，玩家想改随时改——但**不动就不发**（见 submit）。
  // 记下模组原样那一份，用来判断「动没动过」
  const moduleSlots = module.time_slots || []
  const [slotText, setSlotText] = useState(moduleSlots.join('，'))

  const { data: npcs = [] } = useQuery({
    queryKey: ['rpg-npcs', module.id],
    queryFn: () => rpgApi.npcs.list(module.id),
  })
  const template = protagonistCard(npcs)
  // 模组定了主角就是定了，锁不锁都照它预填——原来这里是一颗「套用主角卡」按钮，
  // 而作者在「主角」面板里把人定出来之后，玩家还得再点一下才用得上
  const locked = !!module.lock_protagonist && !!template

  // 角色卡是异步来的，所以只能等它到了再灌。**只灌一次**：这个弹窗的生命周期就是
  // 一次建局，灌第二次只会把玩家刚敲的字盖回主角卡上那一份
  const [filled, setFilled] = useState(false)
  useEffect(() => {
    if (!template || filled) return
    setFilled(true)
    setName(template.name)
    setDesc(protagonistDesc(template))
  }, [template, filled])

  const submit = async () => {
    const charName = name.trim()
    if (!charName || creating) return
    setCreating(true)
    // 和模组那份一字不差 = 玩家没动过 → 发空数组，这一局跟着模组走；真改过才发
    // 他改的，从此刻起这一局冻住（两种行为的定义见后端 rpg_state.slot_table）。
    // 从前这里无条件把预填的那份发回去，于是每一局建出来都当场冻住自己一份，
    // 「跟模组走」那条路一局都没走到过——作者给模组加一格，已经开着的局纹丝不动
    const slots = splitList(slotText)
    try {
      onCreated(await rpgApi.sessions.create(module.id, {
        char_name: charName,
        char_desc: desc.trim(),
        stats,
        time_slots: slots.join('，') === moduleSlots.join('，') ? [] : slots,
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
          {locked && (
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground rounded-lg
              bg-muted/50 px-3 py-2">
              <Lock className="w-3.5 h-3.5 shrink-0 mt-px" />
              这个模组的主角是定好的，名字和出身改不了。下面的数值和时段还是你说了算。
            </p>
          )}

          <div>
            <label className="block text-sm font-medium mb-1.5">名字</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submit() }}
              placeholder="例：阿隼"
              autoFocus={!locked}
              readOnly={locked}
              className={`${INPUT} ${locked ? 'text-muted-foreground' : ''}`}
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1.5">出身与动机</label>
            <textarea
              value={desc}
              onChange={e => setDesc(e.target.value)}
              rows={3}
              readOnly={locked}
              placeholder="你从哪来、会点什么、为什么非要蹚这趟浑水……"
              className={`${INPUT} ${locked ? 'text-muted-foreground' : ''}`}
            />
            {!locked && (
              <p className="text-xs text-muted-foreground mt-1.5">
                GM 每轮都看得到这段，写得越具体，世界对你的反应越贴。
              </p>
            )}
          </div>

          {defs.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1.5">起始数值</label>
              <div className="grid grid-cols-2 gap-3">
                {defs.map(def => (
                  <div key={def.name} className="flex items-center gap-2">
                    <span className="text-sm text-muted-foreground shrink-0">{def.name}</span>
                    <NumInput
                      value={stats[def.name] ?? def.initial}
                      onChange={n => setStats(prev => ({ ...prev, [def.name]: n ?? 0 }))}
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

          {module.time_slots?.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1.5">这一局的时间怎么走</label>
              <input
                value={slotText}
                onChange={e => setSlotText(e.target.value)}
                placeholder="早，中，晚"
                className={INPUT}
              />
              <p className="text-xs text-muted-foreground mt-1.5">
                已经照模组的填好了，想改就改，逗号隔开（中英文逗号都行）。
                <b className="font-medium">留空 = 跟模组一样</b>。
                玩的时候按「结束这个时段」往后推一格，推完最后一格算过了一天。
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
