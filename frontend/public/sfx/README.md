# 音效文件放这儿

这个目录默认是空的——音效文件没有随仓库分发，你得自己放。
**不放也能正常玩**，只是没声音；游戏设定页里的音效开关开着也不会报错。

## 放什么

六个文件，文件名必须是这几个（扩展名固定 `.ogg`）：

| 文件名 | 什么时候响 |
|---|---|
| `dice.ogg` | 掷骰判定开始 |
| `stat-up.ogg` | 任意数值上升 |
| `stat-down.ogg` | 任意数值下降 |
| `turn.ogg` | 点「结束这个时段」推进成功 |
| `enter.ogg` | 真的走到了新地点（被门槛挡住不响） |
| `npc.ogg` | 打开某个角色的档案卡 |

缺哪个，哪个场景就是静音，不影响其它五个。

## 去哪下

推荐 [Kenney · Interface Sounds](https://kenney.nl/assets/interface-sounds) —— **CC0**，
不用署名、不用注册、可商用。解压后从里面挑六个改名即可。
同站的 [UI Audio](https://kenney.nl/assets/ui-audio) 也是一套。

挑的时候注意：`stat-up` / `stat-down` 会在一回合里被连续触发（多条数值同时变），
选短促、不带尾音的，否则听着会糊。播放层已经做了 60ms 节流，同一个音不会叠放。

## 为什么是 .ogg

Kenney 的包同时给 `.ogg` 和 `.wav`。选 ogg 是因为体积小一个数量级，
而且这项目只跑在现代浏览器上，不用考虑 Safari 老版本的兼容问题。
真要用别的格式，改 `src/pages/Rpg/useSfx.ts` 里的 `SFX_DIR` 那一行拼接后缀。
