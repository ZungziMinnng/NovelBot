# RPG 模式：从跑团改成数值驱动

状态：**已实施（2026-09-11）**。计划的十一个阶段全部落地，后端 538 个测试通过，前端类型检查与打包通过。**UI 未经浏览器实测**，手动验收清单见第八节。

---

## 一、为什么要改

原来的 RPG 是一个 AI 当 GM 临场判断「这事有多难」，然后掷 d20 对抗难度值 —— 那是龙与地下城。但这个项目要做的题材是都市、魔法世界、互动养成，**不一定和冒险有关**。这些类型里推动游戏的根本不是「这次撬锁成不成」，而是数值在动、到了某条线就解锁新东西。

所以骰子是冒险题材的一种调味，不是地基。真正的地基是：

```
玩家做一件事 → 数值变了 → 跨过某条线 → 解锁新内容 → AI 按新状态往下写
```

这一版把地基换成这个循环，骰子降级成一个默认关着的可选项。

另外两个一并解决的界面问题：酒馆和 RPG 两个目录里 157 处写死的深色系色值，在 18 套主题里那 6 套浅色底上等于白底白字；设定页只用屏幕中间一条 896px。

## 二、八条已定决策（勿反复推翻）

| 问题 | 定论 |
|---|---|
| 判定方式 | **默认关掉**（`check_mode` 默认 `never`），想要的模组自己开 |
| 数值谁算 | 混合：道具/移动/动作按钮走引擎（数字死的，AI 碰不到）；自由行动交给 AI 提议 |
| 数值挂在谁身上 | 玩家一套 + 每个角色各一套关系数值（定义只写一份，所有角色共用） |
| 阈值触发 | 接在世界书的 `trigger_condition` 上，不另开事件表 |
| 行动方式 | 自由打字 + 模组自定义动作按钮，两者并存 |
| 角色卡 | 照抄酒馆卡字段结构，放进 RPG 自己的表，两边互不牵连 |
| 地点 | 真地图：地点之间有连接（双向可通），移动是明确动作，可加进入条件 |
| 游戏类型 | 一个文本字段进提示词，配三套前端预设（都市/魔法/养成） |

## 三、数据模型

### 玩家数值

`RpgModule.stat_defs`（JSON 列表）定义，字段：`name` / `initial` / `min` / `max`（null = 无上限）/ `for_check`（能否用于判定）/ `on_zero`（无 / 死亡 / 标记）/ `display`（条 / 数字 / 隐藏）。

局里的值**复用 `RpgSession.attributes` 这一列**，没有新增列 —— 它本来就是「名字→数字」的字典，正是新系统要的形状。Python 属性名改叫 `stats`（`mapped_column("attributes", JSON, ...)`），**数据库列名一个字没动**。

### 关系数值

`RpgModule.relation_stat_defs`（JSON 列表），定义一次，每个角色各持一份。存在 `RpgSession.npc_states`，形状 `{"3": {"好感": 62, "met": true}}`，键是 npc_id 的字符串（名字会改，id 不会）。建局时按定义初始化，单个角色要不一样用 `RpgNpc.initial_state` 覆盖。

`met` 是内部标记，控制首次见面才注入外貌，渲染面板时跳过。

### 三张新表

- **`rpg_items`**：`name` / `description` / `category` / `usable` / `consumable` / `effects`（数值增减）/ `sort_order`
- **`rpg_locations`**：`name` / `description` / `connections`（**存名字不存 id**，因为 `RpgNpc.location` 本来就是字符串）/ `enter_requires` / `sort_order`
- **`rpg_actions`**：`name` / `prompt_hint` / `effects` / `relation_effects` / `requires` / `needs_target` / `sort_order`

### 统一条件格式

```json
{"stats": {"精力": {"op": "<=", "value": 20}},
 "relations": [{"npc": "赫敏", "stat": "好感", "op": ">=", "value": 50}],
 "flags": ["已经拿到钥匙", "!已经被发现"],
 "items": ["铁钥匙"]}
```

语义唯一：**条件是附加约束，全部满足才算数**。`flags` 里 `!` 前缀表示这条不能立着。

`check_condition(cond, sess, npcs) -> (bool, 原因)` 写在 `services/rpg_state.py`，**三处共用**：世界书 `trigger_condition`、动作按钮 `requires`、地点 `enter_requires`。这是整个设计里最关键的一处复用 —— 写一遍用三次，所以前端的 `ConditionEditor.tsx` 也只有一份。

