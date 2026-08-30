"""NovelBot 分发包启动器。

首次运行从清华源装依赖，之后直接起服务并打开浏览器。用户全程只需要双击
「启动NovelBot.bat」，机器上不需要预装 Python 或 Node。

包结构（由 tools/build_release.py 生成）：
    启动NovelBot.bat
    runtime/            内嵌 Python
    backend/            app/ + requirements*.txt + .env.example + web/
    tools/launcher.py   本文件
"""
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RUNTIME = ROOT / "runtime"
MARKER = RUNTIME / ".deps-installed"
LOG = ROOT / "install.log"

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
MIRROR_HOST = "pypi.tuna.tsinghua.edu.cn"
PORT = 8000


def python_exe() -> Path:
    """内嵌 runtime 优先；没有就用当前解释器（开发机上直接跑本脚本时）。"""
    embedded = RUNTIME / "python.exe"
    return embedded if embedded.is_file() else Path(sys.executable)


def log(message: str) -> None:
    print(message, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def fail(message: str) -> None:
    log("")
    log("=" * 60)
    log(f"  {message}")
    log(f"  详细信息见：{LOG}")
    log("=" * 60)
    input("\n按回车键退出...")
    sys.exit(1)


# ── 依赖安装 ──────────────────────────────────────────────────────────────────

def pip_install(args: list[str]) -> int:
    """跑一次 pip，输出同时打屏和落日志。返回退出码。"""
    cmd = [
        str(python_exe()), "-m", "pip", "install",
        "-i", MIRROR, "--trusted-host", MIRROR_HOST,
        *args,
    ]
    log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=str(BACKEND),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    with LOG.open("a", encoding="utf-8") as fh:
        for line in proc.stdout:
            print(line, end="", flush=True)
            fh.write(line)
    return proc.wait()


def ensure_dependencies() -> None:
    if MARKER.is_file():
        return

    log("")
    log("=" * 60)
    log("  首次启动，正在下载运行所需的组件（走清华镜像）")
    log("  大约 300-400MB，网速好的话几分钟，请不要关闭窗口")
    log("=" * 60)
    log("")

    # 内嵌 Python 不带 pip，先引导出来
    if subprocess.run(
        [str(python_exe()), "-m", "pip", "--version"],
        capture_output=True,
    ).returncode != 0:
        log("正在准备 pip...")
        get_pip = RUNTIME / "get-pip.py"
        if not get_pip.is_file():
            fail("缺少 runtime/get-pip.py，分发包不完整，请重新下载。")
        if subprocess.run([str(python_exe()), str(get_pip), "-i", MIRROR]).returncode != 0:
            fail("pip 准备失败，请检查网络后重新双击启动。")

    code = pip_install(["-r", "requirements.txt"])
    if code != 0:
        # 网络抖动很常见，自动重试一次；pip 会跳过已装好的包，比重头来快
        log("")
        log("第一次下载没成功，自动重试一次...")
        code = pip_install(["-r", "requirements.txt"])
    if code != 0:
        fail(
            "组件下载失败。多半是网络问题，请检查网络连接后重新双击启动。\n"
            "  已下载的部分会保留，重试不会从头开始。"
        )

    MARKER.write_text("ok", encoding="utf-8")
    log("")
    log("组件安装完成。")


def ensure_env_file() -> None:
    """首次运行从模板生成 .env。API Key 让用户在网页的设置页里填，这里只保证文件存在。"""
    env = BACKEND / ".env"
    example = BACKEND / ".env.example"
    if not env.is_file() and example.is_file():
        env.write_bytes(example.read_bytes())
        log("已生成配置文件 backend/.env")


# ── 启动 ──────────────────────────────────────────────────────────────────────

def port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_server() -> subprocess.Popen:
    """启动 uvicorn。cwd 必须是 backend——config.py 的数据路径和头像目录都相对它。

    不带 --reload：那是开发用的，会多起一个进程、改动文件时还会重启。
    """
    return subprocess.Popen(
        [str(python_exe()), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(BACKEND),
    )


def wait_until_ready(proc: subprocess.Popen, timeout: int = 90) -> bool:
    """轮询 /api/health 直到服务应答。

    必须显式绕过代理：urlopen 默认会读 Windows 系统代理设置，而且不会为
    127.0.0.1 例外。用户开着 Clash 之类的代理时，探测请求会被丢给代理，
    服务明明是好的却一直探不通，最后报"启动超时"。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{PORT}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # 进程已经退出，别再等了
        try:
            with opener.open(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(1)
    return False


def main() -> None:
    os.system("title NovelBot")
    log(f"NovelBot 启动中，程序目录：{ROOT}")

    if not (BACKEND / "app" / "main.py").is_file():
        fail("分发包不完整，找不到 backend/app，请重新解压。")

    ensure_dependencies()
    ensure_env_file()

    if port_busy(PORT):
        fail(
            f"端口 {PORT} 已被占用。可能 NovelBot 已经在运行了——\n"
            f"  请先看看有没有另一个 NovelBot 窗口，或浏览器打开 http://127.0.0.1:{PORT}"
        )

    log("正在启动服务...")
    proc = start_server()

    if not wait_until_ready(proc):
        if proc.poll() is not None:
            fail("服务启动失败，上面的错误信息说明了原因。")
        fail("服务启动超时。")

    url = f"http://127.0.0.1:{PORT}"
    log("")
    log("=" * 60)
    log(f"  NovelBot 已就绪：{url}")
    log("  首次使用请在网页的「设置」里填入 API Key。")
    log("")
    log("  关闭这个窗口就会停止 NovelBot。")
    log("=" * 60)
    log("")
    webbrowser.open(url)

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    main()
