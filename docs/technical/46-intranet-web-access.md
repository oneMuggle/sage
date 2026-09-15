# 内网 Web 访问（网络模式门禁 + 取页下载）

> `release/win7` 分支目标用户的内网/气隙运行场景：让 Sage 能按地址读网页、下文件，同时用一个显式的网络模式门禁让搜索类出网工具在内网模式下对 LLM 不可见。
>
> 设计 spec：`docs/superpowers/specs/2026-09-02-intranet-web-access-design.md`

## 网络模式三档

`backend/domain/network_policy.py` 定义 `NetworkMode`（`str` Enum，值与前端 `NetworkTab` 字面量联合一致）：

| 模式 | 行为 |
|---|---|
| `online` | 现状：搜索可用，任意公网地址可达；`allowed_hosts` 不参与判定 |
| `intranet` | 搜索不注册；取页/下载仅允许 `allowed_hosts` 命中的 host |
| `offline` | `web_search` / `web_fetch` / `http_download` 三个出网工具全部不注册 |

工具的"注册 / 不注册"在 **注册时** 判定（`backend/tools/__init__.py` 的 `register_all_tools` 与 `backend/tools/agent_tool.py` 的 `build_readonly_tool_registry` 都接收 `network_policy` 参数）—— 这是 LLM 根本看不到工具的唯一实现方式。返回"该模式不可用"会让模型多烧一轮并可能重试。

host 校验在 **执行时** 读策略（`NetworkPolicy.check_host(url)`），用户改完白名单立即生效，不必重开会话。

| 门禁方法 | 调用时机 | 行为 |
|---|---|---|
| `search_enabled()` | 注册期 | 仅 `online` 返回 `True` |
| `fetch_enabled()` | 注册期 | `online` / `intranet` 返回 `True`，`offline` 返回 `False` |
| `check_host(url)` | 执行期 | `online` 恒放行；`offline` 恒拒绝；`intranet` 按白名单 |
| `allows_insecure_tls(url)` | 执行期 | host 命中 `insecure_tls_hosts` 时豁免 TLS 校验 |

## Host 白名单通配规则

`NetworkPolicy` 在 `__post_init__` 校验每一条 `allowed_hosts` 与 `insecure_tls_hosts` 条目：

- **通配只支持 `*.` 前缀**，且 `*.` 后至少两段（如 `*.cnki.net`）。`*`、`*.net`、`a.*.net`、`*cnki.net` 全部 `ValueError`。
- `*.cnki.net` 命中 `cnki.net` 自身及任意层级子域（`a.cnki.net`、`b.a.cnki.net` 都算）。
- **后缀混淆不命中**：`evilcnki.net` 不命中 `*.cnki.net`。比对的是"以 `.cnki.net` 结尾"，不是"以 `cnki.net` 结尾"。
- 匹配前 host 统一 `lower()` + 去尾点，避免 `A.CNKI.NET.` 绕过白名单。

空内白名单 + `intranet` 模式是 fail-closed：`check_host` 拒绝一切 URL。这是刻意的 —— 切到内网没填白名单，结果是"什么都访问不了"而不是"什么都能访问"。前端 `NetworkTab` 此时显示提示条引导用户加 host。

## `web_fetch` 四模式

`backend/tools/web_tool.py:WebFetchTool` 通过 `mode` 参数控制返回的字段段：

| `mode` | 返回字段 |
|---|---|
| `text`（默认） | `title`、`content`（正文，已剥 `<script>` / `<style>` / `<noscript>` / `<svg>` / `<template>` 内容） |
| `links` | `text` 的内容 + `links`（`{text, url}` 列表，相对链接对 base_url 做 `urljoin`） |
| `tables` | `text` 的内容 + `tables`（二维数组的列表，文献列表页的核心） |
| `raw` | 整页 HTML（逃生舱，原 `web_fetch` 行为） |

非 HTML content-type（`application/json` 等）走"直接给原文"分支，不做 HTML 抽取。

### 连接模式分派

`intranet` 模式下，host 命中白名单后**跳过** `_validate_subagent_url` 的字面量公网 IP 校验 —— 内网 host 解析出私有 IP 是预期的，按公网规则会全部拒绝。`online` 模式该路径行为完全不变（spec §4 硬要求）。重定向目标在 `intranet` 下也要过 `check_host`。

## `http_download` 边界约束

