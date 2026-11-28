# 文献站点知识沉淀与 HTTP 快路径 —— 设计文档

- **日期**：2026-11-28
- **分支**：`feat/literature-site-knowledge`（基于 `origin/main` @ `2869d0e8b`）
- **路线**：C（B + 全自动沉淀 + 文献库全覆盖）
- **状态**：待用户审阅

---

## 0. 背景与目标

用户在 xueshu789 上完成了一次真实的文献检索与 PDF 下载（双分支真机 E2E），随后提出四个诉求：

1. 当前的「手动登录 + 受控浏览器」访问方式，能否通过技能与记忆等机制在实际使用中**固化**；
2. 除登录外，**检索、下载**能否走 `web_fetch` / `http_download` 等 HTTP 通道以获得更快访问；
3. xueshu789 中的**可用文献库**是否都能利用上，这部分知识**如何沉淀**；
4. 总体目标：使用这类网站时能**避开坑点、探索较优路径、方便以后复用**；并借机评估 Sage 自身能力、参考主流 AI 应用给出优化建议。

勘察结论：**Sage 的骨架已与主流做法同构，缺的是「接线」与「执行点」。** 具体地，`references/` 机制建好了但没有任何 shipped 技能引用它（那份 271 行流程契约从未进入 LLM 上下文）；profile 只有一条自由文本 `pdf.note` 承载站点经验，无法并存多条、无法回写；限速只是「给模型看的文本」而非闸门；另有三个代码缺陷会让文档化的用法直接失败。

**本文档定义目标架构与接口，不含实施步骤**（实施步骤由 writing-plans 阶段产出）。

### 0.1 范围

**在范围内**

- 站点知识模型扩展（profile schema）
- `references/` 接线（让站点知识真正进入 LLM 上下文）
- 文献下载的 HTTP 快路径 + 配套合规闸门
- 单站点多检索后端（文献库）的建模、探测与使用
- 观测 → 经验的自动沉淀闭环
- 合法可得性补充轴（Unpaywall）
- 三个既有代码缺陷的修复

**不在范围内**

- 绕过付费墙、验证码、限速的任何机制（**红线**）
- 替换 `backend/literature/` 的编排方式（维持「无 Python 编排器、LLM 驱动」现状）
- 前端 UI 改造（除非后端 schema 变更强制要求）
- `academic-search` / `cnki-research` 等其他 shipped 技能的站点化（只做通用机制，站点内容后置）

### 0.2 合规红线（不可协商）

| 红线 | 实现落点 |
|---|---|
| 不代填密码、不导出明文密码 | 登录始终由用户在可见浏览器窗口完成；vault 只存 cookie / header / storage_state |
| 不绕过付费墙 | `pdf.forbid` 黑名单 + `compliance.note` 提示 + HTTP 路径同样受 `compliance` 声明约束 |
| 不绕过验证码 / 滑块 | 遇到即停，交还用户（§6.4） |
| 不绕过限速 | profile 的 `rate_limit` 从「提示文本」升级为「真实执行」（§5.5） |
| 不批量无节制抓取 | `max_batch` 超限触发人工确认（§5.5） |

---

## 1. 现状诊断

以下结论均在 `origin/main`（`2869d0e8b`）上逐条复验，行号以 main 为准。

### 1.1 结构性缺口

| # | 缺口 | 证据 |
|---|---|---|
| S1 | **`references/` 机制建好但从未接线** | `backend/skills/skill_md/resources.py:332` 的 `render_body_with_resources` 只把 `{baseDir}/x` 渲染成**相对路径**（`{baseDir}` 单独出现时渲染成 `.`）；`grep -rn "{baseDir}" backend/skills/skill_md/shipped/` **零命中**。故 `literature-research/references/pipeline.md`（271 行契约文档）从未进入 LLM 上下文。 |
| S2 | **站点事实散在「示例模板 / 运行期副本 / 通用文档」三处，且运行期无法回写** | 站点事实的**设计归属**本已是 profile（`backend/literature/README.md:151`、`references/pipeline.md:266-270` 都明说「具体站点的选择器与实测要点写在该站点 profile」）。但实际有三份：① `docs/templates/literature-sites/xueshu789.yaml`（出厂示例，v0.4.0，含 `pdf.interstitial` 与 `pdf.note`）；② `~/.sage/literature_sites/xueshu789.yaml`（用户运行期副本，**已与模板漂移**，模板更新不会同步过来）；③ `backend/literature/README.md:53` 的通用机制段落里以 xueshu789 为例写死了「oversea 网关对国内库 404」这一站点事实。**没有任何机制让运行期的新经验回到 profile**，只能人手改 YAML。 |
| S3 | **profile 无承载「站点经验」的字段** | `models.py:126` 的 `SiteProfile` 无 `notes` / `runbook`。唯一自由文本出口是 `pdf.note`（模板 `xueshu789.yaml:85` 的 ddata 教训就写在这）与 `search.result_hint`，均被 `guidance.py:20` 渲染为提示文本。**一条经验 = 一条字符串**，无法并存多条、无法标记严重级别、无法标记作用面、无法按站点+阶段召回。`version` / `status` / `last_verified_at` 只标记**配置本身**，不标记**这些操作知识**。 |
| S4 | **记忆系统无 site 轴** | `backend/memory/scope.py:27-30` 仅 `user` / `project` / `global`；`grep -rn "site_id" backend/memory/` 零命中。站点经验写进记忆后无法按站点检索、不会被检索流程召回、不受 profile 校验、不版本化。 |
| S5 | **profile 表达不了「一个站点多个检索后端」** | `search.url_template` / `entry_url` 为单值、`input_selectors` 为单组；`capabilities` 是 `Dict[str, bool]` 布尔开关表（全仓仅 `models.py` 内消费一次），不是映射表。 |
| S6 | **profile 只读，无写回** | `backend/literature/profile_store.py` 只有 `discover` / `get` / `list_ids` / `reload`，无 save。`recording.py:36` 的 `write_profile_draft` 写到显式路径，由用户手动搬运。 |
| S7 | **profile 的 `rate_limit` 只是文本** | `grep -rn "rate_limit" backend/literature/*.py` 除 `models.py` 外只有 `guidance.py:98-99`，即渲染成「每篇间隔 >= 5s」交给模型。全仓无任何执行点。 |

