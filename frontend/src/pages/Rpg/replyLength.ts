/** 旁白长度的三个挡位。「不限」固定是 0，不进可编辑的那三档 */
export const TIER_LABELS = ['简短', '适中', '详细'] as const
export const DEFAULT_TIERS = [150, 300, 600]

/** 模组存的三档字数；没存过、存坏了都退回默认，不让下拉框出现空档 */
export const replyTiers = (saved: number[] | undefined): number[] =>
  TIER_LABELS.map((_, i) => {
    const n = Math.round(Number(saved?.[i]))
    return n > 0 ? n : DEFAULT_TIERS[i]
  })
