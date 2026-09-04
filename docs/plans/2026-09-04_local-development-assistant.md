# Sage 本地开发环境与代码运行助手实施计划

## 1. 背景与目标

Sage 当前已经具备代码探索、文件编辑、REPL 和 Bash 工具，但这些能力缺少统一的“本地开发环境”抽象：用户无法让 Sage 可靠地发现本机有哪些可用运行时、判断当前项目的工具链与依赖是否满足，并在明确授权后使用合适的本地运行时验证代码。

本功能将 Sage 的定位从“Python 环境助手”扩展为**本地开发环境与代码运行助手**，以统一运行时接口承载多语言支持，同时优先覆盖 Sage 用户最常见的 Python、Node.js/TypeScript 场景。

### 目标

- 发现本机可用的编程语言运行时和相关工具，而不是只查找 Python。
- 识别项目类型、项目清单和版本/依赖要求。
- 输出结构化的“满足 / 部分满足 / 不满足”环境诊断，以及可执行的修复建议。
- 在用户授权和安全策略允许的前提下，使用用户选定的本地运行时执行代码或验证项目。
- 保证执行能力具有超时、输出上限、工作目录和进程树回收等安全边界。
- 保留 Python 3.8/Win7 LTS 的可降级兼容路径，不将 `main` 与 `release/win7` 合并。

### 非目标与第一版边界

- 不自动安装或卸载 Python、Node.js、conda、npm 包或其他系统组件。
- 不以新工具替代既有 Bash 工具；Shell/PowerShell 继续使用既有高风险审批链。
- 不支持任意网络服务、容器逃逸、系统服务管理或后台常驻进程。
- 第一版实现 Python 和 Node.js/TypeScript 适配器；Go、Rust、Java、C/C++、.NET 等通过可扩展接口预留，后续按需求加入。
- 不把探测结果中的原始环境变量、凭据或密钥内容返回给模型。

## 2. 设计原则

1. **运行时优先于语言专用实现**：核心 API 使用 `runtime_probe`、`runtime_exec`、`project_diagnose`，Python 只是第一个适配器。
2. **探测与执行分离**：环境探测是只读操作；代码执行、编译和依赖安装按执行类操作处理。
3. **低版本可发现、兼容性单独判断**：探测不因版本过低而隐藏运行时；版本约束由诊断器标记为兼容、不兼容或未知。
4. **最小权限**：执行器不隐式提供 `pip install`、`npm install` 等安装能力；所有超出工作区的路径、网络、编译和长期运行操作必须进入审批。
5. **复用既有安全原语**：复用 `subprocess_util`、`PolicyEnforcer`、`ApprovalGate`、`ReplTool` 和 Bash 的输出/进程管理模式。
6. **跨平台显式适配**：Linux/macOS/Windows 使用各自的发现策略；不能假定 POSIX 命令或 `os.killpg` 在所有平台可用。
7. **不污染开发环境**：测试和临时依赖遵循项目既定的 `sage-backend` 环境规则；不向 conda `base` 或系统 Python 安装依赖。

## 3. 现有模块与拟改动范围

### 3.1 可复用模块

| 模块 | 路径 | 用途 |
|---|---|---|
| 工具抽象与注册 | `backend/tools/base.py`、`backend/tools/registry.py`、`backend/tools/__init__.py` | 新增工具的 schema、风险声明和注册 |
| 子进程安全原语 | `backend/tools/subprocess_util.py` | 启动校验、超时、输出截断和进程组回收 |
| Python REPL | `backend/tools/repl_tool.py` | Python 执行生命周期和错误处理参考 |
| Bash 风险校验 | `backend/tools/bash_tool.py`、`backend/tools/bash_validation.py` | 命令风险判定、跨平台 shell 解析参考 |
| 权限体系 | `backend/tools/permissions.py`、`backend/services/permission_gate.py` | 只读/执行/破坏性操作的审批门禁 |
| Agent 配置 | `backend/agents/profiles.py` | Primary/Coder 工具白名单和能力提示 |
| Doctor | `backend/cli/doctor.py`、`backend/cli/checks/` | 环境检查框架和 JSON 诊断格式 |
| Electron 后端桥接 | `electron/main.ts`、`electron/preload.ts`、`electron/doctor.ts` | 桌面端本地探测、认证和 IPC |
| Settings 与 API | `src/pages/settings/Settings.tsx`、`src/shared/api/settingsClient.ts` | 设置页和用户默认运行时配置 |
| 聊天工具展示 | `src/widgets/chat/`、权限审批组件 | 执行进度、结果和审批交互 |

