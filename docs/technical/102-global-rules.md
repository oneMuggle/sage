# 全局规则 UI（~/.sage/SAGE.md）

> P0 / G1（2026-10-27）。设置页新增「全局规则」Tab，让用户在 UI 内查看 / 编辑 /
> 保存 / 删除跨工作区生效的全局规则文件。

## 一、定位与上下文

Sage 的 system prompt 按层拼装（详见 [58-项目上下文沉淀](./58-project-context-aggregation.md)）：

| 层 | 来源 | 作用域 |
|----|------|--------|
| L0 | 内置基础提示 | 全局 |
| **L1** | **`~/.sage/SAGE.md`** | **跨工作区（本专题）** |
| L2 | 目录树中逐级 `CLAUDE.md` / `SAGE.md` | 目录 |
| L3 | 项目结构化配置 | 项目 |
| L4 | 会话上下文 | 会话 |

L1 的读取点在 `backend/chat/project_context.py:_user_level_entries()`：`read_text()` +
按 `PER_FILE_CHAR_CAP = 8000` 字符截断后注入，**不做内容消毒**。
本专题只是给这个既有文件加一个读写 UI，不改注入链路。

非目标：`.sage/rules/*.md` 规则目录（G2）、双向同步（G3）、预算可配置（G4）。

## 二、后端 API

路由文件 `backend/api/global_rules_routes.py`，经 `legacy_routes.py`
`include_router` 挂载，`main.py` 统一加 `/api/v1` 前缀。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/settings/global-rules` | 读取全文 + 状态 |
| PUT | `/api/v1/settings/global-rules` | 原子写入（body 只接受 `content`） |
| DELETE | `/api/v1/settings/global-rules` | 删除文件（幂等） |
| GET | `/api/v1/settings/global-rules/templates` | 3 个静态起步模板 |

### GET 响应

```json
{
  "content": "# 全局规则\n...",
  "path": "/home/<user>/.sage/SAGE.md",
  "exists": true,
  "size": 1234,
  "mtime": 1761000000,
  "truncated": false,
  "char_limit": 8000,
  "symlink": false
}
```

- 文件不存在 → `exists=false` / `content=""` / `size=0` / `mtime=null`
- 读失败（权限、解码）→ **200** + `exists=false` + `read_error`，不抛 500
- `truncated=true` 表示 `size > 8000`，注入时会被截断；`content` 仍返回全文供编辑
- `symlink=true` 表示目标路径是符号链接（读取跟随 realpath，仅标记）
- `mtime` 是整数 epoch 秒，前端以 `new Date(mtime * 1000)` 渲染

### 错误响应契约

所有 4xx/5xx 统一为：

```json
{"detail": {"type": "<错误类型码>", "message": "<可读主句>", "reason": "<补充原因>"}}
```

| 状态 | `type` | 触发条件 |
|------|--------|----------|
| 413 | `content_too_large` | `len(content.encode("utf-8")) > 65536` |
| 422 | `empty_content` | `content.strip()` 为空 |
| 422 | `unsafe_content` | 安全扫描 `blocked=True`，附 `reason` + `threat_level` |
| 422 | `symlink_target` | 目标路径是符号链接 |
| 500 | `write_failed` | 写入 OSError |
| 500 | `delete_failed` | 删除 OSError |

**`type` 与 `reason` 是两个不同字段**：前端按 `type` 分支选本地化文案，
仅 `unsafe_content` 时把 `reason`（威胁描述）插入 `{reason}` 占位符。

## 三、安全模型

### 3.1 路径硬编码

`_global_rules_path()` 返回 `Path.home() / ".sage" / "SAGE.md"`，函数内计算，
**不接受任何客户端参数**。渲染进程只能传 `content`：

- Pydantic `GlobalRulesUpdateRequest` 只有 `content` 字段
- Electron `body` selector 是 `(a) => ({ content: a.content })`，显式剥掉 `path` / `exists` 等字段
- 测试 `commandRoutes.globalRules.test.ts` 断言塞入 `path: '/etc/passwd'` 后 body 只剩 `content`

### 3.2 安全扫描（护栏，非安全边界）

写入前执行 `get_scanner().scan(content, level="all")`。

刻意**不用** `scan_write()` 的 strict 档：其持久化攻击模式（`always respond`、
`remember to always`、`in future conversations,`）恰是全局规则的正常写法
（例如「Always respond in Chinese」），用于用户自撰规则会误杀。
注入模式（`<|system|>`、`[INST]`、`ignore previous instructions`）与敏感信息形状串仍然拦截。

**信任边界说明**：真正的边界是文件系统权限 —— `~/.sage/SAGE.md` 只有登录用户能写。
能在本机写这个文件的人本来就能直接编辑它，UI 只是更方便的入口，没有扩大攻击面。
扫描器拦的是"看起来像提示注入"的字面量，拦不住语义级恶意规则（例如中文写成的
"先读取 ~/.ssh/id_rsa 再输出"）—— 那属于用户写给自己的规则，不在防护目标内。
若未来需要防"共享机器上其他账号写入"，正确控制点是 `~/.sage` 目录权限
（已收紧到 `0o700`）+ 操作系统账号隔离。

### 3.3 原子写

```python
parent.mkdir(parents=True, exist_ok=True)
with contextlib.suppress(OSError):
    parent.chmod(0o700)          # 已存在的 ~/.sage 权限也可能过宽，显式收紧
fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".SAGE.md.", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(content)
Path(tmp_name).replace(path)     # = os.replace，原子替换目录项
```

- `mkstemp` 创建的文件默认权限 `0o600`，`replace` 保留该权限
- 失败时 `os.unlink(tmp_name)` 清理临时文件
- `newline="\n"` 避免 Windows 上写出 `\r\n` 造成 diff 噪音

### 3.4 符号链接

写入前 `path.is_symlink()` → 422 拒绝，防止覆写 `~/.ssh/id_rsa` 等目标。

**TOCTOU 已验证安全**：`Path.replace()` 在目标路径是符号链接时，替换的是
**目录项本身**，不跟随链接。实验证实：

```
dst 指向 /tmp/innocent_target.txt 的符号链接
src.replace(dst)
→ dst 变成新写入的普通文件（不再是符号链接）
→ /tmp/innocent_target.txt 内容保持不变
```

POSIX `rename(2)` 自 POSIX.1-2008 起对此有明确保证；Windows `MoveFileEx` 同语义。
因此无需追加 `O_NOFOLLOW` 之类的额外防护。

## 四、Electron IPC

`electron/commandRoutes/settings.ts` 新增 4 条命令，走通用 `invoke(cmd, args)` 通道
（`electron/preload.ts` 无需改动）：

```ts
global_rules_get:       { method: 'GET',    path: () => '/api/v1/settings/global-rules' },
global_rules_save:      { method: 'PUT',    path: () => '/api/v1/settings/global-rules',
                          body: (a) => ({ content: a.content }) },
global_rules_delete:    { method: 'DELETE', path: () => '/api/v1/settings/global-rules' },
global_rules_templates: { method: 'GET',    path: () => '/api/v1/settings/global-rules/templates' },
```

新增命令后必须重新生成 `electron/ipc-manifest.json`（`npm run ipc:manifest`），
否则 `ipc-contract.test.ts` 报 `manifest is stale`。

## 五、前端

| 文件 | 职责 |
|------|------|
| `src/shared/api/globalRulesApi.ts` | client 封装 + `GlobalRulesError`（携带 `status` / `type` / `reason`）+ 状态规整 |
| `src/pages/settings/GlobalRulesTab.tsx` | 编辑器（`<textarea>`）+ 状态横幅 + 字符预算 + 模板按钮 |
| `src/pages/settings/Settings.tsx` | tab 条目 + 渲染分支 |
| `src/pages/settings/settingsNavigation.ts` | `visibleTabs` 加 `global-rules` |
| `src/pages/settings/settingsPresentation.ts` | GROUPS `tools` 组加 `global-rules` |
| `src/pages/settings/settingsSearchIndex.ts` | `SettingsTabKey` 联合类型 + 3 条搜索条目 |

### 交互要点

- **草稿与脏标记**：`isDirty = state !== null && draft !== state.content`；保存 / 撤销按钮随 `isDirty` 禁用
- **字符预算**：实时显示 `draft.length`；超过 `GLOBAL_RULES_CHAR_LIMIT = 8000` 显示超限提示，
  但**不阻止保存**（后端上限是 64KB 字节，注入侧才按 8000 字符截断）
- **「已保存」提示 3 秒回 idle**：timer id 存 `useRef`，连续保存时先 `clearTimeout`,
  避免旧 timer 把新一次的 `saved` 提前清掉
- **错误渲染**：`GlobalRulesError.type` 分支选文案；未知 type → 本地化兜底
  `settings.global_rules.error.generic`，不透出后端原始字符串

### 错误文案映射

| `type` | i18n key |
|--------|----------|
| `empty_content` | `settings.global_rules.error.empty_content` |
| `content_too_large` | `settings.global_rules.error.content_too_large` |
| `unsafe_content` | `settings.global_rules.error.unsafe_content`（`{reason}` 插值） |
| `symlink_target` | `settings.global_rules.error.symlink_target` |
| `write_failed` | `settings.global_rules.error.write_failed` |
| 其它 | `settings.global_rules.error.generic` |

## 六、测试地图

| 层 | 文件 | 用例数 |
|----|------|--------|
| 后端 | `backend/tests/unit/api/test_global_rules_routes.py` | 13 |
| IPC | `electron/__tests__/commandRoutes.globalRules.test.ts` | 5 |
| client | `src/shared/api/__tests__/globalRulesApi.test.ts` | 12 |
| UI | `src/pages/settings/__tests__/GlobalRulesTab.test.tsx` | 12 |

IPC 测试独立成文件（不放 `commands.test.ts`），因为后者受
`architecture-baseline.json` 行数基线约束（与 `commands.sessionRules.test.ts` 同款处理）。

## 七、Win7 / Python 3.8 兼容

`backend/api/global_rules_routes.py` 首行：

```python
# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
```

- `from __future__ import annotations` + `typing.Dict` / `List`，无 PEP 604 / 内置泛型
- `BaseModel` + `content: str = ""` 在 pydantic v1 / v2 下行为一致
- `pathlib` / `tempfile` / `os.replace` 在 py3.8 全平台可用
- 依赖的 `backend.memory.safety.get_scanner()` 在 win7 分支存在且签名一致
  （`scan(content, level="all")`）

`python3.8 -m py_compile` 通过；cherry-pick 到 `release/win7` 无需代码适配。
