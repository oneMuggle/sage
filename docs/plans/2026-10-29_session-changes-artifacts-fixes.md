# 会话「变更 / 产物」面板缺陷修复与优化方案

- 日期：2026-10-29
- 状态：待评审（未开始实施）
- 范围：`backend/tools/git_tool.py`、`backend/api/workspace_routes.py`、`backend/tools/office_create_tool.py`、`backend/tools/office_update_tool.py`、`backend/data/{artifact_repo,artifact_reader}.py`、`backend/api/artifact_routes.py` 及对应前端 `changes` / `artifacts` / `office` 模块；不涉及数据库 schema 变更

## 1. 背景与目标

用户报告会话页两处面板的三类缺陷：

1. **变更面板（无 git 仓库）**：绑定一个非 git 工作区后，面板直接显示
   `error invoking remote method 'sage.invoke'`，其中含
   `Backend GET cmd=workspace_get_changes → 502`，没有任何可操作提示。
2. **变更面板（有 git 仓库）**：未跟踪的中文文件名显示为
   `02_\347\274\226\210\266...` 这类八进制转义并带引号；点击该类条目后
   同样报 `error invoking remote method 'sage.invoke'`。
3. **产物面板**：LLM 生成的文件不再出现在产物列表；即使历史上能被追踪的
   Word 产物，预览也只呈现成段落文本（类 Markdown 观感），没有 Word 版式。

目标：

- 变更面板在非 git 工作区展示明确、可操作的空态，而不是 502 原始报错；
- git 变更清单完整保留中文 / 空格 / 重命名路径，点击可正常查看 diff 与预览；
- 所有 LLM 生成路径（含工作区受管 Office 文档）都能落 artifact 记录；
- Word 产物默认以 Word 版式（页宽、字体、表格、图片）渲染，结构化文本视图保留为降级/切换项。

## 2. 根因调查（证据）

### 2.1 非 git 仓库 → 502 是「按设计写死」的，UI 没有兜底

`backend/api/workspace_routes.py:328-357` 的 `get_workspace_changes` 直接调用
`GitStatusTool`，只要 git 失败就：

```python
raise _error(502, "git_error", result.error or "git 命令失败")
```

而 `GitStatusTool`（`backend/tools/git_tool.py:238`）在非仓库目录下
`git status` 返回非零，`_run_git` 把 stderr 折叠为 error（如
`fatal: not a git repository ...`），路由原样映射为 502。

前端 `src/features/changes/changesListStore.ts` 的 `friendlyError` 只识别
`workspace_not_bound` 一种错误；Electron 侧 `electron/invoke.ts:96-114` 把
HTTP 状态与响应体拼进 `Error.message`，最终面板把整段 IPC 包装文本原样显示。
结论：**后端把「非 git」当异常，前端没有对应状态**，二者叠加产生用户看到的
无信息量报错。

### 2.2 中文文件名八进制转义：porcelain 输出的默认 C-quoting

`GitStatusTool.execute` 使用：

```python
stdout, error = _run_git(["status", "--porcelain=v1", "-b"], root)
...
"path": line[3:],
```

未关闭 `core.quotepath`，也未使用 `-z`。本机复现（临时仓库）：

```
$ git status --porcelain=v1 -b
?? "02_\347\274\226\345\210\266\350\257\264\346\230\216.txt"

$ git -c core.quotepath=false status --porcelain=v1 -b
?? 02_编制说明.txt
?? "新 文件.txt"          # 含空格仍被引号包裹
```

关键点：`core.quotepath=false` 只解决非 ASCII，**含空格的路径仍会被引号包裹**，
唯一稳健方案是 `-z`（NUL 分隔、原始字节）。`-z` 下：

- 普通条目：`XY <path>\0`；
- 重命名：`R  <new>\0<old>\0`（rename 的第二段是旧路径）。

因此现有 `line[3:]` 会把 `"02_\347..."`（含引号与反斜杠）当作真实路径，

