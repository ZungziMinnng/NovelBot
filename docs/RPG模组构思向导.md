# RPG 模组构思向导

对话式生成整套模组数据，回填到模组编辑页。照小说侧构思助手那套做，
差别在于 RPG 的数据之间有**名字引用**关系，抽取必须分步、且带白名单校验。

## 为什么不能照抄小说侧的全量抽取

小说侧每步都用全部对话重抽一次全量字段，靠 `knownNames` 去重。RPG 不行：

- 角色的 `initial_state` 键 = 关系数值名
- 道具 / 动作的 `effects` 键 = 玩家数值名
- 角色的 `location`、地点的 `connections` = 地点名

全量重抽会让第 4 步把第 2 步已经写进表单的「精力」重抽成「体力」，于是道具
点下去什么都不发生，**不报错、静默失效**。所以：每步只抽这一步的字段，
前面已定的名字当白名单传下去，后端按白名单过滤，丢掉的在预览里标出来。

## 六步及其字段归属

开始向导前先选择世界规模：完整世界会优先搭建大陆/区域、组织和多人物骨架；一块区域的故事则集中描写一个宗门、城市或聚落。这个选择会传给分步对话和一句话整套生成，避免模型默认把完整世界缩成单一小场面。

顺序由依赖决定：数值是地基，地点要在角色之前（角色的 `location` 得指向已存在的地点）。

| 步 | id | 抽出的字段 | 依赖 |
|---|---|---|---|
| 1 | `world` | `genre` `worldview` `opening_scene` `system_instruction` `narration_sample` | — |
| 2 | `stats` | `stat_defs` `relation_stat_defs` | — |
| 3 | `places` | `locations[]` `default_location` | — |
| 4 | `slots` | `time_slots[]` | — |
| 5 | `cast` | `npcs[]`（含 `initial_state` `location` `slot_locations`） | 2 的关系数值名、3 的地点名 |
| 6 | `things` | `items[]` `actions[]` | 2 的玩家/关系数值名、3 的地点名 |

`creator_note` 不生成 —— 既有底线是它不进 prompt、也不给生成入口。

## 后端

### 1. `backend/app/prompts/templates/rpg_wizard.jinja2`（新）

对话模板。单文件按 `{% if stage == ... %}` 分六个分支，同 `brainstorm_indulge.jinja2` 的写法。

变量：`nsfw` `stage` `confirmed` `play_style`（玩法类别决定该聊什么 ——
sim 不用聊判定、slg 要聊经营循环）。

要写进模板的硬约束：
- 玩家角色一律称「你」，不给玩家起名字、不预设性别身份 —— 那是建局时玩家自己填的
- 不写具体数字进叙事类字段，数值由数值表定义
- 数值那一步要引导用户想清「归零会怎样」（`on_zero`）—— 这栏没人会主动想

### 2. `backend/app/prompts/templates/rpg_wizard_extract.jinja2`（新）

抽取模板。按 `stage` 输出不同的 JSON 形状，只输出当前这一步负责的键。

关键：把白名单原样写进提示词 ——
`"initial_state": {"只能用这些键：{{ relation_names }}": 数字}`，
并明确「引用了不在列表里的名字，整条丢掉」。

### 3. `backend/app/services/rpg_prompts.py`

`PROMPTS` 里注册向导对话、抽取和一句话整套生成模板（`label` / `description` / `variables`）。
这是 RPG 提示词的注册点，不加设置页就看不到、用户改不了。

### 4. `backend/app/agents/rpg_wizard.py`（新）

```
STAGES = ["world", "stats", "places", "slots", "cast", "things"]

async def extract_stage(stage, transcript, known, model_ref) -> dict
```

`known` 带 `stat_names` / `relation_names` / `location_names`。

**核心是抽完之后的清洗**，每一项都要有：

- `stat_defs`：`initial` 夹在 `min`..`max` 之间；`display` 只能是 条/数字/隐藏；
  `on_zero` 只能是 无/死亡/标记（对不上落默认值，不是原样写进去）
