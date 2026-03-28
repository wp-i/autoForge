"""
engine/strategist.py
Phase 1 - 立项官: 需求发现与项目方案产出.

通过 GitHub API 搜索痛点, 验证 [DATA_DRIVEN] [ZERO_AUTH] [NO_REPO_CLONE],
最终输出 spec.json 供后续流程消费.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from engine.llm_client import LLMClient, Message

logger = logging.getLogger("autoforge.strategist")

_GITHUB_API = "https://api.github.com"

# 用于排除需要 API Key / 授权的项目的关键词 [ZERO_AUTH]
_AUTH_BLOCKLIST = {
    "api_key",
    "apikey",
    "oauth",
    "login",
    "cookie",
    "token_required",
    "auth_required",
    "signup",
}


@dataclass
class ProjectSpec:
    """立项方案数据."""

    name: str
    description: str
    features: list[str]
    dependencies: list[str]
    rationale: str  # 数据驱动理由

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "features": self.features,
            "dependencies": self.dependencies,
            "rationale": self.rationale,
        }

    def save(self, project_dir: Path) -> Path:
        path = project_dir / "spec.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("spec.json saved -> %s", path)
        return path


class Strategist:
    """需求发现引擎."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._gh_token = os.environ.get("GITHUB_TOKEN", "")
        self._gh_headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._gh_token:
            self._gh_headers["Authorization"] = f"Bearer {self._gh_token}"

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def discover(self) -> ProjectSpec:
        """执行完整发现流程, 返回 ProjectSpec."""
        logger.info("=== Phase 1: Strategist - 需求发现 ===")

        # Step 1 - 请 LLM 提出候选方案
        candidates = self._brainstorm_candidates()
        logger.info("LLM 提出 %d 个候选方案", len(candidates))

        # Step 2 - 逐个校验
        for candidate in candidates:
            name = candidate.get("name", "unknown")
            logger.info("校验候选: %s", name)

            if self._has_auth_keywords(candidate):
                logger.info("  SKIP [ZERO_AUTH] 含授权关键词")
                continue

            if self._is_duplicate_on_github(name):
                logger.info("  SKIP [NO_REPO_CLONE] GitHub 已有高相似项目")
                continue

            # 通过校验 -> 构建 spec
            spec = ProjectSpec(
                name=name,
                description=candidate.get("description", ""),
                features=candidate.get("features", []),
                dependencies=candidate.get("dependencies", []),
                rationale=candidate.get("rationale", ""),
            )
            logger.info("选定项目: %s", spec.name)
            return spec

        raise RuntimeError("Strategist: 所有候选方案均未通过校验, 无法立项")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _brainstorm_candidates(self) -> list[dict[str, Any]]:
        """请 LLM 生成候选项目列表."""
        prompt = (
            "你是 AutoForge 立项官。请提出 3 个适合作为 MCP 工具的小型开源项目方案。\n"
            "要求:\n"
            "- 项目必须完全本地运行或只使用免费公开接口 (不需要 API Key/登录)\n"
            "- 项目必须解决至少 1 个具体痛点, 不是简单 Demo\n"
            "- 每个方案必须包含数据驱动的立项理由\n"
            "- 优先选择 Python 实现\n\n"
            "以 JSON 数组格式返回, 每个元素包含:\n"
            '{"name": "project-name", "description": "...", '
            '"features": ["feat1", "feat2"], '
            '"dependencies": ["lib1>=x.y"], '
            '"rationale": "数据驱动理由..."}'
        )
        messages = [
            Message(
                role="system",
                content="你是一个精通开源生态的技术分析师。只输出 JSON, 不要额外解释。",
            ),
            Message(role="user", content=prompt),
        ]
        result = self.llm.chat_json(messages)
        # result 可能是 list 或 {"candidates": list}
        if isinstance(result, list):
            return result
        return result.get("candidates", result.get("projects", []))

    @staticmethod
    def _has_auth_keywords(candidate: dict[str, Any]) -> bool:
        """检查方案是否涉及授权关键词."""
        text = json.dumps(candidate, ensure_ascii=False).lower()
        return any(kw in text for kw in _AUTH_BLOCKLIST)

    def _is_duplicate_on_github(self, name: str) -> bool:
        """在 GitHub 上查重, 若存在 Stars > 100 的同名/高度相似项目则视为重复."""
        try:
            with httpx.Client(timeout=30) as client:
                r = client.get(
                    f"{_GITHUB_API}/search/repositories",
                    headers=self._gh_headers,
                    params={"q": name, "sort": "stars", "per_page": 5},
                )
                r.raise_for_status()
                items = r.json().get("items", [])
                for repo in items:
                    if repo.get("stargazers_count", 0) > 100:
                        logger.debug(
                            "  GitHub duplicate: %s (%d stars)",
                            repo["full_name"],
                            repo["stargazers_count"],
                        )
                        return True
        except httpx.HTTPError as exc:
            logger.warning("GitHub API error (non-fatal): %s", exc)
        return False
