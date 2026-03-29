<div align="center">

<img src="https://img.shields.io/badge/AutoForge-全自动项目工厂-blue?style=for-the-badge&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIzMiIgdmlld0JveD0iMCAwIDI0IDI0Ij48cGF0aCBmaWxsPSJ3aGl0ZSIgZD0iTTEyIDJDNi40OCAyIDIgNi40OCAyIDEyczQuNDggMTAgMTAgMTAgMTAtNC40OCAxMC0xMFMxNy41MiAyIDEyIDJ6bS0xIDE0LjVsLTQtNCAxLjQxLTEuNDFMMTEgMTQuMTdsNi41OS02LjU5TDE5IDlsLTggOHoiLz48L3N2Zz4=" />

# AutoForge

**从需求发现到 MCP 工具交付，全程零干预的全自动项目工厂**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-orange?style=flat-square)](https://docs.astral.sh/ruff/)
[![Status: Active](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)](https://github.com/wp-i/autoForge)

[功能亮点](#-功能亮点) · [架构设计](#-架构设计) · [快速开始](#-快速开始) · [子项目示例](#-子项目示例-syncsweep) · [配置说明](#️-配置说明)

</div>

---

## 🏭 这是什么？

AutoForge 是一个**全自动项目工厂**。你只需一行命令：

```bash
python main.py
```

它就会**自主完成**从立项到交付的完整开发流程：

1. **Strategist** — 分析 GitHub 生态，数据驱动发现市场缺口
2. **Architect** — 自动搭建项目骨架、隔离环境、MCP 配置
3. **Coder** — TDD 自愈循环：测试 → 失败 → LLM 分析 → 自动修复 → 重测
4. **MCPWrapper** — 自动生成 MCP 协议适配层，可直接挂载到 Claude Desktop
5. **Auditor** — Ruff 静态审计，确保代码质量

**全程零人工干预。** 最终产出一个独立的、即插即用的 MCP 工具。

---

## ✨ 功能亮点

<table>
<tr>
<td width="50%">

### 🧠 数据驱动立项

- 自动扫描 GitHub 生态痛点
- 三轴市场缺口评分（竞争度/需求度/新颖度）
- GitHub 查重：避免重复造轮子
- PyPI 深度鉴权扫描：确保零 API Key 依赖

</td>
<td width="50%">

### 🔧 TDD 自愈循环

- LLM 自动生成测试用例 + 功能代码
- pytest 失败 → 自动喂回错误输出 → LLM 根因分析 → 修复
- **三级自愈策略**：PATCH → RETHINK（换算法）→ NUKE（范式重写）
- 智能死循环逃逸：连续卡死自动升级策略

</td>
</tr>
<tr>
<td width="50%">

### 📦 MCP 原生交付

- 自动解析函数签名生成 MCP Server
- 标准 `inputSchema` JSON Schema 定义
- 生成 Claude Desktop 兼容的 `mcp_config.json`
- `python mcp_server.py` 即可启动

</td>
<td width="50%">

### 🛡️ 全面安全防护

- `[ZERO_AUTH]` 禁止生成需 API Key 的项目
- `[PLATFORM_COMPAT]` 自动过滤 Windows 不兼容依赖
- Token 熔断保护：防止 LLM 调用失控
- 环境隔离：每个子项目独立 venv

</td>
</tr>
</table>

---

## 🏗️ 架构设计

```
                    python main.py
                         │
                         ▼
    ┌────────────────────────────────────────┐
    │           AutoForge State Machine      │
    │                                        │
    │   Phase 1 ──→ Phase 2 ──→ Phase 3     │
    │  Strategist  Architect    Coder        │
    │  需求发现     脚手架      TDD自愈 ⭐    │
    │                                        │
    │   Phase 4 ──→ Phase 5 ──→ Phase 6     │
    │  MCPWrapper  Auditor     Done          │
    │  协议封装     审计       归档交付       │
    └────────────────────────────────────────┘
                         │
                         ▼
              delivered/<ProjectName>/
              ├── src/core.py           # 核心逻辑
              ├── tests/test_core.py    # 测试套件
              ├── mcp_server.py         # MCP 服务器
              ├── mcp_config.json       # Claude Desktop 配置
              ├── .venv/                # 隔离环境
              └── ...
```

### Coder 自愈循环（核心资产）

```
 测试通过？──→ ✅ 完成，进入下一阶段
     │
     ❌ 失败
     │
     ├─ 环境故障？──→ 自动安装缺失插件（免费重试）
     │
     ├─ 同一函数卡 5+ 次？──→ STUCK_ESCAPE: 强制 RETHINK
     │
     ├─ 连续 PATCH 3 次无效？──→ RETHINK（换算法/第三方库）
     │
     ├─ 单函数卡 3+ 次？──→ NUKE（清空重写，全新路径）
     │
     └─ 达到 MAX_RETRIES？──→ GIVE_UP
```

---

## 🚀 快速开始

### 环境要求

- Python 3.12+
- 支持 OpenAI Chat Completions 格式的 LLM API

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/wp-i/autoForge.git
cd autoForge

# 安装依赖
pip install -r requirements.txt

# 配置 API Key（创建 .env 文件）
# Linux / Mac
cat > .env << 'EOF'
AUTOFORGE_LLM_API_KEY=your_api_key_here
AUTOFORGE_LLM_BASE_URL=https://api.deepseek.com
AUTOFORGE_MODEL_NAME=deepseek-chat
GITHUB_TOKEN=your_github_token_here  # 可选
EOF

# Windows
echo AUTOFORGE_LLM_API_KEY=your_api_key_here> .env
echo AUTOFORGE_LLM_BASE_URL=https://api.deepseek.com>> .env
echo AUTOFORGE_MODEL_NAME=deepseek-chat>> .env

# 启动！
python main.py
```

**就这么简单。** AutoForge 会在 `output/` 中构建项目，成功后自动交付到 `delivered/`。

---

## 🔬 子项目示例：SyncSweep

以下是 AutoForge 自动生成的 MCP 工具之一：

> **SyncSweep** — 专为同步文件夹（Dropbox/OneDrive）设计的重复文件清理工具

| 指标 | 数据 |
|------|------|
| 市场缺口评分 | **68.0** / 100 |
| 测试覆盖 | **26/26 PASSED** |
| 自愈轮次 | 8 |
| Token 消耗 | 97,361 |
| 生成时间 | ~18 分钟 |

SyncSweep 提供 4 个 MCP Tool，可直接挂载到 Claude Desktop：

| Tool | 功能 |
|------|------|
| `compare_files` | 比较两个文件的哈希、大小和修改时间 |
| `find_duplicate_chains` | 扫描多个文件夹，找出重复文件链 |
| `detect_sync_conflicts` | 检测同步冲突（基于修改时间差异） |
| `generate_sync_report` | 生成清理报告（含可视化图表和 CSV） |

```bash
# 运行 SyncSweep 测试
cd delivered/SyncSweep
setup_env.bat                    # 一键部署（Windows）
.venv\Scripts\pytest.exe tests -v
```

> 📖 子项目的完整说明见 [delivered/SyncSweep/README.md](delivered/SyncSweep/README.md)

---

## ⚙️ 配置说明

`config.yaml` 关键参数：

```yaml
# 自愈循环控制
max_retries: 8                  # 单轮最大重试次数
force_rethink_after: 3          # 连续 PATCH 无效后强制 RETHINK
test_timeout_seconds: 120       # 单次 pytest 超时

# Token 熔断保护
max_token_per_project: 200000   # 单项目 Token 上限

# LLM 参数
llm:
  temperature: 0.3              # 代码生成偏保守
  max_tokens: 8192
```

`.env` 环境变量：

| 变量 | 必需 | 说明 |
|------|------|------|
| `AUTOFORGE_LLM_API_KEY` | ✅ | LLM API Key |
| `AUTOFORGE_LLM_BASE_URL` | ✅ | API 端点 |
| `AUTOFORGE_MODEL_NAME` | ✅ | 模型名称 |
| `GITHUB_TOKEN` | ❌ | GitHub Token（查重加速） |

---

## 📋 工程约束规则

AutoForge 内置 15 条工程规则，通过 `RULES.md` 定义：

| 规则 | 说明 |
|------|------|
| `[SELF_HEAL_TDD]` | 测试驱动，失败后自动分析修复 |
| `[ZERO_INTERVENT]` | 全程零人工干预 |
| `[MCP_NATIVE]` | 交付物必须包含 MCP Server |
| `[ZERO_AUTH]` | 禁止生成需 API Key 的项目 |
| `[NO_REPO_CLONE]` | GitHub 查重，避免重复造轮子 |
| `[DATA_DRIVEN]` | 立项依据来自 GitHub/PyPI 客观数据 |
| `[ENV_ISOLATION]` | 子项目独立 venv |
| `[LINT_CLEAN]` | 交付前通过 Ruff 静态审计 |
| `[NEAR_SUCCESS_GUARD]` | 通过率 ≥90% 时禁止 NUKE/RETHINK |
| `[STUCK_ESCAPE]` | 单函数卡死 5+ 次时允许升级策略 |

---

## 🧪 已验证的场景

| 场景 | 领域 | 关键发现 |
|------|------|----------|
| SyncSweep | 本地文件系统重复文件清理 | 26 测试全通过，4 个 MCP Tool |

---

## 📂 项目结构

```
autoForge/
├── main.py                    # 状态机入口
├── config.yaml                # 运行配置
├── RULES.md                   # 工程约束规则
├── engine/
│   ├── strategist.py          # Phase 1: 需求发现 + 市场评分
│   ├── architect.py           # Phase 2: 脚手架 + venv + MCP 配置
│   ├── coder.py               # Phase 3: TDD 自愈循环 ⭐ 核心资产
│   ├── mcp_wrapper.py         # Phase 4: MCP 协议封装
│   ├── auditor.py             # Phase 5: Ruff 静态审计
│   ├── llm_client.py          # LLM 调用层 + Token 熔断
│   └── logger.py              # 双路日志（控制台 + 文件）
├── output/                    # 构建目录（git ignored）
├── delivered/                 # 最终交付归档
└── .env                       # API Keys（git ignored）
```

---

## 🛣️ 路线图

- [ ] 支持多语言项目（JS/TS, Rust, Go）
- [ ] 并行锻造：同时生成多个子项目
- [ ] 子项目级 pytest 覆盖率报告
- [ ] Web Dashboard：实时监控锻造状态
- [ ] 子项目回滚/Checkpoint 机制

---

## 🤝 贡献

欢迎参与！请参阅 [贡献指南](#)。

```bash
git checkout -b feature/your-idea
git commit -m "feat: your idea"
git push origin feature/your-idea
# 然后提交 Pull Request
```

---

## 📄 许可证

[MIT](LICENSE) © 2026 AutoForge Team

---

<div align="center">

**[⬆ 返回顶部](#autoforge)**

如果觉得有用，请给个 ⭐ Star！

</div>