- 展示层直接显示乱码；
- `collect_change_stats`（`git_tool.py:126-166`）用该路径拼 `os.path.join(root, rel)`
  统计未跟踪文件行数 → 失败 → +/- 徽章缺失；
- `untracked_file_diff`（`git_tool.py:167-213`）用该路径执行
  `git status --porcelain=v1 -- <quoted>`，匹配不到 `??` → 返回 `None`；
- 点击行的 `workspace_get_change_file` 用该路径查文件 → 404，前端弹
  `error invoking remote method`；
- 重命名条目 `old -> new` 整体作为 path，也无法命中真实文件。

补充验证：`git diff HEAD --numstat` 在 `core.quotepath=false` 下不会给含空格
路径加引号（实测 `1 0 报告 文件.md`），所以 numstat 只需关闭 quotepath，
status 必须走 `-z`。

### 2.3 产物未追踪：受管（绑定工作区）Office 生成路径完全跳过落库

`office_create` 有两条路径（`backend/tools/office_create_tool.py`）：

- **本地路径**（无工作区绑定）：`_generate_document` 成功后调用
  `_record_artifact_safely(...)`（:1558）；
- **受管路径**（会话绑定工作区）：`execute` 在 :1266-1275 先尝试
  `_try_delegate_to_bound_service(...)`，成功后**直接 `return delegated`**，
  而 `_try_delegate_to_bound_service`（:1356-1425）与
  `OfficeToolService.create` 都没有任何 artifact 记录。

本机 `data/sage.db` 取证：

- `artifacts` 表最近一条记录约在 10-20，此后 9 天的 5+ 个会话均为 0 条；
- 会话 `7aa06001-...` 的 `office_create` 工具调用结果含
  `{"document_id": "...", "doc_type": "word", ...}`（受管路径成功），
  同会话 `artifacts` 查询结果为空数组。

这解释了「以前能追踪、现在追踪不到」：随着会话默认绑定工作区，Office 生成
几乎全部走受管路径，而该路径从未落 artifact。

`office_update` 同样存在缺口（`backend/tools/office_update_tool.py:248-292`
只调 `OfficeToolService.update`，无 artifact 记录），因此「首次生成追踪不到、
后续编辑更追踪不到」。

### 2.4 Word 渲染成 Markdown 观感：聊天产物走的是结构化文本组件

- 后端 `artifact_reader.read_office`（`backend/data/artifact_reader.py:200-244`）
  对 docx 返回两份数据：`structured`（`read_docx` 的段落/表格 JSON）与
  `html`（段落拼 HTML）。
- 前端 `ArtifactViewer.tsx:365-390` 只要 `structured` 存在就渲染
  `WordPreview`（`src/features/office/OfficeStructuredPreviews.tsx:199+`）——
  该组件本质是「标题 + 段落 + 表格 + 图片缩略」的阅读视图，没有页宽、分页、
  字体、行距、页眉页脚，因此看起来像 Markdown。
- 同一仓库其实已有两条高保真通路：`/office` 页的
  `DocxNativePreview`（docx-preview 直接在渲染进程解析二进制）与
  `/office/pdf-preview`（LibreOffice 转 PDF）。聊天产物面板**一条都没接**。

### 2.5 附带发现

- **子目录工作区语义错误**：`git status --porcelain` 的路径相对仓库根（实测从
  `sub/` 目录执行仍输出 `sub/a.txt`），而 `collect_change_stats` /
  `changes/file` 都以「工作区根 + path」拼接。若会话绑定的是仓库子目录，
  行数徽章与预览会错位（该场景下变更清单本身也会多出工作区外的文件）。
- **错误信息在 IPC 层被压平**：`electron/invoke.ts` 把后端 JSON detail 拼进
  一条 message，前端无法按 `code` 分支处理，只能字符串匹配。