### 世界书阈值触发

`rpg_world_entries.trigger_condition`（避开 `condition` 这个保留字）。空 = 无条件，同改造前。

- 常驻词条 + 条件 → 满足就每轮注入（「好感过 50 之后她的说话方式变了」）
- 关键词词条 + 条件 → 提到关键词**且**满足条件才注入

好处：不用新建事件表、不用新注入管线、不用新编辑界面。世界书的 `depth` 机制本来就能把内容插到任意位置，事件该有的能力它全有。

## 四、一轮怎么跑

```
玩家输入
 ├─ 点了动作按钮 / 道具「使用」/ 地图某地点 → 请求带 action_id / item_name / move_to
 └─ 自由打字 → 直接走叙事

② 引擎结算已定义的部分（数字死的，AI 碰不到）
   use_item → 查 rpg_items.effects，精确增减
   move     → 查 connections + enter_requires，过了改地点，没过明确拒绝
   action   → 查 rpg_actions.effects / relation_effects

③ （可选，默认关）开了判定 → 成功率判定

④ 装配上下文
   世界书按 关键词 + trigger_condition 双重筛
   在场角色的关系数值进 NPC 块（「赫敏：好感 62/100」）
   已定死的事实夹在玩家那句话的头尾

⑤ 叙事（贵模型，流式）
⑥ 结算（便宜模型，出 JSON）—— 只结算自由行动那部分，引擎算过的明确告知不许再动
⑦ 应用改动 → clamp → 查 on_zero → 存快照
```

**「混合」的落点就在这里**：有定义的东西数字是死的，AI 改不了；没定义的事才让 AI 提议。

## 五、判定：成功率制，默认关闭

`rpg_dice.py` 原地重写（文件名未改），从 d20 对抗换成成功率：

```python
BASE_RATE = {"trivial": 90, "easy": 75, "medium": 55, "hard": 35, "extreme": 15}
成功率 = clamp(BASE_RATE[档位] + (数值 - 10) * 4 + 模组偏移, 5, 95)
```

玩家看到的是「说服　成功率 63%」，不是「D20+2 对抗 16」。

两个开关：`check_mode` 默认 `never`（新模组开箱完全不判定）；`random_check` 默认 true（关掉后变纯数值确定性判定，同一存档重玩结果一样）。

`dc_table` 列复用成成功率表（形状一样），Python 属性名改叫 `rate_table`，列名不动。`dc_ledger` 原样保留 —— 它防的是档位漂移，和换不换算法无关。

## 六、存档回溯

`SNAPSHOT_FIELDS` 一共九项，**`summary` 和 `summarized_upto_id` 必须跟着一起存**：漏了它们，回溯之后摘要里还留着「未来」的剧情，模型会写出玩家没经历过的事 —— 这是最难查的一类 bug。

- 自动档每回合在**动任何东西之前**拍一张（有了权威状态就必须能反悔），只留最近 30 张；手动档永不自动清。
- `_take_save` 必须 `copy.deepcopy`：`AsyncSessionLocal` 是 `expire_on_commit=False`，JSON 列存的是引用，本轮还会就地改这些字典。
- **读档会删掉比这张更晚的存档** —— 它们的 `before_message_id` 指向已不存在的消息，留着只会在下次读档时把进度截断在错误的位置。确认框里写明了。

## 七、界面

### 配色

`index.css` 加两个作用域类，套在两个模式的页面根节点：

```css
.mode-tavern { --primary: 330 81% 60%; --primary-foreground: 0 0% 100%; --ring: 330 81% 60%; }
.mode-rpg    { --primary: 258 90% 66%; --primary-foreground: 0 0% 100%; --ring: 258 90% 66%; }
```

然后把 6 种重复写法机械替换：主按钮 → `bg-primary text-primary-foreground`；次级/标签 → `bg-primary/10 text-primary`；选中态 → `bg-primary/15 text-primary border-primary/40`；取消键 → `border-border text-muted-foreground`。

酒馆的粉、RPG 的紫都保住了，色值集中在一处，`--primary-foreground` 保证前景对比。

**语义色（成功绿/失败红）不能走 primary**，改成双基底写法 `text-emerald-700 dark:text-emerald-300`。这是遗留低对比度问题的唯一正确改法 —— 单基底的 `text-emerald-300` 在浅色底上看不见。

