# 文献站点知识沉淀与 HTTP 快路径 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「手动登录 + 受控浏览器」访问文献站点的经验固化为可复用的站点知识（profile `notes[]` / `backends[]` + skill `references/`），给 PDF 下载加一条受合规闸门与限速约束的 HTTP 快路径，并把观测自动沉淀成下一轮可直接复用的经验。

**Architecture:** 四层，站点差异只落在第 ① 层，代码里不得出现任何站点专属分支。① 站点知识层（`SiteProfile.notes` / `SiteProfile.backends` / skill `references/` / vault）→ ② 访问通路层（既有浏览器路径 + 新增 HTTP 快路径 + 共享合规闸门 `http_site_gate`）→ ③ 多后端层（`backends[]`、探测与枚举）→ ④ 沉淀闭环层（`profile_record_note` 写 sidecar → `guidance` 渲染回上下文）。HTTP 快路径通过**注入式 fetcher**实现，`backend/literature/` 不 import `backend/tools/`，闸门与限速由工具层承担。

**Tech Stack:** Python 3.10（main）/ Python 3.8（release/win7）；FastAPI；dataclass（不引入 pydantic v1/v2 差异）；`httpx`；PyYAML；pytest；ruff（`ERA001` / `Q000` 约束）。

**Spec:** `docs/superpowers/specs/2026-11-28-literature-site-knowledge-and-http-fastpath-design.md`（14 节；本计划逐节对应，附录 B 是验收对照表）

---

## Global Constraints

以下约束对**每个任务**都生效；任务内的隐含需求均包含本节。

### 合规红线（不可协商，spec §0.2）

- 不代填、不读取、不导出用户的卡号与密码；登录始终由用户在**可见浏览器窗口**完成。
- 验证码 / 滑块**一律不自动识别、不绕过**；命中即停，交还用户。
- 不绕过付费墙；只做「合法可得性最大化」（元数据 + OA 轴）。
- 不绕过限速、不批量无节制抓取：文献层 per-host 最小间隔**下限 3 秒**，profile 即使写 `0` 也不放行；`max_batch` 超限触发人工确认。
- 第三方站点默认 `compliance.default_enabled: false`。

### 工程约束

- 后端 Python 一律用 `/home/fz/anaconda3/envs/sage-backend/bin/python`（main）或 `/home/fz/anaconda3/envs/sage-backend-py38/bin/python`（win7）。**禁止**把包装进共享 conda 环境。
- 新增工具必须**三处同步登记**：`backend/tools/tool_bundles.py`（注册）、`backend/domain/tool_names.py`（名字元组）、`backend/tools/permissions.py`（能力分类）。否则 `backend/tests/unit/test_tool_names.py:41`（`ALL_BUILTIN_TOOL_NAMES == 注册面`）与 `backend/tests/unit/test_tool_capabilities.py:40/48`（`TOOL_CAPABILITIES == ALL_BUILTIN_TOOL_NAMES`）会红。
- `ToolCapability` 只有 `READ` / `WRITE` / `EXECUTE` 三个值，不得新增第四个。
- py38 兼容写法：`typing.List` / `typing.Optional`（不写 `list[str]`）；`isinstance` 多类型用 `tuple` 且加 `# noqa: UP038 — py38 兼容`；`datetime.now(timezone.utc)  # noqa: UP017 — py38 兼容`；`date.fromisoformat`（3.7+）可用；`dataclasses.replace`（3.8）可用。
- ruff：中文注释放 docstring 或用破折号规避 `ERA001`；字符串统一双引号（`Q000`）。提交前跑 `ruff check backend/`。
- 行数棘轮：`architecture-baseline.json` 格式 `{"version": 1, "files": {"<path>": <line_count>}}`，**按分支各自实测**（main 与 win7 分别测），只增不减。
- 双分支：`main`（py3.10 / pydantic 2.x）与 `release/win7`（py3.8 / pydantic 1.x）**先合 win7 再合 main**，跨分支**只走 cherry-pick**。禁止 `git merge release/win7`；禁止删除或 force-push `release/win7`；禁止在 main 改 `backend/requirements-py38.txt`、在 win7 改 `backend/requirements.txt`。
- 日志与聊天中**绝不**粘贴 raw `SAGE_LOCAL_AUTH_TOKEN` / bridge token。
- 不打扰用户自己的 checkout `/home/fz/project/sage`（分支 `docs/chat-composer-status-bar`）与其 Vite（端口 1420）。本计划全程在 worktree `/home/fz/project/sage/.worktrees/feat-literature-site-knowledge` 内作业。
- 每个任务结束时 `git commit`，commit message 用 conventional commits（`fix:` / `feat:` / `docs:` / `refactor:` / `test:`）。

### 站点差异归属表（spec §3.3，代码里不得越界）

| 知识类型 | 唯一归属 | 载体 |
|---|---|---|
| 流程契约（运行目录、产物 schema、步骤顺序） | skill `references/pipeline.md` | 纯流程，不含站点事实 |
| 站点操作事实（选择器、href 取法、中间页处理） | profile 的 `notes[]` + `pdf.*` / `search.*` | 版本化、可校验、进指导文本 |
| 合规约定 | profile `compliance.note` + skill 正文红线段 | 机器可读字段 + 不可绕过的流程约定 |
| 用户偏好（常用哪个库、常搜什么） | 记忆系统（`user` scope） | 记忆系统的本职 |

`notes[]` / `backends[]` **不进**记忆系统（记忆无 site 轴，硬塞等于制造第二套真相）。

---

## 文件结构总表

### 新建

| 文件 | 单一职责 |
|---|---|
| `backend/tools/skill_resource_tool.py` | `skill_read_resource` 工具：读技能内 `references/` 等白名单资源，纯只读 |
| `backend/tools/http_site_gate.py` | HTTP 出网前的站点策略闸门（`browser_safety.check_site` + `ConfirmationRegistry`） |
| `backend/tools/profile_note_tool.py` | `profile_record_note` 工具：把一次失败沉淀成站点经验（写 sidecar） |
| `backend/tools/profile_backend_tool.py` | `profile_discover_backends` 工具：解析库清单快照并写 backends sidecar |
| `backend/services/http_rate_limit.py` | per-host 最小间隔限速器（通用下限 1s + 文献层下限 3s） |
| `backend/literature/interstitial.py` | 中间页 HTML 解析 + 主机回退候选生成（纯函数，无 IO） |
| `backend/literature/pdf_check.py` | 下载文件的 magic + 题名校验（浏览器路径与 HTTP 路径共用，避免循环依赖） |
| `backend/literature/http_download.py` | HTTP 下载快路径（注入式 fetcher，原子落盘 + 校验） |
| `backend/literature/knowledge.py` | notes / backends sidecar 的读写与合并 |
| `backend/literature/backends.py` | 库清单快照解析 + 后端状态探测分类 |
| `backend/tests/unit/test_browser_tool_names_parity.py` | B3 回归守卫 |
| `backend/tests/unit/test_credential_error_text.py` | B2 回归守卫 |
| `backend/tests/unit/test_execute_code_rpc_policy.py` | B1 回归守卫 |
| `backend/tests/unit/test_skill_read_resource_tool.py` | `skill_read_resource` 单测 |
| `backend/tests/unit/test_literature_no_site_literals.py` | 站点事实泛化守卫 |
| `backend/tests/unit/test_http_site_gate.py` | 站点策略闸单测 |
| `backend/tests/unit/test_http_rate_limit.py` | 限速器单测 |
| `backend/tests/unit/test_literature_interstitial.py` | 中间页解析单测 |
| `backend/tests/unit/test_literature_http_download.py` | HTTP 下载单测 |
| `backend/tests/unit/test_literature_site_knowledge.py` | notes/backends 模型 + sidecar 单测 |
| `backend/tests/unit/test_literature_backends.py` | 后端枚举/探测单测 |
| `backend/tests/unit/test_literature_unpaywall.py` | Unpaywall lookup 单测 |
| `docs/templates/skills/literature-helper/scripts/parse_interstitial.py` | 用户级脚本：中间页解析（确定性、无副作用判断） |
| `docs/technical/180-literature-site-knowledge.md` | 技术文档（实施完成后并入，替代本计划文件） |

### 修改

| 文件 | 改动 |
|---|---|
| `backend/tools/browser_tool.py:4253-4265` | `BROWSER_TOOL_NAMES` 改为单一事实源（B3） |
| `backend/tools/execute_code_tool.py:40-78` | `RPC_ALLOWED_EXECUTE_TOOLS` 白名单（B1） |
| `backend/tools/download_tool.py:386/493/509` | `credential_set` 文案改为真实机制（B2）+ 站点闸门 |
| `backend/tools/web_tool.py:627/761/777` | 同上（B2）+ 站点闸门 |
| `backend/tools/tool_bundles.py:318` | 注册新工具 |
| `backend/domain/tool_names.py:200/294` | `SKILL_TOOLS` / `ALL_BUILTIN_TOOL_NAMES` 补名 |
| `backend/tools/permissions.py:201` | 新工具能力分类 |
| `backend/skills/skill_md/resources.py` | 新增 `resolve_indexed_resource` |
| `backend/skills/skill_md/auto_activation.py:133` | 自动激活时附带资源清单 |
| `backend/skills/skill_md/shipped/literature-research/SKILL.md` | 运行目录契约 + HTTP 快路径 + 经验沉淀 + 文献库枚举 + `<site>.yaml` 泛化 |
| `backend/literature/models.py:125-143/317/469` | `notes` / `backends` / `contact_email` / `render_search_url(backend_id=)` |
| `backend/literature/profile_store.py:53` | 跳过 sidecar 文件名 + 合并 sidecar |
| `backend/literature/guidance.py:20` | 渲染「站点经验」与「可用后端」段 |
| `backend/literature/run_store.py:43/128` | `record_query` 扩展 + `record_download` / `count_downloads` |
| `backend/literature/search.py:127/262` | `download_pdf` 接 `http_fetch=` + 一次性降级 |
| `backend/literature/verify.py` | `UnpaywallLookup` + `build_oa_lookups` + `verify_run_access` |
| `backend/literature/cli.py:78` | `discover-backends` 子命令 |
| `backend/literature/README.md:53/148` | 站点事实泛化 + 设计规则更新 |
| `docs/plans/2026-11-21_literature-research-paper-pipeline.md:383-391` | 标注 M0 项已由本计划承接 |
| `architecture-baseline.json` | 补新增文件的实测行数（按分支） |

---

## 阶段总览

| 阶段 | 任务 | 交付物 |
|---|---|---|
| **P0 止血** | T1–T6 | 三个代码缺陷修复；`skill_read_resource` 可用；`references/pipeline.md` 进上下文；站点事实不再散落 |
| **P1 快路径** | T7–T11 | 中间页解析 / HTTP 下载 / 站点闸门 / 限速 / 降级 / 可观测性 |
| **P2 覆盖与沉淀** | T12–T17 | `notes[]` `backends[]` 模型 + sidecar + 记录工具 + 枚举探测 + OA 轴 |
| **收尾** | T18–T19 | 文档归档 + 棘轮 + 旧计划标注 + 双分支 PR |

依赖关系见附录 A。

---

### Task 1: 修 B3 —— `BROWSER_TOOL_NAMES` 改为单一事实源

**Files:**
- Modify: `backend/tools/browser_tool.py:4253-4265`
- Test: `backend/tests/unit/test_browser_tool_names_parity.py`

**Interfaces:**
- Consumes: `backend.domain.tool_names.BROWSER_TOOLS`（`backend/domain/tool_names.py:181-194`，12 项）
- Produces: `browser_tool.BROWSER_TOOL_NAMES` —— `tuple[str, ...]`，与 `BROWSER_TOOLS` **集合相等**

**背景（spec §8.3 / B3）：** `browser_tool.py` 的 `BROWSER_TOOL_NAMES` 手抄了 10 项，漏了 `browser_list_accounts` 与 `browser_switch_account`；既有唯一断言只测「某个成员存在」，不比对两个元组，漂移不会被 CI 发现。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_browser_tool_names_parity.py`：

```python
"""BROWSER_TOOL_NAMES 与 domain/tool_names.BROWSER_TOOLS 必须集合相等。

spec §8.3（B3）：原实现手抄 10 项元组，漏掉 browser_list_accounts /
browser_switch_account，且既有断言只测成员存在、不比对元组，漂移不报错。
本文件把「单一事实源」钉成可执行断言。
"""

import pytest

from backend.domain import tool_names
from backend.tools import browser_tool
from backend.tools.permissions import TOOL_CAPABILITIES, ToolCapability

pytestmark = pytest.mark.unit


def test_browser_tool_names_matches_domain_registry() -> None:
    assert set(browser_tool.BROWSER_TOOL_NAMES) == set(tool_names.BROWSER_TOOLS)


def test_browser_tool_names_has_no_duplicates() -> None:
    names = list(browser_tool.BROWSER_TOOL_NAMES)
    assert len(names) == len(set(names)), f"BROWSER_TOOL_NAMES 存在重复项: {names}"


def test_every_domain_browser_tool_has_a_capability() -> None:
    missing = sorted(set(tool_names.BROWSER_TOOLS) - set(TOOL_CAPABILITIES))
    assert not missing, f"browser 工具缺能力登记: {missing}"
    for name in tool_names.BROWSER_TOOLS:
        assert TOOL_CAPABILITIES[name] in (
            ToolCapability.READ,
            ToolCapability.WRITE,
            ToolCapability.EXECUTE,
        )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-literature-site-knowledge
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_browser_tool_names_parity.py -q
```

Expected: FAIL —— `test_browser_tool_names_matches_domain_registry` 报缺 `browser_list_accounts` / `browser_switch_account`。

- [ ] **Step 3: 最小实现**

改 `backend/tools/browser_tool.py`，把第 4253-4265 行整段替换为：

```python
#: 与 domain/tool_names.py 的 BROWSER_TOOLS 保持一致 —— 直接引用而非手抄，
#: 手抄元组曾在 2026-11 漂移（漏 browser_list_accounts / browser_switch_account）
#: 且无测试比对（spec §8.3 / B3）。
BROWSER_TOOL_NAMES = BROWSER_TOOLS
```

并在文件顶部的 import 区加一行（与既有 `from backend.domain...` 分组放在一起）：

```python
from backend.domain.tool_names import BROWSER_TOOLS
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_browser_tool_names_parity.py \
  backend/tests/unit/test_browser_tool.py \
  backend/tests/unit/test_tool_names.py \
  backend/tests/unit/test_tool_capabilities.py -q
```

Expected: PASS（既有 `test_browser_tool.py:1348` 的 `assert "browser_downloads" in browser_tool.BROWSER_TOOL_NAMES` 仍成立）。

- [ ] **Step 5: 提交**

```bash
git add backend/tools/browser_tool.py backend/tests/unit/test_browser_tool_names_parity.py
git commit -m "fix(browser): BROWSER_TOOL_NAMES 改为引用 domain 单一事实源并加集合相等守卫"
```

---

### Task 2: 修 B2 —— `credential_set` 文案指向不存在的工具

**Files:**
- Modify: `backend/tools/download_tool.py:386/493/509`
- Modify: `backend/tools/web_tool.py:627/761/777`
- Test: `backend/tests/unit/test_credential_error_text.py`

**Interfaces:**
- Consumes: `backend.domain.tool_names.ALL_BUILTIN_TOOL_NAMES`（判定文案里提到的工具名是否真实存在）
- Produces: 无新公开符号；只改用户可见错误文案

**背景（spec §8.2 / B2）：** 6 处文案让模型去调 `credential_set` —— **全仓无此工具**。模型照做只会再失败一次。改为指向真实存在的两条路径：浏览器通道 `browser_cookies(action=export)`；HTTP 通道给 `http_download` / `web_fetch` 传 `credential_domain`。**不改工具名**（会破坏既有提示与测试），只改文案。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_credential_error_text.py`：

```python
"""用户可见文案不得指向不存在的工具（spec §8.2 / B2）。

`credential_set` 曾在 download_tool / web_tool 的 6 处错误文案里出现，
但全仓没有这个工具 —— 模型照做只会再失败一次。
"""

import re
from pathlib import Path

import pytest

from backend.domain.tool_names import ALL_BUILTIN_TOOL_NAMES
from backend.tools import download_tool, web_tool

pytestmark = pytest.mark.unit

#: 形如 `credential_set` / `foo_bar_set` 的「工具名」字面量。
#: 反引号可有可无 —— 现有文案是**裸写** ``credential_set``（没有反引号），
#: 只匹配反引号形式会让本测试在未修复时就通过（失去回归价值）。
_TOOL_NAME_LITERAL = re.compile(r"`?([a-z][a-z0-9_]*_set)`?")

_TARGET_FILES = (download_tool, web_tool)


def _module_source(module) -> str:
    """读模块源码（用 Path 读文件，避免 ruff SIM115 的裸 open 告警）。"""
    return Path(str(module.__file__)).read_text(encoding="utf-8")


def test_no_user_visible_text_references_a_nonexistent_set_tool() -> None:
    known = set(ALL_BUILTIN_TOOL_NAMES)
    offenders = []
    for module in _TARGET_FILES:
        source = _module_source(module)
        for match in _TOOL_NAME_LITERAL.finditer(source):
            name = match.group(1)
            if name not in known:
                offenders.append(f"{module.__name__}: {name}")
    assert not offenders, (
        "文案引用了不存在的工具（模型会照做再失败一次）: " + ", ".join(offenders)
    )


def test_credential_set_is_not_referenced_anywhere_in_those_modules() -> None:
    for module in _TARGET_FILES:
        source = _module_source(module)
        assert "credential_set" not in source, (
            f"{module.__name__} 仍含 credential_set 文案"
        )
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_credential_error_text.py -q
```

Expected: FAIL —— 报出 `download_tool` / `web_tool` 中的 `credential_set`。

- [ ] **Step 3: 改文案**

`backend/tools/download_tool.py` 第 386 行（`credential_domain` 参数的 description）改为：

```python
"credential_domain": {
    "type": "string",
    "description": (
        "凭据档案 domain（如 .cnki.net）：browser_cookies action=export 导出的 cookie，"
        "命中域自动附加、跨域剥离；不传时自动从 URL hostname 推断；"
        "过期报 credential_expired，被送到登录页报 login_required"
    ),
},
```

同文件第 493 行（`credential_expired` 错误分支）改为：

```python
error=(
    f"credential_expired: {credential_domain!r} 的凭据已全部过期"
    f"（{', '.join(resolution.expired_names[:5])}）。"
    "请在浏览器重新登录后 browser_cookies action=export 重新导出"
),
```

同文件第 509 行（`credential_not_found` 错误分支）改为：

```python
error=(
    f"credential_not_found: 无 {credential_domain!r} 的凭据档案"
    "（先 browser_cookies action=export 导出）"
),
```

`backend/tools/web_tool.py` 第 627 行（`credential_expired` 分支）改为：

```python
error=(
    f"credential_expired: {credential_domain!r} 的凭据已全部过期"
    f"（{', '.join(resolution.expired_names[:5])}）。"
    "请在浏览器重新登录后 browser_cookies action=export 重新导出"
),
```

同文件第 761 行（`credential_not_found` 分支）改为：

```python
error=(
    f"credential_not_found: 无 {credential_domain!r} 的凭据档案"
    "（先 browser_cookies action=export 导出）"
),
```

同文件第 777 行（schema 里 `credential_domain` 的 description）改为：

```python
"credential_domain": {
    "type": "string",
    "description": (
        "browser_cookies action=export 导出的凭据档案 domain（如 .cnki.net）；"
        "命中域自动附加、跨域剥离；不传时自动从 URL hostname 推断"
    ),
},
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_credential_error_text.py \
  backend/tests/unit/test_download_tool.py \
  backend/tests/unit/test_web_tool.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/tools/download_tool.py backend/tools/web_tool.py \
  backend/tests/unit/test_credential_error_text.py
git commit -m "fix(tools): credential 错误文案改指向 browser_cookies action=export"
```

---

### Task 3: 修 B1 —— `execute_code` RPC 白名单放行浏览器只读/低风险面

**Files:**
- Modify: `backend/tools/execute_code_tool.py:56-79`
- Test: `backend/tests/unit/test_execute_code_rpc_policy.py`

**Interfaces:**
- Consumes: `backend.tools.permissions.classify_tool` / `ToolCapability`
- Produces: `execute_code_tool.RPC_ALLOWED_EXECUTE_TOOLS` —— `frozenset[str]`；`_rpc_denial_reason(tool_name) -> Optional[str]`（返回 `None` 表示允许）

**背景（spec §8.1 / B1）：** RPC 静态拒绝所有 `ToolCapability.EXECUTE` 工具，而 `browser_navigate` / `browser_login` 是 EXECUTE → `backend/literature/sage_driver.py` 的 `navigate()` 在子进程内必失败。修法：给**显式白名单**，这些工具的写操作仍受 `browser_safety` 站点策略与确认闸约束（确认在主循环注册，子进程只需把 `needs_confirmation` 错误传回并退出，由主循环裁决）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_execute_code_rpc_policy.py`：

```python
"""execute_code 子进程 RPC 的准入策略（spec §8.1 / B1）。

RPC 桥没有交互式审批通道，因此默认拒绝 EXECUTE 面；但文献链路
（backend/literature/sage_driver.py）依赖 browser_navigate / browser_snapshot，
它们被归为 EXECUTE —— 静态一刀切会让整条链路在子进程内必失败。
本测试钉住「白名单放行 + 非白名单仍拒」。
"""

import pytest

from backend.tools.execute_code_tool import (
    RPC_ALLOWED_EXECUTE_TOOLS,
    RPC_FORBIDDEN_TOOLS,
    _rpc_denial_reason,
)
from backend.tools.permissions import ToolCapability, classify_tool

pytestmark = pytest.mark.unit


def test_allowed_whitelist_covers_the_documented_browser_surface() -> None:
    expected = {
        "browser_cookies",
        "browser_downloads",
        "browser_interact",
        "browser_navigate",
        "browser_snapshot",
        "browser_tabs",
    }
    assert expected <= set(RPC_ALLOWED_EXECUTE_TOOLS)


def test_whitelisted_tools_are_allowed_over_rpc() -> None:
    for name in sorted(RPC_ALLOWED_EXECUTE_TOOLS):
        assert _rpc_denial_reason(name) is None, f"{name} 应可经 RPC 调用"


def test_non_whitelisted_execute_tools_are_still_denied() -> None:
    denied = [
        name
        for name in ("browser_launch", "browser_login", "bash", "skill")
        if classify_tool(name) is ToolCapability.EXECUTE
    ]
    for name in denied:
        assert name not in RPC_ALLOWED_EXECUTE_TOOLS
        assert _rpc_denial_reason(name) is not None, f"{name} 仍应被拒绝"


def test_forbidden_tools_stay_denied_even_if_whitelisted() -> None:
    assert "ask_user_question" in RPC_FORBIDDEN_TOOLS
    assert _rpc_denial_reason("ask_user_question") is not None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_execute_code_rpc_policy.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'RPC_ALLOWED_EXECUTE_TOOLS'`。

- [ ] **Step 3: 最小实现**

改 `backend/tools/execute_code_tool.py` 第 56-79 行区域：保留现有
`RPC_FORBIDDEN_TOOLS` 定义**不动**，在它**之后**新增白名单常量
（下面第一段只是重贴既有定义供对照，**不要**重复定义），
并调整判定：

```python
#: 子进程桥禁止调用的工具。RPC 在 executor 线程里同步执行，没有交互式
#: 审批通道（execute_code 本身已在主循环获得一次审批），所以凡需要逐次
#: 审批的能力面必须静态拒绝，由 LLM 改在主循环直接调用。
RPC_FORBIDDEN_TOOLS = frozenset(
    {
        # 需要主循环的提问卡片 + 等待通道，子进程内无法完成。
        "ask_user_question",
    }
)

