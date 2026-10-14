import { useState } from 'react'
import { X } from 'lucide-react'
import type { IconType } from 'react-icons'
import {
  GiCardboardBox, GiBroadsword, GiChestArmor, GiKey, GiPotionBall, GiScrollUnfurled,
} from 'react-icons/gi'
import type { RpgItem, RpgModule, RpgSession } from '@/api/client'
import { effectCostReason, norm } from '../condition'
import { ITEM_CATEGORIES, PANEL } from '../rpgUi'
import Empty from './Empty'

/** 每一类的图标和色调。图标来自 game-icons.net（CC BY 3.0，署名在关于页）。
 *  色调写成完整的 class 字符串而不是拼出来的：Tailwind 只认源码里字面出现过的类名 */
const OTHER = '其他'
const LOOK: Record<string, { icon: IconType; tone: string }> = {
  消耗品: { icon: GiPotionBall, tone: 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/30' },
  武器: { icon: GiBroadsword, tone: 'text-rose-600 dark:text-rose-400 bg-rose-500/10 border-rose-500/30' },
  装备: { icon: GiChestArmor, tone: 'text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/30' },
  关键道具: { icon: GiKey, tone: 'text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/30' },
  资料: { icon: GiScrollUnfurled, tone: 'text-violet-600 dark:text-violet-400 bg-violet-500/10 border-violet-500/30' },
  [OTHER]: { icon: GiCardboardBox, tone: 'text-muted-foreground bg-muted/40 border-border' },
}

export default function BagTab({
  sess, items, locked, onUseItem, onDiscardItem, onConfirmClaim, onDismissClaim, module,
}: {
  sess: RpgSession
  items: RpgItem[]
  module?: RpgModule
  locked: boolean
  onUseItem: (name: string, exact: boolean, quantity?: number) => void
  /** 丢弃：keep 是丢完后还剩几件（0 = 整件丢掉），不进剧情 */
  onDiscardItem: (name: string, keep: number) => void
  /** 认下一件新道具。consumable 只在模组里还没有同名定义时才用得上 */
  onConfirmClaim: (id: string, consumable: boolean) => void
  onDismissClaim: (id: string) => void
}) {
  const bag = sess.inventory || []
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [discardQty, setDiscardQty] = useState<Record<string, number>>({})
  // 结算说你拿到了、还没认的那几件。**不混进下面那堆**：下面每一件都是确定在你
  // 身上的东西，这些还只是「模型说你有」
  const claims = sess.item_claims || []
  const itemByName = (name: string) => items.find(i => norm(i.name) === norm(name))

  // 按模组里写的类别分组。没定义、或类别不在这几个里（向导曾经产出过「关键物品」
  // 这种自由写法）的：用得完的归消耗品，其余归「其他」
  const groupOf = (name: string) => {
    const def = itemByName(name)
    if (def && (ITEM_CATEGORIES as readonly string[]).includes(def.category)) return def.category
    return def?.consumable ? '消耗品' : OTHER
  }
  const groups = [...ITEM_CATEGORIES, OTHER]
    .map(label => ({ label, rows: bag.filter(it => groupOf(it.name) === label) }))
    .filter(group => group.rows.length > 0)

  // 选中的那件用完 / 丢光之后就不在背包里了，详情栏随之自己收起
  const current = bag.find(it => it.name === selected)

  const pick = (name: string) => {
    setSelected(selected === name ? null : name)
    setConfirming(false)
  }

  const renderDetail = (it: (typeof bag)[number]) => {
    const def = itemByName(it.name)
    // 有定义且作者勾了「能用」= 引擎精确结算
    const exact = !!def?.usable
    // 没定义的东西照样能点：开局背包名字打歪了、或者剧情里 GM 现给的，
    // 都不是玩家的错，不该让他只能自己打字。
    // 有定义但没勾「能用」的不给按钮——那是作者明说了「这不是用来用的」
    const canUse = exact || !def
    const quantity = def?.consumable ? Math.max(1, quantities[it.name] || 1) : 1
    const effects = Object.fromEntries(Object.entries(def?.effects || {}).map(
      ([name, amount]) => [name, amount * quantity],
    ))
    const blocked = it.qty < quantity ? '数量不足' : effectCostReason(effects, sess, module)
    const dropQty = Math.max(1, Math.min(it.qty, discardQty[it.name] || 1))
    const group = groupOf(it.name)
    const { icon: Icon, tone } = LOOK[group]
    return (
      // 钉在滚动区底部：格子再多，选中的那件的说明和按钮也始终在手边
      <div
        className="sticky bottom-0 -mx-3 -mb-3 px-3 pt-3 pb-3 border-t border-border/60 bg-card
          shadow-[0_-10px_18px_-14px_hsl(var(--foreground)/0.35)]"
      >
        <div className="flex items-start gap-3">
          <span className={`shrink-0 w-11 h-11 rounded-lg border flex items-center justify-center ${tone}`}>
            <Icon className="w-6 h-6" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <p className="text-sm font-medium truncate">{it.name}</p>
              {it.qty > 1 && <span className="text-xs text-muted-foreground shrink-0">×{it.qty}</span>}
            </div>
            <p className="text-[11px] text-muted-foreground">{group}</p>
          </div>
          <button
            onClick={() => setSelected(null)}
            title="收起"
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        {(def?.description || it.note) && (
          <p className="text-xs text-muted-foreground leading-relaxed mt-2 max-h-24 overflow-y-auto">
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
        {confirming ? (
          <div className="flex items-center gap-2 mt-2.5">
            {it.qty > 1 && (
              <input
                type="number"
                min={1}
                max={it.qty}
                value={dropQty}
                onChange={event => setDiscardQty(prev => ({
                  ...prev, [it.name]: Math.max(1, Math.min(it.qty, Number(event.target.value) || 1)),
                }))}
                className="w-16 rounded-lg border bg-transparent px-2 py-1.5 text-xs"
                aria-label={`丢弃${it.name}数量`}
              />
            )}
            <button
              onClick={() => {
                onDiscardItem(it.name, it.qty - dropQty)
                setConfirming(false)
                setSelected(null)
              }}
              disabled={locked}
              className="flex-1 text-xs py-1.5 rounded-lg bg-rose-600 text-white hover:opacity-90 disabled:opacity-40"
            >
              确认丢弃{it.qty > 1 ? ` ${dropQty} 件` : ''}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-xs px-3 py-1.5 rounded-lg border hover:bg-muted"
            >
              取消
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 mt-2.5">
            {canUse && exact && def?.consumable && it.qty > 1 && (
              <input
                type="number"
                min={1}
                max={it.qty}
                value={quantities[it.name] || 1}
                onChange={event => setQuantities(prev => ({
                  ...prev, [it.name]: Math.max(1, Math.min(it.qty, Number(event.target.value) || 1)),
                }))}
                disabled={locked}
                className="w-16 rounded-lg border bg-transparent px-2 py-1.5 text-xs"
                aria-label={`使用${it.name}数量`}
              />
            )}
            {canUse && (
              <button
                onClick={() => onUseItem(it.name, exact, quantity)}
                disabled={locked || !!blocked}
                title={blocked || (exact
                  ? '效果是模组里写死的，AI 改不了'
                  : '模组里没有这件道具的定义：用出来什么效果由 GM 现写，数值不精确')}
                // 描边 = 效果不精确。和「数字是死的」那种明显区分开，
                // 不然玩家会以为两种按钮是一回事
                className={`flex-1 text-xs py-1.5 rounded-lg disabled:opacity-40 ${
                  exact
                    ? 'bg-primary text-primary-foreground hover:opacity-90'
                    : 'border text-muted-foreground hover:bg-muted'
                }`}
              >
                使用
              </button>
            )}
            <button
              onClick={() => setConfirming(true)}
              disabled={locked}
              title="从背包里扔掉，不会进剧情"
              className={`text-xs px-3 py-1.5 rounded-lg border text-muted-foreground
                hover:bg-muted hover:text-rose-600 disabled:opacity-40 ${canUse ? '' : 'flex-1'}`}
            >
              丢弃
            </button>
          </div>
        )}
      </div>
    )
  }

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
      ) : groups.map(group => {
        const { icon: GroupIcon, tone } = LOOK[group.label]
        return (
          <div key={group.label} className="space-y-2">
            <div className="flex items-center gap-1.5 px-0.5 text-xs text-muted-foreground">
              <GroupIcon className="w-3.5 h-3.5" />
              <span>{group.label} · {group.rows.length}</span>
              <span className="flex-1 h-px bg-border/60" />
            </div>
            {/* 窄了自动掉到两列、宽了自动长到四五列：侧栏能拖到 280~520 */}
            <div
              className="grid gap-2"
              style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(72px, 1fr))' }}
            >
              {group.rows.map(it => {
                const on = it.name === selected
                return (
                  <button
                    key={it.name}
                    onClick={() => pick(it.name)}
                    aria-pressed={on}
                    title={it.name}
                    style={on ? { boxShadow: '0 0 0 2px hsl(var(--rpg-bag))' } : undefined}
                    className={`relative aspect-square rounded-lg border flex flex-col items-center
                      justify-center gap-1 px-1 transition hover:brightness-110 ${tone}`}
                  >
                    <GroupIcon className="w-7 h-7" />
                    <span className="w-full text-[11px] leading-tight text-foreground truncate text-center">
                      {it.name}
                    </span>
                    {it.qty > 1 && (
                      <span className="absolute top-1 right-1 min-w-[16px] px-1 rounded-full bg-background/85
                        text-[10px] leading-4 font-medium text-foreground text-center">
                        {it.qty}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
      {current && renderDetail(current)}
    </>
  )
}