### 布局

- 模组设定页：`max-w-4xl` 单列 → `max-w-[1440px]` + `xl:grid-cols-2`。左栏是世界（封面/游戏类型/世界观/开场/叙事风格），右栏是系统（数值/关系数值/动作/道具/地点/角色卡/世界书/判定）。窄屏自动回落单列。
- 游戏页：`max-w-[1600px]`，对话区居中 + 右侧 320px 常驻菜单。

### 游戏页常驻菜单（JRPG 感的关键）

四格 **状态 / 道具 / 地图 / 存档**，宽屏（≥1280px）钉在右侧一直显示，窄屏收成抽屉。

- **状态**：玩家自己（头像/名字/地点 + 每项数值一根横条）→ 每个已知角色一张卡（头像/在不在面前/关系数值横条），点开是全屏角色详情（外貌/性格/分栏档案全摊开）
- **道具**：每件一张卡，效果染色显示（绿 `精力 +30` / 红 `资金 -50`），可用的给「使用」按钮
- **地图**：走不通的灰掉并用红字写明原因
- **存档**：存一个 / 读档 / 删除

改之前这些东西藏在右下角几个 7×7 无标签图标里，而且没道具时按钮整个不出现 —— 那不是 JRPG，JRPG 的状态是常驻在屏幕上的。

## 八、两个坑与一处有意简化

### 坑 1：弹窗被页头遮挡（已修）

`RpgModule.tsx` 的页头是 `sticky top-0 z-20`，`main` 是 `relative z-10`。**`relative z-10` 让 main 成为独立的层叠上下文**，里面的弹窗再怎么调 z 值也只在 main 内部排序 —— 弹窗写的 `z-50` 和页头的 `z-20` 不在同一场比赛里，结果页头压住了弹窗顶部。

修法：`CharacterForm.tsx` 和 `NpcSheet.tsx` 用 `createPortal` 挂到 `document.body`。

**同类风险**：酒馆的开局弹窗（`Tavern.tsx:201`）目前是侥幸没事 —— 它的页头和 main 都是 `z-10`，靠 DOM 顺序才盖得住。哪天给那个页头加 `z-20` 或改成 sticky 就会复现。项目里另外四十来处弹窗都是「写在页面内部 + fixed z-50」的写法，目前大多没踩到只因为父层没起层叠上下文。**新写弹窗一律用 portal。**

### 坑 2：`met` 开局为空（已修）

后端只在角色**真的进过一轮上下文之后**才置 `met`（`rpg_turn.py` 里 `mark_met` 在开流之前调）。所以刚开局那一刻，哪怕 NPC 就站在你的起始地点，侧栏也会写「还没遇到什么人」，动作按钮的对象下拉是空的 —— 第一回合根本没法对她做任何事。

修法：`condition.ts` 里的 `knownNpcs()` 取「见过面的 **或** 此刻在同一地点的」。后端的 `met` 语义没动（它控制的是外貌注入，那个逻辑是对的）。

### 有意简化：没有做自由输入的动作识别

原计划有个 `rpg_action.jinja2`，用便宜模型识别自由打的字属于 `use_item / move / action / free`。**没有实现。** 结构化行动通过请求里的 `action_id` / `item_name` / `move_to` 进来，引擎精确结算；自由打字直接走叙事 + 结算。

**理由**：判定默认关着时，一个普通回合因此只有一次辅助模型调用（结算）而不是两次。「有定义的走引擎」这条决策靠按钮本身就满足了。

**代价**：打字说「我喝下药水」拿到的是 AI 估算的数字，点背包里的「使用」才是精确的 +20。想补上的话就是加这一个模板 + `rpg_turn.py` 里一个分支。

## 九、四列作废但删不掉

`RpgSession.hp` / `hp_max`、`RpgModule.default_attributes` / `default_hp_max`。

项目没有 Alembic，`create_all` 不会删列，而这几列建成了 NOT NULL、默认值只在 Python 侧 —— 从模型里拿掉会让老库插入直接失败。只能留在模型里加注释。要彻底清掉得单独做一次建新表搬数据的迁移，不值得也有风险。

## 十、文件清单

### 后端

