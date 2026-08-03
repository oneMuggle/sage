# office_create 工具自动创建 Office 文档 — Design Spec

- **Date:** 2026-08-03
- **Branch:** `main`（设计文档提交；实现将走 feature 分支）
- **Status:** Draft，待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

用户对 Sage 提问"帮我在桌面上创建一份 Word 文档，写入『今天天气很好』"时，LLM 回复"我没有直接访问本地电脑并在桌面上创建或写入文件的权限"，并附一段需用户自行运行的 Python 代码。原因是：**Office 生成能力存在，但未暴露给 LLM 自动调用**。

| 层 | 现状 | LLM 是否可达 |
|---|---|---|
| 生成函数 | `word.py::generate_docx` / `excel.py::generate_xlsx` / `ppt.py::generate_ppt` | ❌ 仅经 HTTP 端点（`/word/generate` 等） |
| LLM 工具 | `office_list` / `office_read`（`office_tool.py`） | ✅ 但 `requires_tool_context=True`，需 @提及 建立 context 才暴露 |
| 写入路径 | `<workspace>/office/<type>/<id>/<name>`（`managed_document_path` 沙箱） | 写受管工作区，**不触碰桌面** |

因此用户直接提问时，LLM 的工具 schema 里没有"创建文档"能力，只能道歉。

### 1.2 目标

1. 新增 `office_create` LLM 工具：用户直接提问即可触发（**无需 @提及 / tool_context**），自动调用生成器创建 Word / Excel / PPT。
2. 支持**写入任意路径**（桌面 / 下载 / 文档等），而非仅受管工作区。
3. 写入工作区外路径时，经现有 M1 审批链（`permission_request` → `ApprovalDialog` → `permissions_answer`）**逐次用户确认**。
4. 复用现有结构化生成模型（`models.py`），LLM 提供完整结构参数（标题 / 段落 / 表格 / 工作表 / 幻灯片）。

### 1.3 非目标 (YAGNI)

- ❌ **改造 hex `PermissionEngine`**（`chat_service` 链路，`backend/adapters/out/permission/permission_engine.py`）：本期聚焦 legacy 主链路（`/chat/stream`，Electron 前端实际走 `agent_chat_stream` IPC）。
- ❌ **文档预览 / 一键打开**：创建后仅在 Artifacts 面板记录，不做前端预览或唤起 Office。
- ❌ **excel 公式 / 样式 / 多 sheet 高级格式**：沿用生成器现有能力。
- ❌ **PPT 模板增强 / 图片插入**。
- ❌ **前端新增审批 UI**：完全复用 M1 `ApprovalDialog`。
- ❌ **release/win7 同步**：本期只在 main，后续按需 cherry-pick（遵循双分支策略）。

## 2. 用户故事

- **US-1**：作为 Sage 用户，我直接说"帮我在桌面创建 word 文档写入『今天天气很好』"，LLM 自动调用工具生成 `天气.docx` 到桌面，无需我手动操作。
- **US-2**：作为 Sage 用户，LLM 要把文件写到工作区外（桌面 / 任意目录）时，会弹审批框让我确认"允许 / 拒绝"，而不是静默写盘。
- **US-3**：作为 Sage 用户，LLM 创建 Excel（带表头数据）或 PPT（多张幻灯片）同样可用，不局限于 Word。
- **US-4**：作为开发者，写工作区内的目标路径（`workspace_root` 内）不弹审批，与现有 WRITE 工具语义一致。

## 3. 架构

### 3.1 组件总览

```
用户提问 → /chat/stream (legacy SageAgent)
  → get_available_tools → schema 含 office_create（requires_tool_context=False，始终可见）
  → LLM 调用 office_create(doc_type, output_dir, filename, content{...})
  → agent run_loop: enforcer.check("office_create", args)
       │  classify → WRITE · workspace_write 模式矩阵放行 WRITE
       │  path_boundary_validator: output_dir 在 workspace_root 外 → 覆盖为 ask
       ▼
  → needs_approval → emit PERMISSION_REQUEST → ApprovalDialog → permissions_answer
  → 批准 → OfficeCreateTool.execute → generate_*(output_dir=...) → 写盘
  → tool_result → LLM 汇报创建结果
```

### 3.2 改动点 ①：生成器支持任意路径（`backend/office/word.py` / `excel.py` / `ppt.py`）

三个 `generate_*` 函数增加可选参数 `output_dir: Optional[str] = None`：

