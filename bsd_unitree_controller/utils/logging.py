"""日志初始化。

基于 loguru，统一配置日志格式和输出位置。
应用启动时调用 setup_logging() 初始化一次。
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from bsd_unitree_controller.core.config import LogConfig


def setup_logging(log_config: LogConfig) -> None:
    """初始化日志配置。

    Args:
        log_config: 日志配置。
    """
    # 清除默认 handler
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stdout,
        level=log_config.level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # 文件输出（目录为空则跳过）
    if log_config.dir:
        log_dir = Path(log_config.dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=log_config.level,
            rotation="00:00",       # 每天轮转
            retention="30 days",    # 保留 30 天
            encoding="utf-8",
        )
