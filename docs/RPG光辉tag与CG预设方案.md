# RPG 光辉 tag 链路与 CG 预设方案

## 要解决什么

你现在的出图工作流是 Z-Image，文本编码器是 Qwen-3-4B，吃中文自然语言，日常够用。
但碰到画风激烈的题材、或者偏向 A 漫的表达，Z-Image 就跟不上了。你手头有光辉
（Illustrious）模型和它的工作流，想接进来生成二次元立绘，以及子宫透视图、
拟声词这类更专门的内容。

光辉走的是 SDXL 那套 CLIP-L，**只认英文 Danbooru tag**，不认中文散文。所以核心
问题是：怎么把现在这套中文自然语言提示词，在切到光辉工作流时变成准确的 tag。

顺带要做的第二件事：支持 CG 和插图的生成。

---

## 现状：你已经有了一半，但两半没接上

代码里其实已经有两个相关的东西，可惜各干各的：

**会生成 tag 的那个不出图。** 小说侧的角色抽屉
（`frontend/src/pages/Editor/sidebar/CharacterPromptDrawer.tsx`）早就有一对按钮
"生成 SD 标签 / 生成中文描述"，走 `backend/app/prompts/templates/image_prompt_sd_tags.jinja2`，
那个模板第一句就写着"擅长为 Illustrious/光辉系列模型生成"。但它只是**吐一段文本
让你复制**，跟 ComfyUI 没有任何连接。

**会出图的那个不生成 tag。** RPG 立绘链路是真的接了 ComfyUI，但它拼的是中文。
`frontend/src/pages/Rpg/NpcAvatarField.tsx:26` 的 `buildPrompt()` 把外貌、地点
描述、题材、画风、补充词、姿势用「，」连成一句中文。`imagePoses.ts` 里存的
甚至是"站姿全身像"这种中文字符串，注释还专门写了"实测出过图，不动它"。

所以这一版要做的事，本质是**把这两半接起来**：让出图链路在光辉模式下走一遍
tag 转换。

另外补一个现状事实，跟 CG 那部分直接相关：**出图尺寸现在整条链路都是断的**。

`frontend/src/api/client.ts:1842` 的 `generateAvatar` 其实收 width/height
（默认 1024×1536），但唯一的调用点 `NpcAvatarField.tsx:153` 只传了三个参数，
界面上也没有任何地方能改。

比这更麻烦的是**后端这一段也是空转**。`comfyui.py:141-143` 只在 width/height
非 0 时往替换表里加 `%WIDTH%`/`%HEIGHT%`，而我扫了 `backend/data/comfy_workflows/`
下三份工作流，**没有一份带这两个占位符**（只有 `%PROMPT%`）。尺寸真正来自：

- `npc_portrait.json` —— 独立的 `Int` 节点 #189/#190（1024/1536），连到
  `EmptyLatentImage` #107，那边的 width/height 是连线 `["189", 0]` 而不是数字
- 两份 z-image —— `CR SDXL Aspect Ratio` 节点 #216 里硬编码的
  `width: 1024, height: 1536`

所以 API 传的尺寸**现在完全无效**，不只是"界面上没入口"。这和 `%SEED%` 是同一类
问题，但种子有兜底（`comfyui.py:151-160` 会扫 `seed`/`noise_seed` 字段直接改），
尺寸没有。

**已定方案：手动加占位符。** 你在每份工作流里把尺寸数字换成 `%WIDTH%` /
`%HEIGHT%`，跟 `%PROMPT%` 同一套手工约定，代码零改动（`fill()` 已经支持，
`_subst` 对整段等于占位符的情况会换成 int，类型也对）。

代价是重新导出工作流后要再改一次。不选代码兜底的理由：那样 `comfyui.py` 要
多一处读懂工作流结构的代码（现在只有 LoRA 那节是例外），而且 `npc_portrait`
的尺寸藏在上游 `Int` 节点里，扫字段扫不到、得顺着连线找，遇到没预料到的
尺寸节点会**默默失效**——出图尺寸不对但没有任何报错，这种最难查。

---

## 先说三个已确认的坑

这三个是我实际查证过的，不是推测，方案要绕开它们。

### 1. 现有模板开头那几个质量词是假的

`image_prompt_sd_tags.jinja2:4` 让模型以 `masterpiece, best quality, highres`
开头。我下载了真实词表（140,781 条）逐条比对：

- `masterpiece` —— **词表里没有**
- `best_quality` —— **词表里没有**
- `highres` —— 有，5,256,195 条作品用过