#: EXECUTE 面里「允许经 RPC 调用」的显式白名单（spec §8.1 / B1）。
#:
#: 这些工具的写操作仍受 browser_safety 的站点策略与确认闸约束 ——
#: 确认在主循环注册，子进程只需把 needs_confirmation 错误传回并退出，
#: 由主循环裁决。因此放行的是「调用能力」，不是「跳过审批」。
#:
#: 白名单之外的 EXECUTE 工具（browser_launch / browser_login / bash /
#: skill 等）依旧静态拒绝，引导 LLM 改在主循环直接调用。
RPC_ALLOWED_EXECUTE_TOOLS = frozenset(
    {
        "browser_cookies",
        "browser_downloads",
        "browser_interact",
        "browser_navigate",
        "browser_snapshot",
        "browser_tabs",
    }
)
```

把 `_rpc_denial_reason` 的函数体替换为：

```python
def _rpc_denial_reason(tool_name: str) -> Optional[str]:
    """返回静态拒绝原因；``None`` 表示允许经 RPC 调用。"""
    if tool_name in RPC_FORBIDDEN_TOOLS:
        return f"execute_code RPC 禁止调用 {tool_name}（需要主循环交互通道）"
    if tool_name in SELF_MODIFY_TOOLS:
        return (
            f"execute_code RPC 禁止调用自管理工具 {tool_name}；"
            "请在主循环直接调用，以便经用户审批"
        )
    if classify_tool(tool_name) is ToolCapability.EXECUTE:
        if tool_name in RPC_ALLOWED_EXECUTE_TOOLS:
            return None
        return (
            f"execute_code RPC 禁止调用执行面工具 {tool_name}；"
            "请在主循环直接调用，以便经用户审批"
        )
    return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_execute_code_rpc_policy.py \
  backend/tests/unit/test_execute_code.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/tools/execute_code_tool.py backend/tests/unit/test_execute_code_rpc_policy.py
git commit -m "fix(execute-code): RPC 准入加浏览器只读/低风险面白名单"
```

---

### Task 4: 新增 `skill_read_resource` 工具（references 接线的前半）

**Files:**
- Modify: `backend/skills/skill_md/resources.py`（新增 `resolve_indexed_resource`）
- Create: `backend/tools/skill_resource_tool.py`
- Modify: `backend/tools/tool_bundles.py:318`（`_install_skill` 内注册）
- Modify: `backend/domain/tool_names.py:200`（`SKILL_TOOLS`）
- Modify: `backend/tools/permissions.py:201` 附近（能力登记）
- Test: `backend/tests/unit/test_skill_read_resource_tool.py`

**Interfaces:**
- Consumes:
  - `backend.skills.skill_md.resources.build_resource_index(base_dir) -> ResourceIndex`
  - `backend.skills.skill_md.resources.ResourceIndex`（字段 `scripts/references/assets/templates`，均为 `Tuple[Path, ...]`）
  - `backend.skills.skill_md.loader.discover_skill_md_dirs() -> List[Path]`
  - `backend.skills.skill_md.loader._discover_shipped_dir() -> Optional[Path]`
- Produces:
  - `backend.skills.skill_md.resources.resolve_indexed_resource(index, base_dir, relative_path) -> Optional[Path]`
  - `backend.tools.skill_resource_tool.SkillReadResourceTool`（`BaseTool` 子类，工具名 `skill_read_resource`）
  - `backend.tools.skill_resource_tool.resolve_skill_dir(skill_name) -> Optional[Path]`

**背景（spec §4.2）：** `references/` 机制建好但**从未接线** —— `render_body_with_resources` 只把 `{baseDir}/x` 渲染成相对路径，模型无法据此定位文件；`grep -rn "{baseDir}" backend/skills/skill_md/shipped/` 零命中。新增 READ 能力工具，让模型能按需读取 `references/pipeline.md`。技能目录解析顺序必须与 `loader.discover_skill_md_dirs()` 同源，避免「读到的和生效的不是同一份」。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_skill_read_resource_tool.py`：

```python
"""skill_read_resource 工具（spec §4.2）。

只读能力：按 skill 名 + 技能内相对路径读取 references/ 等白名单资源。
路径越界 / 非白名单目录 / 非索引文件一律拒绝并给出明确错误。
"""

import pytest

from backend.skills.skill_md.loader import discover_skill_md_dirs
from backend.tools.skill_resource_tool import (
    SkillReadResourceTool,
    resolve_skill_dir,
)

pytestmark = pytest.mark.unit

SHIPPED_LITERATURE = "literature-research"
PIPELINE_REL = "references/pipeline.md"


def _tool() -> SkillReadResourceTool:
    return SkillReadResourceTool()


def test_shipped_skill_directory_is_resolvable() -> None:
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None, "shipped literature-research 应可解析"
    assert (base / "SKILL.md").is_file()
    assert (base / PIPELINE_REL).is_file()


def test_read_pipeline_reference_returns_content() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path=PIPELINE_REL)
    assert result.success is True, result.error
    assert result.content["path"] == PIPELINE_REL
    assert result.content["total_lines"] > 0
    assert result.content["content"].strip()


def test_offset_and_limit_paginate() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path=PIPELINE_REL, offset=2, limit=3)
    assert result.success is True, result.error
    lines = result.content["content"].splitlines()
    assert len(lines) == 3
    assert result.content["offset"] == 2
    assert result.content["truncated"] is True


def test_absolute_path_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="/etc/passwd")
    assert result.success is False
    assert "path" in (result.error or "").lower()


def test_parent_traversal_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="references/../../escape.md")
    assert result.success is False


def test_non_whitelisted_directory_is_rejected() -> None:
    result = _tool().execute(skill=SHIPPED_LITERATURE, path="SKILL.md")
    assert result.success is False


def test_unknown_skill_is_reported() -> None:
    result = _tool().execute(skill="no-such-skill-xyz", path=PIPELINE_REL)
    assert result.success is False
    assert "no-such-skill-xyz" in (result.error or "")


def test_resolution_order_matches_loader_discovery() -> None:
    """解析顺序必须与技能加载同源：用户层优先于 shipped。"""
    roots = discover_skill_md_dirs()
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    if roots:
        expected_first = roots[0] / SHIPPED_LITERATURE
        if expected_first.is_dir():
            assert base == expected_first.resolve()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_skill_read_resource_tool.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.tools.skill_resource_tool'`。

- [ ] **Step 3a: 在 `resources.py` 增加索引解析函数**

改 `backend/skills/skill_md/resources.py`：第 27 行 import 改为

```python
from typing import List, Optional, Set, Tuple
```

在 `validate_resource_path` 之后（约第 258 行）插入：

```python
def resolve_indexed_resource(
    index: ResourceIndex,
    base_dir: Path,
    relative_path: str,
) -> Optional[Path]:
    """把技能内相对路径解析为已索引的普通文件路径。

    与 :func:`render_body_with_resources` 同口径地复用
    :func:`_indexed_regular_resources` 的完整策略（白名单子目录、隐藏项、
    符号链接 / reparse point、regular file 复核），因此「能渲染」与「能读取」
    不会分叉。

    Args:
        index: 技能的资源索引（由 :func:`build_resource_index` 产出）。
        base_dir: 技能根目录。
        relative_path: 技能内相对路径，如 ``references/pipeline.md``。

    Returns:
        规范化后的绝对路径；不合法或未索引时返回 ``None``。
    """
    text = str(relative_path or "").strip()
    relative = Path(text)
    # 一次性判掉所有非法相对路径（PLR0911：合并成一个 return，避免超过 6 个返回点）。
    if (
        not text
        or "\x00" in text
        or "\\" in text
        or relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or "." in relative.parts
        or relative.parts[0] not in ALLOWED_RESOURCE_DIRS
        or any(part.startswith(".") for part in relative.parts)
    ):
        return None

    try:
        resolved_base = base_dir.resolve(strict=True)
        candidate = resolved_base / relative
        resolved = validate_resource_path(candidate, base_dir=resolved_base)
    except (OSError, RuntimeError, SkillMdSecurityError):
        return None

    authorized = _indexed_regular_resources(index, resolved_base)
    if resolved not in authorized:
        return None
    return resolved
```

- [ ] **Step 3b: 新建工具文件**

创建 `backend/tools/skill_resource_tool.py`：

```python
"""skill_read_resource 工具 —— 读取技能内白名单资源（spec §4.2）。

只读能力（READ）：按「技能名 + 技能内相对路径」读取 ``references/`` /
``assets/`` / ``templates/`` / ``scripts/`` 下的已索引文件。

设计要点
--------
- **渐进披露**：不把资源内容预先灌进 system prompt，模型按需读取。
- **与技能加载同源**：技能目录解析顺序复用
  ``loader.discover_skill_md_dirs()`` + ``loader._discover_shipped_dir()``，
  避免「读到的和生效的不是同一份」。
- **不执行任何代码**：``.py`` 脚本只作为文本返回；脚本执行仍走
  ``ScriptRunner`` 的既有审批通道（spec §4.5）。
- **路径安全**：复用 ``resources.resolve_indexed_resource``，与渲染路径
  同口径的白名单 + 越界 + reparse-point 防护。
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.skills.skill_md.loader import _discover_shipped_dir, discover_skill_md_dirs
from backend.skills.skill_md.resources import (
    build_resource_index,
    resolve_indexed_resource,
)

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

SKILL_READ_RESOURCE_TOOL_NAME = "skill_read_resource"

#: 单次读取的最大行数（防止把大文件整篇灌进上下文）。
MAX_LINES = 2000
#: 默认读取行数。
DEFAULT_LINES = 300


def resolve_skill_dir(skill_name: str) -> Optional[Path]:
    """解析技能目录；解析顺序与技能实际加载顺序一致。

    顺序：``$SAGE_SKILLS_DIR`` > preference ``skills_dir`` > ``$CWD/skills``
    > ``~/.sage/skills`` > shipped。
    """
    name = str(skill_name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None

    candidates: List[Path] = []
    for root in discover_skill_md_dirs():
        candidates.append(root / name)
    shipped = _discover_shipped_dir()
    if shipped is not None:
        candidates.append(shipped / name)

    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _read_text(path: Path) -> Optional[str]:
    """按 no-follow 方式读普通文件内容；不安全或失败返回 ``None``。"""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return None


class SkillReadResourceTool(BaseTool):
    """读取技能内白名单资源。"""

    risk = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=SKILL_READ_RESOURCE_TOOL_NAME,
            description=(
                "读取技能内的白名单资源（如 references/pipeline.md 的流程契约）。"
                "参数 skill=技能目录名，path=技能内相对路径。"
                "只读，不执行代码。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "技能名（目录名），如 literature-research",
                    },
                    "path": {
                        "type": "string",
                        "description": "技能内相对路径，如 references/pipeline.md",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行（1 起），默认 1",
                    },
                    "limit": {
                        "type": "integer",
                        "description": f"读取行数，默认 {DEFAULT_LINES}，上限 {MAX_LINES}",
                    },
                },
                "required": ["skill", "path"],
            },
        )

    def execute(
        self,
        skill: str = "",
        path: str = "",
        offset: int = 1,
        limit: int = DEFAULT_LINES,
        **kwargs: Any,
    ) -> ToolResult:
        """按技能名与相对路径读取资源。"""
        base_dir = resolve_skill_dir(skill)
        if base_dir is None:
            return ToolResult(
                success=False,
                error=f"skill_not_found: 找不到技能 {skill!r}",
            )

        index = build_resource_index(base_dir)
        resolved = resolve_indexed_resource(index, base_dir, path)
        if resolved is None:
            return ToolResult(
                success=False,
                error=f"invalid_resource_path: {path!r} 不是技能 {skill!r} 的可读资源",
            )

        text = _read_text(resolved)
        if text is None:
            return ToolResult(
                success=False,
                error=f"resource_read_failed: 无法读取 {path!r}",
            )

        lines = text.splitlines()
        total = len(lines)
        try:
            start = max(1, int(offset))
        except (TypeError, ValueError):
            start = 1
        try:
            count = int(limit)
        except (TypeError, ValueError):
            count = DEFAULT_LINES
        count = max(1, min(count, MAX_LINES))

        selected = lines[start - 1 : start - 1 + count]
        payload: Dict[str, Any] = {
            "path": path,
            "content": "\n".join(selected),
            "offset": start,
            "limit": count,
            "total_lines": total,
            "truncated": (start - 1 + len(selected)) < total,
        }
        return ToolResult(success=True, content=payload)
```

- [ ] **Step 3c: 三处登记新工具**

`backend/domain/tool_names.py` 第 200 行：

```python
SKILL_TOOLS = ("skill", "skill_read_resource", "skill_save")
```

`backend/tools/permissions.py`：在 `"skill_save": ToolCapability.WRITE,` 下一行插入

```python
    "skill_read_resource": ToolCapability.READ,
```

`backend/tools/tool_bundles.py`：`_install_skill` 函数体改为

```python
def _install_skill(ctx: ToolInstallContext) -> None:
    # M2 part B: in-loop 技能调用（EXECUTE，M1 审批闸口按模式矩阵拦截）
    ctx.registry.register(SkillTool(policy=ctx.policy))
    # skill_read_resource：读取技能内白名单资源（READ，渐进披露）
    from .skill_resource_tool import SkillReadResourceTool

    ctx.registry.register(SkillReadResourceTool(policy=ctx.policy))
```

并在文件顶部的工具 import 区加：

```python
from .skill_resource_tool import SkillReadResourceTool
```

> 若 `tool_bundles.py` 顶部已有集中 import 区，则加在那里；否则上面的函数内延迟 import 也可（避免与 `_install_skill` 同文件的其他延迟 import 风格冲突）。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_skill_read_resource_tool.py \
  backend/tests/unit/test_tool_names.py \
  backend/tests/unit/test_tool_capabilities.py \
  backend/tests/unit/test_tool_bundles_parity.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/skills/skill_md/resources.py backend/tools/skill_resource_tool.py \
  backend/tools/tool_bundles.py backend/domain/tool_names.py \
  backend/tools/permissions.py backend/tests/unit/test_skill_read_resource_tool.py
git commit -m "feat(skills): 新增 skill_read_resource 工具（READ，渐进披露接线）"
```

---

### Task 5: `references/` 接线 —— 自动激活附带资源清单 + SKILL.md 运行目录契约

**Files:**
- Modify: `backend/skills/skill_md/auto_activation.py:133`（`build_context_block`）
- Modify: `backend/skills/skill_md/shipped/literature-research/SKILL.md`
- Test: `backend/tests/unit/test_skill_read_resource_tool.py`（追加）

**Interfaces:**
- Consumes: `backend.skills.skill_md.resources.ResourceIndex`（`doc.resources`）、`SkillMdDocument.base_dir`
- Produces: `auto_activation.render_resource_manifest(base_dir, index) -> List[str]`；`build_context_block` 在技能正文后追加「本技能可用资源（用 skill_read_resource 读取）」块

**背景（spec §4.4 / §4.3）：** 模型必须**知道有文档可读**，但不能预先灌入内容 —— 保持渐进披露。SKILL.md 正文用 `{baseDir}` 写定位提示，实际读取走 `skill_read_resource`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_skill_read_resource_tool.py` 末尾追加：

```python
def test_auto_activation_manifest_lists_pipeline_reference() -> None:
    from backend.skills.skill_md.auto_activation import render_resource_manifest
    from backend.skills.skill_md.resources import build_resource_index

    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    manifest = render_resource_manifest(base, build_resource_index(base))
    joined = "\n".join(manifest)
    assert "references/pipeline.md" in joined
    assert "skill_read_resource" in joined


def test_skill_md_declares_the_run_directory_contract() -> None:
    """SKILL.md 必须写出「用 skill_read_resource 读 pipeline.md」的契约。"""
    base = resolve_skill_dir(SHIPPED_LITERATURE)
    assert base is not None
    text = (base / "SKILL.md").read_text(encoding="utf-8")
    assert "skill_read_resource" in text
    assert "references/pipeline.md" in text
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_skill_read_resource_tool.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'render_resource_manifest'`。

- [ ] **Step 3a: 在 `auto_activation.py` 增加清单渲染**

改 `backend/skills/skill_md/auto_activation.py`：**沿用该文件既有的相对导入风格**
（现为 `from .resources import render_body_with_resources`）。import 区改为下面这样
（`from pathlib import Path` 必须落在 `from dataclasses import ...` 之后、
`from typing import ...` 之前，否则 ruff I001 报 import 排序错）：

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .resources import ResourceIndex, render_body_with_resources
from .skill import SkillMdDocument
from .validation import SkillMdSecurityError
```

> ⚠️ `List` 已在该文件第 45 行随 `Dict, Iterable, List, Sequence, Tuple` 一起导入
> —— **不要**再单独写 `from typing import List`，否则 ruff F811 报重复定义。
> 该文件也**不要**改用 `backend.skills.skill_md.resources` 这种绝对导入，
> 与同目录其余模块的相对导入风格保持一致。

并在 `build_context_block` 之前插入：

```python
#: 资源清单的引导语 —— 与 skill_read_resource 工具描述用同一个名字，
#: 模型据此知道「有文档可读、怎么读」。
_RESOURCE_MANIFEST_HEADER = "本技能可用资源（用 skill_read_resource 读取）："


def _count_lines(path: Path) -> int:
    """统计文件行数；失败返回 0（不因行数统计阻断清单渲染）。"""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def render_resource_manifest(base_dir: Path, index: ResourceIndex) -> List[str]:
    """渲染技能可用资源清单行（spec §4.4）。

    只列索引里的白名单资源，每行格式 ``- <相对路径>（<行数> 行）``；
    没有资源时返回空列表 —— 调用方不注入任何清单块。
    """
    if base_dir is None or index is None:
        return []
    try:
        # 索引里存的是 canonical 绝对路径（build_resource_index 用
        # base_dir.resolve(strict=True) 产出），而 doc.base_dir 未必已解析；
        # 必须先解析 base 再算相对路径，否则 relative_to 抛 ValueError。
        resolved_base = Path(base_dir).resolve()
    except OSError:
        return []
    entries: List[str] = []
    for category in ("references", "scripts", "assets", "templates"):
        for resource in getattr(index, category, ()) or ():
            try:
                relative = Path(resource).relative_to(resolved_base).as_posix()
            except ValueError:
                continue
            entries.append(f"- {relative}（{_count_lines(Path(resource))} 行）")
    if not entries:
        return []
    return [_RESOURCE_MANIFEST_HEADER, *entries]
```

在 `build_context_block` 里，`try: ... except SkillMdSecurityError: ... continue` 这段
**之后**、`parts.append(...)` 之前（即 `for doc in activated:` 循环体内）插入：

```python
            manifest = render_resource_manifest(doc.base_dir, doc.resources)
            if manifest:
                body = body + "\n\n" + "\n".join(manifest)
