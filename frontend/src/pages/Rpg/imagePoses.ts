/**
 * 立绘的姿势 / 取景。结构照 imageStyles.ts，存进 image_config.pose 的是
 * **展开后的 tag** 而不是 key。
 *
 * 和画风相反，这里的 tag 是**中文**：画风用英文是因为 photorealistic 这类词在
 * 扩散模型里语义更锐，而「站姿全身像」这句中文是实测出过图的，不动它。
 *
 * 末尾补一句取景本身是必要的——只给外貌描述，模型多半只画个大头照，不是立绘。
 */
export const IMAGE_POSES = [
  { key: 'none', label: '不指定', tag: '' },
  { key: 'stand_full', label: '站姿全身像', tag: '站姿全身像' },
  { key: 'stand_half', label: '站姿半身像', tag: '站姿半身像，腰部以上' },
  { key: 'bust', label: '胸像特写', tag: '胸像特写，肩部以上' },
  { key: 'sit', label: '坐姿', tag: '坐姿全身像' },
  { key: 'look_back', label: '侧身回望', tag: '侧身回望，全身' },
  { key: 'lying', label: '躺姿', tag: '躺姿，全身' },
  { key: 'dynamic', label: '动态姿势', tag: '动态姿势，全身，衣摆飘动' },
] as const

/**
 * 没设过姿势时用哪个。和加这个功能之前 buildPrompt 末尾那句写死的值逐字一致。
 *
 * **取默认值必须用 `??`，不能用 `||`** —— 这一列有三种状态：
 *   - `undefined`：老模组、从没设过 → 站姿全身像
 *   - `''`：用户明确选了「不指定」 → 什么都不追加
 *   - 其它：用户选的那一档
 * 写成 `cfg.pose || DEFAULT_POSE` 会把「不指定」也吞成默认值，那个按钮就永远
 * 点不出效果。
 */
export const DEFAULT_POSE = '站姿全身像'
