# LLM Wiki 项目创建/打开：原生文件夹选择器

> 日期：2026-06-27
> 状态：待用户审阅
> 作者：Claude (brainstorming 流程产出)

## 1. 背景与目标

### 1.1 当前状态

Sage 的 LLM Wiki 模块在 `src/widgets/wiki/WikiProjectPicker.tsx` 提供两个入口：

| 入口 | 当前实现 | 用户体验问题 |
|---|---|---|
| 创建项目 (`mode='create'`) | `<input type="text">` 手动键入 `basePath` | 路径长、易拼错、不知当前目录有什么 |
| 打开项目 (`mode='open'`) | `<input type="text">` 手动键入 `openPath` | 同上 |

代码里完全没有调用任何原生文件夹选择对话框（Electron `dialog.showOpenDialog`、Tauri `plugin-dialog`、`webkitdirectory` 均未使用）。`electron/main.ts` 也没有 `import { dialog }` —— 这层能力从未被启用。

后端已经有 `wiki_routes.py` 的 `POST /wiki/project/create`、`POST /wiki/project/open`、`GET /wiki/project/list` 三个接口。`listWikiProjects(base_path)` 在 API 客户端 `src/shared/api-client/wiki.ts:99-101` 里已封装，但**前端 UI 从未调用过**。

### 1.2 目标

1. **一键选目录**：在「创建项目」「打开项目」表单上提供「浏览…」按钮，调用原生文件夹选择对话框
2. **最近项目记忆**：把成功创建/打开的项目路径持久化到后端 JSON 文件，下次打开 dialog 默认定位到最近项目的父目录
3. **实时校验**：选完路径后立即调后端预检查，UI 给出可视化反馈（可创建 / 已存在 / 无权限 / 不是 wiki 项目）
4. **不破坏现有**：现有 `POST /project/create` 和 `POST /project/open` 行为不变；老用户首次启动后自动创建 `recent-projects.json`

### 1.3 非目标

- 不重构 wiki 数据模型、不改 `wiki/` 目录结构、不动 HNSW/向量库
- 不引入 SQLite（项目当前 wiki 路径无 DB 基础设施，JSON 文件足够）
- 不把 dialog 调用经后端转发（架构上不可行 —— 见 §3.2）
- 不做 Win7 兼容性特殊处理（Electron 21.4.4 + Python 3.8 跨平台行为已验证一致）
- 不做多用户/多设备同步（单用户本机应用，YAGNI）

### 1.4 约束

- 主分支（main）技术栈：Electron 21.4.4 + Python 3.11 + FastAPI 后端
- LTS 分支（release/win7）技术栈：Electron 21.4.4 + Python 3.8，EOL 2027-12-13
- 不引入新的前端重型依赖（保持现有栈：React + zustand + lucide-react + Tailwind）
- 后端 IPC 桥（`electron/preload.ts` 的 `sage:invoke` 通道）已稳定，新增独立 IPC channel 是低成本操作
- Electron 主进程是唯一能调原生 dialog 的进程（Chromium 安全模型约束）

## 2. 决策摘要

| 决策点 | 选择 | 理由 |
|---|---|---|
| UI 形态 | 保留 `<input>` + 加「浏览…」按钮 | 用户决策：可粘贴、可看清当前值 |
| 默认起始位置 | 最近项目的父目录 | 用户决策：体验最连贯 |
| 创建模式语义 | 选项目目录本身，允许 `createDirectory` | 用户决策；与后端当前行为一致 |
| 最近项目存储 | 后端 JSON 文件（非 SQLite） | 用户决策；项目当前无 DB 基础设施，JSON 足够 |
| 校验时机 | 路径变更后 debounce 300ms 异步预检查 | 用户决策：实时反馈 + 不阻塞 UI |
| Dialog 触发方式 | Electron 主进程直接 IPC，不经后端 HTTP | 后端进程访问不到 BrowserWindow |
| Tauri 迁移 | 不考虑 | Phase 1 (2026-06-13) 已主动迁移离 Tauri |
| 测试 | 后端 pytest + 前端 Vitest + Playwright E2E | 用户决策 |
| 回滚 | 特性开关 `wiki.useFolderPicker` | 万一出问题快速回退到「纯文本输入」 |

## 3. 架构设计

### 3.1 数据流总览（创建项目）