前两个是 NAI leak 时代的遗留，在 Illustrious 上接近空转。这个模板得修。

### 2. 「拟声词」和「子宫透视图」在词表里不叫那个名字

| 你的说法 | 词表里的真实 tag | 用过多少张 |
|---|---|---|
| 拟声词 | `sound_effects`（`onomatopoeia` / `sfx` 是它的别名） | 24,204 |
| 拟声词（另一种） | `emphasis_lines` | 32,545 |
| 子宫 | `uterus`（别名 `womb`） | 7,618 |
| 透视/剖面 | `cross-section`（别名 `crossection` 等） | 11,882 |
| 透视/透视片 | `x-ray`（别名 `xray`） | 11,380 |
| （`internal_cutaway` 这个词表里**没有**，`cutaway` 这个词也不存在） | | |

也就是说，子宫透视图不是某一个 tag，是 `uterus, cross-section, x-ray` 三个真 tag
拼出来的。这正是 LLM 最容易翻车的区间——它很乐意编一个看起来很像样的
`internal_cutaway`，但那个词在模型眼里等于噪声。所以方案里必须有词表兜底。

**订正一处**：我起初以为 `onomatopoeia` 不存在，实际它**是 `sound_effects` 的
注册别名**（`sound_effects,0,24204,"onomatopoeia,sfx"`），LLM 吐这个词是对的，
别名解析会自动折回规范名。真正不存在的是 `internal_cutaway` / `masterpiece` /
`best_quality` / `illustration` 这几个。

### 3. 地点描述是整段中文散文

`NpcAvatarField.tsx:34-37` 把 `place.description` 整段塞进提示词，那段文字是写
给模型读剧情用的，里面会有"宗门里的人都怕她"这种完全非视觉的句子。喂给
Qwen-3-4B 它能凑合理解，喂给 CLIP-L 就是纯噪声。转 tag 时要能把它压成
背景类 tag（`chinese_architecture` 之类），不能整段翻译。

---

## 设计

### 一、加一个「提示词形态」开关

`image_config` 里加一栏 `prompt_form`，取值 `'natural_zh'`（默认，老模组走这条）
或 `'sd_tags'`。你选的是显式指定而不是靠模型名嗅探，理由是文件名是你自己命的，
改名或换加载器就失效。

**这个字段要在三处同步**——这是这个项目最容易出错的地方，
`imageConfig.ts` 和 `rpg_image.py` 的注释都在反复强调两边规则必须一致，
一份配置按两套规则合并，出的图和预览就不是一回事：

1. `frontend/src/pages/Rpg/imageConfig.ts` 的 `mergeImageConfig`
2. `backend/app/services/rpg_image.py` 的 `merge_image_config`
3. `frontend/src/pages/Rpg/ImageSettingsFields.tsx` 加下拉

合并规则照旧：判「key 在不在」，不是「值真不真」，`prompt_form: ''` 按无效值
处理走默认。

LoRA 那块**不用改**。LoRA 覆写本来就按工作流名分组存
（`rpg_image.py:46` 的 `lora_key`），切到光辉工作流自动就是另一组开关，
这个设计现在是对的。

### 二、中文转 tag 的链路

**转换必须发生在出图之前，并且用户看得见。** 这个项目里"看得见能删"是硬原则
（`rpg.py:706`、`NpcAvatarField.tsx:25` 的注释都在说这个），所以在后端
`generate_npc_avatar` 里悄悄转换是不行的。

链路：

- 新模板 `backend/app/prompts/templates/rpg_image_tags.jinja2`
- 按 `add-template` 技能的约定注册到 `backend/app/api/routes/prompts.py` 的 PROMPT_META
- 新 agent 模块 `backend/app/agents/image_tags.py`，函数
  `convert_to_tags(source: str, trial, temperature) -> (tags, dropped)`
  ——收一个纯字符串，不碰 Novel/Character 模型
- 新端点 `POST /rpg/npcs/{npc_id}/prompt-as-tags`，收 `{source}`，
  返回 `{tags: str, dropped: list[str]}`

**前端弹窗要改成两栏**，这是这版唯一一处比较重的 UI 改动：

- 上：中文源文，只读，跟着设置自动重算（就是现在 `buildPrompt` 的输出）
- 下：tag 编辑框，可编辑，转换结果填在这里
- 「重新转换」按钮；源文变了但还没重转时按钮上加提示