### 1.2 代码缺陷

| # | 缺陷 | 证据 | 影响 |
|---|---|---|---|
| B1 | **`execute_code` 的 RPC 静态拒绝让文档化工作流跑不通** | `backend/tools/execute_code_tool.py:64-78` 拒绝所有 `ToolCapability.EXECUTE` 工具；`backend/tools/permissions.py:186` 把 `browser_navigate` 归为 EXECUTE。`backend/literature/sage_driver.py` 的 `navigate()` / `_url()` 均走 `sage.call("browser_navigate")`。 | SKILL.md 教的 `execute_code` + `sage.call(...)` 写法在真实对话里**必失败**。（2026-11-27 的真机 E2E 直调 `ToolRegistry`，绕过了 RPC，故未暴露。） |
| B2 | **错误文案指向不存在的工具** | `credential_set` 出现在 `backend/tools/download_tool.py:386/493/509` 与 `backend/tools/web_tool.py:627/761/777` 的指引文案中；全仓**无此工具**（`backend/domain/tool_names.py` 无该名）。 | LLM 照做只会再失败一次，且错误信息误导排查方向。 |
| B3 | **`BROWSER_TOOL_NAMES` 与 `tool_names.py` 漂移且无守卫** | `backend/tools/browser_tool.py:4092-4103` 10 项；`backend/domain/tool_names.py:178-191` 12 项（多 `browser_list_accounts` / `browser_switch_account`）。注释称「一致性由测试锁定」，但唯一相关断言是 `backend/tests/unit/test_browser_tool.py:1310` 的 `assert "browser_downloads" in browser_tool.BROWSER_TOOL_NAMES`，**并未比对两个元组**。 | 工具清单漂移不会被 CI 发现。 |

### 1.3 能力面缺口

| # | 缺口 | 证据 |
|---|---|---|
| C1 | **HTTP 工具完全绕过站点策略闸** | `grep -n "browser_safety\|check_site" backend/tools/web_tool.py backend/tools/download_tool.py` **零命中**。`browser_safety.check_site(session_id, url)`（`backend/services/browser_safety.py:141`）只服务浏览器工具。 |
| C2 | **HTTP 工具无任何自带限速** | 两文件中仅 `download_tool.py:619` 的 `_sleep(wait)`（重试退避），非 per-host 限速。 |
| C3 | **`web_fetch` 无 html 模式** | `backend/tools/web_tool.py` 的 `VALID_MODES = ("text", "links", "tables", "raw", "files")`；`raw` 可拿到原始 HTML，但需自行解析。 |

---

## 2. 目标架构

分四层，每层职责单一、依赖向下：

```
┌──────────────────────────────────────────────────────────────┐
│ ④ 沉淀闭环层                                                 │
│   观测 → 经验（notes） │ 确定性步骤 → scripts │ OA 可得性轴   │
├──────────────────────────────────────────────────────────────┤
│ ③ 多后端层                                                   │
│   backends[]：库清单、可用性状态、滑块/代理失败原因           │
├──────────────────────────────────────────────────────────────┤
│ ② 访问通路层                                                 │
│   浏览器路径（既有） │ HTTP 快路径（新增） │ 共享合规闸门      │
├──────────────────────────────────────────────────────────────┤
│ ① 站点知识层                                                 │
│   SiteProfile（notes / backends） │ skill references │ vault  │
└──────────────────────────────────────────────────────────────┘
```

**贯穿性原则**：站点差异**只**落在 ① 层；② 层的通路选择与合规校验对所有站点一致；④ 层的沉淀产物回到 ① 层，形成闭环。代码里不得出现任何站点专属分支。

### 2.1 关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 多检索后端的表达 | **profile 内的 `backends[]` 列表**（而非「每个 dbItem 一个 profile」） | 兼容既有 `search_with_profile(profile, query, driver)` 签名与 `get_site_adapter(site_id)` 入口；用户一眼能看到「这个站有哪些库」；避免 `~/.sage/literature_sites/` 膨胀与登录/限速/合规声明重复。 |
| 站点经验的落点 | **profile 的 `notes[]`**（结构化），不是记忆系统、不是 skill 正文 | 记忆无 site 轴（S4）；skill 正文不可版本化、不可按站点校验；profile 已具备「用户可编辑 + 机器可校验 + 运行时进指导文本」三重属性。 |
| 机器写入站点经验 | **sidecar 文件 `<site_id>.notes.yaml`**，不动主 profile YAML | 工具追加会破坏主 YAML 的注释（`recording.py:33` 用 `yaml.safe_dump` 会丢注释，而用户的 `~/.sage/literature_sites/xueshu789.yaml` 有手写头注释）；sidecar 天然分离「人手写配置」与「机器追加经验」。 |
| skill references 的读法 | **新增 `skill_read_resource` 工具**（而非把内容直接注入正文） | 保持 Anthropic 渐进披露（模型按需读）；`{baseDir}` 渲染出的是相对路径，模型无法据此定位文件（S1）；新增工具可复用 `resources.py` 已有的路径白名单与越界校验，不泄露绝对路径。 |
| HTTP 快路径的合规闸门 | **复用 `browser_safety` 的站点策略 + 确认注册表**，并把 profile `rate_limit` 变成真实执行点 | HTTP 路径必须与浏览器路径受同等约束（C1/C2）；`ConfirmationRegistry.create(session_id, kind="site_access", ...)` 与浏览器路径同构，用户在同一个面板裁决。 |
| 确定性步骤的脚本化 | 放**用户级技能**的 `scripts/`，不改 shipped 沙箱边界 | `backend/adapters/out/skill/inproc.py:163` 明确把 shipped 排除在 `allowed_roots` 外，是有意的安全边界；用户级技能已被 `academic-search` 的「路径 B」教过，且 `script_runner.py` 已具备路径校验 + 用户确认 + 沙箱执行。 |

---

## 3. 站点知识模型扩展

### 3.1 `SiteProfile.notes` —— 结构化站点经验

新增字段（`backend/literature/models.py:126` `SiteProfile`）：