```
┌──────────────────┐                                ┌─────────────────────┐
│  React Frontend  │                                │   Electron Main     │
│                  │  invoke('sage:dialog:         │                     │
│  WikiProject     │       select-directory',      │  dialog.showOpen    │
│  Picker          │       {intent, defaultPath})   │  Dialog({...})      │
│                  ├───────────────────────────────►│                     │
│  ┌────────────┐  │                                │  properties:        │
│  │ Browse btn │  │                                │   ['openDirectory', │
│  └────────────┘  │                                │    'createDirectory']│
│                  │◄───────────────────────────────┤                     │
│  setBasePath(p)  │   (path or null)               └─────────────────────┘
│                  │
│  debounce 300ms  │       GET /wiki/project/check?path=...&intent=create
│  fetch check     ├──────────────────────────────►┌─────────────────────┐
│                  │                                │  FastAPI Backend    │
│  显示校验徽章     │◄──────────── {check result} ───│                     │
│                  │                                │  recent_projects.py │
│                  │                                │  (stat + access)    │
│  点「创建」       │       POST /wiki/project/create                         │
│                  ├──────────────────────────────►│                     │
│                  │                                │  mkdir + write      │
│                  │◄───────── {ProjectInfo} ───────┤                     │
│                  │       POST /wiki/recent-projects/record               │
│                  ├──────────────────────────────►│                     │
│                  │                                │  recent_projects.py │
│  关闭 picker     │◄───────────── 204 ─────────────┤  save_recent()      │
└──────────────────┘                                └─────────────────────┘
```

### 3.2 为什么不通过后端 HTTP 触发 dialog

后端 FastAPI 进程**不能**访问 Electron 的 `BrowserWindow`，而 `dialog.showOpenDialog` 必须传 `BrowserWindow` 才能让 dialog 模态附着在主窗口上（避免用户在文件选择器打开时操作主窗口）。即使不传 window 也会丢失模态体验，且 Python 进程根本没有 Electron runtime 的引用。因此 dialog 必须经主进程触发，无法绕开 IPC。

### 3.3 文件 / 模块清单

| 新增 / 修改 | 路径 | 说明 |
|---|---|---|
| 修改 | `electron/main.ts` | 新增 `ipcMain.handle('sage:dialog:select-directory')` |
| 修改 | `electron/preload.ts` | 新增 `selectDirectory(opts)` + 类型声明 |
| 新增 | `backend/storage/recent_projects.py` | `RecentProject` 模型 + `user_data_dir()` + CRUD |
| 修改 | `backend/api/wiki_routes.py` | 新增 3 个路由（见 §4.1） |
| 修改 | `src/widgets/wiki/WikiProjectPicker.tsx` | 加「浏览…」按钮 + 校验徽章 + 默认起始位置 |
| 修改 | `src/shared/api-client/wiki.ts` | 新增 3 个 client 函数 |
| 修改 | `src/shared/types/wiki.ts` | 新增类型（`ProjectCheckResponse` 等） |
| 新增 | `backend/tests/unit/test_recent_projects.py` | 11 个用例 |
| 新增 | `backend/tests/unit/test_project_check.py` | 9 个用例 |
| 新增 | `src/widgets/wiki/__tests__/WikiProjectPicker.test.tsx` | 12 个用例 |
| 新增 | `e2e/wiki-folder-picker.spec.ts` | 3 个 Playwright 用例 |

## 4. 接口契约

### 4.1 后端 HTTP 路由（`backend/api/wiki_routes.py`）

```python
class ProjectCheckResponse(BaseModel):
    exists: bool
    writable: bool
    is_project: bool       # 是否含 wiki/ 子目录
    parent_writable: bool  # 当 exists=False 时，父目录是否可写
    warning: str | None    # 非阻塞提示（如"将建立 wiki/ 结构"）
    error: str | None      # 阻塞错误（如"父目录无写权限"）

@router.get("/project/check", response_model=ProjectCheckResponse)
async def check_project(path: str, intent: Literal["create", "open"]):
    """预检查路径，不实际创建/打开"""

class RecordRecentRequest(BaseModel):
    path: str
    name: str
    intent: Literal["create", "open"]

@router.get("/recent-projects", response_model=list[RecentProject])
async def get_recent_projects():
    """返回最近 10 条项目（按 opened_at 倒序）"""

@router.post("/recent-projects/record", status_code=204)
async def record_recent_project(req: RecordRecentRequest):
    """成功创建/打开后由前端调用，去重 + 移到首位 + 截断到 10 条"""
```