为什么非要两栏、不能像现在这样只有一个框：现在那个框有 `touched` 机制
（`NpcAvatarField.tsx:195-197`），手改过就再也不自动更新。中文模式下这是**好的**
（注释解释了：一边打字一边被冲掉最烦人）。但 tag 模式下会变成坑——你改了姿势，
源文变了，tag 框却还是老的，而且你根本看不出它过期了。两栏之后源文永远跟着
设置走，tag 过期一眼可见。

打开弹窗时自动转一次，这样你要的"自动转"是满足的。

### 三、用真实词表兜住幻觉

**词表来源**：`DominikDoom/a1111-sd-webui-tagcomplete`（MIT，2.8k 星）的
`tags/danbooru.csv`。我下下来验过了，140,781 条，格式是
`name,category,post_count,aliases`，分类为 0=general / 1=artist / 3=copyright /
4=character / 5=meta。

选它的理由：MIT 协议干净、是 A1111/ComfyUI 生态里事实上的标准补全词表、
带 post_count 可以按热度裁剪、带 aliases 能做别名解析。

裁剪后落到 `backend/data/danbooru_tags.csv`。**阈值已实测定下来**：

- artist 整类丢掉（59,201 条画师名，画风由 `imageStyles.ts` 管，用不上）
- general / meta 卡 `post_count >= 50`
- copyright / character 卡 `>= 2000`

结果 26,429 条、709 KB。**不能一刀切**：统一卡 500 会砍掉
`ink_wash_painting`(248)、`anatomical_nonsense`(383) 这类真有用的冷门描述词，
而它们恰恰是中文里会提到、模型又认的。character / copyright 是具体角色名和
作品名（初音未来、原神），你的 NPC 是自己编的人套不上，留着反而诱导模型
把角色画成某个现成角色，所以卡狠一点。

拉取脚本 `backend/scripts/fetch_danbooru_tags.py`，平时不跑，产出已提交进仓库。

**两趟转换**：

1. LLM 自由出草案（给它中文源文，让它出英文 tag）
2. **本地校验**：逐个 tag 规范化（小写、空格换下划线），查词表，走别名解析
   （`womb` → `uterus`、`xray` → `x-ray`）。命中就换成词表里的规范名，
   未命中的收集起来
3. 有未命中时再问一次 LLM：把未命中的词 + 按词重叠粗筛出的候选交给它，
   让它从候选里挑；挑不出就**明确说没有**，而不是编一个

`dropped` 列表回给前端显示出来，不咽下去——和 `BatchGenerate.tsx` 处理
dropped 的做法一致。

**不做向量检索**。你 memory 里记着嵌入端点容易被墙，为这个功能加一条网络依赖
不划算。别名解析 + 词重叠粗筛能覆盖绝大部分情况，剩下覆盖不到的本来就是
"词表里真没有"的情况，如实告诉用户比瞎猜好。

**词面匹配的能力边界（实测，已写成测试）**：`search()` 只在**共享单词**时有效。
`crossection` → `cross-section` 能搜到（别名也进匹配池了）；但
`internal_cutaway` → `cross-section` **搜不到**，因为词表里根本没有 `cutaway`
这个词，两者一个词都不重。这种纯语义跳跃词面匹配到不了——所以第二趟必须把
**中文原文**也带上，让模型看着原意重挑，而不是只给它一堆候选词。

### 四、CG / 插图预设

现在尺寸写死 1024×1536，先把这个口子开出来。

新表 `frontend/src/pages/Rpg/imageFrames.ts`，结构照 `imageStyles.ts` 的样子，
每项 `{key, label, width, height, tag}`：

| key | 显示 | 尺寸 | 构图 tag |
|---|---|---|---|
| `portrait` | 立绘竖版 | 832×1216 | `standing, full body` |
| `cg_wide` | 横幅 CG | 1216×832 | `game_cg` |
| `square` | 方图 | 1024×1024 | `official_art` |

832×1216 是 SDXL 系的标准竖版分辨率，Z-Image 跑这个数也没问题，所以一套表
两边共用，不用按形态分。

**存 key 而不是展开的 tag 串**——这里和 `pose`/`style` 的存法**故意不一样**，
因为它还带着两个数字，不是纯 tag。别照着 `imagePoses.ts` 的注释抄。

弹窗里把尺寸输入框露出来（预填 frame 的值，仍可手改）。构图 tag 由
`frame.tag` 提供，剩下的细节交给转换器补。

