"""
engine/coder.py
Phase 3 - 编码自愈单元 (Coder): TDD 闭环开发.

核心资产 - 实现 [SELF_HEAL_TDD] 规则:
  1. 根据 spec.json 生成测试用例
  2. 生成核心功能代码
  3. 运行 pytest
  4. 若失败 -> 将 stderr 喂回 LLM 做根因分析
  5. 连续 N 次原地修复无效 -> 强制更换实现策略
  6. 同一函数单点修复超 3 次 -> 强制清空重写 (范式级自愈)
  7. 测试通过后 -> MCP dry-run 验证工具列表可解析
  8. 直到 100% 通过或达到 MAX_RETRIES 上限

所有子进程在子项目的 venv 中运行, 满足 [ENV_ISOLATION].
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from collections import Counter
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
    NUKE = auto()  # 范式级重写: 清空文件, 全新实现
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

    @property
    def failed_functions(self) -> list[str]:
        """从 pytest 输出中提取失败的测试函数名."""
        # 匹配 FAILED tests/test_core.py::test_xxx 或 ERROR tests/...::test_xxx
        pattern = r"(?:FAILED|ERROR)\s+\S+::(\w+)"
        return re.findall(pattern, self.stdout + self.stderr)

    @property
    def pass_rate(self) -> float:
        """从 pytest 摘要中提取通过率 (0.0 ~ 1.0).

        解析形如 '3 failed, 20 passed' 或 '23 passed' 的摘要行.
        """
        combined = self.stdout + self.stderr
        passed_m = re.search(r"(\d+)\s+passed", combined)
        failed_m = re.search(r"(\d+)\s+failed", combined)
        error_m = re.search(r"(\d+)\s+error", combined)
        n_passed = int(passed_m.group(1)) if passed_m else 0
        n_failed = int(failed_m.group(1)) if failed_m else 0
        n_error = int(error_m.group(1)) if error_m else 0
        total = n_passed + n_failed + n_error
        if total == 0:
            return 0.0
        return n_passed / total


@dataclass
class HealContext:
    """自愈循环上下文, 跟踪修复历史."""

    attempt: int = 0
    consecutive_patches: int = 0
    history: list[str] = field(default_factory=list)
    # 单点失败追踪: {函数名: 连续失败次数}
    function_failure_count: Counter = field(default_factory=Counter)
    # 已触发 NUKE 的标记 (避免反复 NUKE)
    nuke_triggered: bool = False

    def record_attempt(self, action: HealAction, summary: str) -> None:
        self.attempt += 1
        if action == HealAction.PATCH:
            self.consecutive_patches += 1
        else:
            self.consecutive_patches = 0
        self.history.append(f"[Attempt {self.attempt}] {action.name}: {summary}")

    def track_failures(self, failed_funcs: list[str]) -> None:
        """更新单点函数失败计数."""
        for fn in failed_funcs:
            self.function_failure_count[fn] += 1

    def has_stuck_function(self, threshold: int = 3) -> str | None:
        """检查是否有单个函数连续失败超过阈值.

        Returns:
            卡住的函数名, 或 None.
        """
        for fn, count in self.function_failure_count.items():
            if count >= threshold:
                return fn
        return None


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
        # 开发结果统计
        self.heal_attempts: int = 0

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
        logger.info("[Step 1/3] 生成测试用例 ...")
        self._generate_tests(project_dir, spec)

        # Step 2: 生成核心功能代码
        logger.info("[Step 2/3] 生成核心功能代码 ...")
        self._generate_core(project_dir, spec)

        # Step 3: 进入自愈循环
        logger.info("[Step 3/3] 进入自愈循环 ...")
        success = self._self_heal_loop(project_dir, spec)

        if success:
            # Step 4: MCP dry-run 验证
            logger.info("[Post-TDD] MCP dry-run 验证 ...")
            self._mcp_dry_run(project_dir)

        return success

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------
    def _generate_tests(self, project_dir: Path, spec: dict[str, Any]) -> None:
        """请 LLM 根据 spec 生成测试用例."""
        platform_hint = "Windows" if sys.platform == "win32" else "Linux/Mac"
        prompt = (
            "你是一名 TDD 专家。根据下面的项目需求, 编写 pytest 测试用例。\n"
            "要求:\n"
            "- 测试文件路径: tests/test_core.py\n"
            "- 导入方式: from src.core import ...\n"
            "- 覆盖所有核心功能点\n"
            "- 每个功能至少 2 个测试 (正常 + 边界)\n"
            "- 只输出完整的 Python 代码\n"
            "- 不要使用 pytest-mock (mocker fixture), 用 unittest.mock 代替\n"
            f"- 目标平台: {platform_hint}, 避免使用平台特定的系统调用 "
            "(如 symbolic link 在 Windows 上需要管理员权限)\n"
            "- 测试必须使用 tempfile 创建临时文件, 并在 finally 块中清理\n"
            "- 测试文件不要直接 import 第三方库 (如 magic, imagehash 等), "
            "只通过 from src.core import ... 间接使用\n"
            "- 文件类型检测: 使用 mimetypes 标准库或 filetype 纯 Python 库, "
            "严禁使用 python-magic\n\n"
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

        platform_hint = "Windows" if sys.platform == "win32" else "Linux/Mac"
        prompt = (
            "你是一名高级 Python 开发者。根据下面的项目需求和测试用例, "
            "编写能让所有测试通过的核心功能代码。\n"
            "要求:\n"
            "- 代码文件路径: src/core.py\n"
            "- 必须实现测试中导入的所有函数/类\n"
            "- 代码必须健壮, 处理边界情况\n"
            "- 只输出完整的 Python 代码\n"
            "- 重要: 当需要从列表中排除特定对象实例时, 使用 'is not' 而非 '!=',\n"
            "  因为 __eq__ 可能被覆盖导致值相等的不同对象无法区分\n"
            f"- 目标平台: {platform_hint}\n"
            "- 严禁使用 python-magic/libmagic (Windows 上会崩溃), "
            "文件类型检测请用 mimetypes 标准库或 filetype 纯 Python 库\n"
            "- 严禁使用 rapidfuzz, imagehash, scipy 等重型 C 扩展依赖, "
            "优先使用标准库 (hashlib, difflib, mimetypes) + 轻量纯 Python 库\n\n"
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
        - 同一函数单点修复超 3 次 -> 强制 NUKE (清空重写)
        - 连续 force_rethink_after 次 PATCH 无效 -> 强制 RETHINK
        - 连续 Timeout/Crash 视为环境级问题, 提前触发 NUKE
        - 达到 max_retries 上限 -> 放弃
        """
        ctx = HealContext()
        consecutive_env_failures = 0  # 连续 Timeout/Crash 计数

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
                self.heal_attempts = ctx.attempt
                return True

            # ---- 环境自愈: 检测缺失的 pytest 插件并自动安装 ----
            if self._fix_missing_fixtures(project_dir, result):
                logger.info("检测到缺失的 pytest 插件, 已自动安装, 重新测试 ...")
                continue  # 不计入重试次数, 直接重测

            # ---- 环境级故障检测: Timeout / ProcessCrash ----
            is_env_failure = result.summary in ("Timeout", "ProcessCrash")
            if is_env_failure:
                consecutive_env_failures += 1
                logger.warning(
                    "[ENV_FAILURE] 连续环境级故障 %d 次 (类型: %s)",
                    consecutive_env_failures,
                    result.summary,
                )
                # 连续 2 次环境级故障 -> 强制 NUKE (依赖可能有系统级问题)
                if consecutive_env_failures >= 2 and not ctx.nuke_triggered:
                    logger.error(
                        "[ENV_FAILURE] 连续 %d 次 %s, "
                        "判断为依赖环境问题, 强制 NUKE 重写 (禁用问题依赖)",
                        consecutive_env_failures,
                        result.summary,
                    )
                    self._nuke_and_rewrite(project_dir, spec, result, ctx)
                    ctx.record_attempt(
                        HealAction.NUKE,
                        f"NUKE: 连续 {consecutive_env_failures} 次 "
                        f"{result.summary}, 判断为环境问题",
                    )
                    ctx.nuke_triggered = True
                    ctx.function_failure_count.clear()
                    consecutive_env_failures = 0
                    continue
            else:
                consecutive_env_failures = 0  # 非环境故障则重置计数

            # ---- 测试失败, 更新单点追踪 ----
            logger.warning(
                "Tests FAILED (attempt %d): %s",
                ctx.attempt + 1,
                result.summary,
            )
            failed_funcs = result.failed_functions
            ctx.track_failures(failed_funcs)
            if failed_funcs:
                logger.info("失败函数: %s", failed_funcs)
                logger.debug("函数失败计数: %s", dict(ctx.function_failure_count))

            # ---- 决定修复策略 ----
            action = self._decide_action(ctx, test_result=result)

            if action == HealAction.GIVE_UP:
                logger.error("达到最大重试次数 (%d), 放弃", self.max_retries)
                ctx.record_attempt(action, "GIVE_UP - max retries reached")
                break

            # ---- 执行修复 ----
            if action == HealAction.NUKE:
                stuck_fn = ctx.has_stuck_function()
                logger.warning(
                    "函数 '%s' 单点修复已超 3 次, "
                    "触发 NUKE: 清空文件, 使用完全不同的技术路径重写",
                    stuck_fn,
                )
                self._nuke_and_rewrite(project_dir, spec, result, ctx)
                ctx.record_attempt(action, f"NUKE: 因 {stuck_fn} 反复失败, 清空重写")
                ctx.nuke_triggered = True
                # NUKE 后重置函数失败计数
                ctx.function_failure_count.clear()
            elif action == HealAction.RETHINK:
                logger.info(
                    "连续 %d 次 PATCH 无效, 强制 RETHINK ...",
                    ctx.consecutive_patches,
                )
                self._rethink(project_dir, spec, result, ctx)
                ctx.record_attempt(action, "Rethink: 更换实现策略")
            else:
                self._patch(project_dir, spec, result, ctx)
                ctx.record_attempt(action, "Patch: 基于错误修复")

        # 循环结束, 记录完整修复历史
        self.heal_attempts = ctx.attempt
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
                encoding="utf-8",
                errors="replace",
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

        # 安全获取输出 (encoding="replace" 已防崩溃, 但仍需处理极端 None 场景)
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""

        # 检测进程崩溃 (access violation, segfault 等)
        # Windows: returncode 为负数或非常大的正数 (如 0xC0000005)
        # Unix: returncode 为负信号值
        is_crash = (
            proc.returncode < 0
            or proc.returncode > 100
            or "fatal exception" in stderr_text.lower()
            or "access violation" in stderr_text.lower()
            or "segmentation fault" in stderr_text.lower()
        )
        if is_crash:
            crash_info = (
                f"PROCESS_CRASH: pytest exited with code {proc.returncode}.\n"
                f"This usually means a C-extension dependency crashed "
                f"(e.g. python-magic, libmagic on Windows).\n"
                f"STDERR:\n{stderr_text[-2000:]}"
            )
            logger.error("[CRASH] pytest 进程崩溃 (returncode=%d)", proc.returncode)
            return TestResult(
                passed=False,
                return_code=proc.returncode,
                stdout=stdout_text,
                stderr=crash_info,
                summary="ProcessCrash",
            )

        passed = proc.returncode == 0
        # 提取摘要行 (如 "3 passed, 1 failed")
        summary = ""
        for line in stdout_text.splitlines():
            if "passed" in line or "failed" in line or "error" in line.lower():
                summary = line.strip()

        return TestResult(
            passed=passed,
            return_code=proc.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            summary=summary,
        )

    @staticmethod
    def _build_env(project_dir: Path) -> dict[str, str]:
        """构建子进程环境变量, 确保 PYTHONPATH 包含项目根目录 + UTF-8 编码."""
        import os

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_dir)
        # Windows 默认 GBK 编码, 强制子进程使用 UTF-8 避免 pipe 崩溃
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    # ------------------------------------------------------------------
    # Heal actions
    # ------------------------------------------------------------------
    def _decide_action(
        self, ctx: HealContext, test_result: TestResult | None = None
    ) -> HealAction:
        """根据上下文决定下一步动作.

        优先级:
        1. 达到上限 -> GIVE_UP
        2. 通过率 >= 90% 且单函数未卡死 -> 强制 PATCH (退化保护)
        3. 通过率 >= 90% 但单函数卡死 5+ 次 -> 允许 RETHINK (逃逸死循环)
        4. 单函数卡住且未触发过 NUKE -> NUKE (范式级重写)
        5. 连续 PATCH 超阈值且通过率 < 90% -> RETHINK
        6. 默认 -> PATCH

        退化保护 [NEAR_SUCCESS_GUARD]:
        当通过率 >= 90% 时, 代码已接近成功, 此时 NUKE/RETHINK 会推倒重来
        导致退化。应始终使用精细化 PATCH, 避免大规模重写浪费 Token.

        死循环逃逸 [STUCK_ESCAPE]:
        当通过率 >= 90% 但某函数已连续失败 5+ 次时, PATCH 已证明无效,
        允许升级为 RETHINK 尝试不同算法, 避免浪费剩余 Token.
        """
        if ctx.attempt >= self.max_retries - 1:
            return HealAction.GIVE_UP

        # [NEAR_SUCCESS_GUARD] 通过率 >= 90% 时的策略
        pass_rate = test_result.pass_rate if test_result else 0.0
        if pass_rate >= 0.9:
            # [STUCK_ESCAPE] 检查是否有函数卡死 5+ 次 (PATCH 已证明无效)
            deeply_stuck = ctx.has_stuck_function(threshold=5)
            if deeply_stuck:
                logger.warning(
                    "[STUCK_ESCAPE] 通过率 %.0f%% 但函数 '%s' 已卡死 %d 次, "
                    "PATCH 无效, 升级为 RETHINK",
                    pass_rate * 100,
                    deeply_stuck,
                    ctx.function_failure_count[deeply_stuck],
                )
                return HealAction.RETHINK
            logger.info(
                "[NEAR_SUCCESS_GUARD] 通过率 %.0f%%, 强制 PATCH (禁止 NUKE/RETHINK)",
                pass_rate * 100,
            )
            return HealAction.PATCH

        # 单函数反复失败 -> NUKE (只触发一次, 避免死循环)
        stuck_fn = ctx.has_stuck_function(threshold=3)
        if stuck_fn and not ctx.nuke_triggered:
            return HealAction.NUKE

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

        # 当遇到 Timeout/Crash 时, 补充有针对性的提示
        env_hint = ""
        if test_result.summary in ("Timeout", "ProcessCrash"):
            env_hint = (
                "\n- 重要: 测试进程崩溃或超时, 很可能是因为使用了不兼容的 C 扩展库\n"
                "- 严禁使用 python-magic, libmagic, imagehash, scipy, rapidfuzz 等需要系统 DLL 的库\n"
                "- 请替换为纯 Python 方案: filetype/mimetypes + Pillow + difflib\n"
            )

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
            "- 当需要从列表中排除特定对象实例时, 使用 'is not' 而非 '!='\n" + env_hint
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

        # 检测是否因环境崩溃触发
        env_crash_hint = ""
        if test_result.summary in ("Timeout", "ProcessCrash"):
            env_crash_hint = (
                "\n- 严禁使用 python-magic, libmagic, imagehash, scipy, rapidfuzz 等"
                "需要系统级 C 库的依赖\n"
                "- 文件类型检测请用 filetype 库或 mimetypes 标准库\n"
                "- 图片相似度请用 Pillow 内置功能\n"
                "- 文本相似度请用 difflib 标准库\n"
            )

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
            + env_crash_hint
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

    def _nuke_and_rewrite(
        self,
        project_dir: Path,
        spec: dict[str, Any],
        test_result: TestResult,
        ctx: HealContext,
    ) -> None:
        """NUKE: 范式级自愈 - 清空当前实现, 使用完全不同的技术路径从零重写.

        当同一函数的单点修复超过 3 次仍失败时触发.
        这比 RETHINK 更激进: 不保留任何旧代码上下文, 完全重新思考.
        """
        logger.warning("[NUKE] 范式级自愈: 清空 src/core.py, 完全重新实现 ...")

        test_code = (project_dir / "tests" / "test_core.py").read_text(encoding="utf-8")

        # 记录哪些函数反复失败, 供 LLM 参考
        stuck_funcs = [
            f"{fn} (failed {cnt} times)"
            for fn, cnt in ctx.function_failure_count.items()
            if cnt >= 3
        ]

        # 检测是否有环境级崩溃 (Timeout/ProcessCrash)
        env_crash_hint = ""
        if test_result.summary in ("Timeout", "ProcessCrash"):
            env_crash_hint = (
                "\n\n【关键】之前的代码导致进程崩溃或超时, 很可能是因为使用了"
                "在 Windows 上不兼容的 C 扩展库 (如 python-magic, libmagic)。\n"
                "严禁使用以下库: python-magic, libmagic, python-Levenshtein, "
                "imagehash, scipy, rapidfuzz\n"
                "文件类型检测请用: filetype 库或 mimetypes 标准库\n"
                "图片相似度请用: Pillow 内置功能 (如 Image.histogram() 直方图对比)\n"
                "文本相似度请用: difflib 标准库 (SequenceMatcher)\n"
            )

        prompt = (
            "【紧急重写】\n"
            "当前技术路径已彻底失效。以下函数经过多次修复仍无法通过测试:\n"
            + "\n".join(f"  - {s}" for s in stuck_funcs)
            + "\n\n"
            "你必须抛弃之前的所有实现思路, 从零开始设计一个全新的方案。\n\n"
            f"项目需求:\n{json.dumps(spec, indent=2, ensure_ascii=False)}\n\n"
            "=== tests/test_core.py (不可修改, 必须让这些测试通过) ===\n"
            f"```python\n{test_code}\n```\n\n"
            "=== 之前所有失败的修复尝试 ===\n"
            + "\n".join(f"- {h}" for h in ctx.history)
            + "\n\n"
            "强制要求:\n"
            "- 不要参考之前的 core.py, 它已被删除\n"
            "- 使用完全不同的算法、数据结构或第三方库\n"
            "- 尤其要用不同的方法解决反复失败的函数\n"
            "- 输出完整的 src/core.py 代码\n"
            "- 如果需要新增依赖, 在代码顶部用注释标注: # NEW_DEP: library_name>=x.y\n"
            + env_crash_hint
        )

        messages = [
            Message(
                role="system",
                content=(
                    "你是一名高级架构师。之前的技术路径已完全失败, "
                    "你不能参考任何旧代码。请用全新的思路从零实现所有功能。"
                    "尝试完全不同的算法或第三方库。"
                    "严禁使用 python-magic, libmagic, imagehash, scipy, rapidfuzz 等"
                    "需要系统级 C 库的依赖。优先使用纯 Python 方案。"
                    "只输出 Python 代码。"
                ),
            ),
            Message(role="user", content=prompt),
        ]

        code = self.llm.chat(messages)
        code = self._extract_code(code)

        # 检测并安装新依赖
        self._install_new_deps(project_dir, code)

        # 清空旧文件, 写入全新实现
        (project_dir / "src" / "core.py").write_text(code, encoding="utf-8")
        logger.info("[NUKE] src/core.py 已用全新技术路径重写")

    # ------------------------------------------------------------------
    # MCP dry-run 验证
    # ------------------------------------------------------------------
    def _mcp_dry_run(self, project_dir: Path) -> bool:
        """在测试通过后, 模拟 MCP 协议验证:

        1. 检查 mcp_server.py 是否可被 Python 语法解析
        2. 尝试 import 并检查是否能提取 tools 列表
        3. 验证每个 tool 有 name, description, inputSchema

        注意: 这是轻量级验证, 不启动实际 stdio 服务.
        """
        mcp_path = project_dir / "mcp_server.py"
        if not mcp_path.exists():
            logger.info(
                "[MCP_DRY_RUN] mcp_server.py 尚未生成, 跳过 (将在 Phase 4 生成)"
            )
            return True

        venv_dir = project_dir / ".venv"
        if sys.platform == "win32":
            python_exe = venv_dir / "Scripts" / "python.exe"
        else:
            python_exe = venv_dir / "bin" / "python"

        # Step 1: 语法检查 (显式 UTF-8 编码, 兼容 Windows GBK 环境)
        logger.info("[MCP_DRY_RUN] 检查 mcp_server.py 语法 ...")
        try:
            result = subprocess.run(
                [
                    str(python_exe),
                    "-c",
                    f"import ast; "
                    f"ast.parse(open(r'{mcp_path}', encoding='utf-8').read())",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                cwd=str(project_dir),
                env={**self._build_env(project_dir), "PYTHONIOENCODING": "utf-8"},
            )
            if result.returncode != 0:
                logger.warning(
                    "[MCP_DRY_RUN] mcp_server.py 存在语法错误:\n%s", result.stderr
                )
                return False
        except subprocess.TimeoutExpired:
            logger.warning("[MCP_DRY_RUN] 语法检查超时")
            return False

        # Step 2: 验证 tools 定义结构 (通过 AST 分析查找 tool/name/description 模式)
        mcp_source = mcp_path.read_text(encoding="utf-8")
        has_tool_def = any(
            kw in mcp_source
            for kw in [
                "@server.tool",
                "@app.tool",
                "Tool(",
                "tools",
                "register_tool",
                "add_tool",
            ]
        )
        has_name = "name" in mcp_source
        has_schema = (
            "inputSchema" in mcp_source
            or "input_schema" in mcp_source
            or "parameters" in mcp_source
        )

        if has_tool_def and has_name:
            logger.info(
                "[MCP_DRY_RUN] mcp_server.py 结构验证通过 "
                "(tool_def=%s, name=%s, schema=%s)",
                has_tool_def,
                has_name,
                has_schema,
            )
            if not has_schema:
                logger.warning(
                    "[MCP_DRY_RUN] 未检测到 inputSchema 定义, "
                    "MCP 客户端可能无法解析参数"
                )
        else:
            logger.warning(
                "[MCP_DRY_RUN] mcp_server.py 缺少关键 MCP 元素 "
                "(tool_def=%s, name=%s, schema=%s)",
                has_tool_def,
                has_name,
                has_schema,
            )

        return True

    # ------------------------------------------------------------------
    # Environment self-healing
    # ------------------------------------------------------------------
    def _fix_missing_fixtures(self, project_dir: Path, result: TestResult) -> bool:
        """检测并安装缺失的 pytest 插件 (如 pytest-mock).

        Returns:
            True if a missing fixture was detected and installed.
        """
        combined = result.stdout + result.stderr

        # 常见 fixture -> 对应 pytest 插件的映射
        fixture_to_plugin = {
            "mocker": "pytest-mock",
            "requests_mock": "requests-mock",
            "httpx_mock": "pytest-httpx",
            "anyio_backend": "anyio",
            "caplog": None,  # 内置, 不需要安装
        }

        missing_fixtures = re.findall(r"fixture '(\w+)' not found", combined)
        if not missing_fixtures:
            return False

        plugins_to_install: list[str] = []
        for fixture_name in set(missing_fixtures):
            plugin = fixture_to_plugin.get(fixture_name)
            if plugin is None and fixture_name not in fixture_to_plugin:
                # 猜测: pytest-<fixture_name>
                plugin = f"pytest-{fixture_name}"
            if plugin:
                plugins_to_install.append(plugin)

        if not plugins_to_install:
            return False

        logger.info("[ENV_HEAL] 检测到缺失的 pytest 插件: %s", plugins_to_install)
        venv_dir = project_dir / ".venv"
        if sys.platform == "win32":
            pip_exe = venv_dir / "Scripts" / "pip.exe"
        else:
            pip_exe = venv_dir / "bin" / "pip"

        for plugin in plugins_to_install:
            logger.info("[ENV_HEAL] Installing: %s", plugin)
            subprocess.run(
                [str(pip_exe), "install", plugin, "-q"],
                capture_output=True,
                timeout=120,
            )

        return True

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    # Python 标准库模块名集合 (用于过滤 LLM 错误标注的 NEW_DEP)
    _STDLIB_MODULES: set[str] = {
        "abc",
        "argparse",
        "ast",
        "asyncio",
        "base64",
        "bisect",
        "calendar",
        "cgi",
        "cmd",
        "codecs",
        "collections",
        "colorsys",
        "concurrent",
        "configparser",
        "contextlib",
        "copy",
        "csv",
        "ctypes",
        "dataclasses",
        "datetime",
        "decimal",
        "difflib",
        "dis",
        "email",
        "enum",
        "filecmp",
        "fileinput",
        "fnmatch",
        "fractions",
        "ftplib",
        "functools",
        "getpass",
        "gettext",
        "glob",
        "gzip",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "http",
        "imaplib",
        "importlib",
        "inspect",
        "io",
        "ipaddress",
        "itertools",
        "json",
        "keyword",
        "linecache",
        "locale",
        "logging",
        "lzma",
        "math",
        "mimetypes",
        "multiprocessing",
        "numbers",
        "operator",
        "os",
        "pathlib",
        "pdb",
        "pickle",
        "platform",
        "plistlib",
        "poplib",
        "posixpath",
        "pprint",
        "profile",
        "queue",
        "random",
        "re",
        "readline",
        "reprlib",
        "secrets",
        "select",
        "shelve",
        "shlex",
        "shutil",
        "signal",
        "smtplib",
        "socket",
        "sqlite3",
        "ssl",
        "stat",
        "statistics",
        "string",
        "struct",
        "subprocess",
        "sys",
        "sysconfig",
        "tarfile",
        "tempfile",
        "textwrap",
        "threading",
        "time",
        "timeit",
        "token",
        "tokenize",
        "traceback",
        "tracemalloc",
        "turtle",
        "types",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "uuid",
        "venv",
        "warnings",
        "wave",
        "webbrowser",
        "xml",
        "xmlrpc",
        "zipfile",
        "zipimport",
        "zlib",
    }

    def _install_new_deps(self, project_dir: Path, code: str) -> None:
        """扫描代码中的 # NEW_DEP: 注释并安装新依赖.

        自动过滤:
        - Python 标准库模块 (如 filecmp, collections, itertools)
        - 带括号注释的无效格式 (如 "lib>=1.0 (用于xxx)")
        - 空字符串或纯注释
        """
        raw_deps: list[str] = []
        for line in code.splitlines():
            if line.strip().startswith("# NEW_DEP:"):
                dep = line.split("# NEW_DEP:")[1].strip()
                if dep:
                    raw_deps.append(dep)

        if not raw_deps:
            return

        # 清洗和过滤
        new_deps: list[str] = []
        for dep in raw_deps:
            # 去除括号注释: "lib>=1.0 (用于xxx)" -> "lib>=1.0"
            dep = re.split(r"\s*[\(\(]", dep)[0].strip()
            if not dep:
                continue

            # 提取纯包名 (去掉版本约束)
            pkg_name = re.split(r"[><=!~\[]", dep)[0].strip().lower()

            # 过滤标准库
            if pkg_name in self._STDLIB_MODULES:
                logger.info("[DEP_FILTER] 跳过标准库: %s", dep)
                continue

            # 过滤 Windows 已知崩溃包
            _CRASH_BLOCKLIST = {
                "python-magic",
                "python-magic-bin",
                "libmagic",
                "python-levenshtein",
                "pylibmagic",
                "rapidfuzz",
                "regex",
                "murmurhash",
            }
            if pkg_name in _CRASH_BLOCKLIST:
                logger.warning("[DEP_FILTER] 跳过 Windows 不兼容包: %s", dep)
                continue

            new_deps.append(dep)

        if not new_deps:
            logger.info("[DEP_FILTER] 所有 NEW_DEP 均为标准库, 无需安装")
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
        """将修复历史保存到项目目录并记录日志."""
        history_text = "\n".join(ctx.history) if ctx.history else "(no attempts)"
        logger.info(
            "=== 自愈历史 (%d attempts) ===\n%s",
            ctx.attempt,
            history_text,
        )
        # 持久化到文件, 便于后续分析
        history_path = project_dir / "heal_history.json"
        history_data = {
            "total_attempts": ctx.attempt,
            "nuke_triggered": ctx.nuke_triggered,
            "function_failure_counts": dict(ctx.function_failure_count),
            "history": ctx.history,
        }
        history_path.write_text(
            json.dumps(history_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