### 4.2 Electron IPC 契约（`electron/main.ts` + `electron/preload.ts`）

```ts
// 渲染进程调用：
window.electronAPI.selectDirectory({
  intent: 'create' | 'open',
  defaultPath?: string,  // 可选，OS 不识别时忽略
}): Promise<string | null>;

// 行为：
//   - intent='create': properties=['openDirectory', 'createDirectory']
//   - intent='open':   properties=['openDirectory']
//   - 用户取消: 返回 null
//   - 用户选择: 返回绝对路径字符串
```

### 4.3 状态机（前端 `WikiProjectPicker`）

```
                 ┌──────┐
                 │ idle │ ◄─────────────────────┐
                 └──┬───┘                       │
                    │ path 变化 / 选中路径      │ 用户取消 / 清空
                    ▼                           │
                 ┌─────────┐                    │
                 │checking │ ─── fetch OK ────►├─────────┐
                 └────┬────┘                    ▼         │
                      │                          ┌───┐    │
                      │                          │ ok│    │
                      ▼                          └─┬─┘    │
              ┌────────────┐     warn              │      │
              │  网络/5xx  │ ◄── fetch 4xx/5xx ────┤      │
              └─────┬──────┘                       │      │
                    │                              │      │
                    ▼                              ▼      │
              ┌──────────┐                  ┌─────────┐   │
              │  error   │ ◄── check 业务 ──┤  warn   │   │
              └──────────┘     返回 error   └─────────┘   │
                                                          │
                                       path 清空 ────────┘
```

按钮 enabled 条件：`checkStatus !== 'error' && path !== '' && checkStatus !== 'checking'`

## 5. 错误处理矩阵

| 场景 | 检测点 | 用户可见 | 后端动作 |
|---|---|---|---|
| 用户取消 dialog | IPC 返回 `null` | 输入框值不变 | 无 |
| 路径不存在 + 父目录不可写 | `/project/check` | 红色 ✗ | 200 + `{writable:false}` |
| 路径不存在 + 父目录可写 | `/project/check` | 绿色 ✓ | 200 + `{exists:false, parent_writable:true}` |
| 路径已存在但无 `wiki/`（create） | `/project/check` | 黄色 ⚠ | 200 + `{warning:"将建立结构"}` |
| 路径已存在但含 `wiki/`（create） | `/project/check` | 红色 ✗ | 200 + `{error:"已经是 wiki 项目，请用「打开」"}` |
| 路径已存在但无 `wiki/`（open） | `/project/check` | 红色 ✗ | 200 + `{error:"不是 wiki 项目"}` |
| 路径存在但是文件（非目录） | `/project/check` | 红色 ✗ | 200 + `{error:"不是目录"}` |
| 后端预检查超时 / 5xx | fetch catch | 红色 ✗ + 重试 | 不变 |
| 提交时 backend 报错（磁盘满等） | POST 响应非 2xx | Toast | 不变 |
| `recent-projects.json` 损坏 | `load_recent` 异常 | 起始位置降级 OS 默认 | 备份为 `.bak` |
| Electron IPC 抛错 | 异常冒泡 | Toast | 无 |
| `SAGE_USER_DATA_DIR` 未设 | 缺省分支 | 无感知 | 用 `~/.config/sage` |

## 6. 测试策略

### 6.1 后端 pytest（21 用例）

**`tests/unit/test_recent_projects.py`（11）**：
1. 文件不存在 → `[]`
2. 文件为空 → `[]`
3. 文件损坏 → 备份 `.bak` + `[]`
4. 原子写（崩溃不留半截）
5. 新增条目 → 长度 +1
6. 重复 path → 移到首位
7. 超过 MAX_RECENT (10) → 截断
8. 列表为空 → `most_recent_parent = None`
9. 列表非空 → 返回第一条的 parent
10. 父目录已删 → 容错返回 `None`
11. 环境变量优先级

**`tests/unit/test_project_check.py`（9）**：
12. create + 不存在 + 父可写 → ok
13. create + 不存在 + 父不可写 → error
14. create + 已存在 + 含 wiki/ → error（"已经是 wiki 项目"）
15. create + 存在但是文件 → error
16. open + 不存在 → error
17. open + 非目录 → error
18. open + 存在 + 无 wiki/ → error
19. open + 存在 + 有 wiki/ → ok
20. intent 缺失/非法 → 422
21. path 含 `~` → expanduser