```yaml
notes:
  - id: download-ddata-missing
    title: 结果行 href 必须取元素属性，不能用快照里的截断 URL
    symptom: doDownload 返回「参数错误」
    cause: 完整 href 含 &ddata=文件名|库|题名|库|hash；快照里的 URL 被截断，丢失 ddata
    workaround: 用 browser_interact action=attr attr_name=href 读元素 href
    severity: blocker
    applies_to: [pdf.entry]
    learned_at: "2026-01-15"
    verified_at: "2026-02-03"
    source_run: "e2e-run-001"
```

字段契约：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | str | 是 | 站点内唯一 slug，`^[a-z0-9][a-z0-9-]*$`；同 id 视为更新而非追加 |
| `title` | str | 是 | 一句话概括，≤ 60 字 |
| `symptom` | str | 是 | 观察到的现象（错误文案 / 异常表现） |
| `cause` | str | 否 | 根因；未知时留空 |
| `workaround` | str | 是 | 可执行的绕过/正确做法 |
| `severity` | enum | 是 | `blocker`（阻断，必须先解决）/ `degraded`（能力降级）/ `cosmetic`（仅提示） |
| `applies_to` | list[str] | 否 | 作用面：`search` / `pdf.entry` / `pdf.download` / `login` / `backend:<id>` |
| `learned_at` | date | 是 | 首次记录日期，ISO `YYYY-MM-DD` |
| `verified_at` | date | 否 | 最近一次复验日期，ISO `YYYY-MM-DD`；距今超过 `stale_after_days`（模块常量，默认 180 天，非 profile 字段）在指导文本中标注「未复验」 |
| `source_run` | str | 否 | 来源运行目录名，用于追溯 |

**渲染**：`guidance.py:20` 的 `render_search_guidance` 追加一个 `## 站点经验` 段，按 `severity` 排序（blocker 在前），并对 `applies_to` 与当前阶段相关的条目才渲染 —— 避免把全部经验灌进上下文。

**校验**：`notes[].severity` 必须是三值之一；`notes[].id` 在站点内唯一（重复 id 视为覆盖）；`notes[].learned_at` / `verified_at` 必须可解析为日期。校验失败 → profile 加载时报 `SiteProfileError`，与既有字段同口径（`models.py:19`）。

**合并规则**：`SiteProfileStore.discover()`（`profile_store.py:53`）在加载主 YAML 后，同目录查找 `<site_id>.notes.yaml` 并合并：
- 主 YAML 的 `notes` 为「人写基线」；
- sidecar 的 `notes` 按 `id` 覆盖主 YAML 同 id 条目，其余追加；
- sidecar 缺失时行为不变（向后兼容）。

### 3.2 `SiteProfile.backends` —— 单站点多检索后端

```yaml
backends:
  - id: db3
    label: 中国知网（代理）
    entry_url: https://www.xueshu789.cc/dbItem/3
    status: ready
    reason: ""
    capabilities: {search: true, pdf_download: true}
    checked_at: "2026-01-15"
  - id: db1
    label: 万方（代理）
    entry_url: https://www.xueshu789.cc/dbItem/1
    status: unavailable
    reason: 代理报错
    checked_at: "2026-01-15"
  - id: db2
    label: 维普（代理）
    entry_url: https://www.xueshu789.cc/dbItem/2
    status: blocked
    reason: 触发滑块验证
    checked_at: "2026-01-15"
```

字段契约：

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 站点内唯一；允许与 `notes[].applies_to` 的 `backend:<id>` 对应 |
| `label` | 是 | 人类可读名（如库名） |
| `entry_url` | 是 | 该后端的检索入口 |
| `status` | 是 | `ready` / `blocked` / `unavailable` / `unknown` |
| `reason` | 否 | 非 `ready` 时的原因（代理报错 / 触发滑块 / 需人工验证 …） |
| `capabilities` | 否 | 该后端的能力子集；缺省继承站点级 `capabilities` |
| `overrides` | 否 | 该后端对站点级检索配置的覆盖（如 `input_selectors` / `result_fields`）；缺省继承 |
| `checked_at` | 否 | 最近探测日期，ISO `YYYY-MM-DD` |

> **命名澄清**：`backends[].status` 是**单个检索后端**的可用性；`SiteProfile.status`（`models.py:139`，默认 `"ready"`）是**整个站点 profile** 的状态。两者同名不同义，改动时不要混淆。

**与既有字段的关系（向后兼容）**：`backends` 缺省为空时，行为与现在完全一致（用 `search.entry_url` / `search.url_template`）。`backends` 非空时：
- `search.entry_url` 仍保留，用于**默认后端**（`backends` 中 `status == "ready"` 的第一项；若无可用项则取第一项）；
- `search.url_template` 若含 `{backend_id}` 占位则按所选后端渲染；
- `search.input_selectors` / `result_fields` 允许在 backend 上覆盖（`backends[].overrides`），缺省继承站点级。

**`status` 语义**：

| status | 含义 | 运行时行为 |
|---|---|---|
| `ready` | 已实测可用 | 正常纳入检索候选 |
| `blocked` | 站点侧要求人工交互（滑块 / 验证码 / 二次认证） | **不自动尝试**，列入指导文本提示「需用户手动完成」，命中时交还用户 |
| `unavailable` | 站点侧直接报错（代理失效 / 资源下线） | 排除出候选 |
| `unknown` | 未探测 | 首次使用时提示「可执行一次探测」 |

### 3.3 单一事实源的收敛规则

`references/pipeline.md` **已经是干净的** —— 它 271 行全是流程契约，末尾还明写着「具体站点的选择器与实测要点写在该站点 profile 的注释与模板 README 中，不要写进本数据契约文档」。真正需要收敛的是另外三处。收敛后，站点知识的归属唯一：

| 知识类型 | 唯一归属 | 载体 |
|---|---|---|
| 流程契约（运行目录、产物 schema、步骤顺序） | skill `references/pipeline.md` | 纯流程，不含站点事实 |
| 站点操作事实（选择器、href 取法、中间页处理） | profile 的 `notes[]` + `pdf.*` / `search.*` 字段 | 版本化、可校验、进指导文本 |
| 合规约定 | profile 的 `compliance.note` + skill 正文的红线段 | 机器可读字段 + 不可绕过的流程约定 |
| 用户偏好（我常用哪个库、常搜什么） | 记忆系统（`user` scope） | 记忆系统的本职 |

