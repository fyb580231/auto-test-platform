"""loguru 日志配置：按天切割 + 保留 N 天 + 控制台彩色输出。

服务层与引擎层共用一个 logger 工厂，保证子进程里写出的日志同样落到
``reports/logs``，排查「Web 触发的执行」和「命令行执行」时行为一致。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import settings

_CONFIGURED: bool = False
_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


def setup_logging() -> None:
    """初始化日志系统（幂等，可重复调用）。

    Returns:
        None
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format=_LOG_FORMAT,
        colorize=True,
        enqueue=False,
    )

    log_dir: Path = settings.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_dir / "app_{time:YYYY-MM-DD}.log"),
        level=settings.log_level.upper(),
        format=_LOG_FORMAT.replace("<green>", "")
        .replace("</green>", "")
        .replace("<level>", "")
        .replace("</level>", "")
        .replace("<cyan>", "")
        .replace("</cyan>", ""),
        rotation="00:00",
        retention=f"{settings.log_retention_days} days",
        encoding="utf-8",
        enqueue=True,
        backtrace=settings.debug,
        diagnose=settings.debug,
    )
    _CONFIGURED = True
    logger.info("日志系统初始化完成，输出目录: {}", log_dir)


def get_logger(name: str) -> Any:
    """获取带模块上下文标签的 logger。

    Args:
        name: 模块名，通常是 ``__name__``。

    Returns:
        绑定后的 loguru logger。
    """
    return logger.bind(module=name)


__all__ = ["get_logger", "logger", "setup_logging"]
