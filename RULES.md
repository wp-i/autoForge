[NO_REPO_CLONE] 独特性： 必须调用搜索工具/GitHub API。若目标目录下已有同名项目，或 GitHub 已有高相似度成熟项目，立即重选。
[MCP_NATIVE] MCP 适配： 最终交付物必须包含 mcp-server 封装，确保 openClaw 点击即用。
[ZERO_AUTH] 零授权： 严禁生成需扫码、登录、Cookie 或 API Key 的子项目。
[DATA_DRIVEN] 数据决策： 立项依据必须来自公开客观数据（如：库的下载量趋势、缺失的 MCP 插件类型）。
[ZERO_INTERVENT] 零干预： 从 mkdir 到交付，禁止 stdin 输入，禁止中断请求。
[SELF_HEAL_TDD] 自愈开发： 必须遵循“测试驱动”。若测试失败，捕获报错并重新分析逻辑，修正或更换实现路径。
[FRESH_DATA] 数据保鲜： 必须检索并锁定依赖库的当前最新稳定版本。
[ENV_ISOLATION] 环境隔离： 所有子项目必须在独立的 venv 或隔离目录下构建，不得污染 AutoForge 运行环境。
[NO_API_LIMIT] 运行零成本： 子项目逻辑必须完全本地化或基于免费公开接口，确保用户运行子项目无需付费。
[COMPLEXITY_MIN] 复杂度下限： 拒绝简单的 Demo，项目必须具备解决 1 个以上具体痛点的逻辑闭环。
[LINT_CLEAN] 静态合规： 交付前必须通过静态代码检查（如 Ruff/ESLint），确保代码风格标准。