### 3.2 计划新增或修改文件

#### 后端

- 新增 `backend/domain/runtime.py`：`RuntimeInfo`、`RuntimeCapability`、`ExecutionRequest`、`ExecutionResult`、`Diagnostic` 等领域模型。
- 新增 `backend/tools/runtime_adapter.py`：`RuntimeAdapter` 协议、适配器注册表和统一命令构造接口。
- 新增 `backend/tools/runtime_probe.py`：`runtime_probe` 工具及跨平台运行时发现流程。
- 新增 `backend/tools/runtime_exec.py`：`runtime_exec` 工具，复用安全子进程原语。
- 新增 `backend/tools/project_diagnose.py`：项目清单识别、版本约束解析和诊断报告。
- 新增 `backend/tools/runtime_validation.py`：运行时路径、工作目录、超时和输入约束校验。
- 新增 `backend/tools/adapters/python_adapter.py`：Python/conda/venv 发现、版本和包检查、代码执行命令构造。
- 新增 `backend/tools/adapters/node_adapter.py`：Node.js/npm/pnpm/yarn/bun 发现、版本和项目脚本检查。
- 修改 `backend/tools/__init__.py`：注册统一运行时工具及适配器。
- 修改 `backend/tools/permissions.py` 或对应风险模型：为运行时执行建立清晰的执行风险映射，保持探测只读。
- 修改 `backend/agents/profiles.py`：Primary 可探测和诊断，Coder 可执行；补充存量 profile 升级链和能力提示。
- 新增或修改 `backend/api/env_routes.py`：提供探测、执行、项目诊断和需求检查接口。
- 修改 `backend/main.py`：注册环境路由并初始化运行时注册表。
- 新增/修改 `backend/cli/checks/runtime_env.py`：将运行时发现接入 `sage doctor`。

#### 前端与 Electron

- 新增 `src/shared/api/envClient.ts`：运行时 API 类型和 REST 包装。
- 新增 `src/pages/settings/RuntimeEnvTab.tsx`：运行时列表、刷新、默认运行时和诊断结果。
- 新增 `src/widgets/settings/RuntimeCard.tsx`：运行时卡片及兼容性状态。
- 修改 `src/pages/settings/Settings.tsx`：增加“开发环境”设置页签。
- 修改聊天工具调用展示组件：展示探测结果、诊断详情、代码执行 stdout/stderr 和退出状态。
- 修改 `electron/main.ts`、`electron/preload.ts`：如现有架构需要，增加运行时探测/执行 IPC，并确保与本地认证 token 和后端生命周期一致。

#### 测试与文档

- `backend/tests/unit/test_runtime_probe.py`
- `backend/tests/unit/test_runtime_exec.py`
- `backend/tests/unit/test_project_diagnose.py`
- `backend/tests/unit/adapters/test_python_adapter.py`
- `backend/tests/unit/adapters/test_node_adapter.py`
- `backend/tests/unit/cli/checks/test_runtime_env.py`
- `backend/tests/integration/test_env_routes.py`
- `src/pages/settings/__tests__/RuntimeEnvTab.test.tsx`
- `docs/technical/48-local-development-assistant.md`
- `docs/user-manual/12-local-development-assistant.md`
- 完成功能后更新 `docs/technical/README.md`、`docs/user-manual/README.md`，并删除本计划文件。

## 4. 统一接口设计

### 4.1 运行时适配器

```python
class RuntimeAdapter(Protocol):
    language: str

    def discover(self) -> list[RuntimeInfo]:
        """发现该语言的可用运行时，不修改系统。"""

    def inspect(self, runtime: RuntimeInfo) -> RuntimeCapabilities:
        """读取版本、包管理器和能力信息。"""

    def build_command(
        self,
        runtime: RuntimeInfo,
        source: str,
        cwd: Path,
    ) -> list[str]:
        """将受校验的源码转换为安全的执行命令。"""

    def diagnose(self, project_root: Path) -> list[Diagnostic]:
        """根据项目文件和运行时状态生成诊断。"""
```

适配器不得自行绕过统一的路径校验、审批、超时或输出限制。

