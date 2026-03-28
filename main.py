"""
main.py
AutoForge 状态机调度器 - 全自动项目工厂入口.

按照 IMPLEMENTATION_GUIDE.md 第 3 节定义的 6 阶段流程:
  Phase 1 (Insight)   -> Strategist   需求发现
  Phase 2 (Scaffold)  -> Architect    脚手架生成
  Phase 3 (Develop)   -> Coder        TDD 自愈开发
  Phase 4 (Wrap)      -> MCPWrapper   MCP 协议封装
  Phase 5 (Audit)     -> Auditor      Lint 静态审计
  Phase 6 (Done)      -> 归档交付

运行方式: python main.py
零干预 [ZERO_INTERVENT] - 从启动到交付无需任何人工输入.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from enum import Enum, auto
from pathlib import Path

import yaml
from dotenv import load_dotenv


# =====================================================================
# Phase 定义
# =====================================================================
class Phase(Enum):
    INIT = auto()
    INSIGHT = auto()  # Phase 1: Strategist
    SCAFFOLD = auto()  # Phase 2: Architect
    DEVELOP = auto()  # Phase 3: Coder (self-heal TDD)
    WRAP = auto()  # Phase 4: MCP Wrapper
    AUDIT = auto()  # Phase 5: Lint
    DONE = auto()  # Phase 6: 归档


# =====================================================================
# 配置加载
# =====================================================================
def load_config() -> dict:
    """加载 config.yaml, 不存在则使用默认值."""
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_rules() -> str:
    """读取 RULES.md 内容, 供日志记录."""
    rules_path = Path(__file__).parent / "RULES.md"
    if rules_path.exists():
        return rules_path.read_text(encoding="utf-8")
    return ""


# =====================================================================
# 主调度器
# =====================================================================
class AutoForge:
    """AutoForge 状态机 - 全自动项目工厂."""

    def __init__(self) -> None:
        # 0. 加载环境变量
        load_dotenv(Path(__file__).parent / ".env")

        # 1. 加载配置
        self.config = load_config()
        self.rules = load_rules()

        # 2. 路径
        self.output_root = Path(self.config.get("output_path", "./output")).resolve()
        self.delivered_root = Path(
            self.config.get("delivered_path", "./delivered")
        ).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

        # 3. 运行参数
        self.max_retries = self.config.get("max_retries", 5)
        self.force_rethink_after = self.config.get("force_rethink_after", 3)
        self.test_timeout = self.config.get("test_timeout_seconds", 120)
        llm_cfg = self.config.get("llm", {})

        # 4. 初始化引擎模块
        from engine.logger import ForgeLogger
        from engine.llm_client import LLMClient, LLMConfig
        from engine.strategist import Strategist
        from engine.architect import Architect
        from engine.coder import Coder
        from engine.mcp_wrapper import MCPWrapper
        from engine.auditor import Auditor

        self.forge_logger = ForgeLogger(level=self.config.get("log_level", "INFO"))
        self.log = self.forge_logger.log

        self.llm = LLMClient()  # 从 .env 自动读取配置
        # 覆盖 config.yaml 中的 LLM 参数
        if llm_cfg.get("temperature") is not None:
            self.llm.cfg.temperature = llm_cfg["temperature"]
        if llm_cfg.get("max_tokens") is not None:
            self.llm.cfg.max_tokens = llm_cfg["max_tokens"]

        self.strategist = Strategist(self.llm)
        self.architect = Architect(self.llm, self.output_root)
        self.coder = Coder(
            self.llm,
            max_retries=self.max_retries,
            force_rethink_after=self.force_rethink_after,
            test_timeout=self.test_timeout,
        )
        self.mcp_wrapper = MCPWrapper(self.llm)
        self.auditor = Auditor()

        # 5. 状态
        self.phase = Phase.INIT
        self.project_dir: Path | None = None
        self.spec: dict | None = None

    # ------------------------------------------------------------------
    # 状态机主循环
    # ------------------------------------------------------------------
    def run(self) -> None:
        """执行完整的 6 阶段流水线. 零干预 [ZERO_INTERVENT]."""
        start_time = time.time()
        self.log.info("=" * 60)
        self.log.info("AutoForge 启动")
        self.log.info("=" * 60)
        self.log.info("Rules loaded (%d rules)", self.rules.count("["))
        self.log.info("Output root: %s", self.output_root)

        try:
            self._transition(Phase.INSIGHT)
            self._phase_insight()

            self._transition(Phase.SCAFFOLD)
            self._phase_scaffold()

            self._transition(Phase.DEVELOP)
            success = self._phase_develop()
            if not success:
                self.log.error("Phase 3 FAILED: 自愈循环未能通过所有测试")
                self.log.error("项目保留在: %s (可手动检查)", self.project_dir)
                return

            self._transition(Phase.WRAP)
            self._phase_wrap()

            self._transition(Phase.AUDIT)
            self._phase_audit()

            self._transition(Phase.DONE)
            self._phase_done()

        except Exception:
            self.log.exception("AutoForge 运行异常终止")
            raise
        finally:
            elapsed = time.time() - start_time
            self.log.info("=" * 60)
            self.log.info(
                "AutoForge 结束  耗时: %.1fs  最终阶段: %s", elapsed, self.phase.name
            )
            self.log.info("=" * 60)
            self.forge_logger.detach_project_log()

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------
    def _phase_insight(self) -> None:
        """Phase 1: 调用 Strategist 产出项目方案."""
        project_spec = self.strategist.discover()
        self.spec = project_spec.to_dict()
        self.log.info(
            "立项方案: %s", json.dumps(self.spec, indent=2, ensure_ascii=False)
        )

    def _phase_scaffold(self) -> None:
        """Phase 2: 调用 Architect 创建物理目录."""
        self.project_dir = self.architect.scaffold(self.spec)

        # 绑定项目日志
        self.forge_logger.attach_project_log(self.project_dir)

        # 保存 spec.json
        spec_path = self.project_dir / "spec.json"
        if not spec_path.exists():
            spec_path.write_text(
                json.dumps(self.spec, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def _phase_develop(self) -> bool:
        """Phase 3: 调用 Coder 进入 TDD 自愈循环."""
        return self.coder.develop(self.project_dir, self.spec)

    def _phase_wrap(self) -> None:
        """Phase 4: 调用 MCP Wrapper 完成协议包装."""
        self.mcp_wrapper.wrap(self.project_dir, self.spec)

    def _phase_audit(self) -> None:
        """Phase 5: 执行最终 Lint 检查."""
        passed = self.auditor.audit(self.project_dir)
        if not passed:
            self.log.warning("Lint 检查未完全通过, 但不阻塞交付 (已自动修复)")

    def _phase_done(self) -> None:
        """Phase 6: 将项目移动到交付区, 生成运行日志."""
        self.log.info("=== Phase 6: Done - 归档交付 ===")

        # 生成最终摘要
        summary = {
            "project": self.spec.get("name", "unknown"),
            "status": "delivered",
            "output_dir": str(self.project_dir),
            "features": self.spec.get("features", []),
        }
        summary_path = self.project_dir / "delivery_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 复制到交付区
        self.delivered_root.mkdir(parents=True, exist_ok=True)
        delivered_dir = self.delivered_root / self.spec["name"]
        if delivered_dir.exists():
            shutil.rmtree(delivered_dir)
        shutil.copytree(self.project_dir, delivered_dir)

        self.log.info("项目已交付: %s", delivered_dir)
        self.log.info("包含文件:")
        for f in sorted(delivered_dir.rglob("*")):
            if f.is_file() and ".venv" not in str(f):
                self.log.info("  %s", f.relative_to(delivered_dir))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _transition(self, new_phase: Phase) -> None:
        """状态转换, 记录日志."""
        old = self.phase
        self.phase = new_phase
        self.log.info("Phase transition: %s -> %s", old.name, new_phase.name)


# =====================================================================
# Entry point
# =====================================================================
def main() -> None:
    forge = AutoForge()
    forge.run()


if __name__ == "__main__":
    main()