- `output_dir=None` → **保持现状**：`validate_workspace(workspace_path)` + `managed_document_path(...)`，写 workspace 沙箱。HTTP 端点（`office_routes.py`）不受影响。
- `output_dir` 提供 → 写入 `Path(output_dir).expanduser()` 目录；文件名仍经 `validate_supported_filename`（拦分隔符 / `..` 穿越 / 错误扩展名）。
- 新增 helper `backend/office/path_safety.py::resolve_output_path(output_dir, doc_type, filename) -> Path`：
  - `output_dir` 展开 `~`、resolve；
  - 文件名走 `validate_supported_filename`；
  - 返回拼接路径（不强制 workspace 边界——这是**信任的用户指定目录**）。
- 三个生成器改为调用该 helper，消除重复。

### 3.3 改动点 ②：新工具 `OfficeCreateTool`（`backend/tools/office_create_tool.py`）

```python
class OfficeCreateTool(BaseTool):
    requires_tool_context = False   # 直接提问即触发
    risk = RiskClass.WRITE_LOCAL    # 有副作用，声明写本地
```

**schema（完整结构化，复用 models.py 生成请求字段）：**

```
doc_type: enum["word", "excel", "ppt"]
output_dir: string     # 目标目录（可含 ~，如 ~/Desktop）
filename: string       # 如 天气.docx（缺扩展名自动补，错误扩展名拒绝）
content: object{
  word:  { title, paragraphs[{text, heading?}], tables[{headers, rows[]}] }
  excel: { sheets[{name, headers[], rows[]}] }
  ppt:   { slides[{title, bullets[], notes?}] }
}
```

**execute 流程：**

1. 按 `doc_type` 构造对应生成请求模型（`OfficeWordGenerateRequest` / `OfficeExcelGenerateRequest` / `OfficePptGenerateRequest`），`workspace_path` 置空串（不再用），从 schema 参数填充内容。
2. 调 `generate_*(req, output_dir=output_dir)`。
3. 成功 → 复用 `write_file` 的 `_record_artifact_safely` 模式，把产出文件记录到 Artifacts 面板（`current_tool_context()` 为空时静默跳过）。
4. 返回 `ToolResult(success=True, content={path, filename, bytes})`。

**路径 / 覆盖守卫（execute 内）：**

- `output_dir` resolve 后若为已存在文件而非目录 → 拒绝。
- 目标文件**已存在 → 拒绝并提示换文件名**（不静默覆盖，安全优先；审批 reason 会展示目标路径，用户已可提前感知）。
- 目录不存在 → `mkdir(parents=True, exist_ok=True)`（与 `write_file` 一致）。

### 3.4 改动点 ③：权限层 `path_boundary_validator`（`backend/tools/permissions.py`）

`PermissionEnforcer` 增加**可选**构造参数（与现有 `bash_validator` 完全对称）：

```python
class PermissionEnforcer:
    def __init__(self, mode, rules, bash_validator=None, path_boundary_validator=None):
        ...
```

- 签名：`Callable[[str, Dict[str, Any]], Optional[PermissionDecision]]`——工具名 + args → 返回决策（覆盖 allow）或 `None`（保持原决策）。
- `check()` 在模式矩阵判定 `allow` 之后、返回之前调用；返回非 `None` 则用它覆盖（用于把"写工作区外"从 allow 升级为 ask / deny）。
- **FULL_ACCESS 模式跳过 path_boundary 校验**（用户已确认：full_access 按 M1 语义全放行）——校验仅在非 FULL_ACCESS 模式生效。
- `TOOL_CAPABILITIES["office_create"] = ToolCapability.WRITE`。
- `load_enforcer_from_settings` 增加可选透传参数（默认 `None`，向后兼容）。

**注入实现 `office_path_boundary`（模块级函数，`backend/tools/permissions.py` 或独立模块）：**

- 仅对 `office_create`（WRITE 且带 `output_dir` 参数）生效；非 FULL_ACCESS 模式才调用（见上）。
- `Path(args["output_dir"]).expanduser().resolve()` 落在 `workspace_root`（resolve 后）之内 → 返回 `None`（放行）；
- 落在 workspace 外 → 返回 `_ask("写入工作区外的路径 <resolved>，需要用户确认")`；
- 无 workspace_root（未绑定）→ 返回 `None`（与 `write_file` 未绑定时的跳过边界检查语义一致）。

**装配（`backend/core/legacy/agent.py::_build_permission_enforcer`）：**

- 构造 enforcer 时从 `ToolPolicy.workspace_root` 取边界，注入 `path_boundary_validator`。
- `_build_permission_enforcer` 的 `PermissionEnforcer(...)` 兜底分支同样注入。

### 3.5 改动点 ④：注册（`backend/tools/__init__.py::register_all_tools`）

```python
registry.register(OfficeCreateTool(policy=policy))
```