具体动作：

| # | 动作 | 说明 |
|---|---|---|
| a | `backend/literature/README.md:53` 的站点事实**泛化** | 该段讲的是「中间页两段式下载」的**通用机制**，却以 xueshu789 的 oversea 404 为唯一例证。改为通用表述（如「最终地址主机可能写错 —— 需按 profile 声明的 `host_fallbacks` 逐个回退」），具体站点例子下沉到该站 profile。 |
| b | `backend/literature/README.md:148` 的设计规则**更新** | 「站点差异只写在这里或 skill 的 `references/`」→ 改为「站点差异只写在 profile（`notes` / `backends` / `pdf.*` / `search.*`）；通用机制写在本文件与 skill `references/`」。 |
| c | `literature-research/SKILL.md:257/262` 的 `xueshu789.yaml` 硬编码**泛化** | 改为 `<site>.yaml` 占位（该处是「复制模板到用户目录」的示例命令，站点名不该写死）。同文件 41-45 的合规红线段**保留不动**。 |
| d | `docs/templates/literature-sites/xueshu789.yaml` 与 `~/.sage/literature_sites/xueshu789.yaml` 的漂移**显式化** | 模板是「出厂示例」，运行期副本是「现场状态」。二者**不自动同步**（模板是文档期产物，运行期含本地经验）。新增 `notes[]` 后：模板给示例条目，运行期副本承载真实经验。运行期经验**不回灌模板**（模板是出厂基线，回灌会把某个用户的现场状态固化成所有人的默认）。 |
| e | `references/pipeline.md` **保持纯净** | 不塞任何站点事实，只作为流程契约被 `skill_read_resource` 按需读取（§4）。 |

### 3.4 win7 兼容性

`release/win7` 使用 Python 3.8 + pydantic 1.x，main 使用 3.10 + pydantic 2.x。新增字段全部是**纯数据 + 手写解析**，不引入新语法特性：

- `notes` / `backends` 用 dataclass（`models.py` 现用 dataclass 而非 pydantic model，见 `SiteField` / `SearchSpec` 的写法），避免 pydantic v1/v2 差异；
- 不使用 `list[str]` 注解（3.8 需 `List[str]`），遵循仓库既有 `typing.List` 惯例；
- 日期解析用 `datetime.date.fromisoformat`（3.7+ 可用）。

---

## 4. `references/` 接线

### 4.1 问题

`resources.py:332` 的 `render_body_with_resources` 把 `{baseDir}/references/pipeline.md` 渲染成**相对路径字符串** `references/pipeline.md`，把单独的 `{baseDir}` 渲染成 `.`。这个语义对 `ScriptRunner`（按 `base_dir` 解析脚本路径）是对的，但**模型无法据此定位并读取文件**：

- shipped 技能位于应用安装目录下的 `backend/skills/skill_md/shipped/<name>/`，模型不知道绝对路径；
- `read_file` 工具虽然自 M1 起不做 workspace 边界检查（`backend/tools/file_tool.py` 的 `ReadFileTool.execute` 注释），但仍需一个**可解析的路径**；
- 因此 `literature-research/references/pipeline.md` 这份 271 行、信息密度最高的流程契约文档**从未进入过 LLM 上下文**（S1）。它是 `shipped/` 下**唯一**的 `references/` 目录 —— 即整套渐进披露机制在 Sage 里目前只有一个「没人读的文件」。

### 4.2 方案：新增 `skill_read_resource` 工具

新增工具 `skill_read_resource`，参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `skill` | str | 技能名（目录名），如 `literature-research` |
| `path` | str | 技能内相对路径，如 `references/pipeline.md` |
| `offset` | int | 起始行，默认 1 |
| `limit` | int | 读取行数，默认 300 |

实现要点：

- 复用 `resources.py` 的 `build_resource_index` / `validate_resource_path` / `_indexed_regular_resources` 做**白名单 + 越界 + reparse-point 防护**，不允许读取白名单目录（`scripts` / `references` / `assets` / `templates`）之外的文件；
- 技能目录解析顺序与 `loader.py:86` 的 `discover_skill_md_dirs()` 一致（`$SAGE_SKILLS_DIR` > preference `skills_dir` > `$CWD/skills` > `~/.sage/skills` > shipped），保证与技能实际加载来源同源，避免「读到的和生效的不是同一份」；
- 能力分类 **READ**（本地只读，无副作用，不进 EXECUTE 逐次审批队列）；
- 返回统一结构：`{path, content, offset, limit, total_lines, truncated}`；
- **不执行**任何代码，`.py` 脚本只作为文本返回（脚本执行仍走 `ScriptRunner` 的既有审批通道）。

### 4.3 技能正文的引用写法

`literature-research/SKILL.md` 改为：

```markdown
## 运行目录契约

meta.json / papers.jsonl / evidence.jsonl / claims.jsonl / outline.json /
draft.md / verification.json 的字段定义见 {baseDir}/references/pipeline.md，
需要时用 skill_read_resource 读取
（skill="literature-research", path="references/pipeline.md"）。
```

`{baseDir}` 渲染成相对路径仅作**人类可读的定位提示**，模型实际通过 `skill_read_resource` 的 `skill` + `path` 参数读取。

### 4.4 自动激活时的资源清单

`backend/skills/skill_md/auto_activation.py:133` 的 `build_context_block` 在注入技能正文时，附带一行资源清单（仅当该技能有资源）：

```
本技能可用资源（用 skill_read_resource 读取）：
- references/pipeline.md（271 行）
```

这让模型知道「有文档可读」，但不预先灌入内容 —— 保持渐进披露。

### 4.5 与 `ScriptRunner` 的边界

`script_runner.py` 的 `run_script` 处理**执行**（需用户确认、沙箱、路径校验），`skill_read_resource` 处理**读取**（无需确认）。两者共用 `resources.py` 的路径校验，但权限不同：读取是 READ 能力，执行是 EXECUTE 能力且需逐次审批。

---

## 5. HTTP 快路径

### 5.1 分段链路