**这一节要能生效，前提是工作流里已经加了 `%WIDTH%` / `%HEIGHT%` 占位符**
（见开头那段）。占位符没加的话，界面上选了横幅 CG、尺寸输入框也改了，
出的图还是 1024×1536，而且不报错。所以第 8 步的验证必须在改过的工作流上做。

---

## 分步实施

进度（2026-09-16）：1–4 已完成并跑过测试，5–9 未动。每步后面括号里是实际落地的文件。

1. 落词表：拉 CSV、裁剪、存 `backend/data/danbooru_tags.csv` ✅
   → 验证：打印条数和文件大小，抽查 `uterus` / `cross-section` / `sound_effects` 都在
   （`scripts/fetch_danbooru_tags.py` 抓 `DominikDoom/a1111-sd-webui-tagcomplete`，
   落 26,429 行 / 709KB。网络两坑写在脚本注释里：走 GitHub blob API 不走 raw、
   显式装空代理 opener 绕开注册表里那个假 socks4。）

2. 写词表校验模块（规范化 + 别名解析 + 查表）✅
   → 验证：单测喂 `womb` 得 `uterus`、喂 `internal_cutaway` 得"未命中"
   （`app/services/danbooru_tags.py`：`check()` 保序去重、`search()` 连别名一起匹配
   且按 post_count 排序。20 条测试在 `tests/test_danbooru_tags.py`。校验中发现两处
   订正：`onomatopoeia` 其实是 `sound_effects` 的注册别名（原方案写错）；
   `internal_cutaway` 够不到 `cross-section` 是因为词表里连 `cutaway` 都没有——
   纯语义跳跃词面匹配桥不过去，这直接决定了第二趟必须带中文原文，不能只给候选词。）

3. 加 `prompt_form` 字段，三处同步 ✅
   → 验证：模组设 `sd_tags`、角色不设 → 合并出 `sd_tags`；角色设 `''` → 走默认；
     前端 `mergeImageConfig` 和后端 `merge_image_config` 对同一组输入结果一致
   （前端 `RpgImageConfig` + `imageConfig.ts`，后端 `rpg_image.py` 合并循环，
   `models/rpg.py` 的 image_config 注释。合并判据用 `!== undefined` 不是真值判断——
   空串是有意义的值。12 条测试在 `tests/test_rpg_image_config.py`。）

4. 写 `rpg_image_tags.jinja2` + 注册 + `image_tags.py` ✅
   → 验证：喂一句含"子宫透视图"的中文，出来的 tag 全部能在词表里查到
   （模板注册进 `rpg_prompts.PROMPTS`（=RPG 提示词设置页那份，`render()` 只对这份
   认用户覆盖），`validate()` 补了 unknown 的样例值走空/非空两条分支。
   `image_tags.py` 两趟循环，agent key 用 `"character"`（走 fast 档）。
   端到端用桩模型验：第一趟吐假词→拿词表核→第二趟带着未命中词回炉→最终干净，
   命不中的原样交回不偷扔。4 条测试在 `tests/test_image_tags.py`。）

5. 加 `POST /rpg/npcs/{npc_id}/prompt-as-tags` 端点 ✅
   → 验证：返回 `tags` 和 `dropped`，未命中的确实出现在 dropped 里
   （`rpg.py` 加路由，schema `RpgPromptAsTagsIn/Out`，前端 `rpgApi.npcs.promptAsTags`。
   不落库、不出图——转完交前端 tag 框给用户过目。nsfw 默认关，由弹窗勾选，不自动开。
   用模组的 model_ref（fast 档）。import 检查过路由已注册。）

6. 弹窗改两栏 + 自动转一次 + 重新转换按钮 ✅
   → 验证：改姿势后源文变、tag 框不变、按钮出现提示
   （`NpcAvatarField.tsx`：merged.prompt_form === 'sd_tags' 时走两栏——上面中文源文
   只读、下面 tag 框可改。打开时自动转一次，之后源文或 nsfw 变了亮「源文已变」黄字，
   转不成功的词进 dropped 显示出来不偷扔。nsfw 勾选框默认关。natural_zh 保持原样单栏。）

7. 修 `image_prompt_sd_tags.jinja2`（小说侧那个）的假质量词 ✅
   → 验证：新生成的 tag 里不再出现 `masterpiece` / `best quality`
   （模板第 1 条改成 `absurdres, highres` 并注明别写那俩假词；顺手把 `models/rpg.py`
   注释里那个 `"extra": "best quality"` 例子也换成 `absurdres`——sd_tags 语境里
   摆个假 tag 做示范会误导。拿词表核过：absurdres/highres 命中，另俩落 dropped。）

