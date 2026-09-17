"""出图设置的两层合并：模组那份是总览和默认，某个人那份是稀疏覆写。

为什么要在后端也合一次——出图时**工作流名和 LoRA 覆写是后端从库里现读的**，
不进请求体（前端传一遍反而会和库里漂移，见 routes/rpg.py 里那条注释）。
所以「这个人用哪份工作流、哪几个 LoRA 开着」只能在这里算。

画风 / 姿势 / 补充词则相反：它们已经由前端拼进提示词文本了，用户在弹窗里看得见
也能删，后端不该再动一次。这里仍然把每一项都合出来，是为了让这个函数和前端
`pages/Rpg/imageConfig.ts` 的 `mergeImageConfig` 是**同一条规则**——一份配置在
两处按不同规则合并，出的图和预览就不是一回事，那种偏差极难查。

`frame` 同理：后端不读它（尺寸由前端算完传进请求体），但合并规则必须和
前端一致，否则「跟随模组」在两边算出不同结果。

`prompt_form` 是个例外——后端**要读**它：底模覆写只在英文 tag（`sd_tags`）
形态下生效，而这个门控只能在出图时判一次。光靠前端藏控件挡不住：用户填完
底模再切回中文自然语言，值还留在配置里，藏了控件它照样生效。
"""


def merge_image_config(base: dict | None, over: dict | None) -> dict:
    """模组那份打底，某个人那份盖上去。

    覆写是稀疏的，判据是**键在不在**，不是值真不真：`pose` / `style` / `extra`
    的空串都是有意义的取值（明确「不指定」「不加补充词」），拿 `over.get(k) or
    base.get(k)` 这种写法会把它们一起吞成继承模组——用户点了「不指定」，
    出的图却还带着模组那句「站姿全身像」。

    LoRA 是**逐条**合，不是整套替换：模组把 A 关了、这个人只把 B 的权重调高，
    这是两件互不相干的决定，都该生效。整套替换的话，这个人碰一下 B 就会把模组
    「关掉 A」那一下整片抹掉，A 又悄悄回到图里。底模和 LoRA 同理，也是按
    工作流名逐条合。
    """
    base = base or {}
    over = over or {}
    merged: dict = {}
    for key in ("workflow", "style", "pose", "extra", "prompt_form", "frame"):
        if key in over:
            merged[key] = over[key]
        elif key in base:
            merged[key] = base[key]

    base_loras = base.get("loras") or {}
    over_loras = over.get("loras") or {}
    if base_loras or over_loras:
        # 工作流名取并集：只在一侧出现的那组也要带过来，不然合并结果会丢东西
        merged["loras"] = {
            name: {**(base_loras.get(name) or {}), **(over_loras.get(name) or {})}
            for name in {*base_loras, *over_loras}
        }

    # 底模：一个工作流名对一个文件名，同样是工作流名取并集、逐条盖。
    # 值是字符串所以不用像 LoRA 那样再往里合一层。
    base_ckpts = base.get("checkpoints") or {}
    over_ckpts = over.get("checkpoints") or {}
    if base_ckpts or over_ckpts:
        merged["checkpoints"] = {**base_ckpts, **over_ckpts}
    return merged


def lora_key(cfg: dict | None) -> str:
    """LoRA / 底模覆写按工作流名分组存，这是那个分组名。

    空 workflow 是合法值（走默认工作流），但存 / 取覆写时必须统一补成
    `npc_portrait`：否则用户选了「默认」又调了 LoRA，前端存进 `loras['']`、
    这边去读 `loras['npc_portrait']`，调过的权重就凭空消失了。
    """
    return (cfg or {}).get("workflow", "").strip() or "npc_portrait"


def resolve_workflow(
    module_cfg: dict | None, npc_cfg: dict | None
) -> tuple[str, dict, str]:
    """出图要的三样东西：用哪份工作流（'' = 后端默认）、哪些 LoRA 覆写、哪个底模。

    返回的工作流名保留空串形态，交由调用方决定要不要传给 `comfyui.generate`
    ——那个函数的默认参数本身就是 `npc_portrait`，空串顶上去会找不到文件。

    底模只在 `sd_tags`（英文 tag）形态下才返回：那是光辉这类 SDXL 系工作流的
    用法，中文自然语言那套（Z-Image）不吃 checkpoint。判据是精确相等，所以
    缺省和空串都不生效。
    """
    cfg = merge_image_config(module_cfg, npc_cfg)
    # 分组键复用 lora_key：它本来就是「按工作流名分组的组名」，底模和 LoRA
    # 两份覆写共用一套归一规则，空 workflow 才都会被补成 npc_portrait
    key = lora_key(cfg)
    loras = (cfg.get("loras") or {}).get(key) or {}
    ckpt = ""
    if cfg.get("prompt_form") == "sd_tags":
        ckpt = ((cfg.get("checkpoints") or {}).get(key) or "").strip()
    return cfg.get("workflow", "").strip(), loras, ckpt