```
[浏览器] 点击结果行 / 读元素 href
    → doDownloadUrl = https://www.xueshu789.cc/doDownload?...&ddata=...
         ↓  （登录 cookie 来自 vault）
[HTTP]   GET doDownloadUrl  (Referer=https://www.xueshu789.cc/dbItem/3)
    → 301 → /doDownload/ 「文献下载中」中间页 HTML
         ↓
[解析]   从 HTML 提取最终下载地址
    → var downurl = "https://oversea.cnki.net/docdown/fulltext/download?q=...&invoice=..."
         ↓
[重写]   按 pdf.interstitial.host_fallbacks 生成候选列表
    → https://kns.cnki.net/docdown/fulltext/download?q=...&invoice=...
    → https://oversea.cnki.net/docdown/fulltext/download?q=...&invoice=...
         ↓
[HTTP]   GET 候选[0] → 校验 magic（%PDF-）+ 题名 → 原子落盘
    → 失败则试候选[1]
```

### 5.2 各段可行性（已实测）

| 段 | 可行性 | 依据 |
|---|---|---|
| 取 href | 必须浏览器 | 需登录态 + 结果表由 JS 渲染 |
| 取中间页 | HTTP 可行 | curl 复放已验证：`doDownload` 需带登录 cookie，Referer 为检索页 |
| 解析 downurl | HTTP 可行 | 中间页是含 `var downurl` 的静态 HTML，JS 只做 `window.location` 跳转 |
| 下载 PDF | HTTP 可行 | 同一 q/invoice token 换 `kns.cnki.net` → 200 `application/pdf`（curl 实测 1,070,254 B）；最终域无需 cookie |

**不可 HTTP 化的段**：检索页（`/dbItem/3` → 代理页，JS 渲染 + WAF）。因此快路径从「结果行」开始，检索仍在浏览器。

### 5.3 新模块 `backend/literature/interstitial.py`

纯函数模块，无 IO，单测友好：

```python
def parse_download_url(html: str) -> List[str]:
    """从中间页 HTML 提取候选下载地址，按出现顺序去重。"""

def rewrite_host_candidates(url: str, fallbacks: Sequence[str]) -> List[str]:
    """按 host_fallbacks 依次替换主机生成候选 URL；原域最后兜底。"""

def select_first_valid(candidates, fetch) -> Optional[Tuple[str, bytes]]:
    """按候选顺序取第一个通过校验的响应。"""
```

- `parse_download_url` 的提取顺序：`var downurl = "..."` / `window.location = "..."` / `<a id="successBtn" href="...">`，三者都命中时按上表顺序取，并保留全部候选；
- 复用 `search.py:147` 已有的 `_candidate_download_urls(url, hosts)` 做主机替换（避免两处逻辑漂移），本模块只是把它提取为可复用函数；
- `select_first_valid` 的 `fetch` 是注入的取数函数（生产传 HTTP 实现，测试传 lambda），使「换主机重试」逻辑可离线单测。

### 5.4 凭据：从浏览器分区到 vault

无需新增代码，链路已通：

1. 用户在可见窗口完成登录（`browser_login`）→ cookie 落在 `persist:sage-agent-browser` 分区；
2. `browser_cookies(action=export)` → 写入 `credential_vault`（`browser_tool.py:3275` 起的 `_export_cookies`，落库键 `domain::account_id`）；
3. HTTP 路径调用 `http_download(url=..., credential_domain="xueshu789.cc")` → `download_tool.py:479-512` 解析档案，把 cookie 放进请求头，并按 `cookie_domain_matches` **剥离跨域凭据**（同口径）。

**因此 skill 的固定步骤是**：登录 → `browser_cookies action=export` → 后续下载走 HTTP 快路径。`browser_cookies` 的 `export` 已含跨域检查（`browser_tool.py:3210`）。

### 5.5 合规闸门（HTTP 路径必须与浏览器路径对等）

这是本设计的**硬约束**，不是可选项。当前 HTTP 路径完全裸奔（C1 + C2 + S7），必须补齐：

| 闸门 | 现状 | 目标 |
|---|---|---|
| 站点策略 | HTTP 工具不查 `browser_safety` | `web_fetch` / `http_download` 出网前调 `browser_safety.check_site(ctx.session_id, url)`；返回 `confirm` → 注册 `ConfirmationRegistry.create(session_id, kind="site_access", domain=..., description=...)` 并以 `needs_confirmation: <id>` 形式报错，**与浏览器路径完全同构**，用户在同一个面板裁决 |
| 持久 block | 仅浏览器工具认 | HTTP 路径同样尊重持久 block（`check_site` 返回 `block` → 直接拒绝） |
| 限速 | profile 的 `rate_limit` 只是文本 | 新增 `backend/services/http_rate_limit.py`：per-host 最小间隔（通用层默认 1s，防滥用）；文献层再叠加 profile 的 `rate_limit.min_interval_s`（`models.py:114-116`，现默认 5s），并强制**下限 3s —— profile 即使写 0 也不放行**；`rate_limit.max_batch`（现默认 20）超限 → 人工确认 |
| 批量上限 | 无 | 同一 `credential_domain` 在一个运行目录内连续下载超过 `max_batch` → 触发确认 |

限速器的存储：进程内 per-host 时间戳表 + 运行目录内的计数（`run_store` 已有运行目录契约，可加 `downloads.jsonl` 记录每次下载的域与时间）。

### 5.6 降级策略

HTTP 快路径失败（中间页结构变化、404、凭据过期）时**自动回退浏览器路径**，即现有 `search.py:193` 的 `_download_via_interstitial`。降级必须：

- 在 `query_log` 记录降级原因（可观测性，见 §7.4）；
- **只降级一次**，不在同一次尝试里来回切；
- 降级后仍失败 → 如实报错，不伪造成功。

### 5.7 `web_fetch` 的 html 模式

不新增 `html` 模式。中间页是静态 HTML，`mode="raw"` 足以拿到 `var downurl`；新增模式只会扩大 `VALID_MODES` 的语义面而收益有限。若将来确有结构化提取需求，再评估。

---

## 6. 文献库全覆盖

### 6.1 库清单只能在登录后枚举

