"""
engine/logger.py
双路日志系统: 控制台 + 子项目文件.

每个子项目在 output/<project>/autoforge.log 中保留完整诞生日志,
同时在控制台输出简洁摘要, 满足 IMPLEMENTATION_GUIDE 日志追踪要求.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


_LOG_FMT = "[%(asctime)s] %(levelname)-8s %(name)s :: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"


class ForgeLogger:
    """为每次 AutoForge 会话管理日志."""

    def __init__(self, level: str = "INFO") -> None:
        self._root = logging.getLogger("autoforge")
        self._root.setLevel(getattr(logging, level.upper(), logging.INFO))
        self._root.handlers.clear()

        # --- 控制台 handler ---
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT))
        self._root.addHandler(console)

        self._file_handler: logging.FileHandler | None = None

    def attach_project_log(self, project_dir: Path) -> None:
        """为指定子项目目录追加文件日志."""
        if self._file_handler is not None:
            self._root.removeHandler(self._file_handler)

        log_path = project_dir / "autoforge.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        self._file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        self._file_handler.setFormatter(logging.Formatter(_LOG_FMT, datefmt=_DATE_FMT))
        self._root.addHandler(self._file_handler)
        self._root.info("Project log attached: %s", log_path)

    def detach_project_log(self) -> None:
        """移除文件日志 handler."""
        if self._file_handler is not None:
            self._root.removeHandler(self._file_handler)
            self._file_handler.close()
            self._file_handler = None

    @property
    def log(self) -> logging.Logger:
        return self._root
