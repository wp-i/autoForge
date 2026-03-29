# AutoForge 工程实现指南 (Technical Specification)

## 1. 系统愿景
AutoForge 是一个全自动的"项目工厂"。它根据 `RULES.md` 独立发现需求、编写代码、进行 TDD 闭环自测，并最终交付支持 MCP 协议的本地工具。

## 2. 核心架构模块 (Core Modules)

### A. Strategist (立项官) - `engine/strategist.py`
- **任务**：执行需求发现。利用 Search Tool 寻找 GitHub 痛点或现有 CLI 工具的 MCP 化缺口。
- **决策逻辑**：
    - 验证 [DATA_DRIVEN]：检索客观数据（Star、下载量）。
    - 验证 [ZERO_AUTH]：通过关键词过滤，排除需要 API Key 的项目。浅层扫描文本关键词，深层扫描 PyPI 元数据。
    - 验证 [NO_REPO_CLONE]：通过 GitHub API 进行**精确名称匹配**查重（使用 `"name" in:name` 查询，要求仓库名与候选名高度匹配，避免模糊搜索误判）。
    - **市场缺口评分**：三维量化模型（竞争热度 0-40 + 需求强度 0-40 + 新颖度 0-20），选分最高方案。
- **输出**：一个包含项目名、核心功能点、依赖库清单、市场缺口评分的 `spec.json`。
- **已知修复**：
    - PyPI 元数据中 `home_page` 字段可能为 `None`，已加 `or ""` 防护 (`strategist.py:265`)。
    - GitHub 查重从模糊搜索改为精确名称匹配，避免无关高星项目误判 (`strategist.py:289`)。

### B. Architect (架构师) - `engine/architect.py`
- **任务**：执行环境初始化。
- **动作**：
    - 在 `./output/` 下创建隔离目录 [ENV_ISOLATION]。
    - 自动生成 `requirements.txt` 并锁定版本 [FRESH_DATA]。
    - 初始化基础文件结构：`src/`, `tests/`, `mcp_server.py`, `README.md`。
    - 生成 `mcp_config.json` 模板（Claude Desktop 兼容格式）[MCP_NATIVE]。
    - 生成环境自愈脚本 `setup_env.sh` / `setup_env.bat`。

### C. Coder (代码与自愈单元) - `engine/coder.py`
- **任务**：执行 [SELF_HEAL_TDD] 闭环开发。
- **工作流 (Loop)**：
    1. 根据 `spec.json` 编写测试用例 `tests/test_core.py`。
    2. 编写核心功能逻辑 `src/core.py`。
    3. 执行测试：调用子进程运行 `pytest`。
    4. **环境自愈**：检测缺失的 pytest 插件（如 `mocker` -> `pytest-mock`），自动安装后重测，不计入重试次数。
    5. **错误捕获**：若测试失败，将 Stdout/Stderr 传回 LLM 进行根因分析。
    6. **退化保护 [NEAR_SUCCESS_GUARD]**：当通过率 >= 90% 时，强制使用 PATCH，禁止 NUKE/RETHINK，避免推倒接近成功的代码导致退化和 Token 浪费。
    7. **重构路径**：若连续 3 次原地修复无效**且通过率 < 90%**，强制 LLM 更改实现算法或更换第三方库 (RETHINK)。
    8. **范式级自愈 (NUKE)**：若同一测试函数单点修复超 3 次仍失败**且通过率 < 90%**，清空 `src/core.py` 从零重写。
    9. 判定：直到测试 100% 通过或达到 `Max_Retries` 上限。
- **依赖管理**：
    - 扫描 LLM 生成代码中的 `# NEW_DEP: lib>=x.y` 注释。
    - **自动过滤标准库**（如 `filecmp`, `collections`, `itertools`），避免无效 `pip install`。
    - **清洗注释格式**（如 `lib>=1.0 (用于xxx)` -> `lib>=1.0`）。
- **平台感知**：
    - 测试生成 prompt 包含当前平台信息（Windows/Linux），避免生成平台特定的系统调用。
    - 禁止使用 `pytest-mock`（mocker fixture），统一使用 `unittest.mock`。
