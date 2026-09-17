"""拉取并裁剪 Danbooru tag 词表，产出 backend/data/danbooru_tags.csv。

词表来自 DominikDoom/a1111-sd-webui-tagcomplete（MIT）的 tags/danbooru.csv，
它是 A1111 / ComfyUI 生态里事实上的标准补全词表。我们只要那一个数据文件，
不装它的代码。底层数据是 Danbooru 的公开 tag 统计，插件方只做搬运整理。

两条网络上的坑，都是实测撞出来的，改动前先看这里：

1. **走 GitHub API 的 blob 端点，不走 raw.githubusercontent.com** ——后者在本项目
   的网络环境下连不上（curl 直接 HTTP 000），API 域名可用。
2. **绕开系统代理**。Windows 注册表里那个代理声明成 `socks4://127.0.0.1:10809`，
   但那个端口实际不说 socks4，urllib 照着抓就被 WinError 10054 重置。
   curl 默认不读注册表所以没事，urllib 默认读，所以这里显式装一个空代理的
   opener。别改回 `urllib.request.urlopen`。

这个脚本平时不跑：产出的 CSV 已提交进仓库。只在想更新词表时手动跑一次。
"""

import csv
import json
import sys
import urllib.request
from pathlib import Path

# 空 ProxyHandler = 不读系统代理，理由见模块开头第 2 条
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

REPO = "DominikDoom/a1111-sd-webui-tagcomplete"
SRC_NAME = "danbooru.csv"
OUT = Path(__file__).resolve().parents[1] / "data" / "danbooru_tags.csv"

# Danbooru 的分类编号，和上游 CSV 第二列对应
GENERAL, ARTIST, COPYRIGHT, CHARACTER, META = "0", "1", "3", "4", "5"

# 按分类分别卡 post_count 阈值，**不能一刀切**。
#
# general / meta 是描述词，正是这个功能要用的东西，冷门的也得留：一刀切到 500
# 会砍掉 ink_wash_painting(248)、anatomical_nonsense(383) 这类真正有用的词，
# 而它们恰恰是自然语言里会提到、模型又认的。50 这个线是拿一批立绘常用词
# 试出来的，再低下去大量是错拼和一次性 tag。
#
# copyright / character 是具体作品名和角色名（初音未来、原神……）。RPG 模组里的
# NPC 是你自己编的人，套不上这些名字，留着只会诱导模型把你的角色画成某个现成
# 角色。卡到 2000 只留最知名的那批，纯粹是万一你真想引用。
#
# artist 整类丢掉：59,201 条画师名，自动转换用不上（画风你在 imageStyles.ts 里
# 管），而且打包分发画师名单容易招争议。
THRESHOLDS = {GENERAL: 50, META: 50, COPYRIGHT: 2000, CHARACTER: 2000}


def _blob_sha(name: str) -> str:
    url = f"https://api.github.com/repos/{REPO}/contents/tags?ref=main"
    with _opener.open(url, timeout=30) as r:
        for f in json.load(r):
            if f["name"] == name:
                return f["sha"]
    raise SystemExit(f"上游仓库的 tags/ 下没有 {name}，文件可能改名了")


def _download(sha: str) -> str:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/blobs/{sha}",
        headers={"Accept": "application/vnd.github.raw"},
    )
    with _opener.open(req, timeout=120) as r:
        return r.read().decode("utf-8")


def main() -> None:
    print(f"拉取 {REPO} 的 tags/{SRC_NAME}…")
    raw = _download(_blob_sha(SRC_NAME))

    kept, total = [], 0
    for row in csv.reader(raw.splitlines()):
        # 上游偶有残行；post_count 不是数字的一律跳过，不猜
        if len(row) < 3 or not row[2].isdigit():
            continue
        total += 1
        name, cat, count = row[0], row[1], int(row[2])
        if count >= THRESHOLDS.get(cat, 10**9):
            kept.append((name, cat, count, row[3] if len(row) > 3 else ""))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="" 是 csv 模块在 Windows 上的硬要求，不然每行多一个 \r
    with OUT.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(kept)

    print(f"上游 {total} 条 → 留下 {len(kept)} 条，{OUT.stat().st_size / 1024:.0f} KB")
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    sys.exit(main())
