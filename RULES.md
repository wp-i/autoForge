[NO_REPO_CLONE] 独特性： 必须调用搜索工具/GitHub API，使用精确名称匹配 (`"name" in:name`) 查重。若目标目录下已有同名项目，或 GitHub 已有高相似度成熟项目（Stars>100 且名称高度匹配），立即重选。禁止模糊搜索误判。
[MCP_NATIVE] MCP 适配： 最终交付物必须包含 mcp-server 封装（含 inputSchema），确保 openClaw 点击即用。mcp_server.py 优先使用 `from src.core import ...` 导入路径。
[ZERO_AUTH] 零授权： 严禁生成需扫码、登录、Cookie 或 API Key 的子项目。执行双层扫描：浅层文本关键词 + 深层 PyPI 元数据鉴权关键词检测。
[DATA_DRIVEN] 数据决策： 立项依据必须来自公开客观数据（如：库的下载量趋势、缺失的 MCP 插件类型）。使用三维市场缺口评分模型（竞争热度+需求强度+新颖度）量化排序。
[ZERO_INTERVENT] 零干预： 从 mkdir 到交付，禁止 stdin 输入，禁止中断请求。
[SELF_HEAL_TDD] 自愈开发： 必须遵循"测试驱动"。若测试失败，捕获报错并重新分析逻辑，修正或更换实现路径。含环境自愈（自动安装缺失 pytest 插件）和退化保护（通过率>=90%时禁止 NUKE/RETHINK）。
[NEAR_SUCCESS_GUARD] 退化保护： 当测试通过率 >= 90% 时，强制使用精细化 PATCH 修复，禁止 NUKE（清空重写）和 RETHINK（更换策略），防止推倒接近成功的代码导致退化和 Token 浪费。
[FRESH_DATA] 数据保鲜： 必须检索并锁定依赖库的当前最新稳定版本。
[ENV_ISOLATION] 环境隔离： 所有子项目必须在独立的 venv 或隔离目录下构建，不得污染 AutoForge 运行环境。
[NO_API_LIMIT] 运行零成本： 子项目逻辑必须完全本地化或基于免费公开接口，确保用户运行子项目无需付费。
[COMPLEXITY_MIN] 复杂度下限： 拒绝简单的 Demo，项目必须具备解决 1 个以上具体痛点的逻辑闭环。
[LINT_CLEAN] 静态合规： 交付前必须通过静态代码检查（如 Ruff/ESLint），确保代码风格标准。
[PLATFORM_AWARE] 平台感知： 测试生成和代码生成必须感知当前运行平台（Windows/Linux/Mac），避免生成平台不兼容的系统调用（如 Windows 上的 symlink 需管理员权限）。
[STDLIB_FILTER] 标准库过滤： LLM 生成代码中的 `# NEW_DEP:` 标注必须经过标准库过滤，避免对 `filecmp`、`collections`、`itertools` 等内置模块执行无效的 `pip install`。
[UTF8_SAFE] 编码安全： 所有文件读写操作必须显式指定 `encoding='utf-8'`。Windows 控制台输出强制 UTF-8，避免 GBK 编码导致中文乱码。