### 4.2 `runtime_probe`

```json
{
  "languages": ["python", "javascript"],
  "include_tools": true,
  "include_versions": true,
  "target_version": ">=3.10"
}
```

`target_version` 只用于兼容性标记，不作为发现过滤器。低版本解释器仍返回，但标记为不满足目标约束。

返回统一的 `RuntimeInfo` 列表：

```json
{
  "runtimes": [
    {
      "language": "python",
      "name": "CPython",
      "path": "/opt/conda/envs/ml/bin/python",
      "version": "3.8.18",
      "source": "conda",
      "is_compatible": false,
      "capabilities": ["execute", "package_check"],
      "diagnostics": ["版本低于要求 >=3.10"]
    }
  ],
  "recommended": "/opt/conda/envs/ml/bin/python"
}
```

### 4.3 `runtime_exec`

```json
{
  "language": "python",
  "runtime_path": "/opt/conda/envs/ml/bin/python",
  "code": "print('hello')",
  "cwd": "/workspace/project",
  "timeout": 60,
  "run_in_background": false
}
```

第一版正式支持：

- Python：临时源码文件或 `-c`，不使用 shell 拼接；
- Node.js：临时源码文件或 `--eval`，不使用 shell 拼接。

返回：

```json
{
  "exit_code": 0,
  "stdout": "hello\n",
  "stderr": "",
  "duration_seconds": 0.12,
  "timed_out": false,
  "output_truncated": false
}
```

后台执行仅在既有会话生命周期和资源上限能够复用时开放；否则第一版只提供前台执行，避免引入不必要的会话泄漏风险。

### 4.4 `project_diagnose`

识别并解析：

- Python：`pyproject.toml`、`requirements*.txt`、`environment.yml`、`Pipfile`；
- Node.js：`package.json`、lockfile、`tsconfig.json`；
- 后续适配器：`Cargo.toml`、`go.mod`、`pom.xml`、`*.csproj`、`CMakeLists.txt` 等。

诊断等级：

- `satisfied`：运行时和声明依赖满足；
- `partial`：部分满足、可运行性未知或存在非阻塞警告；
- `unsatisfied`：缺少运行时、版本不符或关键依赖缺失。

修复建议只生成说明和可复制命令，不自动执行安装。

## 5. 安全与权限设计

| 操作 | 风险 | 要求 |
|---|---|---|
| `runtime_probe` | READ | 允许读取版本和工具元数据，不返回敏感环境变量 |
| `project_diagnose` | READ | 仅读取工作区内项目清单和受限元数据 |
| 工作区内 `runtime_exec` | EXECUTE | 普通模式逐次审批；受限工作目录和资源配额 |
| 工作区外解释器或 cwd | EXECUTE/HIGH | 必须额外确认路径和用途 |
| 编译或启动后台进程 | EXECUTE/HIGH | 独立审批；严格超时与进程树清理 |
| 安装/卸载依赖 | DESTRUCTIVE | 第一版不由工具直接执行 |
| Shell/PowerShell/Docker | HIGH/DESTRUCTIVE | 继续使用既有工具和审批链，不由 runtime adapter 绕过 |

强制校验：

- 运行时路径必须是已发现且仍可验证的 regular file，或明确经过用户确认；检查路径替换竞态。
- `cwd` 必须位于当前 workspace，或进入额外审批；禁止路径遍历和隐式切换项目。
- 源码长度、超时时间、输出大小、后台会话数和临时文件生命周期均有上限。
- 进程必须使用参数数组启动，禁止将用户源码或路径拼接进 shell 命令。
- 超时必须回收整个进程树；回收失败要显式报告，不可静默成功。
- stdout/stderr 做上限截断并标识截断状态。
- 错误信息不得泄露 token、密钥、完整敏感环境变量或不必要的系统信息。
- 不自动继承或展示 secrets；必要的环境变量采用最小白名单。

## 6. Agent 与产品交互

### Agent 分工

- **Primary**：可调用 `runtime_probe` 和 `project_diagnose`，负责了解环境并把任务委派给 Coder；不直接执行任意用户代码。
- **Coder**：可调用 `runtime_probe`、`project_diagnose`、`runtime_exec`，先确认运行时和需求，再生成/修改代码，最后在用户授权下验证。
- **其他 Agent**：默认不获得 runtime 执行能力，除非后续需求明确授权。

