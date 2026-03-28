"""
engine/auditor.py
Phase 5 - 静态审计.

对交付项目执行 Ruff lint 检查, 满足 [LINT_CLEAN].
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("autoforge.auditor")


class Auditor:
    """静态代码审计器."""

    def audit(self, project_dir: Path) -> bool:
        """执行 Ruff lint 检查, 返回是否通过."""
        logger.info("=== Phase 5: Auditor - Lint 检查 [%s] ===", project_dir.name)

        # 尝试用子项目 venv 的 ruff, 回退到系统 ruff
        venv_dir = project_dir / ".venv"
        if sys.platform == "win32":
            ruff_exe = venv_dir / "Scripts" / "ruff.exe"
        else:
            ruff_exe = venv_dir / "bin" / "ruff"

        if not ruff_exe.exists():
            # 安装 ruff 到子项目 venv
            if sys.platform == "win32":
                pip_exe = venv_dir / "Scripts" / "pip.exe"
            else:
                pip_exe = venv_dir / "bin" / "pip"
            subprocess.run(
                [str(pip_exe), "install", "ruff", "-q"],
                capture_output=True,
                timeout=120,
            )

        # 先 fix 自动修复
        fix_result = subprocess.run(
            [
                str(ruff_exe),
                "check",
                "--fix",
                str(project_dir / "src"),
                str(project_dir / "mcp_server.py"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        logger.debug("Ruff fix stdout:\n%s", fix_result.stdout)

        # 再 check
        check_result = subprocess.run(
            [
                str(ruff_exe),
                "check",
                str(project_dir / "src"),
                str(project_dir / "mcp_server.py"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if check_result.returncode == 0:
            logger.info("Lint 检查通过 (0 issues)")
            return True

        logger.warning("Lint issues found:\n%s", check_result.stdout)
        return False