### 6.2 前端 Vitest（12 用例）

**`WikiProjectPicker.test.tsx`**：
21. mount → `GET /recent-projects`
22. 最近列表非空 → dialog defaultPath = parent
23. 最近列表为空 → dialog defaultPath = undefined
24. `basePath` 变化 → debounce 300ms 后调 check
25. 300ms 内多次变化 → 只发一次请求
26. `checkStatus='error'` → 创建按钮 disabled
27. `checkStatus='ok'` + 非空 → 启用
28. 点「浏览…」→ 调 `electronAPI.selectDirectory`
29. 返回 null → 输入框不变
30. 返回路径 → 输入框更新
31. 创建成功 → `POST /recent-projects/record`
32. 校验徽章 4 状态文案/图标/颜色正确

### 6.3 Playwright E2E（3 用例）

**`e2e/wiki-folder-picker.spec.ts`**：
33. mock `electronAPI.selectDirectory` → 点按钮 → 输入框回填 → check 徽章 ok → 创建成功
34. 取消 dialog → 输入框不变
35. 第二次打开 dialog → defaultPath = 上次 parent

### 6.4 覆盖率目标

- 后端新增模块 ≥ 90%
- 前端状态机分支 100%
- E2E happy path + 1 error path

## 7. 跨分支兼容性

| 分支 | 影响 | 处理 |
|---|---|---|
| `main` (Python 3.11) | 完全支持 | 正常发版 |
| `release/win7` (Python 3.8) | `Literal` 需 `from __future__ import annotations` 或用 `Union[str, str]` 兼容 | 在 `wiki_routes.py` 顶部加 `from __future__ import annotations`（若当前没有） |

`Path.expanduser()` / `os.access(path, os.W_OK)` 在 Win7 + Python 3.8 上行为与 main 一致，无需特殊处理。

## 8. 发布与回滚

### 8.1 不需要数据迁移

- 不改 wiki 项目结构
- 不动 HNSW / 向量库 / chat session
- `recent-projects.json` 首次启动自动创建（缺失分支返回 `[]`）

### 8.2 发布顺序

1. 特性开关 `wiki.useFolderPicker: boolean`（默认 `true`）—— 通过现有 `appSettings` 暴露
2. dev 验证 → main 跑 CI → 灰度
3. CHANGELOG `### Added` 条目

### 8.3 回滚预案

| 触发条件 | 动作 |
|---|---|
| `selectDirectory` IPC 在某 OS 抛错 | 关特性开关 `wiki.useFolderPicker=false`（不改代码） |
| `recent-projects.json` 损坏 | `load_recent` 已隔离，备份为 `.bak` |
| `/wiki/project/check` 性能问题 | 前端 debounce 300ms 已限流；可加后端 rate limit |

### 8.4 监控（建议）

- `sage:dialog:select-directory` 调用次数 vs POST `/project/create` 次数（转化率）
- `/wiki/project/check` P50/P95 延迟
- `recent-projects.json` 损坏次数
- 取消 dialog 比例（过高说明 UX 还有问题）

## 9. 实施清单（供 writing-plans skill 拆分）

- [ ] 后端：`recent_projects.py` 模块（含 `user_data_dir()` + atomic write + 容错）
- [ ] 后端：`wiki_routes.py` 新增 3 个路由
- [ ] 后端：`test_recent_projects.py` 11 用例
- [ ] 后端：`test_project_check.py` 9 用例
- [ ] Electron：`main.ts` 新增 IPC handler + `dialog` import
- [ ] Electron：`preload.ts` 新增 `selectDirectory` API + 类型
- [ ] 前端：`shared/types/wiki.ts` 新增类型
- [ ] 前端：`shared/api-client/wiki.ts` 新增 3 个 client 函数
- [ ] 前端：`WikiProjectPicker.tsx` 加按钮 + 状态机 + debounce + 徽章
- [ ] 前端：`WikiProjectPicker.test.tsx` 12 用例
- [ ] E2E：`wiki-folder-picker.spec.ts` 3 用例
- [ ] CHANGELOG 条目
- [ ] `appSettings` 加 `wiki.useFolderPicker` 特性开关
