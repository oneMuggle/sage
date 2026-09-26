# LocalBridge 借鉴 P0：文件写入乐观锁 + 凭据路径守卫

> 日期：2026-09-26
> 分支：`feat/localbridge-p0-safety`（worktree `.worktrees/localbridge-p0-safety`）
> 来源分析：`docs/mcp-localbridge-reuse-analysis.md`

## 1. 背景

在 `reference/LocalBridge-Share` 的文件工具（`LocalBridge/src/files.cjs`）中，有两项设计 Sage 目前缺失：

1. **写入乐观锁**：`read_file` 返回内容的 SHA-256 `version`。写已有文件时必须提交这个版本号，写新文件时提交 `"new"`。版本不一致就拒绝写入。
2. **凭据路径黑名单**：文件工具拒绝读写 `.env`、`id_rsa` 等常见凭据文件。

Sage 的子代理可以并行编排，用户也可能同时在编辑器里修改文件。现在 `write_file` / `edit_file` / `apply_patch` 都是“最后写入者胜出”，Agent 可能基于过期内容覆盖别人的改动。另外，LLM 可以直接用 `read_file` 读取 `.env` 中的 API Key，然后把它带进上下文和对话记录。

## 2. 范围

本批次包含：

- 新模块 `backend/tools/file_guard.py`：包含版本计算、`expected_version` 校验和凭据路径判定，都是纯函数。
- `read_file`：返回 `version`；拒绝读取凭据路径。
- `write_file`：新增可选参数 `expected_version`；拒绝写入凭据路径；返回写入后的 `version`。
- `edit_file`：新增可选参数 `expected_version`；拒绝写入凭据路径；返回写入后的 `version`。
- `apply_patch`：每条补丁可选带 `expected_version`，任何一条冲突，整批都不写入；拒绝凭据路径；每个文件返回写入后的 `version`。
- 单元测试 `backend/tests/tools/test_file_guard.py`。

本批次不包含（留给后续批次）：

- 全局急停（Ctrl+Alt+Esc → 后端 pause）：需要统一 chat、orchestration、bash 的取消链路，单独写方案。
- bash / execute_code 对凭据文件的约束：执行类工具无法按路径拦截，由权限模式和审批兜底。
- 把 `expected_version` 设为**必填**：会破坏现有提示词和技能的兼容性。先作为可选参数观察使用率。

## 3. 设计

### 3.1 版本号

- 格式为 `sha256:<64 位小写十六进制>`，按**磁盘原始字节**流式计算。分页和截断都不影响结果，是整个文件的版本。
- `write_file` 在 Windows 上以文本模式写入，会做换行翻译，所以写后版本从磁盘重新计算。`edit_file` 和 `apply_patch` 用 `write_bytes` 精确落盘，直接对写入的字节计算。
- `expected_version` 的语义：

| 取值 | 行为 |
|---|---|
| 省略或 `null` | 不校验，保持现有行为 |
| `"new"` | 目标必须不存在，否则返回 `version_conflict` |
| `"sha256:…"` | 目标必须存在且版本一致，否则返回 `version_conflict` |
| 其他 | 返回 `invalid_expected_version` |

- `apply_patch` 在校验阶段还没有写盘，所以同一文件的多条链式补丁都对照**原始版本**，也就是 `read_file` 拿到的那个版本。
- 冲突时的错误信息明确要求“重新 read_file，不要盲目重试”，与 LocalBridge 的 `uncertainResult` 约定一致。
- 已知限制：校验和写入之间存在一个 TOCTOU 窗口，只能防止协作场景下的误覆盖，不防御恶意的本机进程。

### 3.2 凭据路径守卫

只看路径，不读取文件内容：

- 精确文件名：`.env`、`.git-credentials`、`.netrc`、`_netrc`、`.pgpass`、`.pypirc`、`id_rsa`、`id_dsa`、`id_ecdsa`、`id_ed25519`（含 `_sk` 变体）。
- `.env.*`：放行 `example`、`sample`、`template`、`dist`、`defaults` 这类模板文件，其余拒绝。
- 扩展名：`.pem`、`.key`、`.pfx`、`.p12`、`.jks`、`.keystore`、`.kdbx`、`.ppk`。
- 特定目录下的文件：`.aws/credentials`、`.docker/config.json`、`.kube/config`、`gcloud/credentials.db`、`gcloud/access_tokens.db`。
- `.ssh/` 目录下除 `*.pub`、`known_hosts`、`config`、`authorized_keys` 以外的所有文件。
- `*.pub` 一律放行。
- 设置环境变量 `SAGE_ALLOW_SENSITIVE_PATHS=1` 可以整体关闭守卫，用于调试或用户明确知情的场景。
- 错误信息不回显文件内容。

## 4. 兼容性

- 所有新参数都是可选的，现有调用行为不变。唯一的行为变化是凭据路径被拒绝。
- `edit_file` / `apply_patch` 的“未知参数”提示文本增加了 `expected_version`。
- 只用到 `hashlib`、`os`、`pathlib`，不引入新依赖，兼容 py38（release/win7 线可以直接 cherry-pick）。

## 5. 验收

- `pytest backend/tests/tools/test_file_guard.py` 全部通过。
- 现有的 file / edit / patch 相关测试没有回归。
- `ruff check` 在变更的文件上通过。