实测：`curl https://www.xueshu789.cc/dbList/` → HTTP 200，2188 字节，标题「系统提示」，正文「您还未登陆！ 3 秒后 自动跳转」。因此库清单**必须**在登录态下用浏览器抓取。

### 6.2 抓取流程（显式动作，不自动）

新增 CLI 子命令 `discover-backends`（`backend/literature/cli.py`）与等价工具：

1. 浏览器打开 `/dbList/`；
2. 从快照解析每个库入口（`/dbItem/N`）与库名；
3. 与 `backends[]` 现有条目比对，**新增的标 `unknown`、已存在的保留既有 `status`**（不覆盖人工判定）；
4. 写回 sidecar `<site_id>.backends.yaml`（同 §3.1 的 sidecar 原则，不动主 YAML）。

sidecar 合并规则与 `notes` 一致：主 YAML 的 `backends` 为人写基线，sidecar 覆盖同 `id` 条目。

### 6.3 探测（`status` 的产生方式）

`status != unknown` 需要**一次真实探测**，探测是**显式动作**（用户触发或首次使用该 backend 时提示），不是全量自动 —— 全量自动会连续触发 WAF。

探测规则：

- 打开 `entry_url` → 读取标题与关键错误文案；
- 命中代理报错 → `status: unavailable`，`reason` 记错误文案；
- 命中滑块 / 验证码 → `status: blocked`，`reason` 记「触发滑块验证」；
- 正常渲染出检索表单 → `status: ready`；
- 每次探测记 `checked_at`。

### 6.4 滑块与验证码：交还用户

`status: blocked` 的 backend **不自动重试、不尝试绕过**。运行时行为：

- 从候选 backend 中排除 `blocked`；
- 在指导文本里提示「backend `<id>` 需人工完成滑块验证，请用户在可见窗口操作」；
- 用户在可见窗口完成验证后，由用户显式把 `status` 改为 `ready`（或执行一次带人工介入的探测）。

这与 `browser_safety.classify_interact` 对验证码类动作的既有口径一致。

---

## 7. 沉淀闭环

### 7.1 观测 → 经验（`profile_record_note`）

新增工具 `profile_record_note`（能力分类 `ToolCapability.WRITE` —— `ToolCapability` 只有 READ / WRITE / EXECUTE 三值，`backend/tools/permissions.py:67-72`；本工具只写 `~/.sage/literature_sites/` 下的 sidecar，不触碰主 profile YAML）：

| 参数 | 类型 | 说明 |
|---|---|---|
| `site_id` | str | 目标站点 |
| `note_id` | str | 站点内唯一 slug（同 id 覆盖） |
| `title` / `symptom` / `cause` / `workaround` | str | 见 §3.1 字段契约 |
| `severity` | enum | blocker / degraded / cosmetic |
| `applies_to` | list[str] | 可选 |
| `source_run` | str | 可选，来源运行目录 |

写入 sidecar `<site_id>.notes.yaml`（原子写：`atomic_write_text`，与 `run_store.py` 同口径），读改写时按 `id` 合并。

**触发时机**：一次运行中出现「非预期失败」且根因已定位。LLM 调用该工具 → 经验进 profile → 下次运行时 `guidance.py` 自动渲染 → 不用重蹈覆辙。这是本设计闭环的核心。

### 7.2 确定性步骤 → scripts（Stagehand 模式）

主流做法（Stagehand「AI first run, script thereafter」）：第一次由 AI 跑通，之后固化成脚本走确定性路径。

Sage 侧：`script_runner.py` 已具备路径校验 + 用户确认 + 沙箱执行 + 异常收敛；`academic-search` 的「路径 B」已教用户把技能目录复制到 `~/.sage/skills/`。

设计：

- 脚本落在**用户级技能**目录 `~/.sage/skills/<skill>/scripts/`，例如 `~/.sage/skills/literature-helper/scripts/fetch_paper.py`；
- 职责限于**纯确定性、无副作用判断**的动作：读中间页 HTML、提取 `downurl`、按 fallback 规则生成候选 URL、比对 magic；
- **不做**：决定是否下载（这属合规判断，须留在 agent 侧）、登录、限速豁免；
- `ScriptRunner` 的沙箱边界（`inproc.py:149-155,163`）**不动** —— shipped 仍被排除，用户级脚本在允许根内。

### 7.3 合法可得性补充轴（Unpaywall）

现状：`backend/literature/verify.py` 已有 `CrossrefLookup` / `OpenAlexLookup` / `SemanticScholarLookup`，做**元数据核验**。缺的是「**全文是否合法可得、哪里可得**」这一轴 —— 正是行业主流（OpenScholar / PaperQA2 / ScienceAI / ScholarAgent）的做法：把「拿不到全文」转成「最大化合法可得性」。

新增 `UnpaywallLookup`：

- 端点 `https://api.unpaywall.org/v2/{doi}?email=...`；
- **需要真实 email**（服务要求）：`ComplianceSpec` 现只有 `note` / `default_enabled`（`models.py:120-122`），需**新增 `contact_email: str = ""`** 字段；取不到时该 lookup 标记为 unavailable 并**不阻断**主链路；
- 产出 `best_oa_url` / `oa_status` / `is_oa`；
- 与既有 `access_status` 概念合并为四态：`subscription`（站内授权）/ `oa`（开放获取）/ `closed`（需订阅）/ `unknown`。

**限流与礼貌**：Unpaywall 限额 100k/day；arXiv 3s/request；Europe PMC 禁止批量抓取；PMC 禁止系统性检索。这些约束写在 profile 的 `rate_limit` 与 lookup 实现里。

**不做**：不因 `oa_status` 而改变「是否下载付费文献」的行为 —— 下载权限只由站内授权决定。

### 7.4 可观测性：把降级原因写进 `query_log`

`run_store.record_query` 已有检索日志。扩展其记录项：

- `transport`: `browser` | `http`
- `fallback_reason`: HTTP 快路径失败的具体原因（如 `interstitial_parse_miss`、`host_404`、`credential_missing`）
- `backend_id`: 命中的 backend

这样「为什么这次慢了 / 为什么没走快路径」事后可查，而不是靠猜。

---

## 8. 既有代码缺陷修复

### 8.1 B1：`execute_code` RPC 拒绝 `browser_navigate`