登记后 `office_create` 自动进入 schema 列表、`PermissionEnforcer` 能力表、审批链。

## 4. 数据流（示例：创建 Word 到桌面）

1. 用户：`帮我在桌面创建 word 文档，写入"今天天气很好"` → `/chat/stream`。
2. `SageAgent` 构建 LLM schema：`office_create` 可见（无 tool_context 依赖）。
3. LLM 调用 `office_create(doc_type="word", output_dir="~/Desktop", filename="天气.docx", content={"title": "天气", "paragraphs": [{"text": "今天天气很好"}]})`（`title` 必填非空——`OfficeWordGenerateRequest.title` 有 `min_length=1` 约束，LLM 应生成一个简洁标题）。
4. `enforcer.check("office_create", args)`：WRITE → workspace_write 模式矩阵 allow → `path_boundary_validator` 发现 `~/Desktop` 不在 workspace_root → 返回 `ask`。
5. `needs_approval` → `yield PERMISSION_REQUEST`（含 args 摘要 + reason）→ 前端 `ApprovalDialog` → 用户"允许"。
6. `OfficeCreateTool.execute(...)` → `generate_docx(req, output_dir="~/Desktop")` → 写 `~/Desktop/天气.docx`。
7. `tool_result` → LLM 汇报："已创建 ~/Desktop/天气.docx"。

## 5. 错误处理

| 场景 | 行为 |
|---|---|
| `output_dir` 是已存在文件而非目录 | `ToolResult(success=False, error="output_dir_not_directory")` |
| 目标文件已存在 | `ToolResult(success=False, error="file_exists: 请更换文件名")`，不覆盖 |
| `output_dir` 目录不存在 | 自动 `mkdir(parents=True, exist_ok=True)` |
| 生成失败（bad content / 库异常） | `OfficeGenerateError` → `ToolResult(success=False, error=...)` → 现有 tool_failed 流程 |
| 权限拒绝 / 用户拒绝审批 | 现有 `permission_denied` / 拒绝 reason 流程，不执行 |
| 无 tool_context（Artifacts 记录失败） | 静默跳过记录，不影响创建结果 |

## 6. 方案对比（brainstorming 结论）

| 维度 | **方案 A（选定）** 权限层注入 path_boundary_validator | 方案 B 工具内边界判断 + agent 特判 |
|---|---|---|
| 审批语义 | enforcement-before-dispatch，与 bash_validator 同构 | agent 循环内特判，边界逻辑散落两处 |
| 对 M1 通用组件的侵入 | 加一个可选回调（向后兼容） | 不动 |
| 边界单一事实源 | 是 | 否（agent 特判 + 工具各一份） |
| 前端改动 | 零 | 零 |
| 维护成本 | 低 | 中（核心循环特例累积） |

**选定方案 A**：把"写工作区外需确认"当作 M1 权限体系的一等公民，而非 agent 循环里的特例。

## 7. 测试计划

- **单测 `backend/tests/unit/office/test_path_safety.py`**：`resolve_output_path`（`~` 展开 / 文件名穿越拒绝 / 错误扩展名拒绝 / 分隔符拒绝）。
- **单测 `backend/tests/unit/tools/test_office_create_tool.py`**：
  - 三类型（word / excel / ppt）schema 快照；
  - 三类型 execute 生成到指定 `output_dir`，断言文件存在 + 可读回（复用现有 reader）；
  - 目标文件已存在 → 拒绝不覆盖；
  - `output_dir` 是文件 → 拒绝；
  - 无 tool_context 时 Artifacts 记录静默跳过。
- **单测 `backend/tests/unit/test_permissions_enforcer.py`**：
  - `path_boundary_validator` 工作区内 → 放行；
  - 工作区外 → ask（workspace_write / prompt 模式）；
  - read_only 模式 → deny；
  - full_access 模式 → 放行（用户已确认）；
  - 无 workspace_root → 放行。
- **回归单测**：三个生成器默认行为（不传 `output_dir`）与现有 HTTP 端点行为一致。
- **集成测试**：agent 审批链（`office_create` 工作区外 → PERMISSION_REQUEST → 批准 → 执行成功；拒绝 → 不执行）。

## 8. 实施里程碑

- [ ] M1：`resolve_output_path` + 三个生成器 `output_dir` 参数 + 回归测试
- [ ] M2：`OfficeCreateTool` + schema + execute + 单测
- [ ] M3：`path_boundary_validator` + `PermissionEnforcer` 扩展 + `office_create` 能力登记 + 单测
- [ ] M4：`register_all_tools` 注册 + agent 装配注入 + 集成测试
- [ ] M5：手动验证（Electron 提问 → 审批 → 桌面生成）
