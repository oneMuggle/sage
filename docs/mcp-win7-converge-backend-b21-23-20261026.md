# Win7 收敛 · backend 批次 21–23 复盘（2026-10-26）

> 上游：`docs/mcp-win7-converge-backend-b16-18-20261026.md`（批次 16–20）。
> 本文记录批次 21（权限链，被 #2549 取代）、批次 22（backend 三方重扫 → 零漂移）、
> 批次 23（`nobase` 桶第 1 批）的执行结果与判定台账，以及本轮暴露的闸门缺口。

## 1. 批次 21 — 权限规则前后端成对（关闭）

| 项 | 内容 |
|---|---|
| 分支 | `chore/win7-converge-permission-pair` |
| 范围 | 9 文件（后端 `permission_routes.py` / 前端 `permissionApi.ts` / `PermissionRulesManager.tsx` / i18n） |
| 结局 | **#2553 closed**（注释 issuecomment-6413912461 之外的说明见下） |

并行线上 **#2549**（`2fbaa8b4`）把整条 R99–R106 权限链同步进 win7，39 文件 +4311/−194，
覆盖范围是本批的严格超集：后端三件套、前端四件套、**electron IPC 层**（`commandRoutes/settings.ts`、
`ipc-manifest.json`、3 个 electron 测试）与 6 个新测试文件。

本批 rebase 到含 #2549 的 base 后仅剩 **i18n 键重复**（本批插入的 16 个键 #2549 已自行加过，
合并即同名 object literal 键 → TS 编译错），因此关闭而非续推。

## 2. 批次 22 — backend 三方重扫（关闭：零漂移）

基线：main `1c22cb05` / win7 `d7e1449a` / merge-base `476904b4`。

| 桶 | 数量 | 处置 |
|---|---:|---|
| `safe` | 6 | 直接取 main（PEP 604 命中后转文本层修正） |
| `both` | 68 | `git merge-file -p --diff3` → **clean 31 / conflict 32**（+6 reuse 文本化 = 37 条目） |
| `nobase` | 56 | 见 §3 |
| `allowed` | 18 | 已登记，不动 |
| `win7del` | 1 | `backend/ports/plugin.py`（见 §5） |
| `skip` | 10 | `requirements*.txt` / `environment.yml` 版本钉版策略 |

### 2.1 32 个冲突全判 `W`

- 26 个是 PEP 604 ↔ `Optional` / 注释口径（main 侧更旧）；
- `hooks/runner.py` win7 已用 `fnmatchcase`（#2547 修掉 matcher 大小写平台分歧）；
- `api/permission_routes.py` 只剩 `Optional[JSONResponse]` 一处；
- `core/legacy/agent.py` / `tools/registry.py` win7 保留 `validate_required_args` 单一真源与 py38 `List`；
- `tools/browser_cdp.py` / `tools/credential_vault.py` win7 的 Phase D 多浏览器与 cookie 归一化。

### 2.2 结论：合并结果 36/37 逐字节等于 win7

对 37 份合成文本与三条 ref 的 blob 逐字节比对：

| 结果 | 文件数 |
|---|---:|
| 合成文本 **== win7 head** | **36** |
| == main | 0 |
| 真正与两侧都不同 | 1（`chat_stream_registry.py`，仅本批自己做的导入重排） |

原因不是脚本跳过，而是 py38 文本化层把 main 侧的差异**抵销回 win7 原样**：main 在这些文件上的改动
清一色是更旧的形态，把 PEP 604 回写成 `Optional` 后逐字节落回 win7。抽样证据：

| 文件 | win7 侧优势 |
|---|---|
| `services/scheduler.py` | 带注释的括号式 `from datetime import (UTC as _UTC, …)`（py38 守卫），main 是单行 |
| `mcp/config.py` | `Optional[X]`（9 处），main `X \| None` |
| `tools/adapters/python_adapter.py` | 独有 `_conda_base_dirs()`、`sys.executable` 兜底、Windows `.exe` 后缀扫描（+28 行），main 三样全无 |
| `api/workspace_routes.py` | `_constrained_list` 兼容垫片；main 裸 `Field(min_length=)` 在 pydantic v2 下约束静默失效 |

**因此 #2554 closed**（正文给出完整台账）。`both` 桶至此 68/68 判 win7，实际漂移 0。

### 2.3 闸门缺口：只跑 `--select F,E9` 会漏 `I001`

唯一红是 `Backend (Python 3.8, Win7 LTS)`：

```
backend/api/chat_stream_registry.py:20:1: I001 [*] Import block is un-sorted or un-formatted
```

导入重建时把 `Optional` 放到了行首。修复：`from typing import Any, Callable, Dict, List, Optional`。
**闸门口径更新**：本地验证必须用仓库的 `backend/ruff.toml` 跑**全规则**（`target-version=py311`、
`line-length=100`、`select` 含 `E/W/F/I/N/UP/B/C4/DTZ/T20/PT/Q/RET/SIM/TID/ARG/PTH/ERA/PL`），
`--select F,E9` 只能作为快速预检。