| 文件 | 说明 |
|---|---|
| `app/services/rpg_state.py` | **新**：条件求值 + apply_delta + clamp + on_zero + 背包 + mark_met |
| `app/services/rpg_dice.py` | 成功率公式 + `random_check` 分支；删了 `attr_modifier`/`resolve_dc` |
| `app/services/rpg_context.py` | 删 `COST_HINTS`；`triggered_entries` 加条件过滤；状态块按 `stat_defs` 渲染；NPC 块加关系数值 |
| `app/agents/rpg_turn.py` | 三条引擎分支（use_item/move/action）；判定整体可选；`_fallback_attr` 改成找第一个 `for_check` |
| `app/models/rpg.py` | `attributes`→属性名 `stats`；`dc_table`→`rate_table`；新增 `RpgItem`/`RpgLocation`/`RpgAction` |
| `app/api/routes/rpg.py` | items/locations/actions CRUD；存档四个端点；建局按 defs 初始化；删模组级联新表 |
| `app/database.py` L224-246 | 新增 9 个 `ADD COLUMN` + 6 个 `CREATE INDEX`（仅追加，不可改顺序） |
| `tests/test_rpg_state.py`、`tests/test_rpg_saves.py` | **新** |

### 前端（`src/pages/Rpg/`）

| 文件 | 说明 |
|---|---|
| `condition.ts` | **新**：后端 `check_condition` 的镜像 + `knownNpcs` / `onstage`。**判定权仍在后端**，这里放行后端照样会拦 |
| `StatusSidebar.tsx` | **新**：常驻菜单四格 |
| `NpcSheet.tsx` | **新**：角色详情（portal） |
| `StatBar.tsx` | **新**：一项数值占一整行 |
| `RpgAvatar.tsx` | **新**：走主题色的头像（酒馆的 `CardAvatar` 写死了粉色） |
| `StatDefsSection.tsx` / `ActionSection.tsx` / `ItemSection.tsx` / `LocationSection.tsx` / `ConditionEditor.tsx` / `EffectEditor.tsx` / `genrePresets.ts` | **新**：模组设定页的编辑区 |
| `RpgPlay.tsx` | 改成双栏 + 常驻菜单；删了 `Tray`/`TrayToggle` |
| `RpgModule.tsx` | 加宽双栏 + 挂新 Section |
| `CharacterForm.tsx` | 改用 portal |
| `StatePanel.tsx` | 窄屏用的紧凑条；`npcs` 改为由调用方预筛 |
| `DiceRoll.tsx` | 显示成功率而非 D20 对抗；双基底配色 |

## 十一、验收

```bash
# 后端（项目没装 pytest，用 unittest；python3 在这台机器是 WindowsApps 空壳，会静默失败）
cd backend && PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests -q

# 前端（没有 lint script）
cd frontend && npx tsc --noEmit && npm run build
```

### 浏览器手动清单（未做）

**先新建一个专门的测试模组，不要在已有数据上试** —— `stat_defs` / `relation_stat_defs` 是新列，老行拿到的是空值，面板会是空的。

1. 主题切到「护眼」「玫瑰」这类浅色底，扫一遍酒馆和 RPG 的按钮
2. 套一套预设，或手填 3 项玩家数值、2 项关系数值、3 个动作按钮、2 件道具、3 个地点、2 张角色卡
3. 开局 → 侧栏第一眼就该能看到起始地点的那个 NPC（坑 2 的回归点）
4. 点动作按钮，看数字是否精确
5. 把好感刷到阈值，看挂了条件的词条是否开始生效
6. 走到不相连的地点，看是否被明确拦下并显示原因
7. 自由打字，故意引导模型给离谱数字，看是否被 min/max 夹住且 warning 可见
8. 玩 8 轮，读档回第 3 轮，看消息/玩家数值/关系数值/背包/摘要五样是否一致
9. 点角色卡看详情弹窗有没有被页头压住（坑 1 的回归点）；窄屏抽屉能否正常拉出收回

## 十二、这一版不做

任务日志 · 战斗回合制 · 技能树 · 装备栈与属性加成 · 多 NPC 同场发言 · 从酒馆卡导入 · 自动生成死亡叙事 · 不一致叙事的自动重写 · 数值变化的图表回顾 · 旁白旁显示说话角色的立绘

`pages/Admin/Admin.tsx` 还有约 11 处同样的单基底低对比度色值，计划里标了低优先级，未动。

---

相关文档：`docs/tavern-prompts.md`（酒馆侧，与 RPG 完全独立）