- **大文件预览持锁读盘**：`artifact_routes` 的 content 端点在
  `@with_db_lock` 内做最多 20MB 读盘 + base64，会串行化其他 DB 请求。

## 3. 技术方案

### 3.1 P0：变更清单路径解析改为 `-z`（`backend/tools/git_tool.py`）

`GitStatusTool.execute` 改为：

```python
stdout, error = _run_git(
    ["-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "-b"],
    root,
)
```

解析规则（NUL 分隔）：

- 首个 token 若以 `##` 开头 → 分支/上游/领先落后（沿用现有正则）；
- 其余 token：`XY <path>`；当 `X` 或 `Y` 为 `R`/`C` 时，**下一个 token 是旧路径**，
  消耗之并放入可选字段 `old_path`；
- `path` 保持仓库根相对路径；是否再加 `repo_root` 字段见 3.6。

同时：

- `collect_change_stats` 的 `git diff HEAD --numstat` 加
  `["-c", "core.quotepath=false", ...]`（实测已足够，不需要 `-z`）；
- rename 的 numstat 行解析保留现有 `=>` 分支即可；
- `untracked_file_diff` 的 `git status` 同样加 `core.quotepath=false`，并继续用
  上游传入的**已解码原始路径**做路径参数。

前端无需解码，但 `WorkspaceChangeEntryModel` / `WorkspaceChanges` 可选择性新增
`old_path`（仅展示用，例如「旧名 → 新名」），不改变既有字段。

### 3.2 P0：非 git 工作区返回结构化状态而非 502

后端（`workspace_routes.py`）：

- 新增工具函数 `is_git_repo(root)`（可复用
  `backend/orchestration/worktree.py:57` 的实现或抽到 `git_tool.py`），执行
  `git rev-parse --is-inside-work-tree`；
- `GET /changes`：不是 git 仓库时返回 **200** +
  `WorkspaceChangesResponse(is_git_repo=False, branch="", upstream="", ahead=0, behind=0, clean=True, changes=[])`；
- `WorkspaceChangesResponse` 增加 `is_git_repo: bool = True`（pydantic v1/v2
  均兼容的普通默认值，避免 win7 差异）；
- `GET /changes/diff`、revert 系列在非 git 时返回 409 `not_a_git_repo`
  （防御性，正常 UI 不会触发；`changes/file` 保持既有契约——它是工作区内的
  只读文件读取，既有测试允许非 git 工作区使用）。

前端：

- `src/shared/api/workspaceApi.ts` 的 `WorkspaceChanges` 增加
  `isGitRepo: boolean`（wire 字段 `is_git_repo`，缺失时默认 `true`）；
- `ChangesSection`：`isGitRepo === false` 时渲染专用空态：
  「当前工作区不是 Git 仓库」+ 说明「初始化 Git 仓库后才能追踪变更」，
  隐藏「全部审查」；检查点区（快照实现，不依赖 git）保持可用；
- `changesListStore.friendlyError` 增加映射：
  `not a git repository` / `not_a_git_repo` / `git 可执行文件不可用` →
  用户可读文案（兜底旧后端与 git 缺失场景）。

### 3.3 P0：补全受管 Office 生成/编辑的 artifact 落库

**office_create（受管路径）**：在 `_try_delegate_to_bound_service` 成功分支内，
拿到 `document_id` 后：

```python
doc = get_document_in_workspace(conn, doc_id, binding.workspace_path)
if doc is not None:
    path = document_path(doc)          # <workspace>/office/<type>/<id>/<filename>
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    _spec = json.dumps(content["format_spec"], ensure_ascii=False) \
        if isinstance(content.get("format_spec"), dict) else None
    _record_artifact_safely(
        str(path), size, binding.workspace_path, _spec,
        session_id=ctx.session_id,
    )
```

注意：不得把 `path` 放进工具结果（维持「不回显受管绝对路径」不变式），
只在后端落库。

**office_update（受管路径）**：编辑成功后刷新已存在 artifact 的大小/时间，
而不是新增一条重复记录。建议在 `artifact_repo` 增加：