```

> 锚点：`auto_activation.py` 第 168 行的 `continue` 之后、第 169 行的 `parts.append(` 之前。
> `doc.base_dir` / `doc.resources` 可能为 `None`（既有代码已用
> `if doc.base_dir is not None and doc.resources is not None` 保护），清单渲染须放在
> 该 `if` 之外但对 `None` 做兜底 —— `render_resource_manifest` 已对 `None` 返回 `[]`。

- [ ] **Step 3b: SKILL.md 写运行目录契约**

改 `backend/skills/skill_md/shipped/literature-research/SKILL.md`，在正文合适位置（建议紧跟「工作流程」小节之后）插入新小节：

```markdown
## 运行目录契约

meta.json / papers.jsonl / evidence.jsonl / claims.jsonl / outline.json /
draft.md / verification.json 的字段定义见 {baseDir}/references/pipeline.md，
需要时用 skill_read_resource 读取
（skill="literature-research", path="references/pipeline.md"）。
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_skill_read_resource_tool.py \
  backend/tests/unit/test_skill_auto_activation.py -q
```

Expected: PASS。

> 现有的 `backend/tests/unit/test_skill_auto_activation.py` 对上下文块全部用
> `in` 包含断言（如 `assert "skill body" in result.context_block`），没有「精确
> 等于正文」的用例 —— 追加清单块不会打破既有断言。

- [ ] **Step 5: 提交**

```bash
git add backend/skills/skill_md/auto_activation.py \
  backend/skills/skill_md/shipped/literature-research/SKILL.md \
  backend/tests/unit/test_skill_read_resource_tool.py
git commit -m "feat(skills): 自动激活附带资源清单 + SKILL.md 声明运行目录契约"
```

---

### Task 6: 站点事实泛化收敛（spec §3.3 的 a/b/c 三项）

**Files:**
- Modify: `backend/literature/README.md:53`、`:148`
- Modify: `backend/skills/skill_md/shipped/literature-research/SKILL.md:250-270`
- Test: `backend/tests/unit/test_literature_no_site_literals.py`

**Interfaces:**
- Consumes: 无新符号
- Produces: 守卫测试 `test_literature_no_site_literals.py`，扫描 `backend/literature/*.py` 与 literature SKILL.md，断言不含站点专属字面量

**背景（spec §3.3）：** 站点事实当前散落三处，且运行期无法回写。收敛后站点知识的归属唯一。`references/pipeline.md` **保持纯净**（它是流程契约）。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_no_site_literals.py`：

```python
"""站点专属事实不得写进通用代码与技能正文（spec §3.3）。

站点差异只允许落在 profile（notes / backends / pdf.* / search.*）与
skill 的 references/ 里。通用代码与技能正文出现具体站点主机即视为回归。
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

#: 站点专属字面量（小写主机片段 + 具体站点 id）
_SITE_LITERALS = (
    "xueshu789",
    "cnki.net",
    "oversea.cnki",
    "kns.cnki",
    "xueshu789.cc",
)

_LITERATURE_DIR = Path(__file__).resolve().parents[2] / "literature"
_LITERATURE_SKILL_MD = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "skill_md"
    / "shipped"
    / "literature-research"
    / "SKILL.md"
)


def _literature_sources():
    for path in sorted(_LITERATURE_DIR.glob("*.py")):
        yield path, path.read_text(encoding="utf-8")
    yield _LITERATURE_SKILL_MD, _LITERATURE_SKILL_MD.read_text(encoding="utf-8")


def test_no_site_specific_literals_in_literature_code_or_skill_body() -> None:
    offenders = []
    for path, text in _literature_sources():
        lowered = text.lower()
        for literal in _SITE_LITERALS:
            if literal in lowered:
                offenders.append(f"{path.name}: {literal}")
    assert not offenders, (
        "站点专属事实不得出现在通用代码/技能正文（应下沉到 profile）："
        + ", ".join(offenders)
    )


def test_pipeline_reference_stays_free_of_site_facts() -> None:
    """references/pipeline.md 是纯流程契约 —— 站点事实不许进。"""
    pipeline = (
        _LITERATURE_SKILL_MD.parent / "references" / "pipeline.md"
    ).read_text(encoding="utf-8").lower()
    for literal in _SITE_LITERALS:
        assert literal not in pipeline, f"pipeline.md 不该出现站点事实: {literal}"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_no_site_literals.py -q
```

Expected: FAIL —— `backend/literature/README.md` 不在扫描范围（只扫 `*.py`），但 **literature SKILL.md** 含 `xueshu789.yaml` → 命中。

- [ ] **Step 3: 改三处文案**

**（a）`backend/literature/README.md:53`** —— 把以 xueshu789 oversea 404 为唯一例证的段落改为通用表述。原文（以 xueshu789 为例的那段）替换为：

```markdown
中间页下载采用「两段式」：先请求下载入口，得到一个含最终下载地址的中间页，
再解析出最终地址并下载。最终地址的主机名可能与入口不一致 —— 需按 profile
声明的 `pdf.interstitial.host_fallbacks` 逐个回退，直到拿到通过 magic 与题名校验的文件。
具体站点的回退主机列表写在该站 profile 里，不要写进本文件。
```

**（b）`backend/literature/README.md:148`** —— 设计规则第一条替换为：

```markdown
- 站点差异只写在 profile（`notes` / `backends` / `pdf.*` / `search.*`）；通用机制写在本文件与 skill `references/`
```

**（c）`backend/skills/skill_md/shipped/literature-research/SKILL.md:250-270`** —— 附录里硬编码的 `xueshu789.yaml` 改为占位。把该处所有 `xueshu789.yaml` 字面量替换为 `<site>.yaml`，把示例命令写成：

```bash
cp docs/templates/literature-sites/<site>.yaml ~/.sage/literature_sites/
```

> 同文件 41-45 的合规红线段**保留不动**（spec §3.3 c 明确要求）。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_no_site_literals.py \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_site_profiles.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/literature/README.md \
  backend/skills/skill_md/shipped/literature-research/SKILL.md \
  backend/tests/unit/test_literature_no_site_literals.py
git commit -m "refactor(literature): 站点事实泛化收敛到 profile 归属"
```

---

### Task 7: 新增 `backend/literature/interstitial.py`（中间页解析 + 主机回退）

**Files:**
- Create: `backend/literature/interstitial.py`
- Modify: `backend/literature/search.py:147-163`（`_candidate_download_urls` 改为委托）
- Test: `backend/tests/unit/test_literature_interstitial.py`

**Interfaces:**
- Consumes: 无（纯函数模块，无 IO）
- Produces:
  - `parse_download_url(html: str) -> List[str]`
  - `rewrite_host_candidates(url: str, fallbacks: Sequence[str]) -> List[str]`
  - `select_first_valid(candidates: Sequence[str], fetch: Callable[[str], Optional[Tuple[str, bytes]]], validate: Optional[Callable[[bytes], bool]] = None) -> Optional[Tuple[str, bytes]]`

**背景（spec §5.3）：** 中间页是含 `var downurl` 的静态 HTML；提取顺序：`var downurl = "..."` / `window.location = "..."` / `<a id="successBtn" href="...">`。主机回退按 `pdf.interstitial.host_fallbacks` 生成候选，**原域最后兜底**。`select_first_valid` 的 `fetch` 是注入函数，测试传 lambda → 「换主机重试」可离线单测。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_interstitial.py`：

```python
"""中间页解析与主机回退（spec §5.3）。"""

import pytest

from backend.literature.interstitial import (
    parse_download_url,
    rewrite_host_candidates,
    select_first_valid,
)

pytestmark = pytest.mark.unit

_HTML_VAR = """
<html><body><script>
var downurl = "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz";
</script></body></html>
"""
_HTML_LOCATION = """
<html><body><script>
window.location = "https://example.org/download?token=1";
</script></body></html>
"""
_HTML_ANCHOR = """
<html><body><a id="successBtn" href="https://example.net/dl?x=2">下载</a></body></html>
"""
_HTML_HREF_FIRST = """
<html><body><a href="https://example.org/a" id="successBtn">下载</a></body></html>
"""


def test_parse_var_downurl() -> None:
    assert parse_download_url(_HTML_VAR) == [
        "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz"
    ]


def test_parse_window_location() -> None:
    assert parse_download_url(_HTML_LOCATION) == [
        "https://example.org/download?token=1"
    ]


def test_parse_anchor_href() -> None:
    assert parse_download_url(_HTML_ANCHOR) == ["https://example.net/dl?x=2"]


def test_parse_anchor_href_before_id() -> None:
    """属性顺序不限。"""
    assert parse_download_url(_HTML_HREF_FIRST) == ["https://example.org/a"]


def test_parse_returns_all_candidates_in_order_without_duplicates() -> None:
    html = _HTML_VAR + _HTML_LOCATION
    urls = parse_download_url(html)
    assert len(urls) == 2
    assert urls[0].startswith("https://oversea.cnki.net")
    assert urls[1].startswith("https://example.org")


def test_parse_deduplicates_repeated_urls() -> None:
    html = _HTML_VAR + _HTML_VAR
    assert len(parse_download_url(html)) == 1


def test_parse_misses_return_empty_list() -> None:
    assert parse_download_url("<html><body>无下载链接</body></html>") == []


def test_rewrite_host_candidates_puts_fallbacks_before_original() -> None:
    url = "https://oversea.cnki.net/docdown/fulltext/download?q=abc"
    candidates = rewrite_host_candidates(url, ["kns.cnki.net"])
    assert candidates[0] == "https://kns.cnki.net/docdown/fulltext/download?q=abc"
    assert candidates[-1] == url


def test_rewrite_host_candidates_keeps_path_and_query() -> None:
    url = "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz"
    candidates = rewrite_host_candidates(url, ["kns.cnki.net"])
    assert candidates[0].endswith("?q=abc&invoice=xyz")
    assert "/docdown/fulltext/download" in candidates[0]


def test_rewrite_host_candidates_with_no_fallbacks_returns_original() -> None:
    url = "https://example.org/a?b=1"
    assert rewrite_host_candidates(url, []) == [url]


def test_rewrite_host_candidates_skips_blank_hosts() -> None:
    """空主机必须跳过 —— 否则会产出 ``https:///path`` 这种坏候选。"""
    url = "https://example.org/a?b=1"
    candidates = rewrite_host_candidates(url, ["", "   ", "alt.example"])
    assert candidates == ["https://alt.example/a?b=1", url]


def test_select_first_valid_skips_failing_candidate() -> None:
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if url.startswith("https://oversea.cnki.net"):
            return url, b"%PDF-1.6 body"
        return None

    candidates = rewrite_host_candidates(
        "https://oversea.cnki.net/docdown/fulltext/download?q=abc", ["kns.cnki.net"]
    )
    result = select_first_valid(candidates, fake_fetch)
    assert result is not None
    url, body = result
    assert url.startswith("https://oversea.cnki.net")
    assert body.startswith(b"%PDF-")
    assert len(calls) == 2


def test_select_first_valid_applies_validator() -> None:
    def fake_fetch(url):
        return url, b"<html>not a pdf</html>"

    result = select_first_valid(["https://example.org/a"], fake_fetch, lambda b: b.startswith(b"%PDF-"))
    assert result is None


def test_select_first_valid_returns_none_when_all_fail() -> None:
    assert select_first_valid(["https://example.org/a"], lambda url: None) is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_interstitial.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.literature.interstitial'`。

- [ ] **Step 3: 最小实现**

创建 `backend/literature/interstitial.py`：

```python
"""中间页解析与主机回退候选生成（spec §5.3）。

纯函数模块，无 IO —— 便于离线单测。生产路径由 ``http_download`` 注入
真实的取数函数。
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

#: 提取顺序：var downurl > window.location > successBtn href。
_DOWNURL_PATTERN = re.compile(r"var\s+downurl\s*=\s*['\"]([^'\"]+)['\"]")
_LOCATION_PATTERN = re.compile(r"window\.location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]")
_ANCHOR_PATTERN = re.compile(
    r"<a\b[^>]*\bid\s*=\s*['\"]successBtn['\"][^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_ANCHOR_HREF_FIRST_PATTERN = re.compile(
    r"<a\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*\bid\s*=\s*['\"]successBtn['\"]",
    re.IGNORECASE,
)


def parse_download_url(html: str) -> List[str]:
    """从中间页 HTML 提取候选下载地址，按出现顺序去重。

    三种形态按上表顺序匹配；命中多个时全部保留（按形态优先级）。
    """
    text = html or ""
    found: List[str] = []
    for pattern in (_DOWNURL_PATTERN, _LOCATION_PATTERN):
        for match in pattern.finditer(text):
            found.append(match.group(1).strip())
    for pattern in (_ANCHOR_PATTERN, _ANCHOR_HREF_FIRST_PATTERN):
        for match in pattern.finditer(text):
            found.append(match.group(1).strip())

    seen = set()
    ordered: List[str] = []
    for url in found:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def rewrite_host_candidates(url: str, fallbacks: Sequence[str]) -> List[str]:
    """按 ``fallbacks`` 依次替换主机生成候选 URL；原域最后兜底。

    路径与查询串保持不变。仅返回 ``http(s)`` URL。
    """
    text = str(url or "").strip()
    if not text:
        return []
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return [text]

    candidates: List[str] = []
    seen = set()
    for raw_host in list(fallbacks or ()):
        host = str(raw_host or "").strip()
        if not host:
            continue
        candidate = urlunsplit(
            (parts.scheme, host, parts.path, parts.query, parts.fragment)
        )
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    if text not in seen:
        candidates.append(text)
    return candidates


def select_first_valid(
    candidates: Sequence[str],
    fetch: Callable[[str], Optional[Tuple[str, bytes]]],
    validate: Optional[Callable[[bytes], bool]] = None,
) -> Optional[Tuple[str, bytes]]:
    """按候选顺序取第一个通过校验的响应。

    Args:
        candidates: 候选 URL 序列（``rewrite_host_candidates`` 的输出）。
        fetch: 注入的取数函数；返回 ``None`` 或 ``(url, body)``。
        validate: 可选的响应体校验（如 magic 前缀检查）；不通过则试下一个。

    Returns:
        命中的 ``(url, body)``；全部失败返回 ``None``。
    """
    for candidate in candidates:
        try:
            fetched = fetch(candidate)
        except Exception:  # noqa: BLE001 — 单个候选失败不中断候选序列
            continue
        if not fetched:
            continue
        url, body = fetched
        if validate is not None and not validate(body):
            continue
        return url, body
    return None
```

- [ ] **Step 4: 让 `search.py` 委托复用**

改 `backend/literature/search.py`：第 147-163 行的 `_candidate_download_urls` 改为委托到新模块（避免两处逻辑漂移）：

```python
def _candidate_download_urls(url: str, hosts: List[str]) -> List[str]:
    """生成候选下载地址（主机回退优先，原域最后）。

    委托 ``interstitial.rewrite_host_candidates``，避免两处逻辑漂移。
    """
    return rewrite_host_candidates(url, hosts)
```

并在文件顶部 import 区加（**必须落在 `from .guidance import ...` 之后、
`from .models import ...` 之前**，否则 ruff I001 报 import 排序错）：

```python
from .guidance import render_search_guidance
from .interstitial import rewrite_host_candidates
from .models import SiteProfile, render_search_url
```

⚠️ **同时删掉 `search.py` 第 11 行的 `from urllib.parse import urlsplit, urlunsplit`**
—— 委托后这两个名字在 `search.py` 里再无引用，留着会被 ruff F811/F401 判为未使用导入
而卡住 CI。删前先确认：

```bash
grep -n 'urlsplit\|urlunsplit' backend/literature/search.py
```

只剩第 11 行（import 行本身）时即可删除。

> 既有 `backend/tests/unit/test_literature_interstitial_download.py::test_candidate_urls_order`
> 断言「回退主机在前、重复主机去重、原域最后」，与新实现语义一致，**不需要改**。

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_interstitial.py \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_interstitial_download.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/literature/interstitial.py backend/literature/search.py \
  backend/tests/unit/test_literature_interstitial.py
git commit -m "feat(literature): 新增中间页解析与主机回退候选模块"
```

---

### Task 8: 新增 `backend/services/http_rate_limit.py`（per-host 限速器）

**Files:**
- Create: `backend/services/http_rate_limit.py`
- Test: `backend/tests/unit/test_http_rate_limit.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `DEFAULT_MIN_INTERVAL_S = 1.0`、`LITERATURE_FLOOR_S = 3.0`
  - `HttpRateLimiter(min_interval_s: float = DEFAULT_MIN_INTERVAL_S, floor_s: float = 0.0)`，方法 `reserve(host: str, now: Optional[float] = None) -> float`（返回需等待秒数，0 表示立即放行）、`effective_interval_s`（property）、`reset() -> None`
  - `get_default_limiter() -> HttpRateLimiter`、`reset_default_limiter() -> None`

**背景（spec §5.5）：** profile 的 `rate_limit` 此前**只是给模型看的文本**，全仓无执行点。本任务把它变成真实闸门：通用层默认 1s 防滥用；文献层再叠加 profile 的 `min_interval_s` 并强制**下限 3s —— profile 即使写 0 也不放行**。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_http_rate_limit.py`：

```python
"""per-host 最小间隔限速器（spec §5.5）。"""

import pytest

from backend.services.http_rate_limit import (
    DEFAULT_MIN_INTERVAL_S,
    LITERATURE_FLOOR_S,
    HttpRateLimiter,
    get_default_limiter,
    reset_default_limiter,
)

pytestmark = pytest.mark.unit


def test_first_request_is_immediate() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    assert limiter.reserve("example.org", now=100.0) == 0.0


def test_second_request_within_interval_waits() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("example.org", now=100.0)
    wait = limiter.reserve("example.org", now=101.0)
    assert wait == pytest.approx(1.0)


def test_request_after_interval_is_immediate() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("example.org", now=100.0)
    assert limiter.reserve("example.org", now=102.0) == 0.0


def test_different_hosts_are_independent() -> None:
    limiter = HttpRateLimiter(min_interval_s=2.0)
    limiter.reserve("a.example", now=100.0)
    assert limiter.reserve("b.example", now=100.5) == 0.0


def test_floor_is_enforced_even_when_profile_writes_zero() -> None:
    """profile 即使写 min_interval_s=0 也不放行 —— 文献层下限 3 秒。"""
    limiter = HttpRateLimiter(min_interval_s=0.0, floor_s=LITERATURE_FLOOR_S)
    assert limiter.effective_interval_s == pytest.approx(LITERATURE_FLOOR_S)
    limiter.reserve("example.org", now=100.0)
    assert limiter.reserve("example.org", now=100.1) > 0.0


def test_profile_interval_above_floor_wins() -> None:
    limiter = HttpRateLimiter(min_interval_s=10.0, floor_s=LITERATURE_FLOOR_S)
    assert limiter.effective_interval_s == pytest.approx(10.0)


def test_generic_default_interval() -> None:
    assert DEFAULT_MIN_INTERVAL_S == 1.0
    assert LITERATURE_FLOOR_S == 3.0


def test_reset_clears_state() -> None:
    limiter = HttpRateLimiter(min_interval_s=5.0)
    limiter.reserve("example.org", now=100.0)
    limiter.reset()
    assert limiter.reserve("example.org", now=100.1) == 0.0


def test_default_limiter_is_shared_and_resettable() -> None:
    reset_default_limiter()
    first = get_default_limiter()
    assert get_default_limiter() is first
    reset_default_limiter()
    assert get_default_limiter() is not first
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_http_rate_limit.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.services.http_rate_limit'`。

- [ ] **Step 3: 最小实现**

创建 `backend/services/http_rate_limit.py`：

```python
"""HTTP per-host 最小间隔限速器（spec §5.5）。

存在的理由：profile 的 ``rate_limit.min_interval_s`` 此前**只是渲染给模型看的
文本**，全仓没有执行点 —— 限速等于没有。本模块把它变成真实闸门。

两层下限：
- 通用层 ``DEFAULT_MIN_INTERVAL_S``（1 秒）—— 防止通用 HTTP 工具被用来打站点；
- 文献层 ``LITERATURE_FLOOR_S``（3 秒）—— profile 即使写 ``0`` 也不放行。

存储：进程内 per-host 时间戳表（线程安全）。运行目录内的累计次数由
``run_store.record_download`` 负责，与本模块互补。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

#: 通用层默认最小间隔（秒）。
DEFAULT_MIN_INTERVAL_S = 1.0
#: 文献层的强制下限（秒）—— profile 写 0 也不放行。
LITERATURE_FLOOR_S = 3.0


class HttpRateLimiter:
    """per-host 最小间隔限速器。"""

    def __init__(
        self,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        floor_s: float = 0.0,
    ) -> None:
        """
        Args:
            min_interval_s: 上层声明的最小间隔（来自 profile ``rate_limit``）。
            floor_s: 强制下限；实际间隔 = ``max(min_interval_s, floor_s)``。
        """
        self._min_interval_s = max(0.0, float(min_interval_s))
        self._floor_s = max(0.0, float(floor_s))
        self._last_seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def effective_interval_s(self) -> float:
        """实际生效的最小间隔（秒）。"""
        return max(self._min_interval_s, self._floor_s)

    def reserve(self, host: str, now: Optional[float] = None) -> float:
        """为一次请求占位；返回需要等待的秒数（0 = 立即放行）。

        Args:
            host: 目标主机名。
            now: 当前时刻（``time.monotonic()`` 语义），测试可注入。
        """
        key = str(host or "").strip().lower()
        if not key:
            return 0.0
        current = time.monotonic() if now is None else float(now)
        interval = self.effective_interval_s
        with self._lock:
            previous = self._last_seen.get(key)
            self._last_seen[key] = current
        if previous is None or interval <= 0.0:
            return 0.0
        elapsed = current - previous
        if elapsed >= interval:
            return 0.0
        return interval - elapsed

    def reset(self) -> None:
        """清空所有 host 的时间戳（测试与运行目录切换时用）。"""
        with self._lock:
            self._last_seen.clear()


_DEFAULT_LIMITER: Optional[HttpRateLimiter] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_limiter() -> HttpRateLimiter:
    """返回进程级默认限速器（通用下限，无文献层 floor）。"""
    global _DEFAULT_LIMITER
    if _DEFAULT_LIMITER is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_LIMITER is None:
                _DEFAULT_LIMITER = HttpRateLimiter()
    return _DEFAULT_LIMITER


def reset_default_limiter() -> None:
    """重置进程级默认限速器（测试用）。"""
    global _DEFAULT_LIMITER
    with _DEFAULT_LOCK:
        _DEFAULT_LIMITER = None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_http_rate_limit.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/services/http_rate_limit.py backend/tests/unit/test_http_rate_limit.py
git commit -m "feat(services): 新增 per-host HTTP 最小间隔限速器"
```

---

### Task 9: HTTP 出网前的站点策略闸门（并接线到 web_fetch / http_download）

**Files:**
- Create: `backend/tools/http_site_gate.py`
- Modify: `backend/tools/web_tool.py`（`WebFetchTool.execute` 早期）
- Modify: `backend/tools/download_tool.py`（`HttpDownloadTool.execute` 早期）
- Test: `backend/tests/unit/test_http_site_gate.py`

**Interfaces:**
- Consumes:
  - `backend.services.browser_safety.check_site(session_id, url) -> str`（返回 `allow` / `confirm` / `block`）
  - `backend.services.browser_safety.domain_of(url) -> str`
  - `backend.services.browser_safety.SITE_ACCESS_OPTIONS`
  - `backend.services.browser_safety.get_confirmation_registry() -> ConfirmationRegistry`；`ConfirmationRegistry.create(session_id, kind, *, code, domain, description, options, screenshot_path, fingerprint)`
- Produces:
  - `http_site_gate.SiteGateVerdict`（frozen dataclass：`allowed: bool`、`reason: str`、`confirmation_id: str`、`domain: str`）
  - `http_site_gate.gate_http_url(url: str, session_id: str = "") -> SiteGateVerdict`

**背景（spec §5.5 / C1 / C2）：** HTTP 工具完全绕过站点策略闸，也无任何自带限速。本任务让 HTTP 路径与浏览器路径**受同等约束**，用户在同一个面板裁决。

**附带约束（spec §5.7 / §13）：** 中间页是静态 HTML，用 `web_fetch` 现有的 `mode="raw"` 取回即可 —— **不新增** `html` 模式（扩大 `VALID_MODES` 语义面而收益有限）。本任务**不改** `web_tool.py` 的模式枚举，只在出网前插入闸门调用。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_http_site_gate.py`：

```python
"""HTTP 出网前的站点策略闸门（spec §5.5）。"""

import pytest

from backend.services import browser_safety
from backend.tools.http_site_gate import SiteGateVerdict, gate_http_url

pytestmark = pytest.mark.unit


@pytest.fixture()
def policy_store(monkeypatch):
    """用进程内 dict 替换持久仓储 —— 单测不得写真实 SettingsRepository。

    ``grant_site(..., "always"/"block")`` 会把策略写进用户设置库；这里换成
    内存 store，测试结束后不留下任何真实站点策略。
    """
    store = {}

    def _load():
        return {key: dict(value) for key, value in store.items()}

    def _save(policies):
        store.clear()
        store.update(policies)

    monkeypatch.setattr(browser_safety, "_load_policies", _load)
    monkeypatch.setattr(browser_safety, "_save_policies", _save)
    browser_safety.reset_site_policies_for_tests()
    yield store
    browser_safety.reset_site_policies_for_tests()
    browser_safety.reset_confirmations_for_tests()


def test_allow_verdict_passes(policy_store):
    browser_safety.grant_site("sess-1", "example.org", "session")
    verdict = gate_http_url("https://example.org/a", session_id="sess-1")
    assert isinstance(verdict, SiteGateVerdict)
    assert verdict.allowed is True
    assert verdict.reason == "allow"


def test_block_verdict_is_denied(policy_store):
    browser_safety.grant_site("sess-2", "blocked.example", "block")
    verdict = gate_http_url("https://blocked.example/a", session_id="sess-2")
    assert verdict.allowed is False
    assert verdict.reason == "block"


def test_confirm_verdict_registers_a_confirmation(policy_store):
    verdict = gate_http_url("https://unknown-site.example/a", session_id="sess-3")
    assert verdict.allowed is False
    assert verdict.reason == "confirm"
    assert verdict.confirmation_id
    assert verdict.domain == "unknown-site.example"

    pending = browser_safety.get_confirmation_registry().get(verdict.confirmation_id)
    assert pending is not None
    assert pending.domain == "unknown-site.example"


def test_url_without_host_is_allowed(policy_store):
    verdict = gate_http_url("about:blank", session_id="sess-4")
    assert verdict.allowed is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_http_site_gate.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.tools.http_site_gate'`。

- [ ] **Step 3: 最小实现**

创建 `backend/tools/http_site_gate.py`：

```python
"""HTTP 出网前的站点策略闸门（spec §5.5）。

现状缺陷（C1）：``web_fetch`` / ``http_download`` 完全绕过
``browser_safety`` 的站点策略 —— 浏览器路径要用户确认，HTTP 路径却裸奔。
本模块把两条路径的约束对齐：同样的 ``check_site`` 判定、同样的
``ConfirmationRegistry`` 确认单、同样的 ``needs_confirmation: <id>`` 错误形态，
用户在**同一个**右栏面板裁决。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.services import browser_safety

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteGateVerdict:
    """站点策略判定结果。"""

    allowed: bool
    reason: str
    confirmation_id: str = ""
    domain: str = ""


def gate_http_url(url: str, session_id: str = "") -> SiteGateVerdict:
    """判定一次 HTTP 出网是否被允许。

    Args:
        url: 目标 URL。
        session_id: 会话 id（决定会话级授权与确认单归属）。

    Returns:
        ``SiteGateVerdict``；``allowed=True`` 表示放行。
    """
    domain = browser_safety.domain_of(url)
    if not domain:
        return SiteGateVerdict(allowed=True, reason="allow", domain="")

    verdict = browser_safety.check_site(session_id, url)
    if verdict == "allow":
        return SiteGateVerdict(allowed=True, reason="allow", domain=domain)

    if verdict == "block":
        return SiteGateVerdict(
            allowed=False,
            reason="block",
            domain=domain,
        )

    registry = browser_safety.get_confirmation_registry()
    pending = registry.create(
        session_id,
        "site_access",
        code="site_access",
        domain=domain,
        description=f"访问站点 {domain}：{url}",
        options=list(browser_safety.SITE_ACCESS_OPTIONS),
        fingerprint=f"http:{domain}",
    )
    logger.info("HTTP 出网待确认 domain=%s confirmation=%s", domain, pending.id)
    return SiteGateVerdict(
        allowed=False,
        reason="confirm",
        confirmation_id=pending.id,
        domain=domain,
    )


def gate_error_message(verdict: SiteGateVerdict) -> str:
    """把判定渲染成与浏览器路径同构的错误文案。"""
    if verdict.reason == "block":
        return f"site_blocked: 用户已禁止该站点 {verdict.domain}"
    return (
        f"needs_confirmation: {verdict.confirmation_id} "
        f"访问站点 {verdict.domain}（请在右栏浏览器面板确认）"
    )
```

- [ ] **Step 4: 接线到 `web_tool.py`**

改 `backend/tools/web_tool.py` 的 `WebFetchTool.execute`：在「无效的 URL」检查之后、凭据推断之前插入闸门判定：

```python
        from .http_site_gate import gate_error_message, gate_http_url

        gate = gate_http_url(url, session_id="")
        if not gate.allowed:
            return ToolResult(success=False, error=gate_error_message(gate))
```

> `WebFetchTool` **没有** session 概念（`web_tool.py` 里无 `session_id`），
> 因此固定传空串：`check_site("", url)` 仍会查**持久策略**（用户显式允许/禁止的站点），
> 未持久授权的域名一律落到 `confirm` —— 与浏览器路径的默认行为一致。
> `HttpDownloadTool` 同理。

改 `backend/tools/download_tool.py` 的 `HttpDownloadTool.execute`：在
`url_error = self._validate_target_url(url)` 的早退之后插入**同样**的五行
（模块导入路径为 `.http_site_gate`）。

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_http_site_gate.py \
  backend/tests/unit/test_web_tool.py \
  backend/tests/unit/test_download_tool.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/tools/http_site_gate.py backend/tools/web_tool.py \
  backend/tools/download_tool.py backend/tests/unit/test_http_site_gate.py
git commit -m "feat(tools): HTTP 出网接入站点策略闸门（与浏览器路径同构）"
```

---

### Task 10: HTTP 下载快路径 `backend/literature/http_download.py` + 一次性降级

**Files:**
- Create: `backend/literature/pdf_check.py`（共用校验）
- Create: `backend/literature/http_download.py`
- Modify: `backend/literature/search.py:127-144`（`_normalize` / `validate_pdf` 搬去 `pdf_check.py`）、`:120-124`（`DownloadResult` 加字段）、`:262`（`download_pdf` 加 `http_fetch=` kwarg）
- Test: `backend/tests/unit/test_literature_http_download.py`

**Interfaces:**
- Consumes:
  - `backend.literature.interstitial.parse_download_url` / `rewrite_host_candidates` / `select_first_valid`
  - `backend.literature.models.SiteProfile`（`pdf.interstitial.host_fallbacks` / `pdf.forbid` / `pdf.magic`）
  - `backend.literature.pdf_check.validate_pdf(path, expected_title, magic)`（本任务新建，从 `search.py` 搬来）
- Produces:
  - `pdf_check.normalize_text(text: str) -> str`
  - `pdf_check.validate_pdf(path: Path, expected_title: str, magic: str = "%PDF-") -> List[str]`
  - `http_download.FetchResult(status: int, body: bytes)`
  - `http_download.Fetcher = Callable[[str, str], FetchResult]`（签名：`(url, referer) -> FetchResult`）
  - `http_download.HttpDownloadOutcome(path: Optional[str], ok: bool, transport: str, fallback_reason: str, errors: List[str])`
  - `http_download.download_pdf_http(profile, entry_url, expected_title, dest_dir, fetch, *, referer="") -> HttpDownloadOutcome`
  - `search.DownloadResult` 新增字段 `transport: str = "browser"`、`fallback_reason: str = ""`、`access_status: str = "unknown"`（四态词汇由 `backend.literature.verify.ACCESS_STATUSES` 定义，Task 17 落地；此处先用字面量 `"subscription"`，Task 17 的测试校验两处一致）
  - `search.download_pdf(..., http_fetch=None)` —— `http_fetch` 为 `Optional[Fetcher]`

**背景（spec §5.1/§5.2/§5.6）：** 分段链路「浏览器读 href → HTTP 取中间页 → 解析 downurl → 换主机 → GET PDF → 校验 → 原子落盘」。**不可 HTTP 化的段**是检索页。HTTP 路径失败时**自动回退浏览器路径**，但**只降级一次**，并在 `query_log` 记降级原因。

**关键设计：`http_download` 不自己发 HTTP**，而是接收**注入的 fetcher**。生产环境由技能的 `execute_code` 代码用 `sage.call("http_download", ...)` 适配 —— 闸门与限速因此自动生效，且 `backend/literature/` 保持不 import `backend.tools/`。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_http_download.py`：

```python
"""HTTP 下载快路径（spec §5.1 / §5.6）。"""

from pathlib import Path

import pytest

from backend.literature.http_download import (
    FetchResult,
    download_pdf_http,
)
from backend.literature.models import SiteProfile

pytestmark = pytest.mark.unit


def _profile() -> SiteProfile:
    return SiteProfile(
        id="demo",
        display_name="演示站",
        home_url="https://demo.example",
        domains=("demo.example",),
    )


_INTERSTITIAL_HTML = """
<html><script>
var downurl = "https://oversea.example.net/docdown/fulltext/download?q=abc&invoice=xyz";
</script></html>
"""


def _make_fetcher(body=b"%PDF-1.6 hello", interstitial=_INTERSTITIAL_HTML, status=200):
    calls = []

    def fetch(url, referer=""):
        calls.append((url, referer))
        if "docdown" in url and "interstitial" not in url and url.endswith("invoice=xyz"):
            # 这是最终 PDF 地址
            return FetchResult(status=status, body=body)
        return FetchResult(status=200, body=interstitial.encode("utf-8"))

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_download_pdf_http_writes_the_pdf(tmp_path: Path) -> None:
    fetch = _make_fetcher()
    outcome = download_pdf_http(
        _profile(),
        "https://demo.example/doDownload?x=1",
        "演示题名",
        tmp_path,
        fetch,
    )
    assert outcome.ok is True, outcome.errors
    assert outcome.transport == "http"
    assert outcome.path
    assert Path(outcome.path).read_bytes().startswith(b"%PDF-")


def test_download_pdf_http_without_entry_url_reports_reason(tmp_path: Path) -> None:
    outcome = download_pdf_http(_profile(), "", "题名", tmp_path, _make_fetcher())
    assert outcome.ok is False
    assert outcome.fallback_reason == "no_entry_url"


def test_download_pdf_http_reports_entry_fetch_failure(tmp_path: Path) -> None:
    def failing_fetch(url, referer=""):
        return FetchResult(status=500, body=b"boom")

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, failing_fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "entry_status_500"


def test_download_pdf_http_reports_parse_miss(tmp_path: Path) -> None:
    def plain_fetch(url, referer=""):
        return FetchResult(status=200, body=b"<html>no link</html>")

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, plain_fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "interstitial_parse_miss"


def test_download_pdf_http_reports_candidate_exhausted(tmp_path: Path) -> None:
    """候选地址全部取不到（网络层失败）→ candidate_exhausted。

    注意与下面的 ``magic_mismatch`` 用例区分：那个是「取到了但不是 PDF」。
    """

    def dead_candidates(url, referer=""):
        if "docdown" in url:
            return FetchResult(status=404, body=b"")
        return FetchResult(status=200, body=_INTERSTITIAL_HTML.encode("utf-8"))

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, dead_candidates
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "candidate_exhausted"


def test_download_pdf_http_rejects_non_pdf_body(tmp_path: Path) -> None:
    """候选地址取到了响应但不是 PDF（登录墙 / 错误页）→ magic_mismatch。"""
    fetch = _make_fetcher(body=b"<html>login wall</html>")
    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "magic_mismatch"
    assert not list(tmp_path.glob("*.pdf"))


def test_download_pdf_http_leaves_no_partial_file(tmp_path: Path) -> None:
    fetch = _make_fetcher(body=b"<html>not pdf</html>")
    download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, fetch
    )
    assert not list(tmp_path.glob("*.part"))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_http_download.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.literature.http_download'`。

- [ ] **Step 3a: 抽出 `backend/literature/pdf_check.py`（共用校验，消除循环依赖）**

浏览器路径（`search.py`）与 HTTP 路径（`http_download.py`）都要做「magic + 题名」校验。
若 `http_download.py` 在模块顶层 `from .search import validate_pdf`，而 `search.py`
又要 `from .http_download import download_pdf_http`（Step 4），两者会形成**循环导入**
（运行时 `ImportError`）。因此先把校验逻辑抽到一个中立模块。

创建 `backend/literature/pdf_check.py`：

```python
"""下载文件的 magic + 题名校验（浏览器路径与 HTTP 路径共用）。

独立成模块是为了让 ``search.py`` 与 ``http_download.py`` 都能依赖它而不形成
循环导入：``search`` → ``http_download`` → ``pdf_check``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List


def normalize_text(text: str) -> str:
    """去掉空白与标点，只留字母数字与汉字，用于题名比对。"""
    return re.sub(r"[\s\W_]+", "", text or "")


def validate_pdf(path: Path, expected_title: str, magic: str = "%PDF-") -> List[str]:
    """校验下载文件；返回错误列表，空列表表示通过。"""
    errors: List[str] = []
    if not path.is_file():
        return [f"下载文件不存在: {path}"]
    with path.open("rb") as handle:
        head = handle.read(len(magic))
    if head != magic.encode("ascii"):
        errors.append(f"文件头不是 {magic}")
    if expected_title:
        expected = normalize_text(expected_title)
        actual = normalize_text(path.stem)
        if expected and expected not in actual and actual not in expected:
            errors.append(f"文件名与题名不匹配: {path.name!r} vs {expected_title!r}")
    return errors
```

- [ ] **Step 3b: 新建 `backend/literature/http_download.py`**

创建 `backend/literature/http_download.py`：

```python
"""文献 PDF 的 HTTP 下载快路径（spec §5.1 / §5.6）。

链路：``doDownload`` 入口 → 中间页 HTML → 解析 downurl → 按
``pdf.interstitial.host_fallbacks`` 换主机 → GET PDF → magic + 题名校验
→ 原子落盘。

**本模块不自己发 HTTP**：取数由外部注入的 ``Fetcher`` 完成。生产环境由
技能的 ``execute_code`` 代码用 ``sage.call("http_download", ...)`` 适配 ——
站点策略闸（Task 9）与限速（Task 8）因此自动生效，且本包保持不依赖
``backend.tools``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .interstitial import (
    parse_download_url,
    rewrite_host_candidates,
    select_first_valid,
)
from .models import SiteProfile
from .pdf_check import validate_pdf

logger = logging.getLogger(__name__)

#: 缺省的文件头魔数（profile 未声明 ``pdf.magic`` 时用这个）。
_DEFAULT_MAGIC = "%PDF-"


@dataclass(frozen=True)
class FetchResult:
    """一次 HTTP 取数的结果。"""

    status: int
    body: bytes


#: 取数函数签名：``(url, referer) -> FetchResult``。
Fetcher = Callable[[str, str], FetchResult]


@dataclass
class HttpDownloadOutcome:
    """HTTP 下载结果。"""

    path: Optional[str] = None
    ok: bool = False
    transport: str = "http"
    fallback_reason: str = ""
    errors: List[str] = field(default_factory=list)


def _host_fallbacks(profile: SiteProfile) -> List[str]:
    """取 profile 声明的主机回退列表。"""
    pdf = profile.pdf
    if pdf is None or pdf.interstitial is None:
        return []
    return list(pdf.interstitial.host_fallbacks or ())


def _magic_of(profile: SiteProfile) -> str:
    """取 profile 声明的文件头魔数。"""
    pdf = profile.pdf
    if pdf is None or not pdf.magic:
        return _DEFAULT_MAGIC
    return pdf.magic


def _fetch_entry_html(
    entry_url: str,
    referer: str,
    fetch: Fetcher,
) -> Tuple[str, str, str]:
    """取入口页 HTML；返回 ``(html, reason, message)``。

    失败时 ``reason`` 是可观测原因码（``no_entry_url`` /
    ``entry_fetch_failed`` / ``entry_status_<code>``），``message`` 是人读文案。
    """
    if not entry_url:
        return "", "no_entry_url", "缺少 doDownload 入口 URL"
    try:
        entry = fetch(entry_url, referer)
    except Exception as exc:  # noqa: BLE001 — 取数异常按失败上报，不伪造成功
        return "", "entry_fetch_failed", f"请求入口失败: {exc}"
    if entry.status != 200:
        return "", f"entry_status_{entry.status}", f"中间页 HTTP {entry.status}"
    return entry.body.decode("utf-8", errors="replace"), "", ""


def _candidate_urls(urls: List[str], profile: SiteProfile) -> List[str]:
    """把中间页解析出的 URL 展开成含主机回退的候选序列（保序去重）。"""
    fallbacks = _host_fallbacks(profile)
    candidates: List[str] = []
    for url in urls:
        for candidate in rewrite_host_candidates(url, fallbacks):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _safe_stem(title: str) -> str:
    """把题名转成安全的文件名主干（去非法字符、截断到 120 字符）。

    文件名用题名而不是固定 ``download`` —— 题名校验要比对文件名主干，
    且用户拿到磁盘上也有一个能认出来的名字。
    """
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(title or "").strip())
    text = text.strip(". ")
    return text[:120] or "download"


def _write_atomic(
    dest_dir: Path,
    stem: str,
    body: bytes,
) -> Tuple[Optional[Path], str]:
    """原子落盘；返回 ``(路径, 错误信息)``，成功时错误信息为空串。"""
    dest = Path(dest_dir)
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"创建目录失败: {exc}"
    part = dest / f"{stem}.pdf.part"
    final = dest / f"{stem}.pdf"
    try:
        part.write_bytes(body)
        part.replace(final)
    except OSError as exc:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
        return None, f"落盘失败: {exc}"
    return final, ""


def download_pdf_http(
    profile: SiteProfile,
    entry_url: str,
    expected_title: str,
    dest_dir: Path,
    fetch: Fetcher,
    *,
    referer: str = "",
) -> HttpDownloadOutcome:
    """走 HTTP 快路径下载一篇 PDF。

    Args:
        profile: 站点 profile（提供主机回退、magic 等）。
        entry_url: ``doDownload`` 入口 URL（由浏览器读元素 href 得到）。
        expected_title: 期望题名（用于落盘后校验）。
        dest_dir: 落盘目录。
        fetch: 注入的取数函数。
        referer: 检索页 Referer。

    Returns:
        ``HttpDownloadOutcome``；失败时 ``fallback_reason`` 给出可观测的原因码。
    """
    outcome = HttpDownloadOutcome()

    html, reason, message = _fetch_entry_html(entry_url, referer, fetch)
    if reason:
        outcome.fallback_reason = reason
        outcome.errors.append(message)
        return outcome

    urls = parse_download_url(html)
    if not urls:
        outcome.fallback_reason = "interstitial_parse_miss"
        outcome.errors.append("中间页未解析出下载地址")
        return outcome

    magic = _magic_of(profile)
    saw_non_pdf = False

    def _fetch_candidate(url: str) -> Optional[Tuple[str, bytes]]:
        nonlocal saw_non_pdf
        try:
            result = fetch(url, referer)
        except Exception:  # noqa: BLE001 — 单个候选失败继续试下一个
            return None
        if result.status != 200:
            return None
        if not result.body.startswith(magic.encode("utf-8")):
            # 取到了东西但不是 PDF（多半是登录墙 / 错误页）—— 与「取不到」区分开，
            # 否则两种失败会共用同一个原因码，事后无法定位。
            saw_non_pdf = True
            return None
        return url, result.body

    candidates = _candidate_urls(urls, profile)
    hit = select_first_valid(candidates, _fetch_candidate)
    if hit is None:
        outcome.fallback_reason = "magic_mismatch" if saw_non_pdf else "candidate_exhausted"
        outcome.errors.append(
            "候选地址返回的不是 PDF" if saw_non_pdf else "所有候选下载地址均未取得 PDF"
        )
        return outcome

    final, write_error = _write_atomic(dest_dir, _safe_stem(expected_title), hit[1])
    if final is None:
        outcome.fallback_reason = "write_failed"
        outcome.errors.append(write_error)
        return outcome

    errors = validate_pdf(final, expected_title, magic)
    if errors:
        final.unlink(missing_ok=True)
        body = hit[1]
        outcome.fallback_reason = (
            "magic_mismatch" if not body.startswith(magic.encode("utf-8")) else "title_mismatch"
        )
        outcome.errors.extend(errors)
        return outcome

    outcome.path = str(final)
    outcome.ok = True
    return outcome
```

> `download_pdf_http` 恰好 6 个 return —— ruff PLR0911 默认上限就是 6，
> 再多一个就红。前置校验（取入口页）与落盘都抽成了独立函数，正是为了留出余量。
>
> 原因码语义（**测试与实现必须一致**）：
>
> | 原因码 | 含义 |
> |---|---|
> | `no_entry_url` | 没拿到 ``doDownload`` 入口 URL |
> | `entry_fetch_failed` | 入口取数抛异常 |
> | `entry_status_<code>` | 入口 HTTP 非 200 |
> | `interstitial_parse_miss` | 中间页里解析不出下载地址 |
> | `candidate_exhausted` | **所有候选都没取到**（网络错 / 非 200） |
> | `magic_mismatch` | 取到了响应，但**不是 PDF**（登录墙 / 错误页） |
> | `title_mismatch` | 是 PDF，但文件名与题名对不上 |
> | `write_failed` | 落盘失败 |

- [ ] **Step 4: `search.py` 接一次性降级**

改 `backend/literature/search.py`：

（a）删掉 `search.py` 里原本的 `_normalize`（第 127-128 行）与 `validate_pdf`
（第 131-144 行）定义，改为从 `pdf_check` 导入（`validate_pdf` 在
`backend.literature.search` 这个路径上继续可见，外部调用方不受影响）：

```python
from .pdf_check import validate_pdf
```

同时删掉 `search.py` 里已无引用的 `import re` —— `_normalize` 搬走后
`re` 只被那一处用（**先确认**：

```bash
grep -n '\bre\.' backend/literature/search.py
```

没有命中才删；仍有命中就保留 `import re`）。

（b）`DownloadResult` 加两个字段（第 120-124 行区域）：

```python
@dataclass
class DownloadResult:
    path: Optional[str]
    ok: bool
    errors: List[str] = field(default_factory=list)
    transport: str = "browser"
    fallback_reason: str = ""
    access_status: str = "unknown"
```

（c）`download_pdf` 加 `http_fetch` kwarg（第 262 行签名）：

```python
def download_pdf(
    profile: SiteProfile,
    driver: BrowserDriver,
    expected_title: str,
    dest_dir: Path,
    timeout_s: int = 60,
    *,
    entry_url: str = "",
    entry_selector: str = "",
    http_fetch: Optional[object] = None,
) -> DownloadResult:
```

（d）在函数体开头插入 HTTP 优先 + 一次性降级逻辑：

```python
    if http_fetch is not None:
        http_result = download_pdf_http(
            profile,
            entry_url,
            expected_title,
            dest_dir,
            http_fetch,  # type: ignore[arg-type]
        )
        if http_result.ok:
            return DownloadResult(
                path=http_result.path,
                ok=True,
                errors=list(http_result.errors),
                transport="http",
                access_status="subscription",
            )
        # 只降级一次：记原因后走浏览器路径，不来回切
        browser_result = _download_via_browser_path(
            profile, driver, expected_title, dest_dir, timeout_s,
            entry_url=entry_url, entry_selector=entry_selector,
        )
        browser_result.transport = "browser"
        browser_result.fallback_reason = http_result.fallback_reason
        if browser_result.ok:
            browser_result.access_status = "subscription"
        return browser_result

    result = _download_via_browser_path(
        profile, driver, expected_title, dest_dir, timeout_s,
        entry_url=entry_url, entry_selector=entry_selector,
    )
    if result.ok:
        result.access_status = "subscription"
    return result
```

（e）把原 `download_pdf` 的浏览器主体抽成 `_download_via_browser_path(...)`（保持原逻辑不变，仅改名与加两个带默认值的关键字参数），并在文件顶部 import 区改为（**import 顺序必须是这样，否则 ruff I001 报排序错**）：

```python
from .guidance import render_search_guidance
from .http_download import download_pdf_http
from .interstitial import rewrite_host_candidates
from .models import SiteProfile, render_search_url
from .pdf_check import validate_pdf
```

> 依赖方向是单向的：``search`` → ``http_download`` → ``interstitial`` / ``pdf_check``。
> ``http_download.py`` **不再 import ``search``** —— 否则形成循环导入，运行时直接
> ``ImportError``，lint 查不出来。

> 抽函数时保持原函数体逐行不变，只改函数名与签名。

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_http_download.py \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_interstitial_download.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/literature/pdf_check.py backend/literature/http_download.py \
  backend/literature/search.py backend/tests/unit/test_literature_http_download.py
git commit -m "feat(literature): 新增 PDF HTTP 下载快路径（注入式 fetcher + 一次性降级）"
```

---

### Task 11: `query_log` 扩展 + `downloads.jsonl` 计数

**Files:**
- Modify: `backend/literature/run_store.py:128`（`record_query`）、新增 `record_download` / `count_downloads`
- Test: `backend/tests/unit/test_literature_run_store.py`（若已存在则追加；否则新建）

**Interfaces:**
- Consumes: `LiteratureRun`、`atomic_write_text` / `append_jsonl` / `read_jsonl`
- Produces:
  - `record_query(run, query, site_id, result_count, note=None, *, transport="browser", fallback_reason="", backend_id="") -> None`
  - `record_download(run, domain, url, ok, transport, reason="") -> None`
  - `count_downloads(run) -> int`

**背景（spec §7.4 / §5.5）：** 「为什么这次慢了 / 为什么没走快路径」事后可查。批量上限判定需要一个运行目录内的下载计数。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_run_store.py`：

```python
"""运行目录日志扩展（spec §7.4 / §5.5）。"""

from pathlib import Path

import pytest

from backend.literature.run_store import (
    count_downloads,
    create_run,
    read_jsonl,
    record_download,
    record_query,
)

pytestmark = pytest.mark.unit


def test_record_query_includes_transport_fields(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_query(
        run,
        "关键词",
        "demo-site",
        3,
        transport="http",
        fallback_reason="host_404",
        backend_id="db3",
    )
    rows = read_jsonl(run.run_dir / "query_log.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row["transport"] == "http"
    assert row["fallback_reason"] == "host_404"
    assert row["backend_id"] == "db3"
    assert row["query"] == "关键词"
    assert row["at"]


def test_record_query_defaults_to_browser_transport(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_query(run, "关键词", "demo-site", 1)
    rows = read_jsonl(run.run_dir / "query_log.jsonl")
    assert rows[0]["transport"] == "browser"
    assert rows[0]["fallback_reason"] == ""


def test_record_download_appends_to_downloads_log(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_download(run, "demo.example", "https://demo.example/a.pdf", True, "http")
    record_download(run, "demo.example", "https://demo.example/b.pdf", False, "browser", "host_404")
    rows = read_jsonl(run.run_dir / "downloads.jsonl")
    assert len(rows) == 2
    assert rows[0]["domain"] == "demo.example"
    assert rows[0]["ok"] is True
    assert rows[0]["transport"] == "http"
    assert rows[1]["ok"] is False
    assert rows[1]["reason"] == "host_404"
    assert rows[1]["at"]


def test_count_downloads_counts_only_successful(tmp_path: Path) -> None:
    run = create_run(tmp_path, "主题", "demo-site")
    record_download(run, "demo.example", "https://demo.example/a.pdf", True, "http")
    record_download(run, "demo.example", "https://demo.example/b.pdf", False, "http")
    assert count_downloads(run) == 1
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_run_store.py -q
```

Expected: FAIL —— `TypeError: record_query() got an unexpected keyword argument 'transport'`。

- [ ] **Step 3: 最小实现**

改 `backend/literature/run_store.py`，把 `record_query` 替换为：

```python
def record_query(
    run: LiteratureRun,
    query: str,
    site_id: str,
    result_count: int,
    note: Optional[str] = None,
    *,
    transport: str = "browser",
    fallback_reason: str = "",
    backend_id: str = "",
) -> None:
    """记录一次检索（spec §7.4 扩展了 transport / fallback_reason / backend_id）。"""
    append_jsonl(
        run.run_dir / "query_log.jsonl",
        [
            {
                "query": query,
                "site_id": site_id,
                "result_count": int(result_count),
                "note": note,
                "transport": transport,
                "fallback_reason": fallback_reason,
                "backend_id": backend_id,
                "at": _now_iso(),
            }
        ],
    )
```

并在 `record_query` 之后插入：

```python
def record_download(
    run: LiteratureRun,
    domain: str,
    url: str,
    ok: bool,
    transport: str,
    reason: str = "",
) -> None:
    """记录一次下载尝试（用于批量上限判定与事后排查）。"""
    append_jsonl(
        run.run_dir / "downloads.jsonl",
        [
            {
                "domain": domain,
                "url": url,
                "ok": bool(ok),
                "transport": transport,
                "reason": reason,
                "at": _now_iso(),
            }
        ],
    )


def count_downloads(run: LiteratureRun) -> int:
    """统计运行目录内**成功**的下载次数（批量上限判定用）。"""
    return sum(1 for row in read_jsonl(run.run_dir / "downloads.jsonl") if row.get("ok"))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_run_store.py \
  backend/tests/unit/test_literature_pipeline.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/literature/run_store.py backend/tests/unit/test_literature_run_store.py
git commit -m "feat(literature): query_log 扩展 transport/fallback_reason/backend_id 并加 downloads 计数"
```

---

### Task 12: 扩展站点模型 —— `notes[]` / `backends[]` / `contact_email`

**Files:**
- Modify: `backend/literature/models.py:113-143`（`ComplianceSpec` / `SiteProfile`）、`:317` 起（`profile_from_dict`）、`:469`（`render_search_url`）
- Test: `backend/tests/unit/test_literature_site_knowledge.py`

**Interfaces:**
- Consumes: 既有 `profile_from_dict` / `_require_str` / `_require_dict` / `_str_tuple` / `_ID_RE`
- Produces:
  - `NOTE_SEVERITIES = ("blocker", "degraded", "cosmetic")`
  - `BACKEND_STATUSES = ("ready", "blocked", "unavailable", "unknown")`
  - `@dataclass(frozen=True) class SiteNote`：`id`、`title`、`symptom`、`cause`、`workaround`、`severity`、`applies_to: Tuple[str, ...]`、`learned_at`、`verified_at`、`source_run`
  - `@dataclass(frozen=True) class SiteBackend`：`id`、`label`、`entry_url`、`status`、`reason`、`capabilities: Dict[str, bool]`、`overrides: Dict[str, Any]`、`checked_at`
  - `ComplianceSpec.contact_email: str = ""`
  - `SiteProfile.notes: Tuple[SiteNote, ...] = ()`、`SiteProfile.backends: Tuple[SiteBackend, ...] = ()`
  - `select_backend(profile, backend_id="") -> Optional[SiteBackend]`
  - `select_backend_id(profile) -> str`
  - `render_search_url(profile, query, limit=10, backend_id="") -> str`（支持 `{backend_id}` 占位）

**背景（spec §3.1 / §3.2）：** `notes[]` 承载结构化站点经验（一条经验 = 一条字符串的旧形态无法并存多条、无法标严重级别、无法按阶段召回）；`backends[]` 表达「一个站点多个检索后端」。全部字段可选，缺省行为与现在完全一致。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_site_knowledge.py`：

```python
"""站点知识模型：notes[] / backends[]（spec §3.1 / §3.2）。"""

import pytest

from backend.literature.models import (
    BACKEND_STATUSES,
    NOTE_SEVERITIES,
    SiteProfileError,
    profile_from_dict,
    render_search_url,
    select_backend,
    select_backend_id,
)

pytestmark = pytest.mark.unit

_MINIMAL = {
    "id": "demo",
    "display_name": "演示站",
    "home_url": "https://demo.example",
    "domains": ["demo.example"],
    "search": {
        "url_template": "https://demo.example/s?q={query}&n={limit}",
        "mode": "url",
        "submit_key": "Enter",
        "result_hint": "",
    },
}


def test_minimal_profile_has_no_notes_or_backends() -> None:
    profile = profile_from_dict(dict(_MINIMAL))
    assert profile.notes == ()
    assert profile.backends == ()


def test_notes_are_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "download-ddata-missing",
            "title": "结果行 href 必须取元素属性",
            "symptom": "下载报参数错误",
            "cause": "快照 URL 被截断",
            "workaround": "用 browser_interact action=attr 读 href",
            "severity": "blocker",
            "applies_to": ["pdf.entry"],
            "learned_at": "2026-01-15",
            "verified_at": "2026-02-03",
            "source_run": "run-001",
        }
    ]
    profile = profile_from_dict(raw)
    assert len(profile.notes) == 1
    note = profile.notes[0]
    assert note.id == "download-ddata-missing"
    assert note.severity == "blocker"
    assert note.applies_to == ("pdf.entry",)
    assert note.learned_at == "2026-01-15"
    assert note.verified_at == "2026-02-03"
    assert note.source_run == "run-001"


def test_note_severity_is_validated() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "x",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "catastrophic",
            "learned_at": "2026-01-15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_note_id_must_be_slug() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "Bad Id",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026-01-15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_note_learned_at_must_be_iso_date() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "x",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026/01/15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_duplicate_note_ids_are_overridden_not_appended() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "dup",
            "title": "第一版",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026-01-15",
        },
        {
            "id": "dup",
            "title": "第二版",
            "symptom": "s2",
            "workaround": "w2",
            "severity": "degraded",
            "learned_at": "2026-01-16",
        },
    ]
    profile = profile_from_dict(raw)
    assert len(profile.notes) == 1
    assert profile.notes[0].title == "第二版"


def test_backends_are_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {
            "id": "db3",
            "label": "库三",
            "entry_url": "https://demo.example/dbItem/3",
            "status": "ready",
            "capabilities": {"search": True},
            "checked_at": "2026-01-15",
        },
        {
            "id": "db1",
            "label": "库一",
            "entry_url": "https://demo.example/dbItem/1",
            "status": "unavailable",
            "reason": "代理报错",
        },
    ]
    profile = profile_from_dict(raw)
    assert len(profile.backends) == 2
    assert profile.backends[0].id == "db3"
    assert profile.backends[0].capabilities == {"search": True}
    assert profile.backends[1].reason == "代理报错"


def test_backend_status_is_validated() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {
            "id": "db9",
            "label": "库九",
            "entry_url": "https://demo.example/dbItem/9",
            "status": "maybe",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_select_backend_prefers_requested_id() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {"id": "db1", "label": "一", "entry_url": "https://demo.example/dbItem/1", "status": "ready"},
        {"id": "db2", "label": "二", "entry_url": "https://demo.example/dbItem/2", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    assert select_backend(profile, "db2").id == "db2"
    assert select_backend_id(profile) == "db1"


def test_select_backend_id_skips_blocked_and_unavailable() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {"id": "db1", "label": "一", "entry_url": "https://demo.example/dbItem/1", "status": "blocked"},
        {"id": "db2", "label": "二", "entry_url": "https://demo.example/dbItem/2", "status": "unavailable"},
        {"id": "db3", "label": "三", "entry_url": "https://demo.example/dbItem/3", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    assert select_backend_id(profile) == "db3"


def test_render_search_url_supports_backend_id_placeholder() -> None:
    raw = dict(_MINIMAL)
    raw["search"] = dict(_MINIMAL["search"])  # type: ignore[index]
    raw["search"]["url_template"] = "https://demo.example/s?q={query}&db={backend_id}&n={limit}"
    raw["backends"] = [
        {"id": "db3", "label": "三", "entry_url": "https://demo.example/dbItem/3", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    url = render_search_url(profile, "关键词", limit=5, backend_id="db3")
    assert "db=db3" in url
    assert "q=%E5%85%B3%E9%92%AE%E8%AF%8D" in url


def test_compliance_contact_email_is_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["compliance"] = {"note": "遵守条款", "contact_email": "user@example.org"}
    profile = profile_from_dict(raw)
    assert profile.compliance.contact_email == "user@example.org"


def test_enum_constants() -> None:
    assert NOTE_SEVERITIES == ("blocker", "degraded", "cosmetic")
    assert BACKEND_STATUSES == ("ready", "blocked", "unavailable", "unknown")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_site_knowledge.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'select_backend'`。

- [ ] **Step 3: 最小实现**

改 `backend/literature/models.py`。

（a）import 区改两处：

- `from datetime import date`（若尚未导入）；
- typing 导入补 `List`（`models.py` 现有 `from typing import Any, Dict, Optional, Tuple`，
  下面的 `_parse_notes` / `_parse_backends` 都要用 `List[str]`）：

```python
from typing import Any, Dict, List, Optional, Tuple
```

（b）在 `RateLimitSpec` 之后插入常量与两个 dataclass：

```python
#: 站点经验的严重级别（spec §3.1）。
NOTE_SEVERITIES = ("blocker", "degraded", "cosmetic")

#: 单个检索后端的可用性状态（spec §3.2）。
BACKEND_STATUSES = ("ready", "blocked", "unavailable", "unknown")


@dataclass(frozen=True)
class SiteNote:
    """一条结构化站点经验。"""

    id: str
    title: str
    symptom: str
    workaround: str
    cause: str = ""
    severity: str = "degraded"
    applies_to: Tuple[str, ...] = ()
    learned_at: str = ""
    verified_at: str = ""
    source_run: str = ""


@dataclass(frozen=True)
class SiteBackend:
    """站点内的单个检索后端（文献库）。"""

    id: str
    label: str
    entry_url: str
    status: str = "unknown"
    reason: str = ""
    capabilities: Dict[str, bool] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)
    checked_at: str = ""
```

（c）`ComplianceSpec` 加字段：

```python
@dataclass(frozen=True)
class ComplianceSpec:
    note: str = ""
    default_enabled: bool = False
    contact_email: str = ""
```

（d）`SiteProfile` 末尾加两个字段：

```python
    notes: Tuple[SiteNote, ...] = ()
    backends: Tuple[SiteBackend, ...] = ()
```

（e）新增解析辅助函数（放在 `profile_from_dict` 之前）：

```python
def _parse_iso_date(value: str, field: str) -> str:
    """校验 ISO 日期（``YYYY-MM-DD``）；失败抛 ``SiteProfileError``。"""
    text = str(value or "").strip()
    if not text:
        raise SiteProfileError(f"{field} 不能为空")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise SiteProfileError(f"{field} 必须是 ISO 日期 (YYYY-MM-DD): {text!r}") from exc
    return text


def _parse_notes(raw: Any) -> Tuple[SiteNote, ...]:
    """解析 ``notes`` 列表；同 id 视为覆盖（后者生效）。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SiteProfileError("notes 必须是列表")
    merged: Dict[str, SiteNote] = {}
    order: List[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SiteProfileError(f"notes[{index}] 必须是对象")
        note_id = _require_str(item.get("id"), f"notes[{index}].id", required=True)
        if not _ID_RE.match(note_id):
            raise SiteProfileError(
                f"notes[{index}].id 必须是小写字母/数字/连字符: {note_id!r}"
            )
        severity = _require_str(
            item.get("severity"), f"notes[{index}].severity", required=True
        )
        if severity not in NOTE_SEVERITIES:
            raise SiteProfileError(
                f"notes[{index}].severity 必须是 {list(NOTE_SEVERITIES)} 之一，收到 {severity!r}"
            )
        applies_to = _str_tuple(item.get("applies_to"), f"notes[{index}].applies_to")
        note = SiteNote(
            id=note_id,
            title=_require_str(item.get("title"), f"notes[{index}].title", required=True),
            symptom=_require_str(item.get("symptom"), f"notes[{index}].symptom", required=True),
            workaround=_require_str(
                item.get("workaround"), f"notes[{index}].workaround", required=True
            ),
            cause=_optional_str(item.get("cause"), f"notes[{index}].cause") or "",
            severity=severity,
            applies_to=applies_to,
            learned_at=_parse_iso_date(
                item.get("learned_at"), f"notes[{index}].learned_at"
            ),
            verified_at=(
                _parse_iso_date(item.get("verified_at"), f"notes[{index}].verified_at")
                if str(item.get("verified_at") or "").strip()
                else ""
            ),
            source_run=_optional_str(item.get("source_run"), f"notes[{index}].source_run") or "",
        )
        if note_id not in merged:
            order.append(note_id)
        merged[note_id] = note
    return tuple(merged[key] for key in order)


def _parse_backends(raw: Any) -> Tuple[SiteBackend, ...]:
    """解析 ``backends`` 列表；同 id 视为覆盖（后者生效）。"""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SiteProfileError("backends 必须是列表")
    merged: Dict[str, SiteBackend] = {}
    order: List[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SiteProfileError(f"backends[{index}] 必须是对象")
        backend_id = _require_str(item.get("id"), f"backends[{index}].id", required=True)
        if not _ID_RE.match(backend_id):
            raise SiteProfileError(
                f"backends[{index}].id 必须是小写字母/数字/连字符: {backend_id!r}"
            )
        status = _require_str(item.get("status"), f"backends[{index}].status", required=True)
        if status not in BACKEND_STATUSES:
            raise SiteProfileError(
                f"backends[{index}].status 必须是 {list(BACKEND_STATUSES)} 之一，收到 {status!r}"
            )
        entry_url = _require_str(
            item.get("entry_url"), f"backends[{index}].entry_url", required=True
        )
        capabilities_raw = item.get("capabilities")
        overrides_raw = item.get("overrides")
        backend = SiteBackend(
            id=backend_id,
            label=_require_str(item.get("label"), f"backends[{index}].label", required=True),
            entry_url=entry_url,
            status=status,
            reason=_optional_str(item.get("reason"), f"backends[{index}].reason") or "",
            capabilities=(
                {
                    str(key): bool(value)
                    for key, value in _require_dict(
                        capabilities_raw, f"backends[{index}].capabilities"
                    ).items()
                }
                if capabilities_raw is not None
                else {}
            ),
            overrides=(
                dict(_require_dict(overrides_raw, f"backends[{index}].overrides"))
                if overrides_raw is not None
                else {}
            ),
            checked_at=(
                _parse_iso_date(item.get("checked_at"), f"backends[{index}].checked_at")
                if str(item.get("checked_at") or "").strip()
                else ""
            ),
        )
        if backend_id not in merged:
            order.append(backend_id)
        merged[backend_id] = backend
    return tuple(merged[key] for key in order)
```

（f）在 `models.py` 末尾加公开别名（供 `knowledge.py` / 工具层跨模块调用，避免直接 import
带下划线的私有名）：

```python
#: 公开别名 —— 跨模块（``knowledge.py`` / 工具层）解析站点经验与后端。
parse_notes = _parse_notes
parse_backends = _parse_backends
```

（g）在 `profile_from_dict` 里解析并传入（找到构造 `SiteProfile(...)` 的位置，追加两个 kwarg）：

```python
        notes=_parse_notes(raw.get("notes")),
        backends=_parse_backends(raw.get("backends")),
```

（h）`compliance` 解析处补 `contact_email`（`compliance_note` / `compliance_default`
两个局部变量**并不存在** —— 现有代码直接内联读 `compliance_raw`，所以这里要一并把
`compliance_raw` 的取值写全）：

```python
        compliance=ComplianceSpec(
            note=_require_str(compliance_raw.get("note"), "compliance.note"),
            default_enabled=bool(compliance_raw.get("default_enabled", False)),
            contact_email=_require_str(
                compliance_raw.get("contact_email"), "compliance.contact_email"
            ),
        ),
```

（i）新增后端选择函数（放在 `render_search_url` 之前）：

```python
def select_backend(profile: SiteProfile, backend_id: str = "") -> Optional[SiteBackend]:
    """按 id 取后端；空 id 时取第一个 ``ready`` 后端，没有则取第一个。"""
    if not profile.backends:
        return None
    wanted = str(backend_id or "").strip()
    if wanted:
        for backend in profile.backends:
            if backend.id == wanted:
                return backend
        return None
    for backend in profile.backends:
        if backend.status == "ready":
            return backend
    return profile.backends[0]


def select_backend_id(profile: SiteProfile) -> str:
    """返回默认后端 id；无可用后端返回空串。"""
    backend = select_backend(profile)
    return backend.id if backend is not None else ""
```

（j）`render_search_url` 改为支持 `{backend_id}`：

```python
def render_search_url(
    profile: SiteProfile,
    query: str,
    limit: int = 10,
    backend_id: str = "",
) -> str:
    """渲染检索 URL；校验 scheme 与域名，防止 profile 指向任意主机。"""
    text = (query or "").strip()
    if not text:
        raise SiteProfileError("query 不能为空")
    template = profile.search.url_template
    if not template:
        raise SiteProfileError(f"站点 {profile.id} 未配置 search.url_template")

    resolved_backend_id = backend_id or select_backend_id(profile)
    try:
        url = template.format(
            query=quote(text, safe=""),
            limit=str(int(limit)),
            backend_id=resolved_backend_id,
        )
    except (KeyError, ValueError) as exc:
        raise SiteProfileError(
            f"站点 {profile.id} 的 search.url_template 渲染失败: {exc}"
        ) from exc

    parsed = urlparse(url)
    if parsed.scheme not in _HTTP_SCHEMES or not parsed.hostname:
        raise SiteProfileError(f"检索 URL 必须是 http(s): {url!r}")
    if not is_allowed_host(parsed.hostname, profile.domains):
        raise SiteProfileError(
            f"检索 URL 域名 {parsed.hostname!r} 不在站点域名 {list(profile.domains)} 内"
        )
    return url
```

> 注意：`template.format(...)` 传入 `backend_id` 后，**不含 `{backend_id}` 占位符的模板不受影响**
> —— `str.format` 忽略多余关键字参数。但若用户模板里写了 `{backend_id}` 而 profile 没有
> 任何后端，`resolved_backend_id` 为空串，渲染出 `db=` —— 这是可接受的（模板作者自担）。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_site_knowledge.py \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_literature_pipeline.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/literature/models.py backend/tests/unit/test_literature_site_knowledge.py
git commit -m "feat(literature): 站点模型扩展 notes[]/backends[]/contact_email"
```

---

### Task 13: sidecar 读写与合并（`backend/literature/knowledge.py`）

**Files:**
- Create: `backend/literature/knowledge.py`
- Modify: `backend/literature/profile_store.py:53`（`discover` 跳过 sidecar + 合并）
- Test: `backend/tests/unit/test_literature_site_knowledge.py`（追加）

**Interfaces:**
- Consumes: `backend.literature.models.SiteNote` / `SiteBackend` / `SiteProfile`；`backend.literature.run_store.atomic_write_text`
- Produces:
  - `knowledge.NOTES_SIDECAR_SUFFIX = ".notes.yaml"`、`knowledge.BACKENDS_SIDECAR_SUFFIX = ".backends.yaml"`
  - `knowledge.is_sidecar_filename(name: str) -> bool`
  - `knowledge.sidecar_path(sites_dir: Path, site_id: str, kind: str) -> Path`
  - `knowledge.read_sidecar(path: Path) -> Dict[str, Any]`（YAML 损坏 → 抛 `SiteProfileError`）
  - `knowledge.write_sidecar(path: Path, payload: Dict[str, Any]) -> None`（原子写）
  - `knowledge.merge_notes(base: Sequence[SiteNote], extra: Sequence[SiteNote]) -> Tuple[SiteNote, ...]`
  - `knowledge.merge_backends(base: Sequence[SiteBackend], extra: Sequence[SiteBackend]) -> Tuple[SiteBackend, ...]`
  - `profile_store.user_sites_dir() -> Path`（公开包装）

**背景（spec §3.1 / §2.1）：** 机器写入走 **sidecar** `<site_id>.notes.yaml` —— 不动主 YAML（`recording.py` 的 `yaml.safe_dump` 会毁掉用户手写注释）。sidecar 合并规则：主 YAML 为「人写基线」，sidecar 按 `id` 覆盖同 id 条目，其余追加。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/unit/test_literature_site_knowledge.py` 末尾追加：

```python
def _write_main_profile(directory, site_id="demo", extra=""):
    directory.mkdir(parents=True, exist_ok=True)
    payload = (
        "id: demo\n"
        "display_name: 演示站\n"
        "home_url: https://demo.example\n"
        "domains:\n  - demo.example\n"
        "search:\n"
        "  url_template: https://demo.example/s?q={query}&n={limit}\n"
        "  mode: url\n"
        "  submit_key: Enter\n"
        "  result_hint: ''\n" + extra
    )
    path = directory / f"{site_id}.yaml"
    path.write_text(payload, encoding="utf-8")
    return path


def test_sidecar_suffixes() -> None:
    from backend.literature.knowledge import (
        BACKENDS_SIDECAR_SUFFIX,
        NOTES_SIDECAR_SUFFIX,
    )

    assert NOTES_SIDECAR_SUFFIX == ".notes.yaml"
    assert BACKENDS_SIDECAR_SUFFIX == ".backends.yaml"


def test_is_sidecar_filename() -> None:
    from backend.literature.knowledge import is_sidecar_filename

    assert is_sidecar_filename("demo.notes.yaml") is True
    assert is_sidecar_filename("demo.backends.yaml") is True
    assert is_sidecar_filename("demo.yaml") is False


def test_profile_store_skips_sidecar_files(tmp_path) -> None:
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore

    _write_main_profile(tmp_path)
    (tmp_path / "demo.notes.yaml").write_text("notes: []\n", encoding="utf-8")
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    assert store.list_ids() == ["demo"]


def test_profile_store_merges_sidecar_notes(tmp_path) -> None:
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore

    _write_main_profile(
        tmp_path,
        extra=(
            "notes:\n"
            "  - id: base-note\n"
            "    title: 基线\n"
            "    symptom: s\n"
            "    workaround: w\n"
            "    severity: degraded\n"
            "    learned_at: '2026-01-01'\n"
        ),
    )
    (tmp_path / "demo.notes.yaml").write_text(
        "notes:\n"
        "  - id: base-note\n"
        "    title: 覆盖版\n"
        "    symptom: s2\n"
        "    workaround: w2\n"
        "    severity: blocker\n"
        "    learned_at: '2026-02-01'\n"
        "  - id: extra-note\n"
        "    title: 新增\n"
        "    symptom: s3\n"
        "    workaround: w3\n"
        "    severity: cosmetic\n"
        "    learned_at: '2026-02-02'\n",
        encoding="utf-8",
    )
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    profile = store.get("demo")
    ids = [note.id for note in profile.notes]
    assert "extra-note" in ids
    titles = {note.id: note.title for note in profile.notes}
    assert titles["base-note"] == "覆盖版"


def test_broken_sidecar_raises_explicit_error(tmp_path) -> None:
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore
    from backend.literature.models import SiteProfileError

    _write_main_profile(tmp_path)
    (tmp_path / "demo.notes.yaml").write_text("notes: [\n  - broken\n", encoding="utf-8")
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    with pytest.raises(SiteProfileError):
        store.get("demo")


def test_write_sidecar_is_atomic(tmp_path) -> None:
    from backend.literature.knowledge import write_sidecar

    target = tmp_path / "demo.notes.yaml"
    write_sidecar(target, {"notes": []})
    assert target.is_file()
    assert not list(tmp_path.glob(".tmp-*"))
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_site_knowledge.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.literature.knowledge'`。

- [ ] **Step 3: 最小实现**

创建 `backend/literature/knowledge.py`：

```python
"""站点知识的 sidecar 读写与合并（spec §3.1）。

机器写入的站点经验与后端清单**不进主 profile YAML**，而是写同目录的
sidecar 文件：

- ``<site_id>.notes.yaml``
- ``<site_id>.backends.yaml``

原因：主 YAML 是「人手写配置」，``yaml.safe_dump`` 会毁掉用户手写注释；
sidecar 天然分离「人手写」与「机器追加」。

合并规则：主 YAML 为人写基线，sidecar 按 ``id`` 覆盖同 id 条目，其余追加。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml

from .models import SiteBackend, SiteNote, SiteProfileError
from .run_store import atomic_write_text

logger = logging.getLogger(__name__)

NOTES_SIDECAR_SUFFIX = ".notes.yaml"
BACKENDS_SIDECAR_SUFFIX = ".backends.yaml"


def is_sidecar_filename(name: str) -> bool:
    """判断文件名是否是 sidecar（而非站点 profile 主文件）。"""
    text = str(name or "")
    return text.endswith(NOTES_SIDECAR_SUFFIX) or text.endswith(BACKENDS_SIDECAR_SUFFIX)


def sidecar_path(sites_dir: Path, site_id: str, kind: str) -> Path:
    """返回 sidecar 路径；``kind`` 取 ``"notes"`` 或 ``"backends"``。"""
    suffix = NOTES_SIDECAR_SUFFIX if kind == "notes" else BACKENDS_SIDECAR_SUFFIX
    return Path(sites_dir) / f"{site_id}{suffix}"


def read_sidecar(path: Path) -> Dict[str, Any]:
    """读 sidecar YAML；损坏时抛 ``SiteProfileError``（不静默忽略）。"""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SiteProfileError(f"sidecar YAML 解析失败 {target}: {exc}") from exc
    except OSError as exc:
        raise SiteProfileError(f"sidecar 读取失败 {target}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SiteProfileError(f"sidecar 根节点必须是对象: {target}")
    return raw


def write_sidecar(path: Path, payload: Dict[str, Any]) -> None:
    """原子写 sidecar YAML（保留人手写主文件不动）。"""
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    atomic_write_text(Path(path), text)


def merge_notes(
    base: Sequence[SiteNote], extra: Sequence[SiteNote]
) -> Tuple[SiteNote, ...]:
    """按 id 合并；``extra`` 覆盖 ``base`` 的同 id 条目。"""
    merged: Dict[str, SiteNote] = {}
    order: List[str] = []
    for note in list(base) + list(extra):
        if note.id not in merged:
            order.append(note.id)
        merged[note.id] = note
    return tuple(merged[key] for key in order)


def merge_backends(
    base: Sequence[SiteBackend], extra: Sequence[SiteBackend]
) -> Tuple[SiteBackend, ...]:
    """按 id 合并；``extra`` 覆盖 ``base`` 的同 id 条目。"""
    merged: Dict[str, SiteBackend] = {}
    order: List[str] = []
    for backend in list(base) + list(extra):
        if backend.id not in merged:
            order.append(backend.id)
        merged[backend.id] = backend
    return tuple(merged[key] for key in order)
```

- [ ] **Step 4: `profile_store` 跳过 sidecar 并合并**

改 `backend/literature/profile_store.py`：

（a）把 `_user_sites_dir()` 改名为公开的 `user_sites_dir()`，并同步改 `default()` 里的唯一调用点
（`ProfileRoot(_user_sites_dir(), "user")` → `ProfileRoot(user_sites_dir(), "user")`；全仓仅此一处引用，
不留私有别名）：

```python
def user_sites_dir() -> Path:
    """用户层站点目录（``$SAGE_LITERATURE_SITES_DIR`` 或 ``~/.sage/literature_sites``）。"""
    env_dir = os.environ.get("SAGE_LITERATURE_SITES_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".sage" / "literature_sites"
```

（b）在 `discover()` 的文件遍历里跳过 sidecar：

```python
                if path.name.startswith(".") or path.suffix.lower() not in _YAML_SUFFIXES:
                    continue
                if is_sidecar_filename(path.name):
                    # sidecar 不是站点 profile 主文件；它随主 profile 一起合并
                    continue
```

（c）主 profile 加载成功后，合并同目录 sidecar。在 `profiles[profile.id] = profile` 之前插入：

```python
                try:
                    profile = _merge_sidecars(profile, path.parent)
                except SiteProfileError as exc:
                    errors[path.stem] = exc
                    logger.warning("站点 profile sidecar 无效 %s: %s", path, exc)
                    continue
```

并在类外新增辅助函数：

```python
def _merge_sidecars(profile: SiteProfile, directory: Path) -> SiteProfile:
    """把同目录的 notes / backends sidecar 合并进 profile。"""
    notes_raw = read_sidecar(sidecar_path(directory, profile.id, "notes"))
    backends_raw = read_sidecar(sidecar_path(directory, profile.id, "backends"))
    if not notes_raw and not backends_raw:
        return profile
    notes = parse_notes(notes_raw.get("notes"))
    backends = parse_backends(backends_raw.get("backends"))
    return replace(
        profile,
        notes=merge_notes(profile.notes, notes),
        backends=merge_backends(profile.backends, backends),
    )
```

（d）import 区补（**isort 顺序：`from dataclasses import replace` 属标准库，`.knowledge` / `.models` 属本地包，顺序如下**）：

```python
from dataclasses import replace

from .knowledge import (
    is_sidecar_filename,
    merge_backends,
    merge_notes,
    read_sidecar,
    sidecar_path,
)
from .models import SiteProfile, SiteProfileError, parse_backends, parse_notes
```

> `models.py` 里 `_parse_notes` / `_parse_backends` 是带下划线的模块级函数，Task 12 已在其末尾
> 加上公开别名 `parse_notes` / `parse_backends`。**这里一律用公开别名**，避免跨模块 import
> 私有名（ruff 的 `SLF001` 规则当前未开启，但公开别名是更稳的约定）。

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_site_knowledge.py \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_literature_pipeline.py -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/literature/
```

Expected: PASS + ruff 干净。

- [ ] **Step 6: 提交**

```bash
git add backend/literature/knowledge.py backend/literature/profile_store.py \
  backend/literature/models.py backend/tests/unit/test_literature_site_knowledge.py
git commit -m "feat(literature): 新增 sidecar 读写与合并并接入 profile_store"
```

---

### Task 14: 指导文本渲染「站点经验」与「可用后端」

**Files:**
- Modify: `backend/literature/guidance.py:20`
- Test: `backend/tests/unit/test_literature_guidance.py`（若不存在则新建）

**Interfaces:**
- Consumes: `SiteProfile.notes` / `SiteProfile.backends`
- Produces:
  - `guidance.STALE_AFTER_DAYS = 180`
  - `guidance.render_notes_section(profile, phase="search") -> str`
  - `render_search_guidance(profile, query, limit=10, page_url=None, page_title=None, phase="search") -> str`

**背景（spec §3.1 / §3.2 / §9.1）：** 指导文本要按 `severity` 排序（blocker 在前），只渲染与**当前阶段**相关的条目，避免把全部经验灌进上下文。`blocked` 后端要在文本里提示「需用户手动完成滑块验证」。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_guidance.py`：

```python
"""指导文本中的站点经验与后端（spec §3.1 / §3.2）。"""

import pytest

from backend.literature.guidance import STALE_AFTER_DAYS, render_search_guidance
from backend.literature.models import profile_from_dict

pytestmark = pytest.mark.unit

_BASE = {
    "id": "demo",
    "display_name": "演示站",
    "home_url": "https://demo.example",
    "domains": ["demo.example"],
    "search": {
        "url_template": "https://demo.example/s?q={query}&n={limit}",
        "mode": "url",
        "submit_key": "Enter",
        "result_hint": "",
    },
}


def _profile(notes=None, backends=None):
    raw = dict(_BASE)
    if notes:
        raw["notes"] = notes
    if backends:
        raw["backends"] = backends
    return profile_from_dict(raw)


def test_no_notes_section_when_there_are_no_notes() -> None:
    text = render_search_guidance(_profile(), "关键词")
    assert "站点经验" not in text


def test_notes_section_lists_notes_sorted_by_severity() -> None:
    profile = _profile(
        notes=[
            {
                "id": "cosmetic-one",
                "title": "只是提示",
                "symptom": "s",
                "workaround": "w",
                "severity": "cosmetic",
                "learned_at": "2026-01-01",
            },
            {
                "id": "blocker-one",
                "title": "阻断问题",
                "symptom": "s",
                "workaround": "w",
                "severity": "blocker",
                "learned_at": "2026-01-01",
            },
            {
                "id": "degraded-one",
                "title": "降级问题",
                "symptom": "s",
                "workaround": "w",
                "severity": "degraded",
                "learned_at": "2026-01-01",
            },
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "站点经验" in text
    assert text.index("阻断问题") < text.index("降级问题") < text.index("只是提示")


def test_only_notes_relevant_to_the_phase_are_rendered() -> None:
    profile = _profile(
        notes=[
            {
                "id": "download-note",
                "title": "下载相关",
                "symptom": "s",
                "workaround": "w",
                "severity": "blocker",
                "applies_to": ["pdf.download"],
                "learned_at": "2026-01-01",
            }
        ]
    )
    search_text = render_search_guidance(profile, "关键词", phase="search")
    assert "下载相关" not in search_text
    download_text = render_search_guidance(profile, "关键词", phase="pdf.download")
    assert "下载相关" in download_text


def test_blocked_backend_is_flagged_for_manual_action() -> None:
    profile = _profile(
        backends=[
            {
                "id": "db1",
                "label": "需滑块的库",
                "entry_url": "https://demo.example/dbItem/1",
                "status": "blocked",
                "reason": "触发滑块验证",
            }
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "db1" in text
    assert "滑块" in text or "人工" in text


def test_ready_backend_is_listed_as_candidate() -> None:
    profile = _profile(
        backends=[
            {
                "id": "db3",
                "label": "可用库",
                "entry_url": "https://demo.example/dbItem/3",
                "status": "ready",
            }
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "db3" in text


def test_stale_after_days_constant() -> None:
    assert STALE_AFTER_DAYS == 180
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_guidance.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'STALE_AFTER_DAYS'`。

- [ ] **Step 3: 最小实现**

改 `backend/literature/guidance.py`：import 区改成（isort 顺序：标准库 → 本地包）：

```python
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from .models import SiteField, SiteNote, SiteProfile, is_logged_in, render_search_url
```

> `date.today()` 会触发 ruff `DTZ011`（DTZ 规则集在 `backend/ruff.toml` 里开启，只豁免了
> DTZ005/DTZ006）—— 所以「今天」一律用 `datetime.now(timezone.utc).date()` 推导。

在 `render_search_guidance` 之前插入：

```python
#: 经验超过该天数未复验即在文本中标注「未复验」（spec §3.1）。
STALE_AFTER_DAYS = 180

#: 严重级别排序：blocker 在前。
_SEVERITY_ORDER = {"blocker": 0, "degraded": 1, "cosmetic": 2}


def _is_stale(note: SiteNote, today: Optional[date] = None) -> bool:
    """经验是否已超过 ``STALE_AFTER_DAYS`` 未复验。"""
    if note.verified_at:
        return False
    if not note.learned_at:
        return True
    reference = today or datetime.now(timezone.utc).date()
    try:
        learned = date.fromisoformat(note.learned_at)
    except ValueError:
        return True
    return (reference - learned).days > STALE_AFTER_DAYS


def _relevant_notes(profile: SiteProfile, phase: str) -> List[SiteNote]:
    """筛出与当前阶段相关的经验，按严重级别排序。"""
    selected = [
        note
        for note in profile.notes
        if not note.applies_to or phase in note.applies_to
    ]
    return sorted(selected, key=lambda note: (_SEVERITY_ORDER.get(note.severity, 9), note.id))


def render_notes_section(profile: SiteProfile, phase: str = "search") -> str:
    """渲染「站点经验」段；无相关内容时返回空串。"""
    notes = _relevant_notes(profile, phase)
    if not notes:
        return ""
    lines = ["## 站点经验（按严重度排序，仅列与当前阶段相关的条目）"]
    for note in notes:
        stale = "（未复验）" if _is_stale(note) else ""
        lines.append(f"- [{note.severity}] {note.title}{stale}")
        lines.append(f"  - 现象: {note.symptom}")
        if note.cause:
            lines.append(f"  - 根因: {note.cause}")
        lines.append(f"  - 做法: {note.workaround}")
    return "\n".join(lines)


def render_backends_section(profile: SiteProfile) -> str:
    """渲染「可用检索后端」段；无后端时返回空串。"""
    if not profile.backends:
        return ""
    lines = ["## 可用检索后端"]
    for backend in profile.backends:
        if backend.status == "blocked":
            lines.append(
                f"- {backend.id}（{backend.label}）: 需人工完成验证"
                f"（{backend.reason or '站点侧要求人工交互'}），"
                "请用户在可见窗口操作后自行改为 ready"
            )
        elif backend.status == "unavailable":
            lines.append(f"- {backend.id}（{backend.label}）: 不可用（{backend.reason or '站点侧报错'}）")
        elif backend.status == "unknown":
            lines.append(f"- {backend.id}（{backend.label}）: 未探测，可执行一次探测")
        else:
            lines.append(f"- {backend.id}（{backend.label}）: 可用，入口 {backend.entry_url}")
    return "\n".join(lines)
```

然后改 `render_search_guidance`，共三处小改：

1）签名末尾加 `phase` 参数（其余签名行不动）：

```python
def render_search_guidance(
    profile: SiteProfile,
    query: str,
    limit: int = 10,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
    phase: str = "search",
) -> str:
```

2）在 `return (` 之前插入 extra 计算块：

```python
    notes_block = render_notes_section(profile, phase)
    backends_block = render_backends_section(profile)
    extra = ""
    if backends_block:
        extra += backends_block + "\n"
    if notes_block:
        extra += notes_block + "\n"
```

3）return 里**仅一处**插 `extra` —— 把既有这两行：

```python
        f"合规: {profile.compliance.note or '遵守站点条款与机构授权'}\n\n"
        "请基于 browser_snapshot 解析结果，输出 JSON 数组，每项字段: "
```

改为：

```python
        f"合规: {profile.compliance.note or '遵守站点条款与机构授权'}\n\n"
        + extra
        + "请基于 browser_snapshot 解析结果，输出 JSON 数组，每项字段: "
```

return 里其余各行（`f"站点: ..."` 到 `f"限速: ..."`、结尾的 `"paper_key, title, ..."` /
`"不要编造..."`）**一个字都不改** —— 相邻字符串字面量在编译期自动拼接，插入 `+ extra +`
后语义不变。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_guidance.py \
  backend/tests/unit/test_literature_pipeline.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/literature/guidance.py backend/tests/unit/test_literature_guidance.py
git commit -m "feat(literature): 指导文本渲染站点经验与可用后端"
```

---

### Task 15: `profile_record_note` 工具（观测 → 经验的沉淀闭环）

**Files:**
- Create: `backend/tools/profile_note_tool.py`
- Modify: `backend/tools/tool_bundles.py`（注册）
- Modify: `backend/domain/tool_names.py`（`ALL_BUILTIN_TOOL_NAMES` 所在元组）
- Modify: `backend/tools/permissions.py`（能力登记）
- Test: `backend/tests/unit/test_profile_note_tool.py`

**Interfaces:**
- Consumes: `backend.literature.knowledge.sidecar_path` / `read_sidecar` / `write_sidecar` / `merge_notes`；`backend.literature.models.parse_notes` / `NOTE_SEVERITIES` / `SiteProfileError`；`backend.literature.profile_store.user_sites_dir`
- Produces: `profile_note_tool.ProfileRecordNoteTool`（工具名 `profile_record_note`，能力 `WRITE`）

**背景（spec §7.1）：** 一次运行中出现「非预期失败」且根因已定位 → LLM 调用该工具 → 经验进 profile → 下次运行时 `guidance.py` 自动渲染 → 不用重蹈覆辙。**只写 sidecar，不触碰主 profile YAML**。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_profile_note_tool.py`：

```python
"""profile_record_note 工具（spec §7.1）。"""

from pathlib import Path

import pytest

from backend.literature.knowledge import read_sidecar, sidecar_path
from backend.tools.profile_note_tool import ProfileRecordNoteTool

pytestmark = pytest.mark.unit


def test_record_note_writes_sidecar(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="download-ddata-missing",
        title="结果行 href 必须取元素属性",
        symptom="下载报参数错误",
        cause="快照 URL 被截断",
        workaround="用 browser_interact action=attr 读 href",
        severity="blocker",
        applies_to=["pdf.entry"],
        source_run="run-001",
    )
    assert result.success is True, result.error
    payload = read_sidecar(sidecar_path(tmp_path, "demo", "notes"))
    notes = payload["notes"]
    assert len(notes) == 1
    assert notes[0]["id"] == "download-ddata-missing"
    assert notes[0]["severity"] == "blocker"


def test_record_note_with_same_id_overwrites(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    tool.execute(
        site_id="demo",
        note_id="dup",
        title="第一版",
        symptom="s",
        workaround="w",
        severity="degraded",
    )
    result = tool.execute(
        site_id="demo",
        note_id="dup",
        title="第二版",
        symptom="s2",
        workaround="w2",
        severity="blocker",
    )
    assert result.success is True, result.error
    payload = read_sidecar(sidecar_path(tmp_path, "demo", "notes"))
    notes = payload["notes"]
    assert len(notes) == 1
    assert notes[0]["title"] == "第二版"


def test_invalid_severity_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="x",
        title="t",
        symptom="s",
        workaround="w",
        severity="catastrophic",
    )
    assert result.success is False


def test_invalid_note_id_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    tool = ProfileRecordNoteTool()
    result = tool.execute(
        site_id="demo",
        note_id="Bad Id",
        title="t",
        symptom="s",
        workaround="w",
        severity="blocker",
    )
    assert result.success is False


def test_main_profile_yaml_is_untouched(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(tmp_path))
    main = tmp_path / "demo.yaml"
    main.write_text("id: demo\n", encoding="utf-8")
    tool = ProfileRecordNoteTool()
    tool.execute(
        site_id="demo",
        note_id="x",
        title="t",
        symptom="s",
        workaround="w",
        severity="blocker",
    )
    assert main.read_text(encoding="utf-8") == "id: demo\n"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profile_note_tool.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.tools.profile_note_tool'`。

- [ ] **Step 3: 最小实现**

创建 `backend/tools/profile_note_tool.py`：

```python
"""profile_record_note 工具 —— 观测到经验的沉淀闭环（spec §7.1）。

把一次「非预期失败 + 已定位根因」写成一条结构化站点经验。经验落在
``~/.sage/literature_sites/<site_id>.notes.yaml``（sidecar），
**不触碰主 profile YAML** —— 用户的���写注释不能被机器写入毁掉。

能力分类：WRITE（本地文件副作用）。不涉及网络与外部服务。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.literature.knowledge import (
    merge_notes,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)
from backend.literature.models import NOTE_SEVERITIES, SiteProfileError, parse_notes
from backend.literature.profile_store import user_sites_dir

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

PROFILE_RECORD_NOTE_TOOL_NAME = "profile_record_note"


class ProfileRecordNoteTool(BaseTool):
    """把一次失败沉淀成站点经验。"""

    risk = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=PROFILE_RECORD_NOTE_TOOL_NAME,
            description=(
                "把一次已定位根因的失败记录为站点经验（写入 profile 的 notes sidecar）。"
                "下次运行时该经验会自动出现在检索指导文本里，避免重蹈覆辙。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string", "description": "目标站点 id"},
                    "note_id": {
                        "type": "string",
                        "description": "站点内唯一 slug（小写字母/数字/连字符）；同 id 覆盖",
                    },
                    "title": {"type": "string", "description": "一句话概括（≤60 字）"},
                    "symptom": {"type": "string", "description": "观察到的现象"},
                    "cause": {"type": "string", "description": "根因（未知可留空）"},
                    "workaround": {"type": "string", "description": "可执行的绕过/正确做法"},
                    "severity": {
                        "type": "string",
                        "enum": list(NOTE_SEVERITIES),
                        "description": "blocker（阻断）/ degraded（降级）/ cosmetic（提示）",
                    },
                    "applies_to": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "作用面：search / pdf.entry / pdf.download / login / backend:<id>"
                        ),
                    },
                    "source_run": {"type": "string", "description": "来源运行目录名（可选）"},
                },
                "required": [
                    "site_id",
                    "note_id",
                    "title",
                    "symptom",
                    "workaround",
                    "severity",
                ],
            },
        )

    def execute(
        self,
        site_id: str = "",
        note_id: str = "",
        title: str = "",
        symptom: str = "",
        cause: str = "",
        workaround: str = "",
        severity: str = "degraded",
        applies_to: Optional[List[str]] = None,
        source_run: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """写入一条站点经验（sidecar，按 note_id 覆盖）。"""
        site = str(site_id or "").strip()
        if not site:
            return ToolResult(success=False, error="site_id 不能为空")

        payload: Dict[str, Any] = {
            "id": str(note_id or "").strip(),
            "title": str(title or "").strip(),
            "symptom": str(symptom or "").strip(),
            "cause": str(cause or "").strip(),
            "workaround": str(workaround or "").strip(),
            "severity": str(severity or "").strip(),
            "applies_to": [str(item) for item in (applies_to or [])],
            "learned_at": datetime.now(timezone.utc).date().isoformat(),
            "verified_at": "",
            "source_run": str(source_run or "").strip(),
        }

        try:
            notes = parse_notes([payload])
        except SiteProfileError as exc:
            return ToolResult(success=False, error=f"invalid_note: {exc}")

        target = sidecar_path(user_sites_dir(), site, "notes")
        existing_raw = read_sidecar(target)
        existing = parse_notes(existing_raw.get("notes"))
        merged = merge_notes(existing, notes)
        write_sidecar(
            target,
            {
                "notes": [
                    {
                        "id": note.id,
                        "title": note.title,
                        "symptom": note.symptom,
                        "cause": note.cause,
                        "workaround": note.workaround,
                        "severity": note.severity,
                        "applies_to": list(note.applies_to),
                        "learned_at": note.learned_at,
                        "verified_at": note.verified_at,
                        "source_run": note.source_run,
                    }
                    for note in merged
                ]
            },
        )
        return ToolResult(
            success=True,
            content={"site_id": site, "note_id": notes[0].id, "total_notes": len(merged)},
        )
```

- [ ] **Step 4: 三处登记新工具**

`backend/domain/tool_names.py`：在 `SKILL_TOOLS` 之后新增一行元组（或并入既有元组）：

```python
#: 站点知识沉淀（2026-11 文献站点知识闭环）：把失败沉淀成 profile notes。
PROFILE_TOOLS = ("profile_record_note",)
```

并把 `"profile_record_note"` 加入 `ALL_BUILTIN_TOOL_NAMES` 所在的组合元组（找到 `ALL_BUILTIN_TOOL_NAMES` 定义处，按其拼装方式追加）。

`backend/tools/permissions.py`：在能力表里加

```python
    "profile_record_note": ToolCapability.WRITE,
```

`backend/tools/tool_bundles.py`：在 `_install_skill` 之后新增一个安装函数并挂进 `BUNDLES`：

```python
def _install_profile(ctx: ToolInstallContext) -> None:
    """站点知识沉淀工具（WRITE，只写用户目录下的 sidecar）。"""
    from .profile_note_tool import ProfileRecordNoteTool

    ctx.registry.register(ProfileRecordNoteTool(policy=ctx.policy))
```

并把 `_install_profile` 加进 `BUNDLES` 元组（顺序会影响 `test_tool_bundles_parity.py` 的快照 —— 追加到元组**末尾**，不要插中间）。

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_profile_note_tool.py \
  backend/tests/unit/test_tool_names.py \
  backend/tests/unit/test_tool_capabilities.py \
  backend/tests/unit/test_tool_bundles_parity.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/tools/profile_note_tool.py backend/tools/tool_bundles.py \
  backend/domain/tool_names.py backend/tools/permissions.py \
  backend/tests/unit/test_profile_note_tool.py
git commit -m "feat(tools): 新增 profile_record_note 沉淀站点经验到 sidecar"
```

---

### Task 16: 文献库枚举与探测（`backend/literature/backends.py` + 工具 + CLI）

**Files:**
- Create: `backend/literature/backends.py`
- Create: `backend/tools/profile_backend_tool.py`
- Modify: `backend/literature/cli.py:78`（`discover-backends` 子命令）
- Modify: `backend/tools/tool_bundles.py` / `backend/domain/tool_names.py` / `backend/tools/permissions.py`（工具登记）
- Test: `backend/tests/unit/test_literature_backends.py`

**Interfaces:**
- Consumes: `backend.literature.models.SiteBackend` / `SiteProfile`；`backend.literature.knowledge.sidecar_path` / `read_sidecar` / `write_sidecar` / `merge_backends`
- Produces:
  - `backends.parse_backend_entries(snapshot: str, base_url: str) -> List[SiteBackend]`（`/dbItem/(\d+)` → id `db{N}`）
  - `backends.classify_probe(text: str) -> Tuple[str, str]`（返回 `(status, reason)`）
  - `backends.probe_backend(entry_url: str, fetch_title: Callable[[str], str], fetch_text: Callable[[str], str]) -> Tuple[str, str]`
  - `profile_backend_tool.ProfileDiscoverBackendsTool`（工具名 `profile_discover_backends`，能力 `WRITE`）
  - CLI：`python -m backend.literature.cli discover-backends --site <id> --snapshot <file> [--entry-url <url>] [--backend-id <id>]`

**背景（spec §6.1 / §6.2 / §6.3 / §6.4）：** 库清单**只能**在登录后枚举（`/dbList/` 未登录返回「您还未登陆」）。枚举是**显式动作**（用户触发），不是全量自动 —— 全量自动会连续触发 WAF。新增的库标 `unknown`，已存在的**保留既有 status**（不覆盖人工判定）。`blocked` 不自动重试。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_backends.py`：

```python
"""文献库枚举与探测（spec §6.2 / §6.3 / §6.4）。"""

import pytest

from backend.literature.backends import (
    classify_probe,
    parse_backend_entries,
    probe_backend,
)

pytestmark = pytest.mark.unit

_SNAPSHOT = """
<a href="/dbItem/3">中国知网</a>
<a href="/dbItem/1">万方</a>
<a href="/dbItem/12">维普</a>
<a href="/other/page">别的</a>
"""


def test_parse_backend_entries_from_snapshot() -> None:
    entries = parse_backend_entries(_SNAPSHOT, "https://demo.example/dbList/")
    ids = [entry.id for entry in entries]
    assert "db3" in ids
    assert "db1" in ids
    assert "db12" in ids
    assert len(entries) == 3
    entry = [item for item in entries if item.id == "db3"][0]
    assert entry.entry_url == "https://demo.example/dbItem/3"
    assert entry.status == "unknown"
    assert entry.label


def test_parse_backend_entries_empty_snapshot() -> None:
    assert parse_backend_entries("", "https://demo.example/dbList/") == []


def test_classify_probe_detects_blocked() -> None:
    status, reason = classify_probe("请拖动滑块完成安全验证")
    assert status == "blocked"
    assert "滑块" in reason


def test_classify_probe_detects_unavailable() -> None:
    status, reason = classify_probe("代理访问失败，请稍后重试")
    assert status == "unavailable"
    assert reason


def test_classify_probe_detects_ready() -> None:
    status, reason = classify_probe("请输入检索关键词")
    assert status == "ready"
    assert reason == ""


def test_classify_probe_defaults_to_unknown() -> None:
    status, _ = classify_probe("一些无法判断的页面内容")
    assert status == "unknown"


def test_probe_backend_uses_classification() -> None:
    status, reason = probe_backend(
        "https://demo.example/dbItem/1",
        lambda url: "检索结果",
        lambda url: "代理访问失败",
    )
    assert status == "unavailable"
    assert reason


def test_probe_backend_blocked_is_never_auto_retried() -> None:
    """blocked 状态必须带原因，便于提示用户人工介入。"""
    status, reason = probe_backend(
        "https://demo.example/dbItem/2",
        lambda url: "安全验证",
        lambda url: "请完成验证码",
    )
    assert status == "blocked"
    assert reason
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_backends.py -q
```

Expected: FAIL —— `ModuleNotFoundError: No module named 'backend.literature.backends'`。

- [ ] **Step 3: 最小实现**

创建 `backend/literature/backends.py`：

```python
"""单站点多检索后端的枚举与探测（spec §6.2 / §6.3 / §6.4）。

库清单**只能在登录态下枚举**（未登录访问库清单页只会拿到「您还未登陆」），
因此枚举是**显式动作**（用户触发 / 首次使用该库时提示），不是全量自动 ——
全量自动会连续触发 WAF。
"""

from __future__ import annotations

import re
from typing import Callable, List, Tuple
from urllib.parse import urljoin

from .models import SiteBackend

#: 库入口路径形如 ``/dbItem/3``。
_DB_ITEM_PATTERN = re.compile(r"[\"'(]?/dbItem/(\d+)")

#: 从 ``<a href=".../dbItem/N">库名</a>`` 里同时取编号与库名。
_ENTRY_LINK_PATTERN = re.compile(
    r"href=[\"'][^\"']*/dbItem/(\d+)[^\"']*[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)

#: 命中即判定为 blocked（站点侧要求人工交互）。
_BLOCKED_TOKENS = ("滑块", "验证码", "人机验证", "拖动", "安全验证")

#: 命中即判定为 unavailable（站点侧直接报错）。
_UNAVAILABLE_TOKENS = ("代理报错", "代理访问失败", "资源已下线", "无法访问", "服务不可用", "不存在")

#: 命中即判定为 ready（检索表单已渲染）。
_READY_TOKENS = ("检索", "关键词", "请输入")


def _clean_label(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    return cleaned.strip()


def parse_backend_entries(snapshot: str, base_url: str) -> List[SiteBackend]:
    """从库清单页快照解析出各库入口。

    Args:
        snapshot: 页面快照文本。
        base_url: 库清单页 URL（用于把相对路径拼成绝对 URL）。

    Returns:
        ``SiteBackend`` 列表；状态一律为 ``unknown``（未探测）。
    """
    text = snapshot or ""
    labels = {
        match.group(1): _clean_label(match.group(2))
        for match in _ENTRY_LINK_PATTERN.finditer(text)
    }

    entries: List[SiteBackend] = []
    seen = set()
    for match in _DB_ITEM_PATTERN.finditer(text):
        number = match.group(1)
        backend_id = f"db{number}"
        if backend_id in seen:
            continue
        seen.add(backend_id)
        entry_url = urljoin(base_url, f"/dbItem/{number}")
        label = labels.get(number, "") or f"库 {number}"
        entries.append(
            SiteBackend(
                id=backend_id,
                label=label,
                entry_url=entry_url,
                status="unknown",
            )
        )
    return entries


def classify_probe(text: str) -> Tuple[str, str]:
    """把探测到的页面文本分类为 ``(status, reason)``。

    判定顺序：blocked → unavailable → ready → unknown。
    """
    content = text or ""
    for token in _BLOCKED_TOKENS:
        if token in content:
            return "blocked", f"触发{token}验证"
    for token in _UNAVAILABLE_TOKENS:
        if token in content:
            return "unavailable", f"站点侧报错：{token}"
    for token in _READY_TOKENS:
        if token in content:
            return "ready", ""
    return "unknown", "未探测"


def probe_backend(
    entry_url: str,
    fetch_title: Callable[[str], str],
    fetch_text: Callable[[str], str],
) -> Tuple[str, str]:
    """探测单个后端；返回 ``(status, reason)``。

    Args:
        entry_url: 后端入口 URL。
        fetch_title: 取页面标题的回调。
        fetch_text: 取页面正文的回调。
    """
    try:
        title = fetch_title(entry_url) or ""
        body = fetch_text(entry_url) or ""
    except Exception:  # noqa: BLE001 — 探测失败按 unknown 处理，不中断枚举
        return "unknown", "探测失败"
    return classify_probe(f"{title}\n{body}")
```

- [ ] **Step 4: 新建 `profile_discover_backends` 工具**

创建 `backend/tools/profile_backend_tool.py`：

```python
"""profile_discover_backends 工具 —— 枚举站点可用文献库（spec §6.2）。

库清单必须在登录态下用浏览器抓取，因此本工具接受**快照文本**而不是自己
导航：模型用 browser_snapshot 拿到清单页快照后传给本工具，本工具负责解析、
与既有 backends 比对（**保留人工判定的 status**）、并写回 sidecar。

能力分类：WRITE（写用户目录下的 backends sidecar）。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.literature.backends import parse_backend_entries
from backend.literature.knowledge import (
    merge_backends,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)
from backend.literature.models import SiteBackend, parse_backends
from backend.literature.profile_store import user_sites_dir

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

PROFILE_DISCOVER_BACKENDS_TOOL_NAME = "profile_discover_backends"


class ProfileDiscoverBackendsTool(BaseTool):
    """枚举站点可用检索后端并写回 sidecar。"""

    risk = RiskClass.WRITE_LOCAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=PROFILE_DISCOVER_BACKENDS_TOOL_NAME,
            description=(
                "枚举站点可用的检索后端（文献库）。先用 browser_snapshot 拿到"
                "库清单页快照，再把快照文本传进来；本工具解析后与既有清单比对，"
                "保留人工判定的状态，写回 backends sidecar。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "site_id": {"type": "string", "description": "目标站点 id"},
                    "snapshot": {
                        "type": "string",
                        "description": "库清单页的快照文本",
                    },
                    "entry_url": {
                        "type": "string",
                        "description": "库清单页 URL（用于拼绝对地址）",
                    },
                    "backend_id": {
                        "type": "string",
                        "description": "只探测这一个后端（可选）",
                    },
                },
                "required": ["site_id", "snapshot"],
            },
        )

    def execute(
        self,
        site_id: str = "",
        snapshot: str = "",
        entry_url: str = "",
        backend_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        """解析库清单并写回 backends sidecar。"""
        site = str(site_id or "").strip()
        if not site:
            return ToolResult(success=False, error="site_id 不能为空")
        if not str(snapshot or "").strip():
            return ToolResult(
                success=False,
                error="snapshot 不能为空（请先用 browser_snapshot 拿库清单页快照）",
            )

        target = sidecar_path(user_sites_dir(), site, "backends")
        existing_raw = read_sidecar(target)
        existing = parse_backends(existing_raw.get("backends"))
        existing_by_id = {backend.id: backend for backend in existing}

        discovered = parse_backend_entries(snapshot, entry_url or "https://")
        wanted = str(backend_id or "").strip()
        if wanted:
            discovered = [item for item in discovered if item.id == wanted]
        merged: List[SiteBackend] = []
        for backend in discovered:
            previous = existing_by_id.get(backend.id)
            if previous is not None:
                # 保留人工判定的 status / reason（spec §6.2）
                merged.append(previous)
            else:
                merged.append(backend)

        write_sidecar(
            target,
            {
                "backends": [
                    {
                        "id": backend.id,
                        "label": backend.label,
                        "entry_url": backend.entry_url,
                        "status": backend.status,
                        "reason": backend.reason,
                        "capabilities": dict(backend.capabilities),
                        "overrides": dict(backend.overrides),
                        "checked_at": backend.checked_at,
                    }
                    for backend in merge_backends(existing, merged)
                ]
            },
        )
        return ToolResult(
            success=True,
            content={
                "site_id": site,
                "discovered": [backend.id for backend in merged],
                "total": len(merged),
            },
        )
```

- [ ] **Step 5: CLI 子命令 `discover-backends`**

改 `backend/literature/cli.py`：在 `_build_parser` 里加子命令，并在 `main` 的分发里加分支：

```python
    discover = subparsers.add_parser(
        "discover-backends", help="枚举站点可用文献库并写回 backends sidecar"
    )
    discover.add_argument("--site", required=True, help="站点 id")
    discover.add_argument("--snapshot", required=True, help="库清单页快照文件路径")
    discover.add_argument("--entry-url", default="", help="库清单页 URL")
    discover.add_argument("--backend-id", default="", help="只探测这一个后端")
```

分发分支（**必须插在 `_dispatch` 里 `run = load_run(Path(args.run))` 那行之前** —— 本子命令没有
`--run`，落到那行会 `AttributeError`；同时沿用既有 `_print` 写 JSON，不要用 `print`，否则触发
ruff `T201`）：

```python
    if args.command == "discover-backends":
        from .backends import parse_backend_entries
        from .knowledge import read_sidecar, sidecar_path, write_sidecar
        from .models import parse_backends
        from .profile_store import user_sites_dir

        snapshot = Path(args.snapshot).read_text(encoding="utf-8")
        discovered = parse_backend_entries(snapshot, args.entry_url or "https://")
        if args.backend_id:
            discovered = [item for item in discovered if item.id == args.backend_id]
        target = sidecar_path(user_sites_dir(), args.site, "backends")
        existing = parse_backends(read_sidecar(target).get("backends"))
        existing_by_id = {backend.id: backend for backend in existing}
        merged = [existing_by_id.get(item.id, item) for item in discovered]
        write_sidecar(
            target,
            {
                "backends": [
                    {
                        "id": backend.id,
                        "label": backend.label,
                        "entry_url": backend.entry_url,
                        "status": backend.status,
                        "reason": backend.reason,
                        "capabilities": dict(backend.capabilities),
                        "overrides": dict(backend.overrides),
                        "checked_at": backend.checked_at,
                    }
                    for backend in merged
                ]
            },
        )
        _print({"ok": True, "path": str(target), "total": len(merged)})
        return 0
```

- [ ] **Step 6: 三处登记新工具**

`backend/domain/tool_names.py`：把 `"profile_discover_backends"` 加入 `PROFILE_TOOLS` 元组与 `ALL_BUILTIN_TOOL_NAMES` 的拼装。

`backend/tools/permissions.py`：加

```python
    "profile_discover_backends": ToolCapability.WRITE,
```

`backend/tools/tool_bundles.py`：**不要改动** Task 15 建立的 `_install_profile`，另建一个函数并
追加到 `BUNDLES` 元组**末尾**（新函数一职责，且末尾追加不会打乱既有 bundle 顺序快照）：

```python
def _install_profile_backends(ctx: ToolInstallContext) -> None:
    """文献库枚举工具（WRITE，只写用户目录下的 backends sidecar）。"""
    from .profile_backend_tool import ProfileDiscoverBackendsTool

    ctx.registry.register(ProfileDiscoverBackendsTool(policy=ctx.policy))
```

- [ ] **Step 7: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_backends.py \
  backend/tests/unit/test_tool_names.py \
  backend/tests/unit/test_tool_capabilities.py \
  backend/tests/unit/test_tool_bundles_parity.py -q
```

Expected: PASS。

- [ ] **Step 8: 提交**

```bash
git add backend/literature/backends.py backend/tools/profile_backend_tool.py \
  backend/literature/cli.py backend/tools/tool_bundles.py \
  backend/domain/tool_names.py backend/tools/permissions.py \
  backend/tests/unit/test_literature_backends.py
git commit -m "feat(literature): 新增文献库枚举探测与 discover-backends CLI"
```

---

### Task 17: Unpaywall —— 合法可得性补充轴（四态 `access_status`）

**Files:**
- Modify: `backend/literature/verify.py`
- Modify: `backend/literature/cli.py`（新增 `verify-access` 子命令 —— 否则 OA 轴无调用方）
- Test: `backend/tests/unit/test_literature_unpaywall.py`

**Interfaces:**
- Consumes:
  - `backend.literature.models.ComplianceSpec.contact_email`（Task 12 已加）
  - `backend.literature.models.PaperRecord`（`paper_key` / `title` / `doi`）
  - `backend.literature.run_store.LiteratureRun` / `list_papers(run)` / `write_json(path, data)`（verify.py 已 import）
  - `backend.literature.cli.main(argv) -> int` / `get_default_store()`（cli.py 已有）
- Produces:
  - `verify.ACCESS_STATUSES: Tuple[str, ...] = ("subscription", "oa", "closed", "unknown")`
  - `verify.merge_access_status(*statuses: str) -> str`
  - `verify.UnpaywallLookup(contact_email: str = "", min_interval_s: float = _UNPAYWALL_MIN_INTERVAL_S)`；属性 `name -> str`、`available -> bool`；方法 `lookup(paper: PaperRecord) -> Optional[Dict[str, Any]]`
  - `verify.build_oa_lookups(profile) -> List[MetadataLookup]` —— **OA 轴**（与元数据轴的 `default_lookups()` 分开）
  - `verify.verify_run_access(run, lookups=None, profile=None) -> Dict[str, Any]` —— 写 `access_verification.json`
  - `lookup()` 返回体字段：`{"access_status": "oa" | "closed", "is_oa": bool, "oa_status": str, "best_oa_url": str}`
  - `cli` 新增子命令 `verify-access --run <dir> [--site <site_id>]` —— 输出 `{"ok": true, "items": [...], "oa": n, "subscription": n, "closed": n, "unknown": n}`

**背景（spec §7.3）：** 现状只有**元数据核验**（Crossref / OpenAlex / SemanticScholar），缺「**全文是否合法可得、哪里可得**」这一轴 —— 正是行业主流（OpenScholar / PaperQA2 / ScienceAI）的做法。Unpaywall **需要真实 email**；取不到时该 lookup 标记为 unavailable 并**不阻断**主链路。**不因 `oa_status` 改变「是否下载付费文献」的行为** —— 下载权限只由站内授权决定。

**四态词汇（spec §7.3）：** `subscription`（站内授权，已拿到全文）/ `oa`（开放获取）/ `closed`（需订阅）/ `unknown`（无记录或查询失败）。合并优先级 `subscription > oa > closed > unknown`。`subscription` 由下载路径产出（Task 10 的 `DownloadResult.access_status`）；本任务产出 `oa` / `closed`，查不到时由 `verify_run_access` 判为 `unknown`。

**OA 轴必须与元数据轴分开：** `default_lookups()` 的返回体会被 `metadata_matches()` 判定题名 / 年份 / 作者；Unpaywall 的返回体没有这些字段，混进去只会污染 `metadata_verification.json`。因此另立 `build_oa_lookups()` 与 `verify_run_access()`，`default_lookups()` **保持原样不动**。

**限流与礼貌（spec §7.3）：** Unpaywall 限额 100k/day（远高于本地用量）；本实现在 lookup **内部**做最小间隔节流（`_UNPAYWALL_MIN_INTERVAL_S = 1.0`），窗口内的重复查询直接跳过、不发请求。spec 同时提到的 arXiv 3s/request、Europe PMC 禁批量抓取、PMC 禁系统性检索 —— **本仓尚无** arXiv / Europe PMC / PMC 的 lookup，按 spec §13 的 YAGNI 原则**不预置死代码**；将来新增这些 lookup 时随实现落地对应约束。

**已知实现约束：** `verify._get_json(url)` 的实际签名是 `(url: str) -> Optional[Dict[str, Any]]`（**没有** `timeout` 形参，超时用模块级 `_TIMEOUT_S`），内部已吞掉 `URLError / OSError / ValueError` 并返回 `None`。因此调用方**不要**传 `timeout=`，也**不要**用 `try/except` 包裹来区分「无记录」与「请求失败」—— 两者都表现为 `None`。`_doi_of(paper)` 读的是 **属性** `paper.doi` / `paper.paper_key`，因此测试必须构造真正的 `PaperRecord`，**不能**传 dict。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_literature_unpaywall.py`：

```python
"""Unpaywall OA 可得性轴（spec §7.3）。"""

import pytest

from backend.literature.models import PaperRecord, profile_from_dict
from backend.literature.verify import (
    ACCESS_STATUSES,
    UnpaywallLookup,
    build_oa_lookups,
    merge_access_status,
)

pytestmark = pytest.mark.unit


def _paper(doi: str = "10.1000/xyz") -> PaperRecord:
    """构造真正的 PaperRecord —— ``_doi_of`` 读属性，不接受 dict。"""
    return PaperRecord(paper_key="doi:" + doi, title="示例题名", doi=doi)


def test_lookup_without_email_is_unavailable() -> None:
    lookup = UnpaywallLookup(contact_email="")
    assert lookup.available is False
    assert lookup.name == "unpaywall"


def test_lookup_with_email_is_available() -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    assert lookup.available is True


def test_lookup_without_doi_returns_none() -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    assert lookup.lookup(PaperRecord(paper_key="cnki:demo", title="无 DOI")) is None


def test_lookup_parses_oa_response(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")

    def fake_get(url):
        return {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {"url_for_pdf": "https://repo.example/paper.pdf"},
        }

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    result = lookup.lookup(_paper("10.1000/xyz"))
    assert result is not None
    assert result["is_oa"] is True
    assert result["oa_status"] == "green"
    assert result["best_oa_url"] == "https://repo.example/paper.pdf"
    assert result["access_status"] == "oa"


def test_lookup_marks_closed_access(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")

    def fake_get(url):
        return {"is_oa": False, "oa_status": "closed"}

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    result = lookup.lookup(_paper("10.1000/abc"))
    assert result is not None
    assert result["is_oa"] is False
    assert result["access_status"] == "closed"


def test_lookup_returns_none_when_service_has_no_record(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    monkeypatch.setattr("backend.literature.verify._get_json", lambda url: None)
    assert lookup.lookup(_paper("10.1000/none")) is None


def test_lookup_skips_second_call_inside_min_interval(monkeypatch) -> None:
    """最小间隔节流：窗口内的重复查询不发请求（spec §7.3 限流与礼貌）。"""
    calls = []

    def fake_get(url):
        calls.append(url)
        return {"is_oa": True, "oa_status": "gold"}

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    lookup = UnpaywallLookup(contact_email="user@example.org", min_interval_s=60.0)
    assert lookup.lookup(_paper("10.1000/one")) is not None
    assert lookup.lookup(_paper("10.1000/two")) is None
    assert len(calls) == 1


def _profile(contact_email: str = "") -> object:
    raw = {
        "id": "demo",
        "display_name": "演示站",
        "home_url": "https://demo.example",
        "domains": ["demo.example"],
        "search": {
            "url_template": "https://demo.example/s?q={query}",
            "mode": "url",
            "submit_key": "Enter",
            "result_hint": "",
        },
    }
    if contact_email:
        raw["compliance"] = {"contact_email": contact_email}
    return profile_from_dict(raw)


def test_merge_access_status_prefers_subscription() -> None:
    assert merge_access_status("oa", "subscription") == "subscription"
    assert merge_access_status("closed", "oa") == "oa"
    assert merge_access_status("closed", "unknown") == "closed"
    assert merge_access_status() == "unknown"


def test_access_status_vocabulary_is_shared_with_download_path() -> None:
    """四态词汇由 verify 独占；下载路径用的是同一套字面量（spec §7.3）。"""
    from backend.literature.search import DownloadResult

    assert set(ACCESS_STATUSES) == {"subscription", "oa", "closed", "unknown"}
    assert DownloadResult(path=None, ok=False).access_status == "unknown"
    assert "subscription" in ACCESS_STATUSES


def test_build_oa_lookups_is_empty_without_email() -> None:
    assert build_oa_lookups(_profile()) == []


def test_build_oa_lookups_includes_unpaywall_with_email() -> None:
    lookups = build_oa_lookups(_profile("user@example.org"))
    assert [item.name for item in lookups] == ["unpaywall"]
    assert lookups[0].available is True


def test_oa_axis_does_not_pollute_metadata_axis() -> None:
    """OA 轴与元数据轴分开 —— 混进 default_lookups() 会污染核验报告。"""
    from backend.literature.verify import default_lookups

    names = {item.name for item in default_lookups()}
    assert "unpaywall" not in names
    assert names == {"crossref", "openalex", "semanticscholar"}


def test_verify_run_access_writes_report(tmp_path, monkeypatch) -> None:
    from backend.literature.run_store import create_run, record_papers
    from backend.literature.verify import verify_run_access

    monkeypatch.setattr(
        "backend.literature.verify._get_json",
        lambda url: {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {"url_for_pdf": "https://repo.example/p.pdf"},
        },
    )
    run = create_run(tmp_path, "t", "demo", run_id="r1")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    report = verify_run_access(run, profile=_profile("user@example.org"))
    assert report["items"][0]["access_status"] == "oa"
    assert report["items"][0]["best_oa_url"] == "https://repo.example/p.pdf"
    assert (run.run_dir / "access_verification.json").is_file()


def test_verify_run_access_without_email_marks_unknown(tmp_path) -> None:
    from backend.literature.run_store import create_run, record_papers
    from backend.literature.verify import verify_run_access

    run = create_run(tmp_path, "t", "demo", run_id="r2")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    report = verify_run_access(run, profile=_profile())
    assert report["items"][0]["access_status"] == "unknown"


def test_cli_verify_access_command(tmp_path, capsys) -> None:
    """CLI 入口可达：``--site`` 省略时不配 OA 轴，全部判为 unknown。"""
    import json as _json

    from backend.literature.cli import main
    from backend.literature.run_store import create_run, record_papers

    run = create_run(tmp_path, "t", "demo", run_id="r3")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    code = main(["verify-access", "--run", str(run.run_dir)])
    assert code == 0
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is True
    assert payload["items"][0]["access_status"] == "unknown"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_unpaywall.py -q
```

Expected: FAIL —— `ImportError: cannot import name 'UnpaywallLookup'`。

- [ ] **Step 3: 最小实现**

改 `backend/literature/verify.py`（三处）：顶部补 `import time` 与 `Tuple`；模块常量区追加 `_UNPAYWALL_MIN_INTERVAL_S` / `ACCESS_STATUSES` / `merge_access_status`；文件末尾追加 `UnpaywallLookup` / `build_oa_lookups` / `verify_run_access`：

```python
class UnpaywallLookup:
    """Unpaywall 全文可得性查询（spec §7.3）。

    端点：``https://api.unpaywall.org/v2/{doi}?email=...``。
    **需要真实 email** —— 服务硬性要求。取不到 email 时本 lookup 标记为
    unavailable，**不阻断**主链路（元数据核验照常）。

    本 lookup 只回答「哪里能合法拿到全文」，**不改变**「是否下载付费文献」
    的行为 —— 下载权限只由站内授权决定。

    限流与礼貌：Unpaywall 限额 100k/day（远高于本地用量）；本类内部做
    最小间隔节流 —— 窗口内的重复查询直接返回 ``None``，不发请求。
    """

    name = "unpaywall"

    def __init__(
        self,
        contact_email: str = "",
        min_interval_s: float = _UNPAYWALL_MIN_INTERVAL_S,
    ) -> None:
        self._email = str(contact_email or "").strip()
        self._min_interval_s = float(min_interval_s)
        self._last_request_at: Optional[float] = None

    @property
    def available(self) -> bool:
        """没有 email 就不可用 —— 但不影响主链路。"""
        return bool(self._email)

    def lookup(self, paper: PaperRecord) -> Optional[Dict[str, Any]]:
        """查询一篇文献的 OA 状态；查不到返回 ``None``。

        ``_get_json`` 内部已吞掉网络异常并返回 ``None``，因此「无记录」与
        「请求失败」在这里都表现为 ``None``，由调用方判为 ``unknown``。
        """
        if not self.available:
            return None
        doi = _doi_of(paper)
        if not doi:
            return None
        now = time.monotonic()
        if (
            self._last_request_at is not None
            and (now - self._last_request_at) < self._min_interval_s
        ):
            return None
        self._last_request_at = now
        url = f"https://api.unpaywall.org/v2/{doi}?email={self._email}"
        payload = _get_json(url)
        if not isinstance(payload, dict):
            return None

        is_oa = bool(payload.get("is_oa"))
        best = payload.get("best_oa_location") or {}
        best_url = ""
        if isinstance(best, dict):
            best_url = str(best.get("url_for_pdf") or best.get("url") or "")
        return {
            "access_status": "oa" if is_oa else "closed",
            "is_oa": is_oa,
            "oa_status": str(payload.get("oa_status") or ""),
            "best_oa_url": best_url,
        }


def build_oa_lookups(profile: Any) -> List[MetadataLookup]:
    """按 profile 组装 **OA 轴** 的 lookup 列表。

    与元数据轴的 ``default_lookups()`` **分开**：OA lookup 的返回体没有
    题名 / 年份 / 作者，混进元数据核验只会污染 ``metadata_verification.json``。

    Unpaywall 需要 profile 的 ``compliance.contact_email``；缺失时返回空列表
    —— **不阻断**主链路。
    """
    email = ""
    compliance = getattr(profile, "compliance", None)
    if compliance is not None:
        email = str(getattr(compliance, "contact_email", "") or "")
    if not email:
        return []
    return [UnpaywallLookup(contact_email=email)]


def verify_run_access(
    run: LiteratureRun,
    lookups: Optional[Sequence[MetadataLookup]] = None,
    profile: Any = None,
) -> Dict[str, Any]:
    """对运行目录全部文献跑 OA 轴，写 ``access_verification.json``。

    每篇文献给出四态之一的 ``access_status`` 与 ``best_oa_url``；
    查不到 / 未配置 email 时统一为 ``unknown`` —— **不阻断**主链路。
    """
    if lookups is None:
        lookups = build_oa_lookups(profile) if profile is not None else []
    lookups = list(lookups)
    items: List[Dict[str, Any]] = []
    for paper in list_papers(run):
        statuses: List[str] = []
        best_url = ""
        for lookup in lookups:
            candidate = lookup.lookup(paper)
            if not candidate:
                continue
            status = str(candidate.get("access_status") or "unknown")
            if status in ACCESS_STATUSES:
                statuses.append(status)
            best_url = best_url or str(candidate.get("best_oa_url") or "")
        items.append(
            {
                "paper_key": paper.paper_key,
                "access_status": merge_access_status(*statuses),
                "best_oa_url": best_url,
            }
        )
    report = {
        "items": items,
        "oa": sum(1 for item in items if item["access_status"] == "oa"),
        "subscription": sum(
            1 for item in items if item["access_status"] == "subscription"
        ),
        "closed": sum(1 for item in items if item["access_status"] == "closed"),
        "unknown": sum(1 for item in items if item["access_status"] == "unknown"),
    }
    write_json(run.run_dir / "access_verification.json", report)
    return report
```

同时在 `verify.py` 顶部补两处导入 / 常量：

```python
import time
# typing 行补上 Tuple：
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple
```

并在模块常量区（`_TIMEOUT_S` 之后）追加：

```python
#: Unpaywall 的礼貌间隔（秒）—— 窗口内的重复查询直接跳过，不发请求。
_UNPAYWALL_MIN_INTERVAL_S = 1.0

#: 全文可得性四态（spec §7.3）。
#: ``subscription`` = 站内授权已拿到全文；``oa`` = 开放获取；
#: ``closed`` = 需订阅；``unknown`` = 无记录或查询失败。
ACCESS_STATUSES: Tuple[str, ...] = ("subscription", "oa", "closed", "unknown")

#: 合并优先级 —— 站内授权 > 开放获取 > 需订阅 > 未知。
_ACCESS_STATUS_PRIORITY = ACCESS_STATUSES


def merge_access_status(*statuses: str) -> str:
    """合并多个来源的 ``access_status``，取优先级最高者。"""
    for candidate in _ACCESS_STATUS_PRIORITY:
        if candidate in statuses:
            return candidate
    return "unknown"
```

> `default_lookups()` **保持原样不动** —— OA 轴走 `build_oa_lookups()`。
> `_get_json(url)` 只有一个位置参数，**不要**传 `timeout=`；它内部已用模块级
> `_TIMEOUT_S` 并吞掉网络异常返回 `None`。

**(d) CLI 接线 —— 让 OA 轴有调用方**

`verify_run_access()` 若只有 Python API 而无入口，就是死代码。改
`backend/literature/cli.py`（三处）：

导入行补一个名字：

```python
from .verify import (
    apply_evidence_support,
    default_lookups,
    verify_run_access,
    verify_run_metadata,
)
```

在 `_build_parser()` 里（与既有 `verify-metadata` 子命令并列）新增：

```python
verify_access = sub.add_parser("verify-access", help="全文可得性（OA 轴）核验")
verify_access.add_argument("--run", required=True, help="运行目录")
verify_access.add_argument("--site", default="", help="站点 ID（提供时才装配 OA 轴）")
```

在 `_dispatch(args)` 里（`run = load_run(Path(args.run))` 之后、既有 `verify-metadata` 分支旁）新增分支
（`verify-access` 自带 `--run`，所以放在 `load_run` 之后是安全的 —— 与 Task 16 的 `discover-backends`
不同）：

```python
if args.command == "verify-access":
    profile = get_default_store().get(args.site) if args.site else None
    report = verify_run_access(run, profile=profile)
    _print({"ok": True, **report})
    return 0
```

> `--site` 省略 ⇒ `profile=None` ⇒ `build_oa_lookups()` 不装配 ⇒ 全部判为
> `unknown`。这让 CLI 测试**不依赖用户级 profile 存储**（`~/.sage/literature_sites/`）。
> `get_default_store().get(args.site)` 找不到站点时抛 `SiteProfileError`
> （`ValueError` 子类），已被 `main()` 既有的 `except (ValueError, OSError)` 捕获 →
> 输出 `{"ok": false, "error": ...}` 并返回 1，**无需**额外错误处理。
> `_print` 是 cli.py 已有的 JSON 输出辅助函数，沿用即可。

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_unpaywall.py \
  backend/tests/unit/test_literature_claims.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/literature/verify.py backend/literature/cli.py \
  backend/tests/unit/test_literature_unpaywall.py
git commit -m "feat(literature): 新增 Unpaywall OA 可得性轴（无 email 时不阻断主链路）"
```

---

### Task 18: 文档、用户级脚本、棘轮、旧计划标注与归档

**Files:**
- Create: `docs/templates/skills/literature-helper/scripts/parse_interstitial.py`
- Create: `docs/technical/180-literature-site-knowledge.md`
- Modify: `docs/technical/README.md`（章节目录加一行）
- Modify: `backend/skills/skill_md/shipped/literature-research/SKILL.md`（补三节）
- Modify: `docs/plans/2026-11-21_literature-research-paper-pipeline.md:383-391`（标注承接）
- Modify: `architecture-baseline.json`（补实测行数）
- Delete: `docs/plans/2026-11-28_literature-site-knowledge-and-http-fastpath.md`（本计划文件）

**Interfaces:**
- Consumes: 前序任务的全部产出
- Produces: 面向用户的技能说明 + 技术文档 + 归档

- [ ] **Step 1: 新建用户级脚本模板**

创建 `docs/templates/skills/literature-helper/scripts/parse_interstitial.py`：

```python
#!/usr/bin/env python3
"""中间页解析脚本（用户级技能模板）。

职责**限于确定性、无副作用判断**的动作：读中间页 HTML、提取 downurl、
按 fallback 规则生成候选 URL。**不做**：决定是否下载（合规判断须留在
agent 侧）、登录、限速豁免（spec §7.2）。

用法::

    python parse_interstitial.py --html intermediate.html \\
        --fallback kns.cnki.net --fallback oversea.cnki.net

输出 JSON::

    {"candidates": ["https://.../a", "https://.../b"]}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

#: 仓库根 —— 供「从仓库内 import 公共模块」的路径兜底。
SAGE_REPO_ROOT = "/home/fz/project/sage"


def _load_interstitial_module():
    """尽量复用仓库内的 interstitial 模块；不可用时退回本地实现。"""
    root = Path(SAGE_REPO_ROOT)
    if (root / "backend" / "literature" / "interstitial.py").is_file():
        sys.path.insert(0, str(root))
        try:
            from backend.literature.interstitial import (  # type: ignore[import-not-found]
                parse_download_url,
                rewrite_host_candidates,
            )

            return parse_download_url, rewrite_host_candidates
        except ImportError:
            pass

    import re
    from urllib.parse import urlsplit, urlunsplit

    pattern = re.compile(r"var\s+downurl\s*=\s*['\"]([^'\"]+)['\"]")

    def parse_download_url(html: str) -> List[str]:
        return [match.group(1).strip() for match in pattern.finditer(html or "")]

    def rewrite_host_candidates(url: str, fallbacks) -> List[str]:
        parts = urlsplit(url)
        candidates = [
            urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
            for host in (fallbacks or ())
        ]
        candidates.append(url)
        return candidates

    return parse_download_url, rewrite_host_candidates


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="解析中间页并生成候选下载地址")
    parser.add_argument("--html", required=True, help="中间页 HTML 文件路径")
    parser.add_argument("--fallback", action="append", default=[], help="主机回退（可重复）")
    args = parser.parse_args(argv)

    html = Path(args.html).read_text(encoding="utf-8", errors="replace")
    parse_download_url, rewrite_host_candidates = _load_interstitial_module()
    urls = parse_download_url(html)

    candidates: List[str] = []
    for url in urls:
        for candidate in rewrite_host_candidates(url, args.fallback):
            if candidate not in candidates:
                candidates.append(candidate)

    print(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**落地位置（spec §7.2）：** 上面的文件只是**工厂模板**（`docs/templates/skills/` **不被运行时加载**，与 `docs/templates/literature-sites/` 同理）。真正生效的位置是**用户级技能目录**：

```
~/.sage/skills/literature-helper/scripts/parse_interstitial.py
```

安装方式（写入用户技能目录后由 `ScriptRunner` 在 `allowed_roots` 内执行）：

```bash
mkdir -p ~/.sage/skills/literature-helper/scripts
cp docs/templates/skills/literature-helper/scripts/parse_interstitial.py \
   ~/.sage/skills/literature-helper/scripts/
```

`ScriptRunner` 的沙箱边界**不动** —— shipped 仍被排除；用户级脚本在允许根内。脚本职责**限于确定性、无副作用判断**的动作（读中间页 HTML、提取 `downurl`、按 fallback 规则生成候选 URL、比对 magic）；**不做**：决定是否下载（合规判断须留在 agent 侧）、登录、限速豁免。

- [ ] **Step 2: SKILL.md 补三节**

改 `backend/skills/skill_md/shipped/literature-research/SKILL.md`，追加：

```markdown
## HTTP 快路径（下载优先走 HTTP）

检索页必须用浏览器（JS 渲染 + WAF，不可 HTTP 化）。**下载**可以走 HTTP：

1. 浏览器读结果行的元素 href —— 用 `browser_interact action=attr attr_name=href`，
   不要用快照里被截断的 URL。
2. `browser_cookies action=export` 把登录态写入 vault。
3. HTTP 取 `doDownload` 入口（带 Referer）→ 解析中间页的 `downurl` →
   按 profile 的 `pdf.interstitial.host_fallbacks` 换主机 → 下载并校验 magic + 题名。
4. HTTP 失败**自动回退浏览器路径一次**，并在 `query_log` 记 `fallback_reason`。

## 经验沉淀（把坑点固化下来）

一次失败且根因已定位时，调用 `profile_record_note` 把经验写进 profile 的
`notes` sidecar。下次运行时该经验会自动出现在检索指导文本的「站点经验」段里
（按严重度排序，blocker 在前）—— 不用重蹈覆辙。

## 文献库枚举（多后端）

站点的可用文献库在 `profile.backends` 里；`status` 取值：
`ready`（可用）/ `blocked`（需人工完成滑块或验证码，**不自动重试**，请用户在
可见窗口操作）/ `unavailable`（站点侧报错）/ `unknown`（未探测）。

库清单**只能在登录态下枚举**：用 `browser_snapshot` 拿库清单页快照，再调用
`profile_discover_backends` 解析并写回 `backends` sidecar。已存在的条目**保留**
人工判定的状态。
```

- [ ] **Step 3: 新建技术文档**

创建 `docs/technical/180-literature-site-knowledge.md`（2026-11-28 于本 worktree 实测 `docs/technical/` 最大编号为 179，故取 180；合并前若被其他 PR 抢占则整体顺延）：

```markdown
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
```

- [ ] **Step 4: 在 `docs/technical/README.md` 加目录行**

在章节目录表格末尾追加一行（编号与上一步一致）：

```markdown
| 180 | [文献站点知识沉淀与 HTTP 快路径](./180-literature-site-knowledge.md) | profile `notes[]`/`backends[]` + `references/` 接线 + 下载 HTTP 快路径与合规闸门 |
```

- [ ] **Step 5: 标注旧计划的承接关系**

改 `docs/plans/2026-11-21_literature-research-paper-pipeline.md` 第 383-391 行的 M0 未勾选项，在该小节标题下加一行承接说明：

```markdown
> **承接说明（2026-11-28）**：以下 M0 项已由
> `docs/superpowers/specs/2026-11-28-literature-site-knowledge-and-http-fastpath-design.md`
> 及其配套实施计划承接（HTTP 快路径 / 多后端 / 经验沉淀 / OA 轴），本计划不再重复实现。
```

- [ ] **Step 6: 实测行数并更新 `architecture-baseline.json`**

在**本分支**实测所有新增/修改的 Python 文件行数：

```bash
cd /home/fz/project/sage/.worktrees/feat-literature-site-knowledge
for f in \
  backend/tools/skill_resource_tool.py \
  backend/tools/http_site_gate.py \
  backend/tools/profile_note_tool.py \
  backend/tools/profile_backend_tool.py \
  backend/services/http_rate_limit.py \
  backend/literature/interstitial.py \
  backend/literature/http_download.py \
  backend/literature/knowledge.py \
  backend/literature/backends.py \
  backend/literature/models.py \
  backend/literature/guidance.py \
  backend/literature/profile_store.py \
  backend/literature/run_store.py \
  backend/literature/search.py \
  backend/literature/verify.py \
  backend/literature/cli.py \
  backend/tools/execute_code_tool.py \
  backend/tools/browser_tool.py \
  backend/tools/web_tool.py \
  backend/tools/download_tool.py \
  backend/skills/skill_md/resources.py \
  backend/skills/skill_md/auto_activation.py ; do
  printf '%s %s\n' "$f" "$(wc -l < "$f")"
done
```

把实测值填进 `architecture-baseline.json` 的 `files` 字典（**只增不减**，保留既有条目）。win7 分支的基线在 Task 19 里于 win7 worktree **单独实测**后写入。

- [ ] **Step 7: 全量回归**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/
```

Expected: 全绿、ruff 干净。

- [ ] **Step 8: 提交（不含本计划文件）**

```bash
git add docs/templates/skills/literature-helper/scripts/parse_interstitial.py \
  docs/technical/180-literature-site-knowledge.md docs/technical/README.md \
  backend/skills/skill_md/shipped/literature-research/SKILL.md \
  docs/plans/2026-11-21_literature-research-paper-pipeline.md \
  architecture-baseline.json
git commit -m "docs(literature): 站点知识与 HTTP 快路径技术文档 + 技能说明 + 棘轮基线"
```

- [ ] **Step 9: 归档本计划（删除计划文件）**

项目规则（`feature-development.md`）：功能完成后把内容并入 `docs/technical/` 并**直接删除**计划文件。

```bash
git rm docs/plans/2026-11-28_literature-site-knowledge-and-http-fastpath.md
git commit -m "docs(plans): 文献站点知识计划已并入技术文档并归档"
```

---

### Task 19: 双分支同步（win7 先、main 后）

**Files:**
- Modify: 全部前序任务的文件（在 win7 worktree 里 cherry-pick 后适配）

**Interfaces:**
- Consumes: main 分支上 T1–T18 的全部 commit
- Produces: `release/win7` 与 `main` 各一个 PR

**背景（项目 CLAUDE.md + spec §11）：** 跨分支**只走 cherry-pick**，**先合 win7 再合 main**。win7 是 py3.8 / pydantic 1.x。

- [ ] **Step 1: 建 win7 worktree**

```bash
cd /home/fz/project/sage
scripts/worktree.sh new feat/literature-site-knowledge-win7 --base origin/release/win7
```

（若 `scripts/worktree.sh` 的 `--base` 需要先 fetch：`git fetch origin release/win7` 再执行。）

- [ ] **Step 2: 逐个 cherry-pick**

在 win7 worktree 内按提交顺序 cherry-pick T1–T18 的每个 commit：

```bash
cd <win7-worktree>
git log --oneline origin/main..feat/literature-site-knowledge --reverse
# 逐个：
git cherry-pick <sha1> <sha2> ...
```

- [ ] **Step 3: 按 py38 适配表逐项核对**

| 位置 | main 写法 | win7 写法 |
|---|---|---|
| `backend/literature/models.py` | `list[str]` / `dict[str, Any]` | `List[str]` / `Dict[str, Any]` |
| `backend/literature/knowledge.py` | `list[str]` 注解 | `List[str]` |
| `backend/tools/skill_resource_tool.py` | `str | None` | `Optional[str]` |
| `backend/literature/backends.py` | `Tuple[str, str]` | `Tuple[str, str]`（3.8 支持） |
| `isinstance(x, (a, b))` | tuple 形式 | tuple 形式 + `# noqa: UP038 — py38 兼容` |
| `datetime.now(timezone.utc)` | 直接调用 | `datetime.now(timezone.utc)  # noqa: UP017 — py38 兼容` |

**跑一次 ruff 找 UP006/UP007/UP017/UP038 违规**：

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m ruff check backend/
```

- [ ] **Step 4: win7 侧测试**

```bash
cd <win7-worktree>
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit -q
```

Expected: 全绿（若出现与本分支无关的既有失败，以 `git stash` 前的基线为准比对）。

- [ ] **Step 5: win7 侧单独实测基线并更新 `architecture-baseline.json`**

在 **win7 worktree** 内重复 Task 18 Step 6 的实测命令，把 win7 分支的实测值写进 win7 的 `architecture-baseline.json`（**两个分支的基线独立**，不要把 main 的数值复制过去）。

- [ ] **Step 6: 推 win7 分支并开 PR**

```bash
git push -u origin feat/literature-site-knowledge-win7
gh pr create --base release/win7 --title "feat(literature): 站点知识沉淀与 HTTP 快路径（win7）" \
  --body "$(cat <<'EOF'
## 内容
- 站点知识模型扩展：profile `notes[]` / `backends[]`
- `skill_read_resource` 工具 + `references/` 接线
- PDF 下载 HTTP 快路径 + 站点策略闸门 + per-host 限速器
- 文献库枚举探测 + `profile_record_note` 沉淀闭环 + Unpaywall OA 轴
- 修复三个既有缺陷：BROWSER_TOOL_NAMES 漂移 / credential_set 文案 / execute_code RPC 白名单

## 测试计划
- [x] `pytest backend/tests/unit -q`（py3.8 环境全绿）
- [x] `ruff check backend/` 干净
- [x] 行数基线按 win7 分支实测更新

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

等 CI 绿：

```bash
gh pr checks <pr-number> --watch
```

- [ ] **Step 7: 合 win7 PR**

用户确认后合并（**squash merge**）。合并后清理：

```bash
git push origin --delete feat/literature-site-knowledge-win7
```

**严禁**删除或 force-push `release/win7` 分支本身。

- [ ] **Step 8: 推 main 分支并开 PR**

```bash
cd /home/fz/project/sage/.worktrees/feat-literature-site-knowledge
git push -u origin feat/literature-site-knowledge
gh pr create --base main --title "feat(literature): 站点知识沉淀与 HTTP 快路径" \
  --body "$(cat <<'EOF'
## 内容
（与 win7 PR 相同）

## 与 release/win7 的关系
本 PR 的实现先在 `release/win7` 上 cherry-pick 并适配 py3.8 后合并，再合入 main。

## 测试计划
- [x] `pytest backend/tests/unit -q` 全绿
- [x] `ruff check backend/` 干净
- [ ] 真机 E2E：HTTP 路径落盘的 PDF 通过 magic + 题名校验（需用户在可见窗口完成登录）

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks <pr-number> --watch
```

- [ ] **Step 9: 更新记忆与索引**

更新 `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-literature-site-knowledge-http-fastpath.md`：
把「阶段」改为已完成，写入两个分支的合并 commit 与 PR 号；并在 `MEMORY.md` 的索引行更新状态。

- [ ] **Step 10: 清理 worktree**

```bash
cd /home/fz/project/sage
git worktree remove .worktrees/feat-literature-site-knowledge
git worktree prune
```

---

## 附录 A：任务依赖图

```
T1 (B3) ─┐
T2 (B2) ─┼─→ (无依赖，可并行)
T3 (B1) ─┘

T4 (skill_read_resource) ─→ T5 (references 接线)
T6 (站点事实泛化)          ← 依赖 T4/T5 的产物被扫描（可并行做）

T7 (interstitial) ─→ T10 (http_download) ─→ T11 (query_log)
T8 (rate_limit)  ────────────────↑
T9 (site_gate)   ────────────────┘

T12 (models) ─→ T13 (knowledge/sidecar) ─→ T14 (guidance)
                              ├→ T15 (profile_record_note)
                              └→ T16 (backends 枚举探测)
T17 (Unpaywall) ← T12（需要 compliance.contact_email）

T18 (文档/脚本/棘轮/归档) ← 全部前序
T19 (双分支同步) ← T18
```

**并行提示**：T1/T2/T3 可并行；T4+T6 可并行；T7+T8 可并行；T12 完成后 T13/T14/T15/T16/T17 可并行。

## 附录 B：验收对照表（spec §14）

| # | spec 验收条件 | 对应任务 | 可执行验证 |
|---|---|---|---|
| 1 | `references/pipeline.md` 可被 `skill_read_resource` 读到，且自动激活时出现在资源清单 | T4, T5 | `test_skill_read_resource_tool.py::test_read_pipeline_reference_returns_content`、`::test_auto_activation_manifest_lists_pipeline_reference` |
| 2 | README 与 SKILL.md 不再含站点具体事实 | T6 | `test_literature_no_site_literals.py` |
| 3 | `BROWSER_TOOL_NAMES` 与 `tool_names.BROWSER_TOOLS` 集合相等且有 CI 断言 | T1 | `test_browser_tool_names_parity.py` |
| 4 | `credential_set` 不再出现在任何用户可见文案 | T2 | `test_credential_error_text.py` |
| 5 | HTTP 下载被站点策略覆盖，限速真实生效 | T8, T9, T10 | `test_http_site_gate.py`、`test_http_rate_limit.py`、`test_literature_http_download.py` |
| 6 | `profile.rate_limit` 不再只是文本，有可验证执行点 | T8 | `test_http_rate_limit.py::test_floor_is_enforced_even_when_profile_writes_zero` |
| 7 | 一个 profile 能表达 ≥3 个检索后端及各自状态 | T12, T16 | `test_literature_site_knowledge.py::test_backends_are_parsed`（3 个条目）、`test_literature_backends.py::test_parse_backend_entries_from_snapshot`（3 个库） |
| 8 | 一次失败能被记成一条 `notes`，并在下次指导文本里出现 | T13, T14, T15 | `test_profile_note_tool.py::test_record_note_writes_sidecar`、`test_literature_guidance.py::test_notes_section_lists_notes_sorted_by_severity` |
| 9 | `UnpaywallLookup` 配置 email 时返回 `best_oa_url`，未配置不影响主链路 | T17 | `test_literature_unpaywall.py` |
| 10 | 真机 E2E：HTTP 路径 PDF 通过 magic + 题名校验，耗时显著低于浏览器路径 | T19 Step 8 | 真机手动（需用户在可见窗口登录）—— 在 PR 里勾选前由用户执行 |
