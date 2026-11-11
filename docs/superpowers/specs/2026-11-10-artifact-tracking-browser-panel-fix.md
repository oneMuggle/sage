# 产物追踪治理 + 浏览器面板修复 设计文档

> 日期：2026-11-10
> 状态：Draft
> 范围：backend/data/artifact_repo.py、backend/tools/file_tool.py、backend/tools/design_generate_tool.py、backend/tools/edit_tool.py、backend/tools/patch_tool.py、backend/tools/execute_code_tool.py、backend/tools/bash_tool.py、backend/design/design_studio.py、src/widgets/chat/RightPanel.tsx、src/features/artifacts/artifactApi.ts、src/widgets/chat/artifacts/*

## 1. 背景与目标

用户在 win7 安装包（alpha.77）中观察到三个问题：

1. **产物列表重复**：同一文件多次写入后产生多条记录
2. **HTML 产物未追踪**：设计生成的 HTML 文件不出现在产物面板
3. **浏览器面板显示不全**：右侧边栏的浏览器 Tab 只显示上半部分

根因分析发现产物追踪存在 6 个漏洞（详见下文），需要系统性治理。

## 2. 根因分析

### 2.1 产物重复
- `backend/data/artifact_repo.py:87-142` 的模块级 `record_artifact()` **总是 INSERT** 新行，按 `(session_id, path)` 不去重
- 数据库缺少 `(session_id, path)` UNIQUE 约束

### 2.2 产物追踪不全

| # | 漏洞 | 位置 | 影响 |
|---|---|---|---|
| 1 | 设计产物只写 `design_artifacts` 表，不桥接到 `artifacts` 表 | `backend/data/design_repo.py:118-160` | 设计 HTML 永远不会出现在产物面板 |
| 2 | `edit_tool`/`patch_tool` 修改文件只发 `workspace_changed` 事件，不触发 artifact 刷新 | `backend/tools/edit_tool.py`、`backend/tools/patch_tool.py` | 编辑产物后列表不更新 |
| 3 | `execute_code`/`bash_tool` 写文件无 hook | `backend/tools/execute_code_tool.py`、`backend/tools/bash_tool.py` | 代码生成的 HTML/其他文件无法追踪 |
| 4 | `.html` 的 `kind` 映射不一致：列表端 → `"code"`，内容端 → `"html"` | `file_tool.py:131` vs `artifact_routes.py:59-65` | 前端图标/过滤分组错位 |
| 5 | `current_tool_context()` 返回空 → 静默跳过，无日志 | `file_tool.py:157-159` | 后台任务/非 chat 场景产物丢失无感 |
| 6 | `_record_artifact_safely` 最外层 catch 只写 debug 日志 | `file_tool.py:172-173` | DB 错误导致产物丢失用户无感 |

### 2.3 浏览器面板显示不全
- `RightPanel.tsx` 头部高度 `h-12` = 48px = 3rem
- 内容区高度用 `h-[calc(100%-2.5rem)]` = 100% - 40px
- 8px 差异导致内容区溢出，`overflow-hidden` 裁剪底部

## 3. 修复方案

### 3.1 阶段 1：核心修复

#### 3.1.1 模块级 `record_artifact()` 增加去重

**改动**：`backend/data/artifact_repo.py` 的 `record_artifact()` 函数

**逻辑**：
```python
def record_artifact(path, session_id, tool_call_id=None, workspace_path=None, format_spec=None, conn=None):
    path = str(path)
    conn = conn or _conn()
    kind = detect_artifact_kind(path)
    
    # 按 (session_id, path) 查现有记录
    existing = conn.execute(
        "SELECT id FROM artifacts WHERE session_id = ? AND path = ?",
        (session_id, path),
    ).fetchone()
    
    if existing:
        # UPDATE 现有记录（更新 size/tool_call_id/created_at）
        size = _safe_size(path)
        conn.execute(
            "UPDATE artifacts SET tool_call_id = ?, size = ?, created_at = ? WHERE id = ?",
            (tool_call_id, size, _now_iso(), existing["id"]),
        )
        conn.commit()
        return existing["id"]
    else:
        # INSERT 新记录
        artifact_id = f"art_{uuid4().hex[:24]}"
        size = _safe_size(path)
        conn.execute(
            "INSERT INTO artifacts (id, session_id, tool_call_id, path, name, kind, size, workspace_path, format_spec) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, session_id, tool_call_id, path, _basename(path), kind, size, workspace_path, format_spec),
        )
        conn.commit()
        return artifact_id
```

**注意**：保留 `kind` 的现有映射（`.html` → `"code"`），阶段 2 统一修改。

#### 3.1.2 设计产物桥接到 `artifacts` 表

**改动**：`backend/tools/design_generate_tool.py`

在 `design_studio.generate()` / `iterate()` 调用后追加：
```python
from backend.tools.file_tool import _record_artifact_safely

# design_studio.generate() 返回 DesignArtifact 对象
artifact = studio.generate(project_id, prompt, ...)

# 桥接到 artifacts 表
_record_artifact_safely(
    resolved_path=str(artifact.file_path),
    size=len(artifact.html_content.encode("utf-8")),
    workspace_path=str(project.workspace_path),
    session_id=session_id,  # 从 tool context 读取
    tool_call_id=tool_call_id,
)
```

**前置**：需要确认 `design_studio.generate()` 返回的 artifact 对象包含 `file_path` 和 `html_content`。

#### 3.1.3 `edit_tool`/`patch_tool` 修改后刷新 artifact

**改动**：
- `backend/tools/edit_tool.py`：在写入文件后，调用 `record_artifact()`（已含去重）
- `backend/tools/patch_tool.py`：同上

```python
from backend.data.artifact_repo import record_artifact

# 修改文件后
record_artifact(
    path=str(modified_path),
    session_id=session_id,
    tool_call_id=tool_call_id,
    workspace_path=str(workspace_path),
)
```

#### 3.1.4 浏览器面板高度修复

**改动**：`src/widgets/chat/RightPanel.tsx`

```diff
- ? 'h-[calc(100%-2.5rem)] min-h-0 overflow-hidden'
+ ? 'h-[calc(100%-3rem)] min-h-0 overflow-hidden'
```

### 3.2 阶段 2：优化与补齐

#### 3.2.1 `execute_code`/`bash_tool` 执行后扫描工作区

**方案**：在工具执行前后对工作区目录做 snapshot diff，新增/修改的文件记录为 artifact。

**实现**：
```python
# 通用 helper：backend/tools/_workspace_scan.py
def snapshot_workspace(workspace_path: Path) -> dict[str, float]:
    """返回 {relative_path: mtime}"""
    return {
        str(p.relative_to(workspace_path)): p.stat().st_mtime
        for p in workspace_path.rglob("*")
        if p.is_file()
    }

def diff_and_record(
    workspace_path: Path,
    before: dict[str, float],
    session_id: str,
    tool_call_id: str,
):
    after = snapshot_workspace(workspace_path)
    for rel_path, mtime in after.items():
        if rel_path not in before or before[rel_path] < mtime:
            # 新增或修改
            abs_path = workspace_path / rel_path
            _record_artifact_safely(
                resolved_path=str(abs_path),
                size=abs_path.stat().st_size,
                workspace_path=str(workspace_path),
                session_id=session_id,
                tool_call_id=tool_call_id,
            )
```

**调用点**：
- `execute_code_tool.py`：`execute()` 前后各 snapshot 一次
- `bash_tool.py`：同上

**注意**：大工作区（>10k 文件）的 snapshot 可能慢，需要加超时或跳过。

#### 3.2.2 前端 `kind="html"` 统一

**改动**：
1. `src/features/artifacts/artifactApi.ts`：`ArtifactKind` 类型联合添加 `"html"`
2. `src/widgets/chat/artifacts/ArtifactsSection.tsx`：`FILTER_GROUPS` 添加 html 组
3. `src/widgets/chat/artifacts/ArtifactRow.tsx`：`KIND_ICONS` 添加 html 图标

**后端**：`artifact_repo.py` 的 `_EXT_KIND_MAP` 把 `.html`/`.htm` 映射从 `"code"` 改为 `"html"`。

#### 3.2.3 日志升级

**改动**：`backend/tools/file_tool.py`

```diff
- except Exception:  # noqa: BLE001
-     logger.debug("write_file: 记录产物失败", exc_info=True)
+ except Exception:  # noqa: BLE001
+     logger.warning("write_file: 记录产物失败", exc_info=True)
```

同理，`session_id` 缺失时：
```diff
  if not session_id:
+     logger.warning("_record_artifact_safely: session_id 缺失，跳过记录")
      return
```

## 4. 涉及文件清单

### 阶段 1
- `backend/data/artifact_repo.py` — `record_artifact()` 去重
- `backend/tools/design_generate_tool.py` — 桥接设计产物
- `backend/tools/edit_tool.py` — 修改后记录 artifact
- `backend/tools/patch_tool.py` — 同上
- `src/widgets/chat/RightPanel.tsx` — 高度修复

### 阶段 2
- `backend/tools/_workspace_scan.py` — **新增**，工作区快照 helper
- `backend/tools/execute_code_tool.py` — 执行前后 snapshot
- `backend/tools/bash_tool.py` — 同上
- `backend/tools/file_tool.py` — `_EXT_KIND_MAP` `.html` → `"html"`，日志升级
- `backend/data/artifact_repo.py` — `_EXT_KIND_MAP` 同步修改
- `src/features/artifacts/artifactApi.ts` — `ArtifactKind` 添加 `"html"`
- `src/widgets/chat/artifacts/ArtifactsSection.tsx` — `FILTER_GROUPS` 添加 html
- `src/widgets/chat/artifacts/ArtifactRow.tsx` — `KIND_ICONS` 添加 html

## 5. 测试要点

### 单元/集成测试
- `record_artifact()` 去重：同路径写两次，artifacts 表只有一行
- 设计产物桥接：`design_generate` 工具执行后，`artifacts` 表有对应行
- `edit_tool`/`patch_tool` 后 artifact 的 `created_at` 更新
- 浏览器面板高度：E2E 截图对比

### 手动测试
- 设计工具生成 HTML，检查产物面板是否显示
- 编辑一个已有 artifact 的 HTML，检查列表是否刷新
- `execute_code` 写 HTML，检查产物面板
- 多次 `write_file` 同一路径，检查去重
- 浏览器 Tab 打开网页，检查底部是否被截断

## 6. 风险评估

| 风险 | 缓解 |
|---|---|
| 去重逻辑影响已有重复数据 | 不改数据库 schema，只改写入逻辑；历史重复数据保留 |
| 设计产物桥接缺少 session_id | 从 `current_tool_context()` 读取，失败时 warning 日志 |
| 工作区扫描性能 | 大工作区加超时（>5s 跳过），或只扫描一级目录 |
| `kind="html"` 改动影响现有数据 | 历史数据 `kind="code"` 保留，新数据用 `"html"`；前端兼容两种 |

## 7. 实施顺序

建议分为 2 个 PR：
- **PR A**：阶段 1 全部（4 个核心修复）
- **PR B**：阶段 2 全部（4 个优化）