```python
def refresh_artifact(session_id, path, size) -> bool:
    # UPDATE artifacts SET size=?, created_at=? WHERE id=(
    #   SELECT id FROM artifacts WHERE session_id=? AND path=?
    #   ORDER BY created_at DESC LIMIT 1)
    # 命中后广播 artifact_created（前端沿用同一刷新计数）
```

若查不到（历史会话首次编辑）则回退 `record_artifact` 新增。

补充审计：`office_pdf_tool` / `office_template_tool` / `office_ppt_template_tool`
已有 `_record_artifact_safely` 调用，实施时逐个确认其受管分支是否也有
early-return，若有同类缺口一并补上。

### 3.4 P1：Word 产物高保真预览（聊天产物面板）

推荐方案（后端加一个字段 + 前端复用现有渲染器）：

1. `artifact_reader.read_office(kind="docx")` 额外返回
   `data_url`（`data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,...`，
   沿用 20MB 上限），仅在 docx 分支返回；`ArtifactContent` 类型已有
   `data_url` 字段，无需改 IPC。
2. 把 `DocxNativePreview` 中「拿 blob → `docx-preview.renderAsync` → DOMPurify
   消毒」的部分抽成受控组件 `DocxBlobPreview({ dataUrl })`；
   - `/office` 页继续用 `officeApi.readWordData` 取 data_url 后喂给它；
   - 聊天 `ArtifactViewer` 直接用 `content.data_url` 喂给它，不依赖工作区绑定
     或文件仍在原路径。
3. `ArtifactViewer` docx 分支改为：
   - 默认「Word 版式」：`DocxBlobPreview`；
   - 头部增加「版式 / 文本」切换按钮（仿 markdown 渲染/源码切换的交互）；
   - `DocxBlobPreview` 失败（解析异常、超限、旧后端无 data_url）时自动回退
     `WordPreview` 结构化视图，不阻断阅读。
4. 可选（P2）：若 `artifact.workspace_path` 可用且本机有 LibreOffice，再提供
   「PDF 高保真」第三档，复用 `officeApi.pdfPreview`。

安全：docx 是不受信数据，必须沿用现有 DOMPurify 白名单 +
`sanitizeRenderedDocx`；iframe/sandbox 不适用（docx-preview 产出 DOM）。

### 3.5 P1：错误信息透传（`electron/invoke.ts`）

`invokeBackend` 在 `!res.ok` 时尝试解析响应 JSON：

```ts
const body = safeJson(text);
const detailMsg = body?.detail?.message ?? body?.detail ?? body?.message;
const code = body?.detail?.code;
const err = new Error(detailMsg || `Backend ${route.method} cmd=${cmd} → ${res.status}`);
(err as any).status_code = res.status;
(err as any).code = code;
```

收益：变更面板、产物面板及所有 IPC 命令直接拿到「当前会话尚未绑定工作区」
这类后端文案，而不是 IPC 包装串。需要同步更新断言旧 message 格式的 electron
测试（`electron/__tests__/*`）。

### 3.6 P2：子目录工作区路径归一

若绑定工作区是仓库子目录：

- `GitStatusTool` 增加 `repo_root = git rev-parse --show-toplevel`；
- 路由层把 repo-root 相对路径转为「工作区相对」：
  `abs = repo_root/path`，仅保留 `abs` 位于工作区内的条目，
  回显 `os.path.relpath(abs, workspace_root)`；
- `collect_change_stats` 以 `abs` 读文件/统计；
- diff 路由继续以工作区为 cwd 执行（路径已是工作区相对），并在
  `_guard_path` 内完成边界校验。

该改动可一并消除「变更清单混入工作区外文件」的问题；若评审认为优先级低，
可仅记录为已知限制。

### 3.7 P2：大文件预览不持 DB 锁读盘

`artifact_routes.get_artifact_content` 现状整个函数在 `@with_db_lock` 下。
建议拆为：