- `npcs[].initial_state`：键不在 `relation_names` 里的丢掉
- `npcs[].location`：不在 `location_names` 里的置空
- `items[].effects` / `actions[].effects`：键不在 `stat_names` 里的丢掉
- `actions[].relation_effects`：键不在 `relation_names` 里的丢掉
- `locations[].connections`：指向不存在的地点名的丢掉
- 名字为空的整条丢掉

丢掉的东西要一起返回（`dropped: list[str]`），预览面板要显示它们。
静默丢弃 = 用户以为生成了，实际没有。

字数上限沿用 `rpg_assist.FIELD_SPECS` 里那几栏的值，别另立一套。

模型选择：对话用 `get_agent_client("writer", ...)`（创作活，同 `rpg_assist` 的理由）；
抽取用 `llm_json.call_json` + `get_fast_client`（结构化活，同小说侧）。

**用哪个模型由 `pick_model(chosen, module_ref)` 一处决定**：下拉第一项是
「模组默认模型」（value 是空串），所以空 = 跟模组走、非空 = 用选的那个。三个入口
（对话 / 抽取 / 一键生成）都过它，**不在路由里各判一次**——各自判的后果已经出现过一次：
前端把选择发了出来、路由收下却没用，作者选了 A 模型，实际连的是主页设置里的默认模型，
日志里只有默认模型的名字，界面上完全看不出选择丢在哪一步。

### 5. `backend/app/schemas/rpg.py`

`RpgWizardChatIn`（`messages` `model` `nsfw` `stage` `confirmed` `play_style`）、
`RpgWizardExtractIn`（`stage` `messages` `known` `model`）、
`RpgWizardExtractOut`（各步字段全为 Optional + `dropped: list[str]`）。

### 6. `backend/app/api/routes/rpg.py`

- `POST /modules/{id}/wizard`：SSE 流式对话。复用 `chat.py` 的 `_stream_response`
  （要从 `chat.py` 提出来共用，或在 rpg.py 里照写一份 —— 看 `_stream_response`
  是否只依赖 llm_client；若耦合了 chat 的东西就照写）
- `POST /modules/{id}/wizard/extract`：抽当前这一步

两个都走 `_get_owned_module` 鉴权，两个都**不落库** —— 回填由前端逐项确认后
走已有的子表 API。

## 前端

### 7. `frontend/src/pages/Rpg/wizardStages.ts`（新）

六步的 `id` / `label` / `hint` / `opener`。`id` 必须与后端 `STAGES` 和模板分支一致。

### 8. `frontend/src/api/client.ts`

`streamRpgWizard()` + `rpgApi.wizard.extract()` + 抽取结果的类型。
类型里的数值形状直接复用已有的 `RpgStatDef` / `RpgItem` 等，不另立。

### 9. `frontend/src/pages/Rpg/WizardPanel.tsx`（新）

照 `BrainstormPanel.tsx` 改，砍掉自由聊模式和联网搜索（联网的既有边界是
只给那两个对话，不扩到这里）。保留：步骤条、跳过、回到某步重聊、模型选择。

每步「下一步」= 抽当前步 → 只填空栏 → 进下一步（同 `handleNext`）。
任意阶段都可以点「预览并回填」提取当前对话；最后一步「完成并核对」也会弹全量预览。

### 10. `frontend/src/pages/Rpg/WizardApplyModal.tsx`（新）

预览面板。分组勾选：文本栏逐栏、数值/角色/地点/道具/动作**逐条**勾
（不是整组一个勾 —— 五个角色里想要三个是常见需求）。

顶部显示 `dropped` 警告。另外前端要再算一次引用校验：用户取消勾选某个
数值之后，引用它的道具就悬空了，要当场提示（就是你选的那行
`⚠ 道具「醒酒药」引用了未选的「醉意」`）。

### 11. `frontend/src/pages/Rpg/RpgModule.tsx`

- 顶栏加入口按钮，面板做成右侧抽屉/浮层（页面已是 `xl:grid-cols-2` 两栏，
  再挤一栏会塞不下）
- 回填：主表字段走已有的 `set()`（autosave 会自己存）；
  地点/角色/道具/动作走各自的 `rpgApi.*.create()`，建完
  `invalidateQueries` 对应 queryKey

