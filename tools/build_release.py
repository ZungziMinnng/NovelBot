"""打包 NovelBot 分发包。

白名单复制 —— 只把明确列出的东西放进产物，而不是"复制全部再删掉几个"。
黑名单迟早会漏：backend/data 里会不断新增 novelbot.db.bak-* 和临时导出的
txt，作者每加一个就得记得同步黑名单，漏一次就把整本书发出去了。

打完包会扫一遍产物，命中任何敏感特征就删掉产物并报错。

用法：
    cd backend && ./.venv/Scripts/python.exe ../tools/build_release.py
    可选 --output <目录>   默认放到仓库同级的 NovelBot-dist/
    可选 --skip-frontend   跳过 npm build（前端没改时省时间）
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ── 白名单：只有这些进包 ──────────────────────────────────────────────────────
# (源路径, 包内路径)。目录会整体复制，但受下面的 EXCLUDE_NAMES 过滤。
INCLUDE = [
    (REPO / "backend" / "app", "backend/app"),
    (REPO / "backend" / "requirements.txt", "backend/requirements.txt"),
    (REPO / "backend" / "requirements-rerank.txt", "backend/requirements-rerank.txt"),
    (REPO / "backend" / ".env.example", "backend/.env.example"),
    (REPO / "backend" / "web", "backend/web"),
    (REPO / "tools" / "launcher.py", "tools/launcher.py"),
    (REPO / "tools" / "启动NovelBot.bat", "启动NovelBot.bat"),
    (REPO / "tools" / "安装重排功能.bat", "安装重排功能.bat"),
    (REPO / "tools" / "使用说明.txt", "使用说明.txt"),
]

# 复制目录时跳过的名字（任意层级）
EXCLUDE_NAMES = {"__pycache__", ".pytest_cache", "data", ".env", ".git"}

# ── 泄漏扫描 ──────────────────────────────────────────────────────────────────
# 文件名命中即失败
FORBIDDEN_NAMES = {".env", "novelbot.db", "初始密码.txt"}
FORBIDDEN_SUFFIXES = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")
FORBIDDEN_NAME_PARTS = ("novelbot.db.bak", "_recovered")

# 文本内容命中即失败。密钥不写死在脚本里——从本机 .env 现读，避免脚本自己变成泄漏点
FORBIDDEN_TEXT = ["@Ngnl1020"]


def load_local_secrets() -> list[str]:
    """从本机 backend/.env 读出密钥值，作为扫描特征。脚本本身不存储它们。"""
    env = REPO / "backend" / ".env"
    if not env.is_file():
        return []
    secrets = []
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        # 只挑真正像密钥的值，避免拿 "true" / "gpt-4o" 这种去扫出误报
        if len(value) >= 16 and any(
            w in key.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD")
        ):
            secrets.append(value)
    return secrets


def build_frontend() -> None:
    print("[1/4] 构建前端...")
    frontend = REPO / "frontend"
    if not (frontend / "node_modules").is_dir():
        sys.exit("前端依赖未安装，请先在 frontend 下跑 npm install")
    npx = "npx.cmd" if os.name == "nt" else "npx"
    for args in (
        [npx, "tsc", "--noEmit"],
        [npx, "vite", "build", "--outDir", "../backend/web", "--emptyOutDir"],
    ):
        if subprocess.run(args, cwd=str(frontend)).returncode != 0:
            sys.exit(f"前端构建失败：{' '.join(args)}")


def copy_tree(src: Path, dst: Path) -> None:
    def ignore(_dir, names):
        return [n for n in names if n in EXCLUDE_NAMES]
    shutil.copytree(src, dst, ignore=ignore)


def stage(out: Path) -> None:
    print(f"[2/4] 复制文件到 {out}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for src, rel in INCLUDE:
        if not src.exists():
            sys.exit(f"缺少必需文件：{src}\n（web/ 缺失说明前端还没构建）")
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            copy_tree(src, target)
        else:
            shutil.copy2(src, target)

    (out / "runtime").mkdir(exist_ok=True)
    (out / "runtime" / "放置内嵌Python.txt").write_text(
        "把 python-3.13.x-embed-amd64.zip 解压到这个目录，并额外放入 get-pip.py。\n"
        "解压后需要修改 python313._pth，取消 `import site` 那一行的注释，\n"
        "否则 pip 装的包 import 不到。\n\n"
        "下载地址：https://www.python.org/downloads/windows/ 选 "
        "\"Windows embeddable package (64-bit)\"\n"
        "get-pip.py：https://bootstrap.pypa.io/get-pip.py\n",
        encoding="utf-8",
    )


def scan(out: Path, secrets: list[str]) -> list[str]:
    """扫产物找泄漏。返回问题列表，空表示干净。"""
    print("[3/4] 扫描产物是否含隐私数据...")
    problems = []
    needles = FORBIDDEN_TEXT + secrets
    for path in out.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(out)
        name = path.name.lower()
        if name in {n.lower() for n in FORBIDDEN_NAMES}:
            problems.append(f"文件名命中：{rel}")
        if name.endswith(FORBIDDEN_SUFFIXES):
            problems.append(f"数据库文件：{rel}")
        if any(part in name for part in FORBIDDEN_NAME_PARTS):
            problems.append(f"备份/导出文件：{rel}")
        # 只读文本类文件找密钥，二进制跳过
        if path.suffix.lower() in {
            ".py", ".txt", ".md", ".json", ".js", ".css", ".html",
            ".jinja2", ".bat", ".example", ".yml", ".yaml", ".ts",
        }:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for needle in needles:
                if needle and needle in content:
                    problems.append(f"内容含敏感串：{rel}（{needle[:6]}...）")
    return problems


def make_zip(out: Path) -> Path:
    print("[4/4] 打包 zip...")
    archive = out.with_suffix(".zip")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, Path(out.name) / path.relative_to(out))
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(REPO.parent / "NovelBot-dist"))
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--no-zip", action="store_true")
    args = parser.parse_args()

    out = Path(args.output).resolve()
    if out.is_relative_to(REPO):
        sys.exit(f"产物目录不能在仓库内（避免被 git 带上）：{out}")

    if args.skip_frontend:
        print("[1/4] 跳过前端构建")
    else:
        build_frontend()

    stage(out)

    problems = scan(out, load_local_secrets())
    if problems:
        shutil.rmtree(out, ignore_errors=True)
        print("\n" + "=" * 60)
        print("  发现隐私数据，已删除产物：")
        for p in problems[:20]:
            print(f"    - {p}")
        print("=" * 60)
        sys.exit(1)
    print("  干净，未发现数据库/密钥/密码。")

    total_mb = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"\n完成：{out}（{total_mb:.1f} MB，不含内嵌 Python）")

    if not args.no_zip:
        archive = make_zip(out)
        print(f"压缩包：{archive}（{archive.stat().st_size / 1024 / 1024:.1f} MB）")

    print(
        "\n还需手动做一件事：按 runtime/放置内嵌Python.txt 的说明，"
        "把内嵌 Python 和 get-pip.py 放进 runtime/，然后重新压缩。"
    )


if __name__ == "__main__":
    main()