8. 加 `imageFrames.ts` + 弹窗露尺寸 + buildPrompt 接 frame ✅（代码）／⚠️（真机验收待用户）
   → 验证：**先在工作流里把尺寸换成 `%WIDTH%`/`%HEIGHT%`**，再验选横幅 CG 出的是
     1216×832、手改尺寸能覆盖。占位符没加就验不出来（会静默出 1024×1536）
   （imageFrames.ts 上一批已建。这批把 frame.tag 拼进 buildPrompt、frame.width/height
   由弹窗 submit 传进 generateAvatar。真机出图那步要用户先在工作流里加占位符，
   代码侧到此为止。**没有手改尺寸输入框**——画幅档已经覆盖立绘/CG/方图三种，
   再加个自由尺寸框是 YAGNI，要再说。）

9. `ImageSettingsFields.tsx` 加形态下拉和帧预设 ✅
   → 验证：预览那一行和实际发出的提示词逐字一致
   （加了「提示词形态」和「画幅」两栏，都带「跟随模组」档、选中态看 cfg 不看 eff。
   预览 tail 追加了 frame.tag，顺序和 buildPrompt 对齐。顺手把「额外补充」里
   `masterpiece, best quality` 的占位提示也换成真 tag。）

---

## 怎么验收

最终标准是**同一句中文源文，切到光辉工作流后出的图，和 Z-Image 出的图在内容上
对得上**——衣服颜色、发型、场景该在的都在，只是画风变了。

具体拿三句试：一句普通的日常立绘、一句带子宫透视图的、一句带拟声词的。
后两句是这版存在的理由，它们过不了就等于没做。

---

## 风险与不做的事

**不做图库**。你选了先做预设，图库留成后续独立一批。现在出图仍然只能从某个
NPC 的立绘按钮进去，结果存 `npc.avatar_url`，一人一张。

**不引 TIPO / DanTagGen / DanbotNL 做依赖**。这几个都是真实存在的项目
（我验过：[ComfyUI_DanTagGen](https://github.com/huchenlei/ComfyUI_DanTagGen)
GPL-3.0 89 星、[danbot-comfy-node](https://github.com/p1atdev/danbot-comfy-node)
Apache-2.0 35 星、[sd-danbooru-tags-upsampler](https://github.com/p1atdev/sd-danbooru-tags-upsampler)
Apache-2.0 107 星），但不用它们的理由有三条：它们跑在 ComfyUI 里，转换过程
对用户完全不可见，违反"看得见能删"；DanbotNL 知识截止 2024-08，新番新角色
认不出；它们拿不到 NPC 的完整上下文。LLM 路线能吃满上下文，也和这个项目
已有的模板体系一致。

**要提一句**：你点名的 `ThetaCursed/Illustrious-NoobAI-Style-Explorer` 我核实过，
**这个仓库不存在**——GitHub API 返回 404，`ThetaCursed` 也不是真实用户，
Pages 站点同样 404。那个名字来自我第一轮搜索结果，当时我没验证就转述了。
所以它不能作为词表来源，上面换成了 `a1111-sd-webui-tagcomplete`。

**负向提示词**：现在 `%PROMPT%` 只填正向。SDXL 系对负向比较敏感，你得在自己
导出的工作流里烘一段固定的负向。要不要加 `%NEGATIVE%` 占位符是另一个决定，
这版先不做。

**画风词打架**：`imageStyles.ts` 存的 `photorealistic, realistic, photography`
是给 Z-Image 用的英文描述，在光辉上不一定合适。转换器要能识别画风类的输入
并换成光辉认的 tag，这一步容易翻车，实施时要专门试。

**前置动作（两件手工活）**：

1. 把光辉工作流导出到 `backend/data/comfy_workflows/`。现在那目录下三份全是
   Z-Image（我扫过了）。导出时照 `comfyui.py` 开头的约定：正向提示词那段文字
   整体换成 `%PROMPT%`。
2. **想用 CG 预设的每一份工作流**（含现有三份）都要把尺寸数字换成 `%WIDTH%` /
   `%HEIGHT%`。具体位置：`npc_portrait.json` 是 `Int` 节点 #189/#190 的
   `Number` 值；两份 z-image 是 `CR SDXL Aspect Ratio` #216 的 `width`/`height`。
   不改的话尺寸那一栏是死的。
