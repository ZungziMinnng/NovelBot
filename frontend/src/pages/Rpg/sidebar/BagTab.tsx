import { X } from 'lucide-react'
import type { RpgItem, RpgSession } from '@/api/client'
import { norm } from '../condition'
import { PANEL } from '../rpgUi'
import Empty from './Empty'

export default function BagTab({
  sess, items, locked, onUseItem, onConfirmClaim, onDismissClaim,
}: {
  sess: RpgSession
  items: RpgItem[]
  locked: boolean
  onUseItem: (name: string, exact: boolean) => void
  /** 认下一件新道具。consumable 只在模组里还没有同名定义时才用得上 */
  onConfirmClaim: (id: string, consumable: boolean) => void
  onDismissClaim: (id: string) => void
}) {
  const bag = sess.inventory || []
  // 结算说你拿到了、还没认的那几件。**不混进下面那堆**：下面每一件都是确定在你
  // 身上的东西，这些还只是「模型说你有」
  const claims = sess.item_claims || []
  const itemByName = (name: string) => items.find(i => norm(i.name) === norm(name))

  return (
    <>
      {claims.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-medium px-1" style={{ color: 'hsl(var(--rpg-bag))' }}>
            新获取 · {claims.length}
          </p>
          {claims.map(claim => (
            <div key={claim.id} className={`${PANEL} p-3 relative`}>
              {/* 右上角一颗叉，不是底下一颗按钮：结算读歪的时候「这不是我拿的」
                  是最常用的那个动作，它得比确认更近手 */}
              <button
                onClick={() => onDismissClaim(claim.id)}
                disabled={locked}
                title="这不是我拿到的东西"
                className="absolute top-2 right-2 p-1 rounded text-muted-foreground
                  hover:text-foreground hover:bg-muted disabled:opacity-40"
              >
                <X className="w-3.5 h-3.5" />
              </button>
              <div className="flex items-baseline gap-2 pr-7">
                <p className="text-sm font-medium flex-1 truncate">{claim.name}</p>
                {claim.qty > 1 && <span className="text-xs text-muted-foreground">×{claim.qty}</span>}
              </div>
              {/* 正文原话。名字往往只是个称呼（「那包药」），不摆原话玩家没法
                  判断这到底是不是他真拿到的东西 */}
              {(claim.hint || claim.note) && (
                <p className="text-xs text-muted-foreground mt-1 leading-relaxed line-clamp-3">
                  {claim.hint || claim.note}
                </p>
              )}
              {claim.known_item_id ? (
                // 模组里定义过：用不用得完那条定义已经写了，这里只问「认不认」
                <button
                  onClick={() => onConfirmClaim(claim.id, true)}
                  disabled={locked}
                  title="模组里已有这件道具的定义，按那一条入库"
                  className="mt-2.5 w-full text-xs py-1.5 rounded-lg bg-primary
                    text-primary-foreground hover:opacity-90 disabled:opacity-40"
                >
                  收下
                </button>
              ) : (
                // 没定义过：用一次就没，还是能一直用，只有玩家知道——认下来之后
                // 这一条就**变成**模组道具表里的定义
                <div className="flex gap-2 mt-2.5">
                  <button
                    onClick={() => onConfirmClaim(claim.id, true)}
                    disabled={locked}
                    title="用一次少一个"
                    className="flex-1 text-xs py-1.5 rounded-lg bg-primary
                      text-primary-foreground hover:opacity-90 disabled:opacity-40"
                  >
                    一次性
                  </button>
                  <button
                    onClick={() => onConfirmClaim(claim.id, false)}
                    disabled={locked}
                    title="能反复用，数量不会因为用掉而减少"
                    className="flex-1 text-xs py-1.5 rounded-lg border hover:bg-muted disabled:opacity-40"
                  >
                    重复使用
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {bag.length === 0 && claims.length === 0 ? (
        <Empty>身上什么都没有。</Empty>
      ) : bag.map((it, i) => {
        const def = itemByName(it.name)
        // 有定义且作者勾了「能用」= 引擎精确结算
        const exact = !!def?.usable
        // 没定义的东西照样能点：开局背包名字打歪了、或者剧情里 GM 现给的，
        // 都不是玩家的错，不该让他只能自己打字。
        // 有定义但没勾「能用」的不给按钮——那是作者明说了「这不是用来用的」
        const canUse = exact || !def
        return (
          <div key={`${it.name}-${i}`} className={`${PANEL} p-3`}>
            <div className="flex items-baseline gap-2">
              <p className="text-sm font-medium flex-1 truncate">{it.name}</p>
              {it.qty > 1 && <span className="text-xs text-muted-foreground">×{it.qty}</span>}
            </div>
            {(def?.description || it.note) && (
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                {def?.description || it.note}
              </p>
            )}
            {def && Object.keys(def.effects || {}).length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {Object.entries(def.effects).map(([name, delta]) => (
                  <span
                    key={name}
                    className={`text-[11px] px-1.5 py-0.5 rounded ${
                      delta >= 0
                        ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                        : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                    }`}
                  >
                    {name} {delta >= 0 ? `+${delta}` : delta}
                  </span>
                ))}
              </div>
            )}
            {canUse && (
              <button
                onClick={() => onUseItem(it.name, exact)}
                disabled={locked}
                title={exact
                  ? '效果是模组里写死的，AI 改不了'
                  : '模组里没有这件道具的定义：用出来什么效果由 GM 现写，数值不精确'}
                // 描边 = 效果不精确。和上面那种「数字是死的」明显区分开，
                // 不然玩家会以为两种按钮是一回事
                className={`mt-2.5 w-full text-xs py-1.5 rounded-lg disabled:opacity-40 ${
                  exact
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'border text-muted-foreground hover:bg-muted'
                }`}
              >
                使用
              </button>
            )}
          </div>
        )
      })}
    </>
  )
}
