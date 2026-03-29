"""
engine/strategist.py
Phase 1 - 策略官: 需求发现、市场缺口评估与项目方案产出.

通过 GitHub API + PyPI 元数据搜索痛点, 验证 [DATA_DRIVEN] [ZERO_AUTH] [NO_REPO_CLONE],
引入"市场缺口评分"对候选方案量化排序, 最终输出 spec.json 供后续流程消费.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from engine.llm_client import LLMClient, Message

logger = logging.getLogger("autoforge.strategist")

_GITHUB_API = "https://api.github.com"
_PYPI_API = "https://pypi.org/pypi"

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

# Windows 上已知会崩溃或需要系统级 DLL 的包黑名单
_PLATFORM_BLOCKLIST = {
    "python-magic",
    "python-magic-bin",
    "libmagic",
    "python-levenshtein",
    "pylibmagic",
    "rapidfuzz",
    "regex",
    "murmurhash",
}

# 深度扫描: 依赖库文档/描述中的强鉴权关键词
_DEEP_AUTH_KEYWORDS = {
    "api_key",
    "api key",
    "apikey",
    "oauth",
    "oauth2",
    "token",
    "access_token",
    "bearer",
    "authorization",
    "credentials",
    "secret_key",
    "client_id",
    "client_secret",
    "signup",
    "sign up",
    "register",
    "authentication required",
}


@dataclass
class MarketGapScore:
    """市场缺口评分明细."""

    competition_score: float = 0.0  # 竞争热度 (0-40): 搜索结果越少分越高
    demand_score: float = 0.0  # 需求强度 (0-40): issue 活跃度 / star 趋势
    novelty_score: float = 0.0  # 新颖度 (0-20): 相关仓库少 = 蓝海
    total: float = 0.0
    breakdown: str = ""

    def compute_total(self) -> float:
        self.total = self.competition_score + self.demand_score + self.novelty_score
        return self.total


@dataclass
class ProjectSpec:
    """立项方案数据."""

    name: str
    description: str
    features: list[str]
    dependencies: list[str]
    rationale: str  # 数据驱动理由
    market_gap_score: float = 0.0
    score_breakdown: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "features": self.features,
            "dependencies": self.dependencies,
            "rationale": self.rationale,
            "market_gap_score": self.market_gap_score,
            "score_breakdown": self.score_breakdown,
        }

    def save(self, project_dir: Path) -> Path:
        path = project_dir / "spec.json"
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("spec.json saved -> %s", path)
        return path


class Strategist:
    """需求发现引擎 - 数据驱动的策略官."""

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
        """执行完整发现流程, 返回 ProjectSpec.

        流程:
        1. LLM 头脑风暴 3 个候选方案
        2. 浅层校验: 文本级 ZERO_AUTH + NO_REPO_CLONE
        3. 深层校验: 依赖库 PyPI 元数据鉴权扫描
        4. 市场缺口评分 (竞争热度 + 需求强度 + 新颖度)
        5. 选分最高且通过校验的方案
        """
        logger.info("=== Phase 1: Strategist - 需求发现 (增强版) ===")

        # Step 1 - 请 LLM 提出候选方案
        candidates = self._brainstorm_candidates()
        logger.info("LLM 提出 %d 个候选方案", len(candidates))

        # Step 2 - 逐个校验 + 评分
        scored_candidates: list[tuple[dict[str, Any], MarketGapScore]] = []

        for candidate in candidates:
            name = candidate.get("name", "unknown")
            logger.info("校验候选: %s", name)

            # [ZERO_AUTH] 浅层: 文本关键词
            if self._has_auth_keywords(candidate):
                logger.info("  REJECT [ZERO_AUTH] 含授权关键词")
                continue

            # [NO_REPO_CLONE] GitHub 查重
            if self._is_duplicate_on_github(name):
                logger.info("  REJECT [NO_REPO_CLONE] GitHub 已有高相似项目")
                continue

            # [PLATFORM_COMPAT] 平台兼容性检查: 过滤 Windows 不兼容依赖
            deps = candidate.get("dependencies", [])
            bad_dep = self._check_platform_blocklist(deps)
            if bad_dep:
                logger.info(
                    "  REJECT [PLATFORM_COMPAT] 依赖 '%s' 在 Windows 上不兼容",
                    bad_dep,
                )
                continue

            # [ZERO_AUTH] 深层: 依赖库 PyPI 元数据鉴权扫描
            flagged_dep = self._scan_deps_for_auth(deps)
            if flagged_dep:
                logger.info(
                    "  REJECT [ZERO_AUTH_DEEP] 依赖 '%s' 的文档含强鉴权关键词, "
                    "自动驳回并跳过",
                    flagged_dep,
                )
                continue

            # [DATA_DRIVEN] 市场缺口评分
            score = self._compute_market_gap_score(name, candidate)
            logger.info("  市场缺口评分: %.1f/100 (%s)", score.total, score.breakdown)
            scored_candidates.append((candidate, score))

        if not scored_candidates:
            raise RuntimeError("Strategist: 所有候选方案均未通过校验, 无法立项")

        # Step 3 - 选分最高的方案
        scored_candidates.sort(key=lambda x: x[1].total, reverse=True)
        best_candidate, best_score = scored_candidates[0]

        spec = ProjectSpec(
            name=best_candidate.get("name", "unknown"),
            description=best_candidate.get("description", ""),
            features=best_candidate.get("features", []),
            dependencies=best_candidate.get("dependencies", []),
            rationale=best_candidate.get("rationale", ""),
            market_gap_score=best_score.total,
            score_breakdown=best_score.breakdown,
        )
        logger.info(
            "选定项目: %s (市场缺口评分: %.1f/100)", spec.name, spec.market_gap_score
        )
        return spec

    # ------------------------------------------------------------------
    # Brainstorm
    # ------------------------------------------------------------------
    def _brainstorm_candidates(self) -> list[dict[str, Any]]:
        """请 LLM 生成候选项目列表."""
        prompt = (
            "你是 AutoForge 立项官。"
            "请围绕以下领域提出 3 个适合作为 MCP 工具的小型开源项目方案:\n"
            "领域方向: 基于本地文件系统的重复文件扫描与清理工具\n\n"
            "要求:\n"
            "- 项目必须完全本地运行, 不需要 API Key/登录/网络\n"
            "- 项目名称必须独特且有辨识度, 使用创造性命名 (如组合词、新造词)\n"
            "- 项目必须解决至少 1 个具体痛点, 不是简单 Demo\n"
            "- 每个方案必须包含数据驱动的立项理由\n"
            "- 优先选择 Python 实现\n"
            "- 依赖库只使用纯本地库 (如 xxhash, pathlib 等), 不要使用需要网络的库\n"
            "- 严禁使用需要系统级 C 库/DLL 的包 (如 python-magic, libmagic, "
            "python-Levenshtein 等), 因为它们在 Windows 上常崩溃\n"
            "- 文件类型检测请用纯 Python 方案 (如 filetype, mimetypes 标准库)\n"
            "- 图片处理尽量用 Pillow, 不要引入 imagehash/scipy 等重型依赖\n\n"
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

    # ------------------------------------------------------------------
    # Validation: shallow auth check
    # ------------------------------------------------------------------
    @staticmethod
    def _has_auth_keywords(candidate: dict[str, Any]) -> bool:
        """浅层检查: 方案文本是否涉及授权关键词."""
        text = json.dumps(candidate, ensure_ascii=False).lower()
        return any(kw in text for kw in _AUTH_BLOCKLIST)

    # ------------------------------------------------------------------
    # Validation: platform compatibility [PLATFORM_COMPAT]
    # ------------------------------------------------------------------
    @staticmethod
    def _check_platform_blocklist(dependencies: list[str]) -> str | None:
        """检查依赖是否包含 Windows 上已知不兼容的包.

        Returns:
            被拦截的依赖名 (如有), 或 None.
        """
        for dep_spec in dependencies:
            pkg_name = re.split(r"[><=!~\[]", dep_spec)[0].strip().lower()
            if pkg_name in _PLATFORM_BLOCKLIST:
                return pkg_name
        return None

    # ------------------------------------------------------------------
    # Validation: deep dependency auth scan [ZERO_AUTH]
    # ------------------------------------------------------------------
    def _scan_deps_for_auth(self, dependencies: list[str]) -> str | None:
        """深层扫描: 检查每个依赖库的 PyPI 描述/主页是否含强鉴权关键词.

        Returns:
            被标记的依赖名 (如有), 或 None (全部安全).
        """
        for dep_spec in dependencies:
            # 提取包名 (去掉版本约束)
            pkg_name = re.split(r"[><=!~\[]", dep_spec)[0].strip()
            if not pkg_name or pkg_name.lower() == "pytest":
                continue

            try:
                with httpx.Client(timeout=15) as client:
                    r = client.get(f"{_PYPI_API}/{pkg_name}/json")
                    if r.status_code != 200:
                        logger.debug(
                            "  PyPI lookup failed for '%s' (HTTP %d)",
                            pkg_name,
                            r.status_code,
                        )
                        continue

                    data = r.json()
                    info = data.get("info", {})

                    # 拼接可检索文本: 摘要 + 描述 + 主页 + 关键词
                    searchable = " ".join(
                        [
                            info.get("summary", "") or "",
                            (info.get("description", "") or "")[:2000],
                            info.get("home_page", "") or "",
                            " ".join(info.get("keywords", "") or []),
                        ]
                    ).lower()

                    for kw in _DEEP_AUTH_KEYWORDS:
                        if kw in searchable:
                            logger.debug(
                                "  [ZERO_AUTH_DEEP] '%s' PyPI 描述含关键词 '%s'",
                                pkg_name,
                                kw,
                            )
                            return pkg_name

            except httpx.HTTPError as exc:
                logger.debug("  PyPI scan error for '%s': %s", pkg_name, exc)
                continue

        return None

    # ------------------------------------------------------------------
    # Validation: GitHub dedup [NO_REPO_CLONE]
    # ------------------------------------------------------------------
    def _is_duplicate_on_github(self, name: str) -> bool:
        """在 GitHub 上查重, 若存在 Stars > 100 的精确同名项目则视为重复.

        使用精确名称匹配 (in:name) 避免模糊搜索误判.
        """
        try:
            with httpx.Client(timeout=30) as client:
                # 使用精确名称匹配, 而非模糊搜索
                r = client.get(
                    f"{_GITHUB_API}/search/repositories",
                    headers=self._gh_headers,
                    params={
                        "q": f'"{name}" in:name',
                        "sort": "stars",
                        "per_page": 5,
                    },
                )
                r.raise_for_status()
                items = r.json().get("items", [])
                for repo in items:
                    repo_name = repo.get("name", "").lower()
                    # 要求仓库名称与候选名高度匹配 (包含关系)
                    if (
                        name.lower() in repo_name or repo_name in name.lower()
                    ) and repo.get("stargazers_count", 0) > 100:
                        logger.info(
                            "  GitHub duplicate: %s (%d stars)",
                            repo["full_name"],
                            repo["stargazers_count"],
                        )
                        return True
        except httpx.HTTPError as exc:
            logger.warning("GitHub API error (non-fatal): %s", exc)
        return False

    # ------------------------------------------------------------------
    # Market Gap Scoring [DATA_DRIVEN]
    # ------------------------------------------------------------------
    def _compute_market_gap_score(
        self, name: str, candidate: dict[str, Any]
    ) -> MarketGapScore:
        """计算市场缺口评分 (0-100).

        三个维度:
        1. 竞争热度 (0-40): GitHub 搜索结果数越少 -> 分越高 (蓝海)
        2. 需求强度 (0-40): 相关仓库的 Issue/Star 活跃度 -> 有需求但供给不足
        3. 新颖度   (0-20): 精确匹配少 -> 概念新颖
        """
        score = MarketGapScore()
        parts = []

        try:
            with httpx.Client(timeout=30) as client:
                # --- 竞争热度: 按名称搜索仓库总数 ---
                r = client.get(
                    f"{_GITHUB_API}/search/repositories",
                    headers=self._gh_headers,
                    params={"q": name, "sort": "stars", "per_page": 5},
                )
                r.raise_for_status()
                search_data = r.json()
                total_count = search_data.get("total_count", 0)
                items = search_data.get("items", [])

                # 竞争越少分越高: 0结果=40分, 100+结果=5分
                if total_count == 0:
                    score.competition_score = 40.0
                elif total_count <= 5:
                    score.competition_score = 35.0
                elif total_count <= 20:
                    score.competition_score = 28.0
                elif total_count <= 50:
                    score.competition_score = 20.0
                elif total_count <= 100:
                    score.competition_score = 12.0
                else:
                    score.competition_score = 5.0
                parts.append(f"竞争:{score.competition_score:.0f}(共{total_count}结果)")

                # --- 需求强度: 检查相关仓库的 open issues 和 stars ---
                total_open_issues = 0
                avg_stars = 0.0
                if items:
                    total_open_issues = sum(
                        r.get("open_issues_count", 0) for r in items[:5]
                    )
                    avg_stars = sum(
                        r.get("stargazers_count", 0) for r in items[:5]
                    ) / len(items[:5])

                # Issue 多 = 需求明确但未被满足; star 适中 = 有关注但不饱和
                issue_factor = min(total_open_issues / 50.0, 1.0) * 20.0
                # star 在 10-500 之间最佳 (有关注但不过度成熟)
                if avg_stars < 10:
                    star_factor = 8.0  # 太冷门
                elif avg_stars <= 500:
                    star_factor = 20.0  # 甜蜜区
                elif avg_stars <= 2000:
                    star_factor = 12.0  # 有点拥挤
                else:
                    star_factor = 5.0  # 已饱和
                score.demand_score = issue_factor + star_factor
                parts.append(
                    f"需求:{score.demand_score:.0f}"
                    f"(issues:{total_open_issues},avg_stars:{avg_stars:.0f})"
                )

                # --- 新颖度: 精确匹配名称的仓库数 ---
                r2 = client.get(
                    f"{_GITHUB_API}/search/repositories",
                    headers=self._gh_headers,
                    params={
                        "q": f'"{name}" in:name',
                        "sort": "stars",
                        "per_page": 5,
                    },
                )
                r2.raise_for_status()
                exact_count = r2.json().get("total_count", 0)
                if exact_count == 0:
                    score.novelty_score = 20.0
                elif exact_count <= 3:
                    score.novelty_score = 15.0
                elif exact_count <= 10:
                    score.novelty_score = 10.0
                else:
                    score.novelty_score = 3.0
                parts.append(f"新颖:{score.novelty_score:.0f}(精确{exact_count}个)")

        except httpx.HTTPError as exc:
            logger.warning("市场评分 GitHub API 异常 (非致命): %s", exc)
            # 降级: 给一个中等默认分
            score.competition_score = 20.0
            score.demand_score = 20.0
            score.novelty_score = 10.0
            parts.append("(API异常,使用默认分)")

        score.compute_total()
        score.breakdown = " | ".join(parts)
        return score
