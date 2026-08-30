"""统一日志配置。

项目里有上百处 logger.info/warning/exception 调用，但在此之前从未配置过 handler，
全部落到 uvicorn 默认配置上：WARNING 以下被丢弃、异常堆栈看不到、控制台一关就没了。
这里在进程启动最早期装好 root handler，让所有 app.* 的 logger 都有去处。
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_configured = False


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    """装配 root logger。重复调用无副作用（uvicorn --reload 会重新导入模块）。"""
    global _configured
    if _configured:
        return

    resolved = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(resolved)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_dir:
        try:
            path = Path(log_dir)
            path.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                path / "novelbot.log",
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as e:
            # 日志目录不可写不该拖垮启动，控制台日志已经装好了
            root.warning("文件日志初始化失败，仅保留控制台输出: %s", e)

    # httpx 每次 LLM 调用都会 INFO 一条请求行，会把真正的业务日志冲掉
    logging.getLogger("httpx").setLevel(logging.WARNING)
    _configured = True