回填顺序必须是 地点 → 角色 → 道具动作，理由同上：后面的引用前面的。

## 测试

`backend/tests/test_rpg_wizard.py`（新）：

1. 六步的 stage id 在模板里都有对应分支（照 `test_rpg_prompts.py` 的写法）
2. 两个新模板都在 `PROMPTS` 里注册了
3. 清洗逻辑逐项（mock 掉 LLM）：
   - `initial_state` 里的野键被丢掉且进了 `dropped`
   - `effects` 里的野键被丢掉
   - `initial` 超出 `min`..`max` 被夹住
   - `display` / `on_zero` 非法值落默认
   - `connections` 指向不存在的地点被丢掉
   - 空名字的整条被丢掉

`docs/RPG数值驱动改造.md` 末尾补一段说明向导的存在和它的校验责任。

## 实施顺序

1. 模板 + 注册 + schema → verify: `pytest backend/tests/test_rpg_wizard.py -k prompt`
2. `rpg_wizard.py` 清洗逻辑 + 测试 → verify: 清洗用例全绿
3. 两个路由 → verify: 手动打一次 extract，确认野键被丢
4. 前端 stages + client → verify: `npm run build`
5. `WizardPanel` + `WizardApplyModal` → verify: 走完六步，并可在任意一步预览回填
6. 接进 `RpgModule` → verify: 回填后刷新页面数据还在

## 需要你确认的两处

- `_stream_response` 在 `chat.py` 里，可能耦合了 chat 专有的东西。若要共用得提到
  公共位置 —— 这是动既有代码，我会先看再决定，倾向照写一份避免动 chat。
- 生成出来的地点没有 `x`/`y` 坐标（默认 0，落兜底网格）。手绘地图那块要你自己拖。

## 追加：单摊一键生成（2026-09-12）

向导是「从零攒一整套」；这个是「某一摊补几个」。地点/角色/道具/动作四摊各挂一个
「AI 生成」按钮（`BatchGenerate.tsx`），点开填一句要求 + 拖一个数量滑块（1~10），
生成后就地预览、逐条勾选，确认才建行。

和向导共用后端清洗（`_clean_places`/`_clean_cast`/`_clean_things`）。区别：

- **白名单靠查库，不靠对话累积**。路由 `POST /modules/{id}/generate/{kind}` 现查
  模组的 `stat_defs`/`relation_stat_defs`、`RpgLocation.name`、以及同类已有名字，
  传给 `rpg_wizard.generate_batch`。
- **同名跳过只建新的**：和库里已有的重名的剔掉、进 dropped。作者要的是补充不是覆盖。
- **新地点能连回旧地图**：`_clean_places` 加了 `known_names` 参，connections 的合法
  目标 = 本批新建 + 模组已有。向导第一次生成时不传（只认本批），单摊补充时传已有。
- 单摊生成不碰 `default_location`（那是模组层面的决定，`generate_batch` 里 pop 掉）。

模板 `rpg_generate.jinja2`（PROMPTS 第 12 个），按 kind 分支。前端 `rpgApi.modules.generate`。
测试 `GenerateBatchTests` in `test_rpg_wizard.py`。

## 追加：两种构思入口

向导初始页明确分成两种模式：

- **开始分步构思**：按世界观、数值、地点、时段、角色、道具与动作六步逐步对话；每一步都可以提取并预览回填。
- **一句话生成整套**：输入一个简单想法，调用 `POST /modules/{id}/wizard/generate` 一次生成所有编辑页字段。助手先在对话中给出生成简介，再打开预览；用户可以选择「回填到模组」或「换一套」重新随机生成。

一句话模式不进入自由追问，也不直接落库。后端会按数值名、关系名和地点名清洗角色、道具、动作的引用；不匹配的引用会列在 `dropped` 中。

地点支持可选父地点。没有父地点的是大陆/区域级大地图节点；设置父地点后，游玩时进入父地点页即可打开其内部小地图，例如宗门下面的正殿、炼丹房。未设置层级的旧地点继续按原来的平面地图显示。
