# AutoForge 工程实现指南 (Technical Specification)

## 1. 系统愿景
AutoForge 是一个全自动的“项目工厂”。它根据 `RULES.md` 独立发现需求、编写代码、进行 TDD 闭环自测，并最终交付支持 MCP 协议的本地工具。

## 2. 核心架构模块 (Core Modules)

### A. Strategist (立项官) - `engine/strategist.py`
- **任务**：执行需求发现。利用 Search Tool 寻找 GitHub 痛点或现有 CLI 工具的 MCP 化缺口。
- **决策逻辑**：
    - 验证 [DATA_DRIVEN]：检索客观数据（Star、下载量）。
    - 验证 [ZERO_AUTH]：通过关键词过滤，排除需要 API Key 的项目。
    - 验证 [NO_REPO_CLONE]：通过 GitHub API 进行查重评分。
- **输出**：一个包含项目名、核心功能点、依赖库清单的 `spec.json`。

### B. Architect (架构师) - `engine/architect.py`
- **任务**：执行环境初始化。
- **动作**：
    - 在 `./output/` 下创建隔离目录 [ENV_ISOLATION]。
    - 自动生成 `requirements.txt` 或 `package.json` 并锁定版本 [FRESH_DATA]。
    - 初始化基础文件结构：`src/`, `tests/`, `mcp_server.py`, `README.md`。

### C. Coder (代码与自愈单元) - `engine/coder.py`
- **任务**：执行 [SELF_HEAL_TDD] 闭环开发。
- **工作流 (Loop)**：
    1. 根据 `spec.json` 编写测试用例 `tests/test_core.py`。
    2. 编写核心功能逻辑 `src/core.py`。
    3. 执行测试：调用子进程运行 `pytest`。
    4. **错误捕获**：若测试失败，将 Stdout/Stderr 传回 LLM 进行根因分析。
    5. **重构路径**：若连续 3 次原地修复无效，强制 LLM 更改实现算法或更换第三方库。
    6. 判定：直到测试 100% 通过或达到 `Max_Retries` 上限。

### D. MCP Wrapper (协议封装) - `engine/mcp_wrapper.py`
- **任务**：自动化协议适配 [MCP_NATIVE]。
- **动作**：解析 `src/core.py` 中的函数签名，自动生成标准的 MCP `Tools` 注册代码，确保 `openClaw` 可直接调用。

## 3. 状态机流程 (Main Dispatcher)
1. **Init**: 加载 `RULES.md` 和环境变量。
2. **Phase 1 (Insight)**: 调用 Strategist 产出项目方案。
3. **Phase 2 (Scaffold)**: 调用 Architect 创建物理目录。
4. **Phase 3 (Develop)**: 调用 Coder 进入“编码-测试-修复”循环。
5. **Phase 4 (Wrap)**: 调用 MCP Wrapper 完成协议包装。
6. **Phase 5 (Audit)**: 执行最终 Lint 检查 [LINT_CLEAN]。
7. **Phase 6 (Done)**: 将项目移动到交付区，生成运行日志。

## 4. 关键技术约束 (Engineering Constraints)
- **子进程安全**：所有执行动作（pip install, pytest）必须通过受限的 subprocess 调用，并记录所有日志。
- **配置驱动**：重试次数、输出路径、偏好语言必须在根目录 `config.yaml` 中可配置。
- **日志追踪**：每个生成的子项目文件夹内必须包含一个 `autoforge.log`，记录其“诞生过程”中的所有决策和修复历史。

## 5. 初始任务 (Bootstrap Task)
请 Claude 首先实现 `main.py` 骨架及 `engine/coder.py` 的自愈循环逻辑，这是 AutoForge 最核心的资产。