1. 持锁查询 artifact 元数据；
2. 释放锁后读文件 / base64；
3. 必要时再次持锁写版本。

与现有 `read_pdf` 20MB 口径一致，只是减少锁竞争。

## 4. 实施步骤

- [x] 步骤 1：`git_tool.py` 改用 `-z` + `core.quotepath=false` 解析 status，
      处理 rename 双 token；同步 `collect_change_stats` / `untracked_file_diff`
- [x] 步骤 2：新增 `is_git_repo` + `WorkspaceChangesResponse.is_git_repo`，
      `/changes` 非仓库返回 200 空态；diff/revert 返回 409 `not_a_git_repo`
      （实测 `changes/file` 既有契约允许非 git 工作区预览，未加守卫）
- [x] 步骤 3：前端 `workspaceApi` 类型 + `ChangesSection` 非 git 空态 +
      `friendlyError` 文案映射
- [x] 步骤 4：`office_create` 受管分支补 `_record_artifact_safely`
      （含 workspace_path / format_spec / session_id）
- [x] 步骤 5：`artifact_repo.refresh_artifact` + `office_update` 受管分支接入；
      审计其余 office_* 工具（pdf/template 均已有落库调用，无同类 early-return）
- [x] 步骤 6：后端 docx 产物返回 `data_url`；抽取 `DocxBlobPreview`；
      `ArtifactViewer` 接入「Word 版式 / 文本」切换与失败回退
- [x] 步骤 7：`electron/invoke.ts` 错误 detail 透传 + 测试更新
- [x] 步骤 8：P2 子目录工作区路径归一（`git_repo_root` +
      `to_workspace_relative_path`，列表/徽章/diff/预览/撤销全覆盖）
- [x] 步骤 9：P2 大文件预览不持 DB 锁（content 端点移除全函数级
      `@with_db_lock`，单条查询仍由 `_LockedConnection` 保证）
- [x] 步骤 10：相关测试 + ruff / py38 兼容 / tsc / eslint 全绿；
      手工验收（见 §6）待桌面端联调

## 8. 实施记录（2026-10-29，review 后补充）

本轮 review 发现并已一并修复：

- **撤销路径同样受 C-quote 影响**：`backend/office/workspace_revert.py`
  的 `git status` 也改为 `-z` + `core.quotepath=false`，否则列表能点开中文
  文件但「撤销/删除」仍失败（新增中文已跟踪/未跟踪撤销测试）。
- **git 缺失 vs 非仓库**：`git_repo_status()` 返回 `Optional[bool]`，
  git 不可用/超时 → None → 502 `git_error`；明确非仓库 → 200 空态。
  避免把「未安装 git」误显示成「不是 Git 仓库」。
- **rename 的 +/- 徽章**：numstat 解析新增 `_numstat_new_path()`，
  正确还原 `dir/{old => new}` 的新路径；响应新增可选 `old_path` 字段。
- **docx 空渲染回退**：`DocxBlobPreview` 渲染后校验节点数，空 DOM 也走
  `onError` 回退结构化视图。
- **测试库连接**：`artifact_repo.record_artifact/refresh_artifact` 与
  `_record_artifact_safely` 支持传入已有 `conn`，受管 office 路径使用会话
  连接，避免测试误开真实全局库。

仍未实施（后续优化，不影响本轮验收）：

- docx `data_url` 仍随 content 响应返回（最大 20MB → base64 约 27MB）；
  若实测大文档拖慢 IPC，可拆独立懒加载端点；
- `created_at` 在 `refresh_artifact` 时被当「最后修改时间」重写
  （表结构无 `updated_at` 列；当前列表语义为「最近活跃」）。

## 5. 测试计划

### 5.1 后端单测 / 集成测试

