import type { RpgImageConfig, RpgLoraOverride } from '@/api/client'

/**
 * 出图设置现在是两层：模组那份是**总览 + 默认**，角色那份是**稀疏覆写**。
 * 这里三个纯函数就是这套东西的全部逻辑，组件只负责画界面。
 *
 * 后端出图时也要合一次（`services/rpg_image.py`），两边规则必须一致——
 * 前端预览的那句话和实际发给 ComfyUI 的不是一句，比没有预览更糟。
 */

/**
 * 把「模组那份」和「角色那份」合成出真正生效的一份。
 *
 * 角色那份是稀疏的：某个字段**没有这个 key** = 跟随模组，有这个 key = 这个
 * 角色覆写。所以合并时判的是「key 在不在」，不是「值真不真」。
 *
 * **必须写 `over.X !== undefined ? over.X : base.X`，不能用 `||` 也不能用 `??`。**
 * 因为这几栏的空串是有意义的取值：
 *   - `pose: ''` = 明确「不指定姿势」，不是「没设过」
 *   - `extra: ''` = 明确「不加补充词」
 *   - `style: ''` = 明确「不加画风 tag，全交给工作流」
 * 写成 `over.pose || base.pose` 会把这三种情况一起吞成继承模组——用户点了
 * 「不指定」，出的图却还是带着模组那个「站姿全身像」，那几个按钮就永远点不出
 * 效果。`??` 虽然放得过空串，但这份数据的语义本来就是「有没有这个 key」，
 * 显式写 `!== undefined` 才是照着语义写，不用读者自己去推 nullish 的边界。
 */
export function mergeImageConfig(base: RpgImageConfig, over: RpgImageConfig): RpgImageConfig {
  const merged: RpgImageConfig = {
    workflow: over.workflow !== undefined ? over.workflow : base.workflow,
    style: over.style !== undefined ? over.style : base.style,
    pose: over.pose !== undefined ? over.pose : base.pose,
    extra: over.extra !== undefined ? over.extra : base.extra,
    prompt_form: over.prompt_form !== undefined ? over.prompt_form : base.prompt_form,
    frame: over.frame !== undefined ? over.frame : base.frame,
  }

  // LoRA **逐条**深合并，不是整套替换。理由：模组把 A 关了、这个角色只把 B 的
  // 权重从 0.8 调到 1.2，这是两件互不相干的决定，都该生效。要是整套替换
  // （`over.loras ?? base.loras`），角色只碰一下 B 就会把模组「关掉 A」那一下
  // 整片抹掉，出图时 A 又悄悄回来了。
  const baseLoras = base.loras || {}
  const overLoras = over.loras || {}
  if (base.loras !== undefined || over.loras !== undefined) {
    const loras: Record<string, Record<string, RpgLoraOverride>> = {}
    // 工作流名取并集：只在一侧出现的那组也要带过来，不然合并结果会丢东西
    for (const key of new Set([...Object.keys(baseLoras), ...Object.keys(overLoras)])) {
      loras[key] = { ...baseLoras[key], ...overLoras[key] }
    }
    merged.loras = loras
  }

  // 底模和 LoRA 一样按工作流名分组、一样逐条合：模组把 anime 那份指到某个底模、
  // 这个角色只改了 real 那份，是两件互不相干的决定，都该留下。值是字符串，
  // 所以不用像 LoRA 那样再往里合一层。
  const baseCkpts = base.checkpoints || {}
  const overCkpts = over.checkpoints || {}
  if (base.checkpoints !== undefined || over.checkpoints !== undefined) {
    merged.checkpoints = { ...baseCkpts, ...overCkpts }
  }

  return merged
}

/**
 * 打一个补丁：`{...cfg, ...next}` 之后**把值为 undefined 的 key 删掉**。
 *
 * 为什么非删不可：这份配置的稀疏性就是靠「key 在不在」表达的。留一个
 * `pose: undefined` 在对象里，`JSON.stringify` 发给后端时确实会把它丢掉、
 * 后端看到的没问题，但**本地**判 `cfg.pose === undefined` 的地方（「跟随模组」
 * 按钮的选中态就是这么判的）会以为这个角色设过姿势，于是「跟随模组」不高亮、
 * 用户怎么点都回不到跟随状态——刷新一下又好了，这种 bug 最难查。
 *
 * 所以「恢复跟随」统一走 `patch({ xxx: undefined })`，而不是让调用方各自
 * 去 `delete` 一遍。
 */
export function patchConfig(cfg: RpgImageConfig, next: Partial<RpgImageConfig>): RpgImageConfig {
  const out: Record<string, unknown> = { ...cfg }
  for (const k of Object.keys(next)) {
    const v = (next as Record<string, unknown>)[k]
    if (v === undefined) delete out[k]
    else out[k] = v
  }
  return out as RpgImageConfig
}

/**
 * LoRA 和底模两份覆写都是**按工作流名分组**存的：
 * `{工作流名: {LoRA 文件名: {on, strength}}}` / `{工作流名: checkpoint 名}`。
 * 要读写当前这组，就得先算出「当前用的是哪个工作流名」——两者共用这一个。
 *
 * 空 workflow 是合法值（表示走后端默认），但**后端读覆写时会先把它补成
 * `'npc_portrait'`**。所以这里也必须补成同一个名字，否则角色选了「默认」、
 * 又调了 LoRA，覆写会存进 `loras['']`，出图时后端去读 `loras['npc_portrait']`
 * 读了个空——用户调的权重就凭空消失了。
 */
export function loraKeyOf(cfg: RpgImageConfig): string {
  return (cfg.workflow || '').trim() || 'npc_portrait'
}
