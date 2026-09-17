/**
 * 立绘的基础画风。按钮显示中文，实际拼进提示词的是英文 tag——
 * Z-Image 的文本编码器是 Qwen-3-4B，中英文都吃，但英文画风 tag 在扩散模型里
 * 语义更锐（「写实」这两个字的向量比 photorealistic 散得多）。
 *
 * 存进 image_config.style 的是**展开后的 tag 串**而不是 key：这样后端和拼提示词
 * 的地方都不用认识这张表，以后加画风只改这一个文件。
 *
 * 只能单选：写实和日漫勾在一起会让模型两头打架。hentai、质量词、画师串这些
 * 不在这里，放抽屉里那个自由补充框。
 */
export const IMAGE_STYLES = [
  { key: '', label: '不指定', tag: '' },
  { key: 'real', label: '写实', tag: 'photorealistic, realistic, photography' },
  { key: 'semi', label: '半写实', tag: 'semi-realistic, 2.5d' },
  { key: '3d', label: '3D', tag: '3d render, 3dcg, octane render' },
  { key: 'cg', label: 'CG', tag: 'cg art, game cg, digital painting' },
  { key: 'anime', label: '日漫', tag: 'anime, manga style, japanese animation' },
] as const
