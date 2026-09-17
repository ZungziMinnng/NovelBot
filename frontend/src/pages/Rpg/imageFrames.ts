/**
 * 出图画幅：尺寸 + 一句构图 tag。立绘是竖的，CG 是横的，插图多半是方的。
 *
 * **存的是 key，不是展开值**——这和隔壁 imageStyles.ts / imagePoses.ts 故意不一样。
 * 那两张表存展开后的 tag 串，好处是后端和拼提示词的地方都不用认识表本身；
 * 但画幅还带着 width / height 两个数字，展开成一个字符串装不下，所以只能存 key
 * 再回表查。加新画幅时改这一个文件就够，但**别把这里的 key 直接拼进提示词**。
 *
 * 尺寸都是 64 的倍数：SDXL 系的 UNet 按 8x 下采样再过 patch，不是 64 倍数会被
 * 悄悄裁掉几个像素。832×1216 / 1216×832 是 SDXL 官方训练用的分辨率档，
 * Z-Image 跑这两个数也正常，所以一套表两条链路共用，不按 prompt_form 分。
 */
export const IMAGE_FRAMES = [
  {
    key: 'portrait',
    label: '立绘竖版',
    width: 832,
    height: 1216,
    /** 竖幅要明说全身，不然模型爱画大头照 */
    tag: 'standing, full_body',
  },
  {
    key: 'cg_wide',
    label: '横幅 CG',
    width: 1216,
    height: 832,
    /** game_cg 是真 tag（66,079 张），带出的是galgame 那种带场景的构图 */
    tag: 'game_cg, scenery',
  },
  {
    key: 'square',
    label: '方图插图',
    width: 1024,
    height: 1024,
    tag: 'official_art, upper_body',
  },
] as const

/**
 * 没设过画幅时用哪一档。
 *
 * `portrait` 的 832×1216 和加这个功能之前写死的 1024×1536 **不是同一个数**：
 * 老值不是 SDXL 的标准档，在光辉上容易出构图畸变（人物被拉长、多头）。
 * 换成标准档是有意的，代价是老模组重新生成时构图会和之前那张略有不同——
 * 立绘本来每次重摇都不一样，这个代价可以接受。
 */
export const DEFAULT_FRAME = 'portrait'

/**
 * 按 key 取一档，取不到就落回默认档。
 *
 * **一定要有兜底**：`frame` 存在库里的 JSON 列里，用户导入别人的模组、或者
 * 这张表以后删掉某一档，都会留下一个查不到的 key。返回 undefined 会让调用方
 * 拿到 `undefined.width` 直接白屏，落回默认档只是构图不如预期。
 */
export function frameOf(key: string | undefined) {
  return IMAGE_FRAMES.find(f => f.key === key)
    ?? IMAGE_FRAMES.find(f => f.key === DEFAULT_FRAME)!
}
