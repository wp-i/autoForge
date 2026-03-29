"""
engine/mcp_wrapper.py
Phase 4 - MCP 协议封装.

解析 src/core.py 的函数签名, 自动生成标准 MCP Tools 注册代码,
确保 openClaw 可直接调用. 满足 [MCP_NATIVE].
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from engine.llm_client import LLMClient, Message

logger = logging.getLogger("autoforge.mcp_wrapper")


class MCPWrapper:
    """自动化 MCP 协议适配器."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    def wrap(self, project_dir: Path, spec: dict[str, Any]) -> None:
        """读取 src/core.py, 生成 mcp_server.py."""
        logger.info("=== Phase 4: MCP Wrapper - 协议封装 [%s] ===", spec["name"])

        core_path = project_dir / "src" / "core.py"
        if not core_path.exists():
            raise FileNotFoundError(f"src/core.py not found in {project_dir}")

        core_source = core_path.read_text(encoding="utf-8")

        prompt = (
            "你是一名 MCP 协议专家。根据下面的 Python 源码, "
            "生成一个完整的 mcp_server.py 文件。\n"
            "要求:\n"
            "- 使用 stdio 传输 (stdin/stdout)\n"
            "- 为每个公共函数注册为 MCP Tool\n"
            "- 包含完整的 tool name, description, inputSchema (JSON Schema)\n"
            "- 可直接 `python mcp_server.py` 运行\n"
            "- 只输出完整的 Python 代码, 不要解释\n\n"
            f"=== src/core.py ===\n{core_source}\n"
            f"=== spec.json features ===\n{spec.get('features', [])}\n"
        )
        messages = [
            Message(
                role="system",
                content="你是 MCP 协议开发专家。只输出可执行的 Python 代码。",
            ),
            Message(role="user", content=prompt),
        ]
        code = self.llm.chat(messages)
        code = self._extract_code(code)

        mcp_path = project_dir / "mcp_server.py"
        mcp_path.write_text(code, encoding="utf-8")
        logger.info("mcp_server.py generated -> %s", mcp_path)

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
