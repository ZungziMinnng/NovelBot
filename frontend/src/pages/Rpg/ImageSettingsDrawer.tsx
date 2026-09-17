import type { RpgModule as Module } from '@/api/client'
import ImageSettingsFields from './ImageSettingsFields'

/**
 * 出图设置：挑工作流、开关 LoRA、挑姿势、挑基础画风、写自由补充词。
 *
 * 签名照 `GenerationParams` 取 `{ form, set }`——改动写进表单，由页面上已有的
 * `useAutosave` 落库，这里不自己发请求（两条写路径同时改 image_config 会互相盖）。
 *
 * 那几栏本身搬去了 `ImageSettingsFields`，因为角色的立绘弹窗也要用同一套 UI
 * 对同一份设置做**稀疏覆写**（见 imageConfig.ts）。这里只剩「把它接到模组表单
 * 上」这一层，所以短——这一份是总览和默认值，单个角色再微调。
 */
export default function ImageSettingsDrawer({
  form, set,
}: {
  form: Module
  set: <K extends keyof Module>(key: K, value: Module[K]) => void
}) {
  return (
    <div className="p-4 overflow-y-auto h-full">
      <ImageSettingsFields
        cfg={form.image_config || {}}
        onChange={next => set('image_config', next)}
        genre={form.genre || ''}
      />
    </div>
  )
}