`backend/tools/download_tool.py:HttpDownloadTool`，风险类 `EXTERNAL`（出网 + 写盘，取更严的语义）。

### 工作区 fail-closed

`BaseTool._enforce_workspace` 在 `policy.workspace_root` 为 `None` 时返回 `None`（放行）—— legacy 聊天链路在会话无 workspace 绑定时确实是 `None`。下载的字节来自网络而非本地已有内容，写入位置不确定的风险更高，故 `http_download` 不依赖该方法兜底，未绑定时直接返回 `workspace_not_bound` 错误。

### 双重大小上限

| 层 | 触发时机 | 行为 |
|---|---|---|
| Content-Length 预检 | 响应头到达 | 声明值 > `max_bytes` 立即拒，不写盘 |
| 实际字节累计 | 流式写入过程中 | 累计 > `max_bytes` 中断并 `unlink(missing_ok=True)` 半成品 |

`Content-Length` 是服务器说的，不可信 —— 声明 10 字节实发 5000 字节的响应会在写入阶段被实际字节兜底拦住。

模块常量 `MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024`（100 MiB）。

### 文件名净化

`sanitize_filename(name)` 处理路径分隔符（正反斜杠都剥）、NUL 字节、首尾点与空格；不安全字符换下划线；净化后为空或全是下划线则回退 `download.bin`。最大 120 字符。

`derive_filename(url, disposition)` 的优先级：

1. `Content-Disposition`（用 `email.message.Message.get_filename()`，同时处理 `filename="x"` 与 RFC 5987 的 `filename*=UTF-8''%XX`）
2. URL path 末段（`unquote` + `PurePosixPath` 取 basename）

`filename` 参数（用户显式传入）也走 `sanitize_filename`。绝对路径直接拒（`filename_must_be_relative`）。同名文件不覆盖，落到带 `-N` 后缀的新名字。

### Artifact 注册

落盘后调 `_record_artifact_safely`（`backend/tools/file_tool.py`）挂进 Artifacts 面板。记录失败静默，不阻断下载结果。

## 配置存储位置

存 `preferences` 表的 KV key `network_policy`，value 为 JSON 字符串，category `network`。`backend/data/settings_repo.py:KEYS` 白名单含 `network_policy`：

```json
{
  "mode": "intranet",
  "allowed_hosts": ["*.example-mirror.internal", "docs.example.internal"],
  "insecure_tls_hosts": ["docs.example.internal"]
}
```

**不走 `app_settings` blob**：后者有 `LEGAL_TOP_KEYS` 白名单校验（`backend/data/settings_canonicalizer.py:47`），加新顶层字段要同步改前端 `AppSettings`、后端白名单、契约测试三处。KV 只需在 `KEYS` 加一条。

加载器 `backend/tools/network_config.py:load_network_policy(repo=None) -> NetworkPolicy` **fail-safe 方向**：JSON 解析失败 / mode 非法 / 字段类型不对 / `__post_init__` 校验抛 → 全部回退 `NetworkPolicy()`（ONLINE）并 `logger.warning`。配置读不出来时不应该把用户既有能力锁死。

加载惰性 import `SettingsRepository`，避免 `tools` ↔ `data` 循环依赖（与 `backend/tools/permissions.py:388` 同手法）。

## 关键 Invariant

**`insecure_tls_hosts` 中每一项都必须被 `allowed_hosts` 覆盖**（按通配规则判定，不是字符串子集）。`__post_init__` 校验这条；前端 `NetworkTab` 在用户移除 `allowed_host` 条目时**同步剔除失去覆盖的 TLS 豁免项**（`removeAllowedHost` 的过滤逻辑）。否则孤儿 TLS 豁免会让 `NetworkPolicy.__post_init__` 抛 `ValueError`，加载器兜住后整份配置被拒、整个工具栈 fail-safe 回 ONLINE —— 内网模式被静默关掉。

注意 invariant 的方向性：

- 配置读不出来（解析失败 / 字段非法）→ ONLINE（不锁死用户既有能力）
- 配置读出来了但明确写了 `intranet` 且白名单为空 → 严格执行空白单（fail-closed）

两者不矛盾：前者处理故障，后者执行用户意图。

`load_network_policy` 的返回值经过 `NetworkPolicy.__post_init__` 校验，校验失败同样 fail-safe 回 ONLINE。所以"写入了一个坏配置"与"读不出配置"在系统层面是同一类失效。