## 3. 批次 23 — `nobase` 桶 56（第 1 批：6 文件取 main）

`nobase` = merge-base 无此文件、win7 与 main 各自新增。逐文件做 win7 ↔ main 全文比对，
按「main 侧独有行是否含实质逻辑」分类：

| 判定 | 数量 | 说明 |
|---|---:|---|
| 取 main（PR #2556） | 6 | main 侧有 win7 缺失的实质修复/功能 |
| 保留 win7 | 50 | win7 侧更优（pydantic v1 垫片 / 安全实现 / 独有功能 / 纯 typing） |

### 3.1 取 main 的 6 个文件

| 文件 | main 侧改动 | 依据 |
|---|---|---|
| `design/templates.py` | 模板 assets key 改 `relative_to(...).as_posix()` | Windows 下 key 写成 `assets\...`，与模板内引用对不齐 |
| `services/project_wiki_generator.py` | `SourceFile.path` 改 `rel_posix = rel_path.as_posix()`，`path_filter` 同用 | 项目相对逻辑标识被反斜杠污染，会进 wiki 序列化与依赖分析 |
| `api/legacy_chat_routes.py` | P1 插话落库：注入成功后写一行 `subtype='steering'` 消息（+17 行，失败只告警） | win7 侧注入只排队内存、不落库，流末对账取不到该消息 |
| `data/session_event_backfill.py` | 逐 session 包 `try/except` + `failed_sessions` 计数 | 单个坏会话不再中断整批回填 |
| `data/artifact_version_repo.py` | `try/except OSError: pass` → `contextlib.suppress(OSError)` | 纯 ruff SIM105 收敛 |
| `skills/skill_md/skills_dir_policy.py` | except 元组补 `TypeError` | `Path(...).expanduser()` 遇非 str 值抛 `TypeError`，当前会穿透 |

### 3.2 保留 win7 的 50 个（按类别）

- **pydantic v1 兼容垫片**：`backend.compat.win7.pydantic_compat`（`ConfigDict` / `field_validator`）与
  `_constrained_list` —— `api/worktree_routes.py`、`api/git_status_routes.py`、`office/toc_refresh.py`、
  `api/legacy_memory_routes.py`（另含 `memory_id` / `id` 双拼兼容）、`model_catalog/schemas.py`
  （v1/v2 双实现，win7 269 行 vs main 124 行）。
- **win7 独有的安全/健壮实现**：`mcp/oauth.py` 的 `_validate_endpoint_url`（https / loopback 强校验，
  RFC 8252 §7.3，main 侧已删）；`remote_mcp/tools.py` 的 junction 检测与 `MAX_REGEX_LENGTH`；
  `remote_mcp/listener.py` 的 `MAX_BODY_BYTES` + `_request_rejection`；`mcp/oauth_store.py` 的
  `mkstemp + chmod(0600)` 原子写；`mcp/oauth_loopback.py` 的 `path_only` 判定；
  `plugins/manifest.py` 的 v1 `max_items` / v2 `max_length` 分支。
- **win7 独有功能**：`api/legacy_memory_list_routes.py` 流式返回（+76 行）、`services/arena_accounts.py`（+70 行）。
- **typing-only（py38 回写）**：20 个文件的 main 侧独有行全是 PEP 585/604，按计划 §2 不动。
- **复核订正**：`api/chat_session_lifecycle.py` 初判 MIX，复核仍判 keep-win7 —— win7 的 `_run_db_sync()`
  是 `run_in_executor` + `with _SQLITE_LOCK`（worker 内持锁），main 的 `py_compat.to_thread(lambda: ...)`
  反而丢掉 `_SQLITE_LOCK`；且 win7 独有 `_compact_in_progress` / `_compact_in_progress_add` 互斥护栏。

## 4. 闸门（本轮最终口径）

| 闸 | 口径 |
|---|---|
| 语法 | `compile()` 全文件；py38 目标 |
| lint | `python -m ruff check backend/` + 仓库 `backend/ruff.toml` **全规则**（不再只跑 `F,E9`） |
| 合成文本 | 无 CRLF、无冲突标记、行尾空白 0 |
| 架构行数 | 逐文件核对 `architecture-baseline.json`（仅基线内文件受限） |
| 推送 | 全量 blob 重建树（`base_tree` + entries），不依赖局部 diff |

## 5. 剩余待办

| 项 | 数量 | 说明 |
|---|---:|---|
| `nobase` | 0 | 56 个已全部裁决（6 取 main / 50 keep-win7），#2556 落地 |
| `win7del` | 1 | `backend/ports/plugin.py`：main 新增（merge-base 无、win7 无）；win7 的 `backend/ports/` 已有 9 个兄弟文件，补一个纯 Protocol 契约文件属纯增量，下一批补回 |
| `allowed` | 18 | 已登记意图差异，不动 |

**结论**：backend 非测试域的可自动收敛面已清零；剩余动作只有 `ports/plugin.py` 补回与登记差异维护。
