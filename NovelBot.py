"""NovelBot launcher — starts backend and frontend in separate console windows."""
import msvcrt
import os
import subprocess
import time

ROOT        = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, 'backend')
FRONTEND_DIR = os.path.join(ROOT, 'frontend')
PYTHON      = os.path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')

_backend:  subprocess.Popen | None = None
_frontend: subprocess.Popen | None = None


# ── process helpers ────────────────────────────────────────────────────────────

def _kill(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                       capture_output=True)
    except Exception:
        pass


def _kill_port(port: int) -> None:
    r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if f':{port} ' in line and 'LISTENING' in line:
            parts = line.split()
            pid = parts[-1]
            if pid.isdigit():
                subprocess.run(['taskkill', '/F', '/T', '/PID', pid],
                               capture_output=True)


def _kill_uvicorn_workers() -> None:
    subprocess.run(
        ['powershell', '-Command',
         "Get-CimInstance Win32_Process "
         "| Where-Object {$_.CommandLine -like '*multiprocessing-fork*'} "
         "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
         "-ErrorAction SilentlyContinue }"],
        capture_output=True,
    )


# ── start / stop ───────────────────────────────────────────────────────────────

def start_backend() -> None:
    global _backend
    _backend = subprocess.Popen(
        ['cmd', '/k',
         f'title NovelBot Backend'
         f' && {PYTHON} -m uvicorn app.main:app'
         f' --host 127.0.0.1 --port 8000 --reload'],
        cwd=BACKEND_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def start_frontend() -> None:
    global _frontend
    _frontend = subprocess.Popen(
        ['cmd', '/k', 'title NovelBot Frontend && npm run dev'],
        cwd=FRONTEND_DIR,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def stop_all() -> None:
    global _backend, _frontend
    _kill(_backend);  _backend  = None
    _kill(_frontend); _frontend = None
    _kill_port(8000)
    _kill_port(5173)
    _kill_uvicorn_workers()


def restart_backend() -> None:
    global _backend
    _kill(_backend); _backend = None
    _kill_port(8000)
    _kill_uvicorn_workers()
    time.sleep(1)
    start_backend()


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    os.system('title NovelBot Launcher')

    if not os.path.isfile(PYTHON):
        print(f'[NovelBot] 找不到虚拟环境: {PYTHON}')
        input('按任意键退出...')
        return

    print('[NovelBot] 清理残留进程...')
    stop_all()
    time.sleep(1)

    print('[NovelBot] 启动后端 (port 8000)...')
    start_backend()
    time.sleep(2)

    print('[NovelBot] 启动前端 (port 5173)...')
    start_frontend()

    print()
    print('  ==========================================')
    print('   Backend:   http://127.0.0.1:8000')
    print('   Frontend:  http://localhost:5173')
    print('  ==========================================')
    print()
    print('  [Q] 停止所有服务     [R] 重启后端')
    print()

    while True:
        try:
            ch = msvcrt.getch()
        except KeyboardInterrupt:
            ch = b'q'

        if ch in (b'\x00', b'\xe0'):   # arrow / function keys — skip extra byte
            msvcrt.getch()
            continue

        key = ch.lower()
        if key == b'q':
            print('[NovelBot] 停止所有服务...')
            stop_all()
            print('[NovelBot] 完成，再见！')
            break
        elif key == b'r':
            print('[NovelBot] 重启后端...')
            restart_backend()
            print('[NovelBot] 后端已重启。')


if __name__ == '__main__':
    main()