推荐对话流程：

```text
用户描述任务
  → Primary 识别项目与需求
  → runtime_probe 发现可用运行时
  → project_diagnose 判断版本/依赖
  → Coder 编写或修改代码
  → 申请 runtime_exec 审批
  → 使用选定运行时执行
  → 返回结果、错误和修复建议
```

前端应清晰区分：

- “已发现但版本过低”；
- “满足项目要求”；
- “缺少依赖”；
- “需要用户批准执行”；
- “执行失败”和“代码本身返回非零退出码”。

## 7. 分阶段实施步骤

### 阶段 0：设计确认与基线

- [ ] 确认运行时助手定位，以及第一版支持 Python + Node.js/TypeScript。
- [ ] 确认不提供自动依赖安装，安装建议由 Sage 生成、用户自行批准执行。
- [ ] 确认执行风险、Primary/Coder 分工、缓存策略和 Win7 降级策略。
- [ ] 使用 `sage-backend` 环境运行后端基线测试；不安装新依赖。

### 阶段 1：通用领域模型与只读探测

- [ ] 创建运行时领域模型和适配器协议。
- [ ] 实现 Python 适配器：系统 Python、conda、venv、低版本解释器发现与版本标记。
- [ ] 实现 Node.js 适配器：node/npm/pnpm/yarn/bun 发现。
- [ ] 实现 `runtime_probe` 和跨平台命令调用。
- [ ] 接入 `sage doctor` 的运行时检查。
- [ ] 编写适配器和探测工具单元测试，覆盖未安装、低版本、重复路径、命令超时和异常输出。

**阶段验收**：不执行用户代码即可列出运行时；低版本运行时可见但标记不兼容；doctor JSON 能报告运行时状态。

### 阶段 2：项目识别与需求诊断

- [ ] 实现 manifest 检测和项目类型识别。
- [ ] 解析 Python 与 Node.js 的版本和依赖声明。
- [ ] 实现 `project_diagnose`，输出满足度、明细和修复建议。
- [ ] 处理无 manifest、多个项目根、损坏配置和无法确定版本等情况。
- [ ] 编写诊断单元测试和集成测试。

**阶段验收**：对 Sage 自身项目能够正确识别 Python + React/Electron，并区分版本不符与依赖缺失。

### 阶段 3：统一安全执行器

- [ ] 实现 `runtime_validation`：路径、cwd、源码、超时和资源限制校验。
- [ ] 实现 `runtime_exec`，复用 `subprocess_util` 的安全启动、输出上限和进程树回收。
- [ ] 接入风险分类和 `ApprovalGate`，确保探测不审批、执行按策略审批。
- [ ] 先支持 Python、Node.js 前台执行；评估是否需要后台会话。
- [ ] 编写执行工具测试：成功、非零退出、低版本、超时、输出截断、非法解释器、路径遍历、进程回收失败。

**阶段验收**：Coder 可在用户批准后使用发现到的本地解释器验证代码，且任何失败都以结构化结果显式返回。

### 阶段 4：Agent、API、Electron 与前端

- [ ] 注册工具并更新 Primary/Coder profile 及存量 profile 升级逻辑。
- [ ] 增加环境 API：探测、诊断、执行和需求检查；所有非公开请求遵守本地认证中间件。
- [ ] 在 Electron 端接入 API/IPC，保证正常模式下后端 token 一致；避免另起不一致的后端。
- [ ] 增加 Settings → 开发环境页面，支持刷新和选择默认运行时。
- [ ] 在聊天中展示探测、诊断、审批和执行结果。
- [ ] 编写 REST、Electron stub 和前端组件测试。

**阶段验收**：用户可以从设置页查看运行时，也可以在聊天中完成“识别项目 → 选择运行时 → 批准执行 → 查看结果”的闭环。

### 阶段 5：兼容性、性能、安全复核与文档

- [ ] 在 Linux/macOS/Windows 策略上完成探测测试；验证路径和命令差异。
- [ ] 使用 `sage-backend` 和独立的 Python 3.8 环境分别验证 main 与 Win7 兼容代码；不修改错误分支的 requirements。
- [ ] 完成 security reviewer、python/typescript reviewer 和 code reviewer 检查。
- [ ] 验证单元、集成、关键 E2E 测试与覆盖率目标（80%+）。
- [ ] 编写并归档技术文档 `48-local-development-assistant.md`。
- [ ] 编写用户手册 `12-local-development-assistant.md`，更新两个 README 索引。
- [ ] 删除本计划文件（按项目文档规范，plans 只保留进行中的计划）。

