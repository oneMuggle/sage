# 12 · 本地开发环境助手

> 在 Settings → **开发环境** Tab 里，一键看到本机可用的 Python / Node.js 运行时，
> 诊断当前项目的运行时是否齐备，并能"试跑"一段代码验证运行时真实可用。

---

## 1. 什么时候用

- 刚装好 Python / Node.js，不确定 PATH 是否配置正确
- 工作区换了新项目，想知道需要哪些运行时、是否都装好了
- 想用某个具体解释器（比如 conda 环境里的 Python）跑一段快速测试
- 怀疑某个工具（npm / pnpm / yarn / bun）没装或版本不对

---

## 2. 打开方式

1. 点击窗口右上角的 **⚙ 设置** 图标
2. 在左侧 Tab 列表找到 **开发环境**（位于"MCP"和"演化"之间）
3. 进入 Tab 后会自动执行一次 **探测** 和 **诊断**，无需手动点击

---

## 3. 三个区块

### 3.1 本机运行时（自动探测）

Tab 一打开就会自动扫描本机：
- Python：系统 Python、所有 conda 环境、当前目录的 venv
- Node.js：PATH 上的 node + npm / pnpm / yarn / bun 工具链

显示内容：
- 每个运行时按语言分组
- **推荐**的运行时（通常是系统默认或最高兼容版本）带蓝色"推荐"徽章
- 版本号、路径、发现来源（system / conda / venv）

**只读操作**：不会执行任何命令，不会改动你的环境。

点击右上 **重试** 按钮可以再次探测。

### 3.2 项目诊断

根据工作区里的文件（`package.json`、`pyproject.toml`、`requirements.txt` 等）
推断项目类型，比对需要的运行时是否在"本机运行时"里都齐备。

显示内容：
- **项目类型**（如 `python-node`、`python-only`、`unknown`）
- **满足度**：✓ 全部满足 / ⚠ 需要处理
- 需要处理时，下方列出诊断条目，每条带：
  - 严重度徽章：`INFO` / `WARN` / `ERROR`
  - 诊断代码（如 `PYTHON_NOT_FOUND`）
  - 说明文字 + 修复提示

**示例**：
- ⚠ `NODE_NOT_FOUND` — "工作区需要 Node.js，但未发现任何 Node 运行时" → "安装 Node.js：https://nodejs.org/"
- ⚠ `PYTHON_VERSION_OLD` — "发现 Python 3.8，但项目要求 >=3.10" → "安装更高版本的 Python 或在 venv 里使用 3.10+"

### 3.3 试跑代码片段

从上方的探测结果里选一个运行时，粘贴一段代码，点 **执行** 验证它真的能跑。

操作步骤：
1. **运行时** 下拉框里选择一个运行时（默认选推荐项）
2. 在 **代码文本框** 里输入要执行的代码（默认是一段 Python "hello" 示例）
3. 点 **执行** 按钮

**权限闸口**：
- 执行操作需要用户批准，与 Bash 工具使用同样的审批弹窗
- 批准前不会执行；拒绝后显示 "权限被拒绝" 的琥珀色提示
- 执行成功后显示 stdout / stderr / 退出码 / 耗时

**失败显示**：
- 🔴 红色块：执行失败（非零退出码 / 异常）
- 🟡 琥珀色块：权限被拒绝
- 输出区分 stdout（白底）和 stderr（红底）

---

## 4. 常见问题

### Q: 探测结果里没有我的 conda 环境？

A: 确认 `conda` 命令在你的 PATH 上（`conda info --base` 应该能输出路径）。
如果 `conda env list` 显示的环境不在探测结果里，是 conda 命令报错，
看"本机运行时"底部的"警告"行会列出具体错误。

### Q: 推荐运行时不是我想要的那个？

A: 推荐规则是：is_default 标记最高的运行时 → 否则第一个能执行的运行时 →
否则列表第一个。如果你偏好特定的，可以在"试跑代码"的下拉框里手动切换。

### Q: 项目诊断显示"需要处理"，我该怎么修？

A: 看每条诊断下面的 `fix_hint`（蓝色小字），里面是给定的修复提示。
典型修复：
- `PYTHON_NOT_FOUND` → 安装 Python 3.10+
- `NODE_NOT_FOUND` → 安装 Node.js（推荐 LTS）
- `PYTHON_VERSION_OLD` → 升级 Python，或创建 venv 指向更高版本

### Q: 试跑时报权限错误？

A: `runtime_exec` 与 Bash 工具使用同样的 PermissionEnforcer，默认需要用户批准。
弹窗出现时点"批准"即可；若之前设过"总是拒绝"，去设置里的权限面板重置。

### Q: 我想探测远程机器 / Docker 里的运行时？

A: 当前版本（v1）仅支持本机探测。远程 / Docker / WSL 内部探测在后续版本计划中。

---

## 5. 与 LLM Agent 的关系

你在 Chat 里让 LLM "帮我看看本机有哪些 Python" 时，LLM 会调用
`runtime_probe` 工具（与你刚在设置里点的那次探测是同一个后端端点）。
Chat 流里会渲染为 **"Probe python, javascript"** 这样的友好标题。

同理，"帮我诊断一下这个项目" → `project_diagnose`（"Diagnose /path/to/project"）。

`runtime_exec` 在 Chat 里渲染为 "Run in python" `scope: local`，
并且会触发权限审批——与你手动在 Tab 里点执行走的是同一条审批闸口。
