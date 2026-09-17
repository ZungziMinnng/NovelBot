import { useQuery } from '@tanstack/react-query'
import { rpgApi, type RpgImageConfig, type RpgLoraOverride } from '@/api/client'
import { DEFAULT_FRAME, IMAGE_FRAMES, frameOf } from './imageFrames'
import { DEFAULT_POSE, IMAGE_POSES } from './imagePoses'
import { IMAGE_STYLES } from './imageStyles'
import { loraKeyOf, mergeImageConfig, patchConfig } from './imageConfig'
import { INPUT } from './rpgUi'

/** `ZIT\breast-size-ZIT-Breast-Slider.safetensors` → `breast-size-ZIT-Breast-Slider` */
const loraLabel = (path: string) =>
  path.split(/[\\/]/).pop()!.replace(/\.safetensors$/i, '')

/** 「跟随模组」在工作流下拉里的哨兵值。不能用 `''`：那是「明确选后端默认
 *  npc_portrait」，和「不覆写」是两个意思 */
const INHERIT = '__inherit'

/**
 * 出图设置那几栏：工作流、LoRA、姿势、基础画风、额外补充，加末尾的预览块。
 *
 * 抽成一个组件是因为它现在有**两个宿主，改的还是同一份东西**：
 *   - `ImageSettingsDrawer` 里那份是模组的，性质是「默认值」
 *   - `NpcAvatarField` 的生成弹窗里那份是单个角色的，性质是「稀疏覆写」
 *
 * 靠 `inherit` 区分：不传 = 模组模式（行为、文案、className 和抽出来之前逐字
 * 一样）；传了 = 角色模式，每一栏多一档「跟随模组」，预览按合并后的值画。
 *
 * 组件自己**不发写请求、不管落库时机**：值全从 `cfg` 读、改动全走 `onChange`。
 * 两个宿主的落库节奏完全不一样——模组靠页面的 autosave，角色靠弹窗关窗 /
 * 生成前那两下手动 PATCH——把「什么时候写库」留在宿主手里，这里只管画。
 */