## 8. 风险、依赖与缓解

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| 任意本地代码执行扩大攻击面 | 高 | 统一审批、workspace/cwd 限制、最小环境变量、超时和进程树回收 |
| 运行时路径被替换或伪装 | 高 | regular file + 可执行检查、发现结果验证、路径竞态防护、未知路径额外审批 |
| 适配器绕过安全策略 | 高 | adapter 只负责发现和命令构造，执行统一经过 validation/executor |
| 依赖安装通过代码间接发生 | 高 | 第一版不提供安装工具；对执行结果和能力提示明确说明边界 |
| Windows/macOS/Linux 行为差异 | 中 | 平台适配器、mock subprocess、真实平台 CI/E2E 分层验证 |
| 低版本 Python/Node 无法解析现代代码 | 中 | 低版本仍可发现；诊断显示兼容性；执行前提示版本约束 |
| 后台执行资源泄漏 | 中 | 第一版优先前台执行；若开放后台，复用 registry 上限和生命周期清理 |
| 多项目根识别错误 | 中 | 明确 workspace root，manifest 冲突标记为 partial，不静默选择 |
| Sage 正常模式 token 失配 | 高 | 复用现有 Electron `spawnBackend()` 和认证流程，不手动启动旁路后端 |
| Win7 Python 3.8 不兼容新实现 | 中 | 将兼容性代码隔离，运行时探测可用，后台能力按平台降级并单独测试 |

### 依赖

- 既有 Python/TypeScript 依赖和子进程原语；第一阶段不新增第三方依赖。
- 项目固定的 `sage-backend` conda 环境用于后端测试。
- Node.js 运行时探测依赖本机 PATH 和常见包管理器，不假定全部存在。
- 前端验证依赖现有 npm 依赖和 Vite/Electron 测试设施。

## 9. 验收标准

- [ ] `runtime_probe` 能发现 Python、conda/venv、Node.js 及常见 Node 包管理器；未安装项目不崩溃。
- [ ] 低版本运行时仍会被发现，并准确标记版本兼容性。
- [ ] `project_diagnose` 能识别 Python + React/Electron 项目，并区分满足、部分满足、不满足。
- [ ] `runtime_exec` 只在允许的运行时和目录执行，支持超时、输出截断和进程树回收。
- [ ] 探测/诊断不触发执行审批；代码执行在需要时触发现有审批 UI。
- [ ] Primary 不直接执行代码；Coder 能完成探测、诊断、编写和授权后验证。
- [ ] Settings 页面能查看、刷新和选择默认运行时。
- [ ] 不提供隐式依赖安装，不泄露 secrets，不新增任意 shell 绕过。
- [ ] 后端单元/集成、前端单元和关键 E2E 测试覆盖新功能，覆盖率达到 80% 目标。
- [ ] 技术文档和用户手册完成，计划文档按规范删除。
- [ ] `release/win7` 保持独立；兼容修复只能按需 cherry-pick 并在 Python 3.8 环境验证。

## 10. 建议的提交与 PR 拆分

1. `feat(runtime): add cross-language runtime models and discovery`
2. `feat(runtime): diagnose project requirements`
3. `feat(runtime): execute approved local runtime code`
4. `feat(runtime): expose runtime assistant in agents and UI`
5. `docs(runtime): document local development assistant`

每个 PR 在 `feat/local-development-assistant` 或其派生 feature 分支上完成，遵循现有 feature branch、CI、AI review 和用户合并流程。不得直接向 `main` 提交。

## 11. 待确认决策

- [ ] 第一版是否确定支持 Python + Node.js/TypeScript，其他语言只实现扩展接口。
- [ ] `runtime_exec` 是否第一版仅支持前台执行，后台会话留到后续迭代。
- [ ] 是否将执行风险建模为独立 `RUNTIME_EXECUTE`，还是复用现有 `EXECUTE` 并增加工具级策略。
- [ ] 默认运行时保存于 Settings 的用户偏好，还是只保存在当前会话内。
- [ ] Go/Rust/Java/C++/.NET 的优先级和首个后续迭代范围。
