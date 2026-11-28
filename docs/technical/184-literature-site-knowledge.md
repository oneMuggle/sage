# 文献站点知识沉淀与 HTTP 快路径

## 一句话简介

把「手动登录 + 受控浏览器」访问文献站点的经验固化为可复用的站点知识
（profile `notes[]` / `backends[]` + skill `references/`），给 PDF 下载加一条
受合规闸门与限速约束的 HTTP 快路径，并把观测自动沉淀成下一轮可直接复用的经验。

## 架构：四层

| 层 | 职责 | 落点 |
|---|---|---|
| ① 站点知识层 | 站点操作事实与多后端清单 | `SiteProfile.notes` / `SiteProfile.backends` / skill `references/` / vault |
| ② 访问通路层 | 浏览器路径 + HTTP 快路径 + 共享合规闸门 | `search.py` / `http_download.py` / `http_site_gate.py` |
| ③ 多后端层 | 库清单、可用性状态、失败原因 | `backends[]` / `backends.py` |
| ④ 沉淀闭环层 | 观测 → 经验；确定性步骤 → 脚本；OA 轴 | `profile_record_note` / 用户级 `scripts/` / `UnpaywallLookup` |

**贯穿性原则**：站点差异只落在 ① 层；代码里不得出现任何站点专属分支。

## 站点知识模型

### notes[] —— 结构化站点经验

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 站点内唯一 slug；同 id 视为覆盖 |
| `title` | 是 | 一句话概括（≤60 字） |
| `symptom` | 是 | 观察到的现象 |
| `cause` | 否 | 根因 |
| `workaround` | 是 | 可执行的绕过/正确做法 |
| `severity` | 是 | `blocker` / `degraded` / `cosmetic` |
| `applies_to` | 否 | `search` / `pdf.entry` / `pdf.download` / `login` / `backend:<id>` |
| `learned_at` | 是 | ISO 日期 `YYYY-MM-DD` |
| `verified_at` | 否 | ISO 日期；超过 180 天未复验会标注 |
| `source_run` | 否 | 来源运行目录 |

### backends[] —— 单站点多检索后端

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 站点内唯一；可被 `notes[].applies_to` 的 `backend:<id>` 引用 |
| `label` | 是 | 人类可读名 |
| `entry_url` | 是 | 检索入口 |
| `status` | 是 | `ready` / `blocked` / `unavailable` / `unknown` |
| `reason` | 否 | 非 `ready` 时的原因 |
| `capabilities` | 否 | 能力子集；缺省继承站点级 |
| `overrides` | 否 | 对站点级检索配置的覆盖 |
| `checked_at` | 否 | 最近探测日期 |

> `backends[].status` 是**单个检索后端**的可用性；`SiteProfile.status` 是**整个
> 站点 profile** 的状态。两者同名不同义。

## sidecar 机制

机器写入的站点经验与后端清单写同目录 sidecar，**不动主 profile YAML**
（`yaml.safe_dump` 会毁掉用户手写注释）：

- `~/.sage/literature_sites/<site_id>.notes.yaml`
- `~/.sage/literature_sites/<site_id>.backends.yaml`

合并规则：主 YAML 是人写基线，sidecar 按 `id` 覆盖同 id 条目。

## HTTP 快路径

```
浏览器读元素 href → HTTP GET doDownload（带 vault cookie + Referer）
→ 301 → 中间页 HTML → 解析 downurl → 按 host_fallbacks 换主机
→ GET PDF → magic + 题名校验 → 原子落盘
```

**不可 HTTP 化**：检索页（JS 渲染 + WAF）。快路径从「结果行」开始。

**合规闸门**：HTTP 出网前与浏览器路径**同构**地过 `browser_safety.check_site`；
限速器通用下限 1 秒、文献层强制下限 3 秒（profile 写 0 也不放行）；
`max_batch` 超限触发人工确认。

**降级**：HTTP 失败**只降级一次**回浏览器路径，原因记进 `query_log` 的
`fallback_reason`。任何失败都如实上报，不静默降级后报告成功。

## 合法可得性轴（Unpaywall）

`UnpaywallLookup` 回答「哪里能合法拿到全文」，产出 `access_status`
（`oa` / `closed`）/ `is_oa` / `oa_status` / `best_oa_url`。需要 profile 的
`compliance.contact_email`；缺失时该 lookup 不可用但**不阻断**主链路。

**不因 `oa_status` 改变「是否下载付费文献」的行为** —— 下载权限只由站内授权决定。

## 合规红线

- 不代填、不读取、不导出卡号与密码；登录由用户在可见窗口完成。
- 验证码 / 滑块一律不自动识别、不绕过；命中即停交还用户。
- 不绕过付费墙；只做合法可得性最大化。
- 不绕过限速、不批量无节制抓取。

## 相关章节

- [文献调研子系统](./164-literature-research-subsystem.md)
- [Win7 LTS Release Workflow](./16-win7-lts-release-workflow-design.md)