| 用例 | 断言 |
|---|---|
| `test_git_tool.py::test_status_non_ascii_paths` | 中文文件名 `path` 为原文，无引号/八进制 |
| `test_git_tool.py::test_status_path_with_spaces` | `新 文件.txt` 原文 |
| `test_git_tool.py::test_status_rename_entries` | `path` 为新名，`old_path` 为旧名 |
| `test_workspace_changes_routes.py::test_changes_non_git_workspace` | 200，`is_git_repo=false`，`changes=[]` |
| `test_workspace_changes_routes.py::test_diff_non_git_workspace` | 409 `not_a_git_repo` |
| `test_changes_untracked_unicode_preview` | 未跟踪中文文件 diff/预览 200 |
| `test_office_create_tool`（新增 managed fixture） | 成功生成后 `artifact_repo.list_artifacts(session)` 含 1 条，kind=`docx`，workspace_path 正确 |
| `test_office_update_tool` | 编辑后 artifact 数量不增加、size/created_at 刷新 |
| `test_artifact_routes::docx_content_includes_data_url` | base64 前缀正确、超限返回 ok=False |

### 5.2 前端测试

- `changesListStore`: `isGitRepo=false` 不下发 error；`git_error` 映射文案；
- `ChangesSection`: 非 git 空态文案 + 检查点仍渲染；
- `ArtifactViewer`: docx 分支默认渲染 `docx-blob-preview`；切换按钮存在；
  `data_url` 缺失/渲染抛错时回退 `office-structured-preview`；
- `electron/invoke` 测试：JSON detail 被解析为 message/code。

### 5.3 手工验收

1. 绑定一个**非 git** 目录 → 变更面板显示友好空态，无 502；
2. 绑定含 `02_编制说明.txt` / `新 文件.txt` / 重命名条目的仓库 → 列表
   显示原文；点击可看 diff 与预览；+/- 徽章正常；
3. 在绑定工作区的会话中让 LLM `office_create` 生成 Word → 产物面板立即出现
   该文档（事件驱动刷新），`artifacts` 表有行；
4. 点击该 Word 产物 → 默认 Word 版式（页宽/字体/表格/图片），可切换为文本；
5. `office_update` 编辑后产物大小/时间刷新、无重复行。

## 6. 风险与依赖

| 风险 | 缓解 |
|---|---|
| `-z` 解析改动影响 LLM `git_status` 工具输出（path 不再带 `old -> new`） | 增量字段 `old_path`；检索所有消费方（前端、prompt 示例） |
| win7 / py3.8：`List`/`Optional` 注解、pydantic v1 默认值 | 沿用文件头 `# ruff: noqa: UP006...` 风格；避免 v2-only 约束 |
| 非 git 返回 200 改变既有契约 | 旧测试 `test_non_repo_directory_fails_gracefully` 保留在工具层；路由测试改为新契约 |
| docx base64 撑大 content 响应 | 沿用 20MB 上限；超限仅返回 structured；可后续拆独立端点 |
| docx-preview 动态 import / DOMPurify 安全 | 复用 `/office` 页已验证的渲染 + 消毒链路；失败回退结构化 |
| 受管文档绝对路径泄露 | 只在后端落库，不回写 ToolResult |
| 错误文案透传影响其他命令的测试断言 | 保留后备 message 格式；分批更新断言 |

依赖：现有 `docx-preview`、`dompurify` 前端依赖；后端无新增依赖；
不改数据库 schema（`artifacts` 表已有 `workspace_path` / `format_spec` 列）。

## 7. 验收标准

- [ ] 非 git 工作区无 502 原始报错，有空态与操作引导；
- [ ] 中文/空格/重命名路径在列表、diff、预览三处均正确；
- [ ] 绑定工作区的 `office_create` / `office_update` 100% 产生/刷新 artifact；
- [ ] Word 产物默认 Word 版式渲染，且结构化视图可切换、失败可回退；
- [ ] 新增/更新测试全绿，win7 py38 分支回归通过；
- [ ] 无绝对受管路径回显到 LLM 结果。
