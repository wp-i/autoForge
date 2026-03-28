"""
engine/coder.py
Phase 3 - 编码自愈单元 (Coder): TDD 闭环开发.

核心资产 - 实现 [SELF_HEAL_TDD] 规则:
  1. 根据 spec.json 生成测试用例
  2. 生成核心功能代码
  3. 运行 pytest
  4. 若失败 -> 将 stderr 喂回 LLM 做根因分析
  5. 连续 N 次原地修复无效 -> 强制更换实现策略
  6. 直到 100% 通过或达到 MAX_RETRIES 上限

所有子进程在子项目的 venv 中运行, 满足 [ENV_ISOLATION].
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from engine.llm_client import LLMClient, Message

logger = logging.getLogger("autoforge.coder")


# =====================================================================
# Data types
# =====================================================================
class HealAction(Enum):
    """自愈动作类型."""

    PATCH = auto()  # 原地修补当前实现
    RETHINK = auto()  # 更换算法/第三方库
    GIVE_UP = auto()  # 达到上限, 放弃


@dataclass
class TestResult:
    """单次 pytest 执行结果."""

    passed: bool
    return_code: int
    stdout: str
    stderr: str
    summary: str = ""  # 人类可读摘要

    @property
    def error_snippet(self) -> str:
        """提取供 LLM 分析的关键错误片段 (最多 3000 字符)."""
        combined = f"STDOUT:\n{self.stdout}\n\nSTDERR:\n{self.stderr}"
        return combined[-3000:]


@dataclass
class HealContext:
    """自愈循环上下文, 跟踪修复历史."""

    attempt: int = 0
    consecutive_patches: int = 0
    history: list[str] = field(default_factory=list)

    def record_attempt(self, action: HealAction, summary: str) -> None:
        self.attempt += 1
        if action == HealAction.PATCH:
            self.consecutive_patches += 1
        else:
            self.consecutive_patches = 0
        self.history.append(f"[Attempt {self.attempt}] {action.name}: {summary}")


# =====================================================================
# Coder 主类
# =====================================================================
class Coder:
    """编码自愈引擎 - AutoForge 最核心的资产."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_retries: int = 5,
        force_rethink_after: int = 3,
        test_timeout: int = 120,
    ) -> None:
        self.llm = llm
        self.max_retries = max_retries
        self.force_rethink_after = force_rethink_after
        self.test_timeout = test_timeout

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------
    def develop(self, project_dir: Path, spec: dict[str, Any]) -> bool:
        """执行完整的 TDD 自愈开发流程.

        Returns:
            True  -> 测试全部通过, 开发成功
            False -> 达到重试上限仍有失败
        """
        logger.info("=== Phase 3: Coder - TDD 自愈开发 [%s] ===", spec["name"])

        # Step 1: 生成测试用例
        logger.info("[Step 1/2] 生成测试用例 ...")
        self._generate_tests(project_dir, spec)

        # Step 2: 生成核心功能代码
        logger.info("[Step 2/2] 生成核心功能代码 ...")
        self._generate_core(project_dir, spec)

        # Step 3: 进入自愈循环
        return self._self_heal_loop(project_dir, spec)

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------
    def _generate_tests(self, project_dir: Path, spec: dict[str, Any]) -> None:
        """请 LLM 根据 spec 生成测试用例."""
        prompt = (
            "你是一名 TDD 专家。根据下面的项目需求, 编写 pytest 测试用例。\n"
            "要求:\n"
            "- 测试文件路径: tests/test_core.py\n"
            "- 导入方式: from src.core import ...\n"
            "- 覆盖所有核心功能点\n"
            "- 每个功能至少 2 个测试 (正常 + 边界)\n"
            "- 只输出完整的 Python 代码\n\n"
            f"项目需求:\n{json.dumps(spec, indent=2, ensure_ascii=False)}\n"
        )
        messages = [
            Message(
                role="system",
                content="你是 Python TDD 专家。只输出可执行的 pytest 代码, 不要解释。",
            ),
            Message(role="user", content=prompt),
        ]
        code = self.llm.chat(messages)
        code = self._extract_code(code)

        test_path = project_dir / "tests" / "test_core.py"
        test_path.write_text(code, encoding="utf-8")
        logger.info("测试用例已写入: %s", test_path)

    def _generate_core(self, project_dir: Path, spec: dict[str, Any]) -> None:
        """请 LLM 根据 spec 和测试用例生成核心代码."""
        test_source = (project_dir / "tests" / "test_core.py").read_text(
            encoding="utf-8"
        )

        prompt = (
            "你是一名高级 Python 开发者。根据下面的项目需求和测试用例, "
            "编写能让所有测试通过的核心功能代码。\n"
            "要求:\n"
            "- 代码文件路径: src/core.py\n"
            "- 必须实现测试中导入的所有函数/类\n"
            "- 代码必须健壮, 处理边界情况\n"
            "- 只输出完整的 Python 代码\n\n"
            f"项目需求:\n{json.dumps(spec, indent=2, ensure_ascii=False)}\n\n"
            f"测试用例 (必须让这些测试通过):\n```python\n{test_source}\n```\n"
        )
        messages = [
            Message(
                role="system",
                content="你是 Python 开发专家。只输出可执行的 Python 代码, 不要解释。",
            ),
            Message(role="user", content=prompt),
        ]
        code = self.llm.chat(messages)
        code = self._extract_code(code)

        core_path = project_dir / "src" / "core.py"
        core_path.write_text(code, encoding="utf-8")
        logger.info("核心代码已写入: %s", core_path)

    # ------------------------------------------------------------------
    # Self-healing loop (核心自愈循环)
    # ------------------------------------------------------------------
    def _self_heal_loop(self, project_dir: Path, spec: dict[str, Any]) -> bool:
        """自愈循环: 测试 -> 失败 -> 分析 -> 修复 -> 重测.

        这是 AutoForge 的核心循环, 实现 [SELF_HEAL_TDD]:
        - 每次测试失败后, 将 stdout/stderr 传回 LLM 做根因分析
        - 连续 force_rethink_after 次 PATCH 无效 -> 强制 RETHINK
        - 达到 max_retries 上限 -> 放弃
        """
        ctx = HealContext()

        while ctx.attempt < self.max_retries:
            # ---- 执行测试 ----
            logger.info(
                "--- 自愈循环 [Attempt %d/%d] 运行测试 ---",
                ctx.attempt + 1,
                self.max_retries,
            )
            result = self._run_tests(project_dir)

            if result.passed:
                logger.info(
                    "ALL TESTS PASSED (attempt %d) %s",
                    ctx.attempt + 1,
                    result.summary,
                )
                return True

            # ---- 测试失败, 决定修复策略 ----
            logger.warning(
                "Tests FAILED (attempt %d): %s",
                ctx.attempt + 1,
                result.summary,
            )
            action = self._decide_action(ctx)

            if action == HealAction.GIVE_UP:
                logger.error("达到最大重试次数 (%d), 放弃", self.max_retries)
                ctx.record_attempt(action, "GIVE_UP - max retries reached")
                break

            # ---- 执行修复 ----
            if action == HealAction.RETHINK:
                logger.info(
                    "连续 %d 次 PATCH 无效, 强制 RETHINK ...", ctx.consecutive_patches
                )
                self._rethink(project_dir, spec, result, ctx)
                ctx.record_attempt(action, "Rethink: 更换实现策略")
            else:
                self._patch(project_dir, spec, result, ctx)
                ctx.record_attempt(action, f"Patch: 基于错误修复")

        # 循环结束, 记录完整修复历史
        self._save_heal_history(project_dir, ctx)
        return False

    # ------------------------------------------------------------------
    # Test runner
    # ------------------------------------------------------------------
    def _run_tests(self, project_dir: Path) -> TestResult:
        """在子项目 venv 中运行 pytest."""
        venv_dir = project_dir / ".venv"
        if sys.platform == "win32":
            pytest_exe = venv_dir / "Scripts" / "pytest.exe"
            python_exe = venv_dir / "Scripts" / "python.exe"
        else:
            pytest_exe = venv_dir / "bin" / "pytest"
            python_exe = venv_dir / "bin" / "python"

        # 优先用 pytest 可执行文件, 回退到 python -m pytest
        if pytest_exe.exists():
            cmd = [str(pytest_exe), str(project_dir / "tests"), "-v", "--tb=short"]
        else:
            cmd = [
                str(python_exe),
                "-m",
                "pytest",
                str(project_dir / "tests"),
                "-v",
                "--tb=short",
            ]

        logger.debug("Running: %s", " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.test_timeout,
                cwd=str(project_dir),
                env=self._build_env(project_dir),
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False,
                return_code=-1,
                stdout="",
                stderr=f"TIMEOUT: pytest exceeded {self.test_timeout}s",
                summary="Timeout",
            )

        passed = proc.returncode == 0
        # 提取摘要行 (如 "3 passed, 1 failed")
        summary = ""
        for line in proc.stdout.splitlines():
            if "passed" in line or "failed" in line or "error" in line.lower():
                summary = line.strip()

        return TestResult(
            passed=passed,
            return_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            summary=summary,
        )

    @staticmethod
    def _build_env(project_dir: Path) -> dict[str, str]:
        """构建子进程环境变量, 确保 PYTHONPATH 包含项目根目录."""
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_dir)
        return env

    # ------------------------------------------------------------------
    # Heal actions
    # ------------------------------------------------------------------
    def _decide_action(self, ctx: HealContext) -> HealAction:
        """根据上下文决定下一步动作."""
        if ctx.attempt >= self.max_retries - 1:
            return HealAction.GIVE_UP
        if ctx.consecutive_patches >= self.force_rethink_after:
            return HealAction.RETHINK
        return HealAction.PATCH

    def _patch(
        self,
        project_dir: Path,
        spec: dict[str, Any],
        test_result: TestResult,
        ctx: HealContext,
    ) -> None:
        """PATCH: 基于错误信息, 请 LLM 修复当前代码."""
        logger.info("[PATCH] 请求 LLM 根因分析并修复 ...")

        current_code = (project_dir / "src" / "core.py").read_text(encoding="utf-8")
        test_code = (project_dir / "tests" / "test_core.py").read_text(encoding="utf-8")

        prompt = (
            "测试执行失败。请分析错误原因并修复 src/core.py。\n\n"
            "=== 当前 src/core.py ===\n"
            f"```python\n{current_code}\n```\n\n"
            "=== tests/test_core.py ===\n"
            f"```python\n{test_code}\n```\n\n"
            "=== 测试错误输出 ===\n"
            f"```\n{test_result.error_snippet}\n```\n\n"
            "要求:\n"
            "- 仔细分析错误的根本原因\n"
            "- 修复 src/core.py 使所有测试通过\n"
            "- 只输出修复后的完整 src/core.py 代码\n"
            "- 不要修改测试文件\n"
        )

        # 附加修复历史, 避免重复犯错
        if ctx.history:
            prompt += "\n=== 之前的修复尝试 ===\n"
            for h in ctx.history[-3:]:  # 只取最近 3 次
                prompt += f"- {h}\n"
            prompt += "\n请避免重复之前的修复方案, 尝试不同的方法。\n"

        messages = [
            Message(
                role="system",
                content=(
                    "你是一名擅长调试的 Python 专家。"
                    "仔细阅读错误信息, 找出根本原因, 输出修复后的完整代码。"
                    "只输出 Python 代码, 不要解释。"
                ),
            ),
            Message(role="user", content=prompt),
        ]

        code = self.llm.chat(messages)
        code = self._extract_code(code)
        (project_dir / "src" / "core.py").write_text(code, encoding="utf-8")
        logger.info("[PATCH] src/core.py 已更新")

    def _rethink(
        self,
        project_dir: Path,
        spec: dict[str, Any],
        test_result: TestResult,
        ctx: HealContext,
    ) -> None:
        """RETHINK: 连续修补无效, 强制更换实现算法或第三方库.

        这是 IMPLEMENTATION_GUIDE 规定的关键策略:
        "若连续 3 次原地修复无效, 强制 LLM 更改实现算法或更换第三方库"
        """
        logger.info("[RETHINK] 强制更换实现策略 ...")

        test_code = (project_dir / "tests" / "test_core.py").read_text(encoding="utf-8")

        prompt = (
            "之前的实现方案已连续多次修复失败, 现在必须彻底更换实现策略。\n\n"
            f"项目需求:\n{json.dumps(spec, indent=2, ensure_ascii=False)}\n\n"
            "=== tests/test_core.py (不可修改) ===\n"
            f"```python\n{test_code}\n```\n\n"
            "=== 最近的错误 ===\n"
            f"```\n{test_result.error_snippet}\n```\n\n"
            "=== 失败历史 ===\n"
            + "\n".join(f"- {h}" for h in ctx.history[-5:])
            + "\n\n"
            "强制要求:\n"
            "- 必须使用完全不同的算法或第三方库来实现\n"
            "- 不要重复之前失败的方案\n"
            "- 输出完整的 src/core.py 代码\n"
            "- 如果需要新增依赖, 在代码顶部用注释标注: # NEW_DEP: library_name>=x.y\n"
        )
        messages = [
            Message(
                role="system",
                content=(
                    "你是一名架构师。之前的实现路径已经失败, "
                    "你必须提出一个全新的实现方案。换一种算法或第三方库。"
                    "只输出 Python 代码。"
                ),
            ),
            Message(role="user", content=prompt),
        ]

        code = self.llm.chat(messages)
        code = self._extract_code(code)

        # 检测是否引入新依赖
        self._install_new_deps(project_dir, code)

        (project_dir / "src" / "core.py").write_text(code, encoding="utf-8")
        logger.info("[RETHINK] src/core.py 已用全新策略重写")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _install_new_deps(self, project_dir: Path, code: str) -> None:
        """扫描代码中的 # NEW_DEP: 注释并安装新依赖."""
        new_deps: list[str] = []
        for line in code.splitlines():
            if line.strip().startswith("# NEW_DEP:"):
                dep = line.split("# NEW_DEP:")[1].strip()
                if dep:
                    new_deps.append(dep)

        if not new_deps:
            return

        logger.info("检测到新依赖: %s", new_deps)
        venv_dir = project_dir / ".venv"
        if sys.platform == "win32":
            pip_exe = venv_dir / "Scripts" / "pip.exe"
        else:
            pip_exe = venv_dir / "bin" / "pip"

        for dep in new_deps:
            logger.info("Installing new dep: %s", dep)
            subprocess.run(
                [str(pip_exe), "install", dep, "-q"],
                capture_output=True,
                timeout=120,
            )

        # 更新 requirements.txt
        req_path = project_dir / "requirements.txt"
        existing = req_path.read_text(encoding="utf-8") if req_path.exists() else ""
        with open(req_path, "a", encoding="utf-8") as f:
            for dep in new_deps:
                if dep not in existing:
                    f.write(f"{dep}\n")

    @staticmethod
    def _extract_code(raw: str) -> str:
        """从 LLM 回复中提取 Python 代码块."""
        if "```python" in raw:
            start = raw.index("```python") + 9
            end = raw.index("```", start)
            return raw[start:end].strip()
        if "```" in raw:
            start = raw.index("```") + 3
            end = raw.index("```", start)
            return raw[start:end].strip()
        return raw.strip()

    @staticmethod
    def _save_heal_history(project_dir: Path, ctx: HealContext) -> None:
        """将修复历史追加到 autoforge.log."""
        history_text = "\n".join(ctx.history) if ctx.history else "(no attempts)"
        logger.info(
            "=== 自愈历史 (%d attempts) ===\n%s",
            ctx.attempt,
            history_text,
        )