- **代码质量提示**：
    - LLM prompt 中包含 `is not` vs `!=` 的提示，避免重复文件等场景中因 `__eq__` 覆盖导致的对象身份比较错误。

### D. MCP Wrapper (协议封装) - `engine/mcp_wrapper.py`
- **任务**：自动化协议适配 [MCP_NATIVE]。
- **动作**：解析 `src/core.py` 中的函数签名，自动生成标准的 MCP `Tools` 注册代码，确保 `openClaw` 可直接调用。
- **MCP dry-run 验证**：
    - 语法检查使用显式 UTF-8 编码（`open(..., encoding='utf-8')`），兼容 Windows GBK 环境。
    - 验证 tools 定义结构（tool_def、name、inputSchema）。

### E. Auditor (审计员) - `engine/auditor.py`
- **任务**：执行最终 Lint 检查 [LINT_CLEAN]。
- **动作**：先 `ruff check --fix` 自动修复，再 `ruff check` 最终验证。

## 3. 状态机流程 (Main Dispatcher)
1. **Init**: 加载 `RULES.md`、`config.yaml` 和环境变量。
2. **Phase 1 (Insight)**: 调用 Strategist 产出项目方案（含市场缺口评分 + 深度鉴权扫描）。
3. **Phase 2 (Scaffold)**: 调用 Architect 创建物理目录（含 MCP 配置模板 + 环境自愈脚本）。
4. **Phase 3 (Develop)**: 调用 Coder 进入"编码-测试-修复"循环（含范式级 NUKE 重写 + MCP dry-run + 退化保护）。
5. **Phase 4 (Wrap)**: 调用 MCP Wrapper 完成协议包装。
6. **Phase 5 (Audit)**: 执行最终 Lint 检查 [LINT_CLEAN]。
7. **Phase 6 (Done)**: 将项目移动到交付区，生成运行日志，更新工厂看板。

## 4. 关键技术约束 (Engineering Constraints)
- **子进程安全**：所有执行动作（pip install, pytest）必须通过受限的 subprocess 调用，并记录所有日志。
- **配置驱动**：重试次数、输出路径、偏好语言、Token 熔断上限必须在根目录 `config.yaml` 中可配置。
- **日志追踪**：每个生成的子项目文件夹内必须包含一个 `autoforge.log`，记录其"诞生过程"中的所有决策和修复历史。
- **Windows 兼容**：控制台日志强制 UTF-8 输出，所有文件操作显式指定 `encoding='utf-8'`。
- **Token 熔断**：单项目 Token 消耗超过 `max_token_per_project` 时强制终止锻造。

## 5. 自愈循环策略矩阵 (Heal Strategy Matrix)

| 条件 | 动作 | 说明 |
|------|------|------|
| `attempt >= max_retries - 1` | GIVE_UP | 达到重试上限 |
| `pass_rate >= 90%` | PATCH (强制) | **[NEAR_SUCCESS_GUARD]** 退化保护 |
| 单函数失败 >= 3 次且未 NUKE 过 | NUKE | 范式级重写 |
| 连续 PATCH >= `force_rethink_after` | RETHINK | 更换算法/库 |
| 默认 | PATCH | 基于错误修复 |

## 6. 环境自愈清单 (Environment Self-Healing)

| 检测模式 | 自动修复 | 计入重试 |
|----------|----------|----------|
| `fixture 'mocker' not found` | `pip install pytest-mock` | 否 |
| `fixture 'requests_mock' not found` | `pip install requests-mock` | 否 |
| `fixture 'httpx_mock' not found` | `pip install pytest-httpx` | 否 |
| `# NEW_DEP: stdlib_module` | 自动跳过（标准库过滤） | N/A |
| `# NEW_DEP: lib>=1.0 (注释)` | 自动清洗括号注释 | N/A |

## 7. 初始任务 (Bootstrap Task)
请 Claude 首先实现 `main.py` 骨架及 `engine/coder.py` 的自愈循环逻辑，这是 AutoForge 最核心的资产。
