# 115 · 新会话页工作区绑定跳过机制

> 2026-11-04 · fix/skip-workspace-binding-when-none

## 问题背景

用户在新会话页选择"不绑定项目"后，提交消息仍被自动绑定到某个项目。根因：前端 `projectId = null` 只表示"不绑定到项目实体"，后端缺少"跳过工作区解析"语义，`DefaultWorkspaceResolver` 解析链（`user_preference → detected_root → scratch`）会尽力找一个目录绑定，违背用户意图。

## 解决方案

引入显式 `skip_workspace_binding` 信号贯穿前后端：

```
用户选择"不绑定项目" → projectId = null
  ↓
Welcome.tsx handleSubmit → createSession(effectiveProjectId === null)
  ↓
store.createSession(skipBinding = true)
  ↓ invoke('create_session', { skipWorkspaceBinding: true, detectedRoot: null })
  ↓
后端 POST /sessions → skip_workspace_binding=True
  ↓
legacy_session_routes.create_session: if not data.skip_workspace_binding: resolver.resolve_default_workspace(...)
  ↓
workspace_binding = None → 会话不出现在项目分区
```

## 修改文件

### 后端

**`backend/api/legacy_models.py`**：
```python
class SessionCreate(BaseModel):
    title: str = "新对话"
    parent_id: Optional[str] = None
    detected_root: Optional[str] = None
    skip_workspace_binding: bool = False  # 新增
```

**`backend/api/legacy_session_routes.py`**：
```python
workspace_binding = None
if not data.skip_workspace_binding:
    try:
        resolver = DefaultWorkspaceResolver()
        resolution = resolver.resolve_default_workspace(detected_root=data.detected_root)
        if resolution is not None:
            conn = get_database().get_connection()
            bind_session_workspace(conn, session.id, resolution.path)
            workspace_binding = {...}
    except Exception as exc:
        logger.warning("create_session: workspace resolution/bind failed (fail-open)", ...)
```

### 前端

**`src/shared/lib/store.ts`**：
```typescript
createSession: async (skipBinding = false) => {
  let detectedRoot: string | null = null;
  if (!skipBinding) {
    // skipBinding=true 时不嗅探，避免 detected_root 触发自动绑定
    try {
      detectedRoot = (await window.electronAPI?.getDetectedProjectRoot?.()) ?? null;
    } catch (err) { ... }
  }
  const session = await invoke<Session>('create_session', {
    title: '新对话',
    detectedRoot,
    skipWorkspaceBinding: skipBinding,
  });
  ...
}
```

**`src/pages/Welcome.tsx`**：
```typescript
sessionId = effectiveProjectId
  ? (await projectApi.createSession(effectiveProjectId)).session.id
  : await createSession(effectiveProjectId === null);  // null → skipBinding=true
```

## API 契约

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip_workspace_binding` | `bool` | `false` | `true` 时跳过整个工作区解析链，不绑定任何工作区；`false` 时保持现有解析链（向后兼容） |

## 主流应用对标

| 应用 | 无项目模式 | 自动嗅探 | 显式选择优先 |
|------|------------|----------|--------------|
| Cursor | ✓ 不自动绑定 | ✗ | ✓ |
| Cline | ✓ 可清除绑定 | ✗ | ✓ |
| Windsurf | ✓ 默认无上下文 | ✗ | ✓ |
| Claude.ai | 无项目概念 | — | — |
| ChatGPT | 无项目概念 | — | — |
| **Sage** | ✓ `skip_binding=true` | ✓ 但用户拒绝时跳过 | ✓ |

## 边界与风险

1. **工具调用 403 风险**：无工作区会话调用 `read_file`/`list_dir` 等工具时可能 403。工具调用前应有"请选择工作区"提示（已有机制）。
2. **向后兼容**：`skip_workspace_binding` 默认 `false`，现有客户端不受影响。
3. **`user_preference` 污染**：本次修复不改变 `open_project` 自动写入 `last_workspace_path` 的行为（阶段 2 待优化）。

## 测试覆盖

- **后端**：`backend/tests/integration/test_skip_workspace_binding.py`
  - `test_create_session_skip_workspace_binding_true`：`skip_workspace_binding=True` 时 `resolve_default_workspace` 不被调用
  - `test_create_session_skip_workspace_binding_false`：`skip_workspace_binding=False` 时正常走解析链
  - `test_create_session_default_calls_resolver`：不传字段时默认走解析链（向后兼容）

- **前端**：`src/pages/__tests__/Welcome.skipWorkspaceBinding.test.tsx`
  - `calls createSession(true) when projectId is null`：用户未选择项目时传递 `skipBinding=true`
  - `calls createSession(false) or createSession() when projectId is selected`：未来可扩展

## 未来阶段

- **阶段 2**：移除 `open_project` 自动写入 `last_workspace_path` 的行为，工作区选择器独立
- **阶段 3**：`detected_root` 降级为提示，用户确认后才绑定