**问题**：`execute_code_tool.py:64-78` 静态拒绝 EXECUTE 类工具，而 `browser_navigate` 是 EXECUTE（`permissions.py:186`），导致 `sage_driver.py` 的导航在子进程内必失败。

**方案（二选一，实施时按 §10 的测试证据定）**：

- **方案 1（推荐）**：给 `RPC_FORBIDDEN_TOOLS` 增加**显式白名单** `RPC_ALLOWED_EXECUTE_TOOLS = frozenset({"browser_navigate", "browser_snapshot", "browser_interact", "browser_tabs", "browser_downloads", "browser_cookies"})`，并保留「子进程内不触发逐次审批」的前提 —— 这些浏览器工具的写操作仍受 `browser_safety` 的站点策略与确认闸约束（确认在主循环注册，子进程只需传递 `needs_confirmation` 错误并退出，由主循环裁决）。
- **方案 2**：改 `literature-research` 技能，使导航与快照在主循环直接调用工具，中间页解析与 PDF 落盘才进 `execute_code`。**不动 RPC 语义**，风险最低，但技能正文要写得更啰嗦。

**推荐方案 1**，因为它让 `backend/literature/sage_driver.py` 这层抽象真正可用（目前它是一层死代码）。若实施中发现子进程内无法安全处理确认流程，回退方案 2。

### 8.2 B2：`credential_set` 文案指向不存在的工具

`download_tool.py:386/493/509` 与 `web_tool.py:627/761/777` 的文案改为指向真实存在的机制：
- 浏览器通道：`browser_cookies(action=export)` → 写 vault；
- HTTP 通道：给 `http_download` / `web_fetch` 传 `credential_domain`。

**不改工具名**（会破坏既有提示与测试），只改文案与提示的可行替代路径。

### 8.3 B3：`BROWSER_TOOL_NAMES` 漂移

- 把 `browser_list_accounts` / `browser_switch_account` 补进 `browser_tool.py:4092` 的元组（与 `tool_names.py:178-191` 对齐）；
- 新增**真正的**一致性测试：断言两个元组**集合相等**（而非只断言单个成员存在）；
- 把断言放进 CI 必跑路径。

---

## 9. 数据流与错误处理

### 9.1 一次「检索 → 下载」的完整数据流

```
用户：帮我找 X 主题的文献并下载全文
  │
  ├─ auto_activation 命中 literature-research → 注入正文 + 资源清单
  ├─ skill_read_resource 读取 references/pipeline.md（按需）
  ├─ profile_store.get(site_id) → SiteProfile（含 notes / backends）
  ├─ guidance.render_search_guidance(profile) → 注入「站点经验」段
  │     · blocker 级经验优先显示
  │     · backends 中 status=ready 的列为候选；blocked 的提示人工介入
  ├─ 浏览器：打开 backend.entry_url → 检索 → 读结果行 href
  │     · 需要登录时 → browser_login（可见窗口，用户手动）
  │     · 登录后 → browser_cookies action=export（写 vault，供后续 HTTP 用）
  ├─ HTTP 快路径：GET doDownload → 解析 → 换主机 → GET PDF → 校验 → 落盘
  │     · 失败 → 降级浏览器路径（记 fallback_reason）
  └─ record_query(transport, fallback_reason, backend_id)
```

### 9.2 错误分类与处置

| 错误 | 来源 | 处置 |
|---|---|---|
| `needs_confirmation: <id>` | 站点策略闸（浏览器或 HTTP） | 交还用户在确认面板裁决；工具层不自行放行 |
| `credential_missing` / `credential_expired` | vault | 提示重新 `browser_cookies action=export`；**不代填密码** |
| `interstitial_parse_miss` | HTTP 解析 | 降级浏览器路径 |
| `host_404`（全部候选都 404） | HTTP 下载 | 降级浏览器路径；记 `fallback_reason=host_404` |
| `magic_mismatch` / `title_mismatch` | PDF 校验（`search.py:131`） | 视为下载失败，删除临时文件，不接受「看起来对」的结果 |
| `backend_blocked`（滑块） | backend 探测 | 排除该 backend，提示用户人工完成，**不自动重试** |
| 限速超限 | 限速器 | 等待至允许时刻，或提示用户确认继续 |

**统一原则**：任何失败都**如实上报**并留下可追溯记录（`query_log`）；不允许「静默降级后报告成功」。

---

## 10. 测试策略

### 10.1 单元测试

| 模块 | 用例要点 |
|---|---|
| `literature/interstitial.py` | downurl 三种提取形态；候选 URL 顺序；主机替换；`select_first_valid` 用注入的 fake fetch 验证「首个失败 → 试下一个」 |
| `literature/models.py` | `notes` / `backends` 解析、校验、id 重复覆盖、severity 枚举拒绝、日期解析失败报错 |
| `literature/profile_store.py` | sidecar 合并（主 YAML 与 sidecar 同 id → sidecar 覆盖）；sidecar 缺失 → 行为不变；sidecar 损坏 → 明确报错而非静默忽略 |
| `tools/skill_resource_tool.py` | 路径越界（`../`、绝对路径、符号链接）、非白名单目录、reparse point、越界返回明确错误；读取 shipped 与用户级技能均成功 |
| `tools/permissions.py` / `execute_code` | `browser_navigate` 在白名单内可经 RPC 调用；非白名单 EXECUTE 仍被拒 |
| `tools/download_tool.py` / `web_tool.py` | 站点策略闸：block → 拒绝；confirm → 注册确认并报错；allow → 放行 |
| `services/http_rate_limit.py` | per-host 最小间隔；全局下限不被 profile 的 0 绕过；`max_batch` 超限触发确认 |

### 10.2 集成测试

- profile + skill 联动：加载一个带 `notes` / `backends` 的 profile → `render_search_guidance` 产出含「站点经验」段且 blocker 在前；
- `skill_read_resource` 与技能加载同源：加载的技能目录与 `skill_read_resource` 解析的目录一致。

### 10.3 真机 E2E（沿用 2026-11-27 的 harness 形态）