export default function ImageSettingsFields({ cfg, onChange, genre, inherit }: {
  cfg: RpgImageConfig
  onChange: (next: RpgImageConfig) => void
  /** 模组题材，只用来画预览 */
  genre: string
  /** 给了就是「角色微调」模式：每一栏多一个「跟随模组」档，预览按合并后的值画。
   *  不给就是模组模式，和以前完全一样 */
  inherit?: RpgImageConfig
}) {
  const npcMode = inherit !== undefined
  // 生效值：真正会拼进提示词的那份。LoRA 的取值基线、预览、姿势/画风的默认档
  // 全看它。但**按钮的选中态不能看它**，理由见下面姿势那一栏的注释
  const eff = inherit ? mergeImageConfig(inherit, cfg) : cfg
  // 稀疏靠「有没有这个 key」表达，所以传 undefined 进来时要让 patchConfig
  // 真把 key 删掉，不能留一个 `pose: undefined` 在对象里
  const patch = (next: Partial<RpgImageConfig>) => onChange(patchConfig(cfg, next))

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ['rpg-comfy-workflows'],
    queryFn: rpgApi.comfyWorkflows,
  })

  // 这份工作流里有哪些 LoRA。空 workflow 是合法值（后端走默认 npc_portrait），
  // 但工作流列表都还没读到时就别问了——那会儿多半连目录都是空的。
  // key 用 eff 而不是 cfg：角色可能覆写了工作流，拿 cfg 的原始值会在「角色选了
  // 别的流」时去问错一份工作流有哪些 LoRA
  const loraKey = loraKeyOf(eff)
  const { data: loras = [], isLoading: loraLoading, error: loraError } = useQuery({
    queryKey: ['rpg-comfy-loras', loraKey],
    queryFn: () => rpgApi.comfyLoras(loraKey),
    enabled: workflows.length > 0,
    retry: false,
  })

  // 这一层存的那组覆写，和上一层（模组）存的那组。取某个 LoRA 的当前值时
  // 三层落回：本层覆写 → 模组覆写 → 工作流文件里的原始值
  const ov = (cfg.loras || {})[loraKey] || {}
  const modOv = (inherit?.loras || {})[loraKey] || {}
  const setLora = (lora: string, next: RpgLoraOverride) =>
    patch({ loras: { ...(cfg.loras || {}), [loraKey]: { ...ov, [lora]: next } } })

  // 姿势是三态：undefined = 没设过走默认，'' = 明确不指定。必须用 ?? 不能用 ||
  const pose = eff.pose ?? DEFAULT_POSE
  const frame = frameOf(eff.frame)
  // 生效的提示词形态：缺省当中文，只有显式 sd_tags 才是 tag 形态。预览块靠它换文案
  const isTags = eff.prompt_form === 'sd_tags'
  // 预览用的几段，顺序和 NpcAvatarField.buildPrompt 里追加的完全一致，
  // 不然这里看到的和实际发出去的不是一句话
  const tail = [genre, eff.style, eff.extra, pose, frame.tag]
    .map(s => (s || '').trim())
    .filter(Boolean)

  // 底模只在英文 tag 形态下才问：中文那套（Z-Image）不吃 checkpoint，问了白问，
  // 而且这个查询要连 ComfyUI——不卡住的话它没开时会给每个用户凭空报错
  const { data: ckptInfo, error: ckptError } = useQuery({
    queryKey: ['rpg-comfy-checkpoints', loraKey],
    queryFn: () => rpgApi.comfyCheckpoints(loraKey),
    enabled: workflows.length > 0 && isTags,
    retry: false,
  })
  // 空 slots = 这份工作流走 UNETLoader 单文件、根本不写底模，整块不画
  const ckptSlots = ckptInfo?.slots || []
  const slotNames = Array.from(new Set(ckptSlots.map(s => s.name)))
  const ownCkpt = (cfg.checkpoints || {})[loraKey]
  // 工作流文件里写的那个名字也要进选项：它可能已经不在 ComfyUI 里了（换过盘、
  // 删过文件）。只列 available 的话 select 的 value 匹配不上任何一项，浏览器
  // 会默默显示第一项，看着像「已经改成了别的底模」，其实动都没动
  const ckptOptions = Array.from(new Set([
    ...(ckptInfo?.available || []), ...slotNames, ...(ownCkpt ? [ownCkpt] : []),
  ]))
  // 选空 = 不覆写，把这个工作流的条目删掉。条目清空了整个 key 也删掉，
  // 免得库里留一个 `checkpoints: {'': ''}` 这种没意义的残渣
  const setCkpt = (name: string) => {
    const next = { ...(cfg.checkpoints || {}) }
    if (name) next[loraKey] = name
    else delete next[loraKey]
    patch({ checkpoints: Object.keys(next).length ? next : undefined })
  }

  return (
    <div className="space-y-5">
      <div>
        <label className="text-sm font-medium mb-2 block">工作流</label>
        {isLoading ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : workflows.length === 0 ? (
          // 空列表不画空下拉：那看着像「加载失败」，而真实原因是文件还没放
          <p className="text-xs text-muted-foreground leading-relaxed">
            <code>backend/data/comfy_workflows/</code> 下还没有工作流。
            在 ComfyUI 里用「工作流 → 导出（API）」存一份，
            把正向提示词那段文字整体换成 <code>%PROMPT%</code>，放进这个目录。
          </p>
        ) : (
          <select
            value={npcMode ? (cfg.workflow ?? INHERIT) : (cfg.workflow || '')}
            // 写 undefined 让 patchConfig 把这个 key 删掉，这才叫「不覆写」
            onChange={e => patch({
              workflow: e.target.value === INHERIT ? undefined : e.target.value,
            })}
            className={INPUT}
          >
            {npcMode && (
              <option value={INHERIT}>
                跟随模组（{inherit?.workflow?.trim() || '默认 npc_portrait'}）
              </option>
            )}
            <option value="">默认（npc_portrait）</option>
            {workflows.map(w => <option key={w} value={w}>{w}</option>)}
          </select>
        )}
        <p className="text-xs text-muted-foreground mt-1.5">
          换工作流等于换画风底子和出图耗时，里面的 LoRA 和采样步数都不一样。
        </p>
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">提示词形态</label>
        <div className="flex flex-wrap gap-1.5">
          {npcMode && (
            <button
              onClick={() => patch({ prompt_form: undefined })}
              title="这一栏不覆写，跟着模组走"
              className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                cfg.prompt_form === undefined
                  ? 'bg-primary text-primary-foreground ring-primary'
                  : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
              }`}
            >
              跟随模组
            </button>
          )}
          {/* undefined 缺省 = 中文（老模组行为）。选中态看 cfg 不看 eff，同姿势那栏 */}
          {([
            ['natural_zh', '中文自然语言'],
            ['sd_tags', '英文 tag（光辉）'],
          ] as const).map(([val, label]) => {
            const cur = npcMode ? cfg.prompt_form : (eff.prompt_form ?? 'natural_zh')
            return (
              <button
                key={val}
                onClick={() => patch({ prompt_form: val })}
                className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                  cur === val
                    ? 'bg-primary text-primary-foreground ring-primary'
                    : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          光辉（Illustrious）这类 SDXL 工作流只认英文 tag，选它出图时会先把中文转成
          tag 给你过目再发。Z-Image 吃中文，保持「中文自然语言」就行。
        </p>
      </div>

      {/* 底模只在英文 tag 形态下才有意义，而且得这份工作流真的认底模才画——
          走 UNETLoader 单文件的（默认的 npc_portrait 就是）填了也不生效，
          画一个没反应的下拉比不画更糟。读不出来的话单独说一声，别静默消失 */}
      {isTags && ckptError && (
        <p className="text-[11px] text-destructive leading-relaxed whitespace-pre-wrap">
          {(ckptError as { response?: { data?: { detail?: string } } })
            .response?.data?.detail || '读不到可用底模列表'}
        </p>
      )}
      {isTags && ckptSlots.length > 0 && (
        <div>
          <label className="text-sm font-medium mb-2 block">底模</label>
          <select
            value={ownCkpt ?? (npcMode ? INHERIT : '')}
            onChange={e => setCkpt(e.target.value === INHERIT ? '' : e.target.value)}
            className={INPUT}
          >
            {npcMode ? (
              <option value={INHERIT}>
                跟随模组（{inherit?.checkpoints?.[loraKey]?.trim() || '用工作流自带的'}）
              </option>
            ) : (
              <option value="">用工作流自带的</option>
            )}
            {ckptOptions.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <p className="text-xs text-muted-foreground mt-1.5">
            换掉工作流里写死的底模。<b>一处不落</b>：这份工作流有 {ckptSlots.length} 处
            写了底模（含高清修复阶段那处），会一起换成你选的这个——
            只改一半的话，前几步用新模型、高清修复还用旧的，风格会漂。
            {slotNames.length > 1 && !ownCkpt && (
              <>
                {' '}它现在这几处<b>本来就不一样</b>（{slotNames.join(' / ')}），
                不选就保持原样。
              </>
            )}
          </p>
        </div>
      )}

      <div>
        <label className="text-sm font-medium mb-2 block">画幅</label>
        <div className="flex flex-wrap gap-1.5">
          {npcMode && (
            <button
              onClick={() => patch({ frame: undefined })}
              title="这一栏不覆写，跟着模组走"
              className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                cfg.frame === undefined
                  ? 'bg-primary text-primary-foreground ring-primary'
                  : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
              }`}
            >
              跟随模组
            </button>
          )}
          {IMAGE_FRAMES.map(f => {
            // 选中态看 cfg 不看 eff（同姿势那栏）；缺省档是 DEFAULT_FRAME
            const cur = npcMode ? cfg.frame : (eff.frame ?? DEFAULT_FRAME)
            return (
              <button
                key={f.key}
                onClick={() => patch({ frame: f.key })}
                title={`${f.width}×${f.height}，${f.tag}`}
                className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                  cur === f.key
                    ? 'bg-primary text-primary-foreground ring-primary'
                    : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
                }`}
              >
                {f.label}
              </button>
            )
          })}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          决定尺寸和一句构图 tag。横幅 CG 出的是 {frameOf(eff.frame).width}×
          {frameOf(eff.frame).height} 那种带场景的图。
          <b>工作流里要先把尺寸换成 <code>%WIDTH%</code>/<code>%HEIGHT%</code></b>，
          否则尺寸不生效（还是出工作流写死的那个）。
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium">LoRA</label>
          {Object.keys(ov).length > 0 && (
            <button
              onClick={() => {
                // 只删当前工作流名下这一组。别的工作流名的覆写是另一回事，
                // 一起删掉的话用户切回旧工作流会发现调过的权重全没了
                const { [loraKey]: _drop, ...rest } = cfg.loras || {}
                patch({ loras: rest })
              }}
              className="text-xs text-muted-foreground hover:text-foreground underline"
            >
              {npcMode ? '全部跟随模组' : '全部恢复工作流默认'}
            </button>
          )}
        </div>
        {loraLoading ? (
          <p className="text-xs text-muted-foreground">读取中…</p>
        ) : loraError ? (
          // 读不出来多半是工作流文件本身的问题（JSON 坏了、是界面格式），
          // 后端那句话已经说清该怎么办，原样显示比写「加载失败」有用
          <p className="text-xs text-destructive leading-relaxed whitespace-pre-wrap">
            {(loraError as { response?: { data?: { detail?: string } } })
              .response?.data?.detail || '读不到这份工作流的 LoRA'}
          </p>
        ) : loras.length === 0 ? (
          <p className="text-xs text-muted-foreground leading-relaxed">
            这份工作流里没找到 LoRA 节点。只认原生的 <code>LoraLoader</code> 和 rgthree 的{' '}
            <code>Power Lora Loader</code>——用别的加载器就得回 ComfyUI 里调。
          </p>
        ) : (
          <div className="space-y-1.5">
            {loras.map(slot => {
              // 三层落回：本层覆写 → 模组覆写 → 工作流文件里的原始值。
              // 用 `??` 不能用 `||`：`{on:false,strength:0}` 是合法覆写，
              // `||` 会把它当假值跳过、掉回工作流原始值——模组明明关了它
              const cur = ov[slot.lora] ?? modOv[slot.lora]
                ?? { on: slot.on, strength: slot.strength }
              const mine = slot.lora in ov
              const fromModule = !mine && slot.lora in modOv
              return (
                <div key={slot.lora} className="rounded-lg border bg-muted/30 px-2.5 py-2">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-primary"
                      checked={cur.on}
                      onChange={e => setLora(slot.lora, {
                        on: e.target.checked,
                        // 从「关」拨到「开」时权重还是 0 的话，开了也等于没开
                        strength: e.target.checked && cur.strength === 0 ? 1 : cur.strength,
                      })}
                    />
                    <span
                      title={slot.lora}
                      className={`text-xs truncate ${cur.on ? 'font-medium' : 'text-muted-foreground'}`}
                    >
                      {loraLabel(slot.lora)}
                    </span>
                    {mine ? (
                      <span className="ml-auto shrink-0 text-[10px] text-primary">已改</span>
                    ) : fromModule ? (
                      // 说一句「这个数不是工作流文件里的」，免得用户以为文件被改过
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                        模组改过
                      </span>
                    ) : null}
                  </label>
                  <div className={`flex items-center gap-2 mt-1.5 ${cur.on ? '' : 'opacity-40'}`}>
                    <input
                      type="range"
                      min={-1}
                      max={2}
                      step={0.05}
                      value={cur.strength}
                      disabled={!cur.on}
                      aria-label={`${loraLabel(slot.lora)} 权重`}
                      onChange={e => setLora(slot.lora, {
                        on: cur.on, strength: Number(e.target.value),
                      })}
                      className="flex-1 accent-primary disabled:cursor-not-allowed"
                    />
                    <span className="w-10 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                      {cur.strength.toFixed(2)}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <p className="text-xs text-muted-foreground mt-1.5 leading-relaxed">
          只能开关和调权重，<b>加新的 LoRA 还得回 ComfyUI 改工作流再导出</b>。
          这里的改动只在出图时临时打进去，你存的工作流文件不会被改写。
          滑块能拉到负数：breast-size 这类 slider LoRA 往负方向拉是反向效果，
          普通画风 LoRA 拉负数只会出鬼图。
        </p>
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">姿势</label>
        <div className="flex flex-wrap gap-1.5">
          {npcMode && (
            <button
              onClick={() => patch({ pose: undefined })}
              title="这一栏不覆写，跟着模组走"
              className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                cfg.pose === undefined
                  ? 'bg-primary text-primary-foreground ring-primary'
                  : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
              }`}
            >
              跟随模组
            </button>
          )}
          {IMAGE_POSES.map(p => {
            // 角色模式下选中态**看 cfg 不看 eff**：eff 是合并后的值，模组那边
            // 恰好也是这一档时，「跟随模组」和这一档会同时高亮，看着像单选坏了。
            // 模组模式才用生效值（那份本来就没有「跟不跟随」这一说）
            const on = npcMode ? cfg.pose === p.tag : pose === p.tag
            return (
              <button
                key={p.key}
                onClick={() => patch({ pose: p.tag })}
                title={p.tag || '提示词里不加姿势，构图完全交给模型'}
                className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                  on
                    ? 'bg-primary text-primary-foreground ring-primary'
                    : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
                }`}
              >
                {p.label}
              </button>
            )
          })}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          单选，拼在提示词最后。选「不指定」就一句都不加——但只给外貌描述的话，
          模型多半只画个大头照。
        </p>
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">基础画风</label>
        <div className="flex flex-wrap gap-1.5">
          {npcMode && (
            <button
              onClick={() => patch({ style: undefined })}
              title="这一栏不覆写，跟着模组走"
              className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                cfg.style === undefined
                  ? 'bg-primary text-primary-foreground ring-primary'
                  : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
              }`}
            >
              跟随模组
            </button>
          )}
          {IMAGE_STYLES.map(s => {
            // 同姿势那一栏：角色模式看 cfg，不看合并后的 eff
            const on = npcMode ? cfg.style === s.tag : (eff.style || '') === s.tag
            return (
              <button
                key={s.key}
                onClick={() => patch({ style: s.tag })}
                title={s.tag || '提示词里不加画风词，完全由工作流决定'}
                className={`text-xs px-2.5 py-1 rounded-lg ring-1 ${
                  on
                    ? 'bg-primary text-primary-foreground ring-primary'
                    : 'bg-primary/10 text-primary ring-primary/30 hover:bg-primary/20'
                }`}
              >
                {s.label}
              </button>
            )
          })}
        </div>
        <p className="text-xs text-muted-foreground mt-1.5">
          单选。写实和日漫勾在一起会让模型两头打架。
        </p>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium">额外补充</label>
          {npcMode && cfg.extra !== undefined && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-primary">已改写</span>
              <button
                onClick={() => patch({ extra: undefined })}
                className="text-xs text-muted-foreground hover:text-foreground underline"
              >
                跟随模组
              </button>
            </div>
          )}
        </div>
        <input
          // 空串和 undefined 在角色模式下是两回事：空串 = 覆写成「什么都不加」，
          // undefined = 还没覆写。输入框两者都是空的，所以差别靠上面那个
          // 「已改写」和这里的 placeholder 说清
          value={cfg.extra ?? ''}
          onChange={e => patch({ extra: e.target.value })}
          placeholder={
            npcMode && cfg.extra === undefined
              ? (inherit?.extra?.trim()
                  ? `跟随模组：${inherit.extra}`
                  : '跟随模组（模组也没写）')
              : '例：absurdres, hentai, 画师串'
          }
          className={INPUT}
        />
        <p className="text-xs text-muted-foreground mt-1.5">
          质量词、画师串、题材倾向这些自己往里写，原样拼进提示词。
        </p>
      </div>

      {/* 选了英文 tag 形态时，这段中文只是**转换前的源文**，不是最终发出去的提示词——
          出图时会先调接口转成英文 tag。标题和末句都说清，免得用户以为中文原样进了图 */}
      {isTags && (
        <p className="text-[11px] text-amber-500 mb-2">
          下面这段是<b>转换前的中文源文</b>。选了「英文 tag」，出图时会先把它转成英文
          Danbooru tag（含姿势、画幅那几段）再发——最终提示词以生成弹窗里的 tag 框为准。
        </p>
      )}
      <div className="rounded-lg border bg-muted/40 p-3">
        <p className="text-xs font-medium mb-1">{isTags ? '中文源文（转换前）' : '会追加成这样'}</p>
        <p className="text-xs text-muted-foreground leading-relaxed break-all">
          角色外貌描述……，<span className="text-muted-foreground/70">常驻地点及其描述……</span>
          {tail.length ? <>，<span className="text-foreground">{tail.join('，')}</span></> : null}
        </p>
        {npcMode ? (
          // 角色弹窗里说「上面基本信息里的题材栏」没意义——那一栏不在这个弹窗里。
          // 只留最要紧的一句：这段字就是上面提示词框里的内容
          <p className="text-[11px] text-muted-foreground mt-2">
            这一句就是上面提示词框里那段的后半截，没改的项跟着模组走。
          </p>
        ) : (
          <p className="text-[11px] text-muted-foreground mt-2">
            地点那一段来自这个人「常驻地点」在<b>地点</b>里那一条的描述——不带地点的话，
            模型会把人摆在白墙或者摄影棚幕布前面。
            题材来自上面「基本信息」里的<b>题材</b>栏（现在是
            {genre.trim() ? `「${genre.trim()}」` : '空的'}）。
            点「生成立绘」时这整句会预填进弹窗，不想要的段落可以当场删。
          </p>
        )}
      </div>
    </div>
  )
}