- 登录 → `browser_cookies export` → HTTP 快路径检索页取 href → HTTP 取中间页 → 换主机 → 落盘 PDF → 校验 magic + 题名；
- 与浏览器路径**同篇对比**：同一结果行，两条路径的落盘文件应字节级一致（或至少 magic + 题名 + 页数一致）；
- 记录耗时对比（目标：HTTP 路径 ≤ 浏览器路径的 1/3）。

### 10.4 回归

- `backend/tests/unit/test_literature_*.py` 全绿；
- `architecture-baseline.json` 行数棘轮：新增文件需同步基线（按分支实测值，win7 与 main 各自实测）；
- `ruff check` 干净（含 ERA001 中文注释规避、Q000 双引号约束）。

---

## 11. 实施阶段划分与双分支策略

三个阶段，每阶段可独立验证、独立成 PR。**实施计划由 writing-plans 阶段产出，本节只给阶段边界。**

| 阶段 | 内容 | 对应本文档 |
|---|---|---|
| **P0 止血** | 修 B1 / B2 / B3；`skill_read_resource` 工具；`references/pipeline.md` 接线；站点事实泛化收敛（§3.3 的 a/b/c 三项） | §4, §8 |
| **P1 快路径** | `interstitial.py`；HTTP 下载路径；站点策略闸 + 限速器；降级与 `query_log` 扩展 | §5, §7.4 |
| **P2 覆盖与沉淀** | `backends[]` 模型 + `discover-backends` + 探测；`notes[]` + `profile_record_note`；Unpaywall 轴；用户级脚本固化 | §3, §6, §7 |

**双分支**：`main`（py3.10 / pydantic 2.x）与 `release/win7`（py3.8 / pydantic 1.x）并行开发，**先合 win7 再合 main**（沿用既有惯例，避免基线/棘轮冲突）。跨分支只走 cherry-pick，win7 侧需适配：日期解析、typing 注解、`Optional` 用法、pydantic v1/v2 差异。

**与既有计划的关系**：`docs/plans/2026-11-21_literature-research-paper-pipeline.md` 中未勾选的 M0 项（以 xueshu789 为首个样例录制全流程、四个 REST adapter、去重与导出、钉 `paper_query_log`）与本设计**重叠**。处理方式：那些 M0 项由本计划承接并在计划文档中标注归属；该计划文档保留其余未完成项，完成后按项目规范合并进 `docs/technical/` 并删除计划文件。

---

## 12. 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 站点改版（中间页结构、选择器、库入口） | 快路径与 backends 失效 | profile 版本化 + `notes` 记录症状 + `last_verified_at` / `checked_at` 陈旧提示 + `validate-profile` 扩展 |
| HTTP 快路径被站点风控识别 | 下载失败 | 失败自动降级浏览器路径；限速保守；不做高频重试 |
| 合规闸门引入额外交互摩擦 | 用户体验下降 | 闸门只在**首次访问该域**与**超出批量上限**时触发，不做逐次确认 |
| `notes` / `backends` 引入 schema 变更 | 旧 profile 解析失败 | 全部字段可选、缺省行为不变；`SiteProfileStore.discover` 对旧文件零影响 |
| shipped 技能路径在安装包中变化 | `skill_read_resource` 定位失败 | 技能目录解析复用 `loader.discover_skill_md_dirs()`，与技能实际加载同源 |
| 限速器误伤正常 HTTP 使用 | 通用工具变慢 | 限速器为通用层（默认 1s）+ 文献层叠加（≥3s），只对**同一 host 的连续请求**生效 |
| win7 py38 语法/依赖差异 | 移植失败 | 新增代码只用 3.8 兼容语法；不引入新依赖；win7 先合再合 main |

**外部依赖**（均为公开服务，无需密钥，除 Unpaywall 需真实 email）：

| 服务 | 用途 | 限额 / 要求 |
|---|---|---|
| Unpaywall | OA 全文可得性 | 100k/day，需真实 email |
| Crossref | 元数据核验 | polite pool（`mailto=`） |
| OpenAlex | 元数据核验 | 免费 key（约 $0.10–1/day），全文 $10/1000 |
| Semantic Scholar | 元数据核验 | 无 key 有限速 |
| arXiv | 预印本 | 3s/request，单连接 |
| Europe PMC | OA 全文 | 禁止批量抓取 |

---

## 13. 明确不做的事（YAGNI）

- 不做「自动填卡号密码」的任何变体；
- 不做验证码 / 滑块的自动识别或绕过；
- 不做付费墙检测与规避（只做「合法可得性最大化」）；
- 不把 `notes` / `backends` 塞进记忆系统（记忆无 site 轴，硬塞等于制造第二套真相）；
- 不新增 `web_fetch` 的 html 模式；
- 不放开 shipped 脚本的沙箱边界；
- 不做「一个站点多份 profile」的家族机制（`backends[]` 已覆盖）；
- 不为 `academic-search` / `cnki-research` 等其他 shipped 技能做站点化改造（通用机制就绪后另立计划）。

---

## 14. 验收标准

P0–P2 全部完成后，下列条件成立：

1. `literature-research/references/pipeline.md` 可被 `skill_read_resource` 读到，且自动激活时出现在资源清单里；
2. `backend/literature/README.md` 与 `literature-research/SKILL.md` **不再含**站点具体事实（README 的 oversea 例证泛化、SKILL 的 `xueshu789.yaml` 改 `<site>.yaml`），站点事实只在 profile 的 `notes` / `pdf` / `search` 字段；`references/pipeline.md` 保持纯流程契约；
3. `BROWSER_TOOL_NAMES` 与 `tool_names.BROWSER_TOOLS` 集合相等，且有 CI 断言守护；
4. `credential_set` 不再出现在任何用户可见文案里；
5. HTTP 下载路径被 `browser_safety` 站点策略覆盖，限速真实生效（可在测试中断言最小间隔）；
6. `profile.rate_limit` 不再只是文本 —— 有可验证的执行点；
7. 一个 profile 能表达 ≥ 3 个检索后端及其各自状态；
8. 一次失败能被记成一条 `notes`，并在下次运行的指导文本里出现；
9. `UnpaywallLookup` 在配置了 email 时能返回 `best_oa_url`，未配置时**不影响**主链路；
10. 真机 E2E：HTTP 路径落盘的 PDF 通过 magic + 题名校验，耗时显著低于浏览器路径。
