# 浏览器多账号管理设计文档

> **日期**：2026-11-20
> **状态**：草案
> **分支**：feat/browser-multi-account
> **基线**：release/win7 (f02321c7e)

---

## 1. 背景与目标

### 1.1 问题

Sage 当前的浏览器登录系统（`browser_login` + `credential_vault`）按域名存储凭据，一个域名只能保存一个账号的登录态。重新登录同域名会覆盖上一个账号的 cookies。这导致以下场景无法实现：

- **串行接力**：一个网页流程需要多个用户账号按顺序完成不同步骤（如审批链、多人协作表单）
- **并行操作**：同时维护多个同站账号，在不同任务中使用不同账号
- **AI 代理智能切换**：AI 在执行浏览器任务时根据需要自动识别并切换账号

### 1.2 目标

| 目标 | 说明 |
|------|------|
| G1 | 同一网站支持多个命名账号共存，凭据互不覆盖 |
| G2 | 账号切换通过 CDP 注入/快照 cookies + localStorage，毫秒级无感切换 |
| G3 | AI 代理可通过工具调用切换账号（实时确认）或规划接力流程后批量执行 |
| G4 | 用户可在设置页预设账号池，也可在登录流程中随时新增并命名 |
| G5 | 向后兼容：现有单账号凭据自动迁移为 `default` 账号 |

### 1.3 非目标

- 不做指纹级隔离（不需要防反关联）
- 不做多浏览器进程并行（方案 A 为单实例 cookie swap）
- 不做跨机器账号同步

---

## 2. 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (UI)                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ 账号池管理   │  │ 登录时命名    │  │ AI 切换提示 │  │
│  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘  │
└─────────┼────────────────┼────────────────┼─────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────┐
│              Backend API Layer                       │
│  POST /api/v1/browser-accounts  (创建)              │
│  GET  /api/v1/browser-accounts  (列表)              │
│  PUT  /api/v1/browser-accounts/{id} (编辑)          │
│  DELETE /api/v1/browser-accounts/{id} (删除)        │
│  POST /api/v1/browser-accounts/switch (切换)        │
│  POST /api/v1/browser-accounts/login  (带账号登录)  │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              BrowserAccountService                   │
│  - 账号注册表 CRUD                                    │
│  - 切换编排：save_current → load_target              │
│  - 登录关联：login → capture → save to account       │
└──────┬───────────────────────────────┬──────────────┘
       │                               │
       ▼                               ▼
┌──────────────────┐    ┌─────────────────────────────┐
│ account_registry │    │  credential_vault (扩展)     │
│ (新 SQLite 表)    │    │  key: domain:account_id     │
│                  │    │  支持同域名多条目             │
└──────────────────┘    └─────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────┐
│              Browser CDP Layer                       │
│  Network.getCookies / Network.setCookies            │
│  DOMStorage.getDOMStorageItems / setDOMStorageItem   │
│  Page.reload (切换后刷新页面使新凭据生效)             │
└─────────────────────────────────────────────────────┘
```

---

## 3. 数据模型

### 3.1 账号注册表（新增 SQLite 表）

```sql
CREATE TABLE IF NOT EXISTS browser_accounts (
    id TEXT PRIMARY KEY,           -- UUID v4
    label TEXT NOT NULL,           -- 用户可见的账号名称，如"张三的工作号"
    domain TEXT NOT NULL,          -- 关联的域名，如 ".cnki.net"
    color TEXT,                    -- 可选颜色标签（UI 区分用）
    notes TEXT,                    -- 备注
    is_default INTEGER DEFAULT 0,  -- 该域名下的默认账号
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(label, domain)          -- 同域名下账号名不重复
);
```

**设计决策**：
- `domain` 与 credential_vault 的 domain key 对齐（如 `.cnki.net`）
- `label` 在同域名下唯一，方便用户识别
- `is_default`：每个域名最多一个默认账号，向后兼容现有单账号场景
- `color`：可选的颜色标签，用于 UI 快速区分（参考 Firefox Containers 的彩色标签）

### 3.2 Credential Vault 重构

**现状**：`vault: { domain: CredentialEntry }` — 每域名一条

**目标**：`vault: { "domain:account_id": CredentialEntry }` — 每域名每账号一条

**迁移策略**：
1. 启动时检测旧格式条目（key 中无 `:` 分隔符或第二段不是 UUID）
2. 自动为每个旧条目创建一条 `browser_accounts` 记录（label="默认账号"，is_default=1）
3. 将旧 key `domain` 重命名为 `domain:account_id`
4. 迁移在 `_VAULT_LOCK` 内原子完成，保证并发安全

**向后兼容**：
- `load_credential(domain)` 等旧 API 保留，自动解析为该 domain 的 default account
- 新增 `load_credential_for_account(domain, account_id)` 显式指定账号
- `find_credential_for_host()` 默认返回该域名下 is_default=1 的账号凭据

### 3.3 CredentialEntry 扩展

现有 `CredentialEntry` 新增字段：

```python
{
    "kind": "cookie",
    "account_id": "uuid-v4",        # 新增：关联的账号 ID
    "account_label": "张三的工作号",  # 新增：冗余存储，方便 list 展示
    "cookies_enc": "enc:...",
    "saved_at": 1732089600000,
    "updated_at": 1732089600000,
    "source_profile": "login-default",
    "origins_enc": "enc:...",
    "storage_saved_at": 1732089600000,
}
```

---

## 4. 核心组件

### 4.1 BrowserAccountService

新增服务：`backend/services/browser_account_service.py`

```python
class BrowserAccountService:
    """管理浏览器多账号的注册、切换、登录关联。"""

    def __init__(self, repo: SettingsRepository):
        self._repo = repo
        self._lock = threading.Lock()
        # 当前活跃账号（按 browser_id 追踪，进程内状态）
        self._active: dict[str, str] = {}  # browser_id → account_id

    # ── 账号 CRUD ──

    def create_account(
        self, label: str, domain: str,
        color: str | None = None, notes: str | None = None,
        is_default: bool = False
    ) -> BrowserAccount: ...

    def list_accounts(
        self, domain: str | None = None
    ) -> list[BrowserAccount]: ...

    def get_account(self, account_id: str) -> BrowserAccount | None: ...

    def update_account(
        self, account_id: str,
        label: str | None = None,
        color: str | None = None,
        notes: str | None = None,
        is_default: bool | None = None
    ) -> BrowserAccount: ...

    def delete_account(self, account_id: str) -> bool: ...

    # ── 切换 ──

    def switch_account(
        self,
        target_account_id: str,
        browser_session: BrowserSession | None = None,
    ) -> SwitchResult:
        """
        切换到目标账号。
        1. 快照当前浏览器 cookies + localStorage → 保存到当前账号
        2. 清除浏览器当前 cookies + localStorage
        3. 注入目标账号的 cookies + localStorage
        4. 刷新当前页面（如有）
        """
        ...

    def get_active_account(self) -> BrowserAccount | None:
        """返回当前浏览器激活的账号。"""
        ...

    # ── 登录关联 ──

    def start_login_for_account(
        self, url: str, account_id: str | None = None
    ) -> str:
        """
        发起登录。如果 account_id 已指定，登录完成后凭据直接存入该账号。
        如果 account_id 为 None，则创建新账号（需先提供 label）。
        """
        ...

    def complete_login_for_account(
        self, account_id: str, cookies: list, origins: list
    ) -> None:
        """登录完成后，将凭据保存到指定账号。"""
        ...
```

### 4.2 Cookie State Swap 实现

核心切换逻辑位于 `BrowserAccountService.switch_account()`，通过 CDP 调用实现：

```python
async def _swap_cookie_state(
    self,
    session: BrowserSession,
    target_account: BrowserAccount,
) -> None:
    """通过 CDP 实现 cookie/localStorage 热切换。"""

    cdp = session.cdp_client  # 已有的 CDP websocket 客户端

    # Step 1: 清除当前浏览器所有 cookies
    await cdp.send("Network.clearBrowserCookies")

    # Step 2: 清除 localStorage（遍历所有 origins）
    # 通过 DOMStorage.clear 逐 origin 清除
    current_frame = await cdp.send("Page.getFrameTree")
    # ... 遍历 frames 清除

    # Step 3: 注入目标账号的 cookies
    target_creds = credential_vault.load_credential(
        target_account.domain, account_id=target_account.id
    )
    for cookie in target_creds:
        await cdp.send("Network.setCookie", {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path", "/"),
            "secure": cookie.get("secure", False),
            "httpOnly": cookie.get("httpOnly", False),
            "sameSite": cookie.get("sameSite", "Lax"),
        })

    # Step 4: 注入 localStorage
    target_origins = credential_vault.load_storage_origins(
        target_account.domain, account_id=target_account.id
    )
    for origin_data in target_origins:
        origin = origin_data["origin"]
        for key, value in origin_data["items"].items():
            await cdp.send("DOMStorage.setDOMStorageItem", {
                "storageId": {"securityOrigin": origin, ...},
                "key": key,
                "value": value,
            })

    # Step 5: 刷新页面使新凭据生效
    await cdp.send("Page.reload", {"ignoreCache": True})
```

**关键约束**：
- 切换前必须先快照当前状态（如果当前有激活账号）
- 整个过程在一次操作内完成（<1s），用户只需看到页面刷新
- 如果目标账号没有存储的凭据（新账号），只执行清除步骤

### 4.3 SiteLoginJobs 扩展

现有 `SiteLoginJobs` 的单槽位限制放松：

```python
# 现状
MAX_WORKERS = 1  # 同时只能一个登录任务

# 改后
MAX_WORKERS = 1  # 仍为 1（同一时刻只能展示一个登录窗口）
# 但增加 account_id 维度：
# - 同 URL 同 account_id → 复用现有 job
# - 同 URL 不同 account_id → 排队等待（不报错）
# - 不同 URL → 仍报 login_in_progress（避免混淆）
```

**登录完成后**：
- 如果登录时指定了 `account_id`，凭据自动存入该账号
- 如果未指定，弹出命名对话框让用户输入 label，创建新账号后存入
- 如果是对已有账号"重新登录"，直接更新该账号的凭据

---

## 5. AI Agent 工具

### 5.1 新增工具：`browser_switch_account`

注册在 `backend/tools/browser_tool.py`：

```python
class BrowserSwitchAccountTool(BaseTool):
    """切换浏览器当前激活的账号。"""

    name = "browser_switch_account"
    description = """
    切换到指定的浏览器账号。切换后，当前浏览器的 cookies 和 localStorage
    会替换为目标账号的登录态。适用于需要在多个用户身份间切换完成任务的场景。

    使用前可调用 browser_list_accounts 查看可用账号。
    """

    parameters = {
        "type": "object",
        "properties": {
            "account_id": {
                "type": "string",
                "description": "目标账号 ID。可从 browser_list_accounts 获取。"
            },
            "account_label": {
                "type": "string",
                "description": "或通过账号名称指定（模糊匹配）。"
            }
        }
    }

    async def execute(self, account_id=None, account_label=None):
        # 1. 解析目标账号
        # 2. 快照当前账号状态
        # 3. 切换 cookies + localStorage
        # 4. 返回切换结果
        ...
```

### 5.2 新增工具：`browser_list_accounts`

```python
class BrowserListAccountsTool(BaseTool):
    """列出可用的浏览器账号。"""

    name = "browser_list_accounts"
    description = "列出所有已注册的浏览器账号，可按域名过滤。"

    parameters = {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "可选，按域名过滤。"
            }
        }
    }
```

### 5.3 现有工具增强

`browser_login` 工具增加可选参数：

```python
# 新增参数
"account_id": {
    "type": "string",
    "description": "登录到指定账号。如果为空，将创建新账号。"
},
"account_label": {
    "type": "string",
    "description": "新账号的名称（仅在创建新账号时使用）。"
}
```

`web_fetch` 工具增加可选参数：

```python
# 新增参数
"account_id": {
    "type": "string",
    "description": "使用指定账号的凭据访问页面。不指定则使用默认账号。"
}
```

### 5.4 AI 交互模式

**模式一：实时识别 + 确认**

AI 在执行浏览器操作时检测到需要切换账号（如遇到权限不足、需要另一身份操作），主动提示：

```
AI: "当前以「张三的工作号」登录，但下一步需要「李四的审批号」才能操作。
     是否切换到「李四的审批号」？"
User: "是"
AI: [调用 browser_switch_account] → 切换成功 → 继续执行
```

**模式二：先规划后执行**

AI 在对话开始时规划整个接力流程：

```
AI: "我已规划好审批流程：
     步骤 1-3：以「张三」身份填写申请表
     步骤 4-5：切换到「李四」身份进行审批
     步骤 6：切换到「王五」身份最终确认
     是否开始执行？"
User: "开始"
AI: [按序执行，每步切换前自动调用 switch_account]
```

---

## 6. 前端 UI

### 6.1 设置页增强：账号池管理

在现有 `SiteSessionsSection.tsx` 下方新增「账号管理」区域：

```
┌─────────────────────────────────────────────────────────┐
│ 🔑 账号管理                                              │
├─────────────────────────────────────────────────────────┤
│ 域名筛选: [全部 ▼]                                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  🟢 知网 CNKI                                           │
│  ├── 张三的工作号  (默认)  ● 绿色   2小时前  [切换] [编辑] [删除] │
│  ├── 李四的审批号          ● 蓝色   30分钟前  [切换] [编辑] [删除] │
│  └── + 添加账号                                          │
│                                                         │
│  🟢 万方数据                                             │
│  └── 默认账号             ● 灰色   1天前    [切换] [编辑] [删除] │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**交互**：
- 按域名分组展示该域名下的所有账号
- 「切换」按钮：立即将该账号设为活跃（触发 CDP cookie swap）
- 「添加账号」：弹出登录窗口 + 命名对话框
- 每个账号显示颜色标签、保存时间、操作按钮

### 6.2 登录时命名

当用户在设置页点击「登录」且该域名已有账号时：

```
┌────────────────────────────────────┐
│ 该站点已有以下账号：                  │
│  ○ 张三的工作号（重新登录，更新凭据） │
│  ○ 创建新账号                       │
│                                     │
│  如果选择"创建新账号"，请在浏览器     │
│  中用新账号登录，完成后输入名称：      │
│  [                    ]             │
│                                     │
│  [开始登录]                         │
└────────────────────────────────────┘
```

### 6.3 AI 切换确认弹窗

当 AI 调用 `browser_switch_account` 时，前端弹出确认：

```
┌────────────────────────────────────┐
│ 🔄 账号切换请求                      │
│                                     │
│  AI 需要切换到「李四的审批号」         │
│  当前活跃：张三的工作号               │
│  目标站点：cnki.net                  │
│                                     │
│  [允许]  [拒绝]  [允许本次会话内所有]  │
└────────────────────────────────────┘
```

### 6.4 聊天面板状态指示

在聊天消息中显示当前浏览器使用的账号：

```
[🌐 当前浏览器账号：张三的工作号 (CNKI)]
正在访问 https://kns.cnki.net/ ...
```

---

## 7. 错误处理

| 场景 | 处理方式 |
|------|---------|
| 目标账号凭据已过期 | 切换成功，但提示用户"该账号凭据可能已过期，建议重新登录" |
| 切换过程中浏览器已关闭 | 返回错误"浏览器未运行"，AI 可自动重新打开 |
| 同域名账号名重复 | 创建时校验 UNIQUE 约束，返回 409 Conflict |
| 删除账号时有活跃会话 | 自动切换到同域名其他账号（如有）或清除浏览器状态 |
| Vault 迁移失败 | 保留旧格式不动，log warning，不阻断启动 |
| CDP 注入 cookies 失败 | 回滚到切换前状态（从快照恢复），返回错误 |

---

## 8. 实施步骤

### Phase 1：数据层（后端）

- [ ] 1.1 创建 `browser_accounts` SQLite 表
- [ ] 1.2 实现 `BrowserAccountService` CRUD 方法
- [ ] 1.3 重构 `credential_vault` key 结构，添加 `account_id` 维度
- [ ] 1.4 实现 vault 自动迁移（旧格式 → 新格式）
- [ ] 1.5 向后兼容层：旧 API 自动路由到 default account

### Phase 2：浏览器切换（后端）

- [ ] 2.1 实现 CDP cookie/localStorage 快照（`snapshot_account_state`）
- [ ] 2.2 实现 CDP cookie/localStorage 注入（`swap_cookie_state`）
- [ ] 2.3 实现 `switch_account()` 编排逻辑
- [ ] 2.4 扩展 `SiteLoginJobs` 支持 account_id 维度
- [ ] 2.5 扩展 `browser_login` 工具支持 account_id/account_label 参数

### Phase 3：API 层（后端）

- [ ] 3.1 新增 `/api/v1/browser-accounts` REST 端点
- [ ] 3.2 新增 `POST /switch` 端点
- [ ] 3.3 扩展 `web_fetch` 支持 account_id 参数

### Phase 4：AI 工具（后端）

- [ ] 4.1 实现 `browser_switch_account` 工具
- [ ] 4.2 实现 `browser_list_accounts` 工具
- [ ] 4.3 注册工具到工具注册表
- [ ] 4.4 实现切换确认 IPC 协议（AI → 前端 → 用户确认）

### Phase 5：前端 UI

- [ ] 5.1 设置页账号池管理组件
- [ ] 5.2 登录时命名对话框
- [ ] 5.3 AI 切换确认弹窗
- [ ] 5.4 聊天面板当前账号状态指示

### Phase 6：测试

- [ ] 6.1 单元测试：credential_vault 迁移逻辑
- [ ] 6.2 单元测试：BrowserAccountService CRUD
- [ ] 6.3 集成测试：cookie swap 切换流程
- [ ] 6.4 E2E 测试：多账号接力场景

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Vault 迁移数据损坏 | 用户丢失已保存的登录态 | 迁移前备份 vault JSON；失败时回滚到旧格式 |
| CDP cookie 注入不兼容某些网站 | 登录后仍无法使用 | 切换后自动执行 verify 检查；失败时建议重新登录 |
| localStorage 大小超限 | 注入失败 | 复用现有 `_clean_origins()` 限制逻辑（256KB 上限） |
| 多账号凭据增多导致 vault 膨胀 | 启动变慢 | 观察实际数据量；必要时拆分 vault 为多行存储 |
| 切换时页面刷新打断用户操作 | 用户体验差 | 切换前检查是否有未保存的表单（可选：提示用户） |

---

## 10. 与现有系统的关系

- **credential_vault.py**：扩展 key 结构，保留旧 API 兼容层
- **browser_tool.py**：新增 `browser_switch_account` / `browser_list_accounts` 工具
- **browser_cdp.py**：无需改动（已有 CDP 客户端基础设施）
- **site_login_jobs.py**：扩展支持 account_id 维度
- **web_tool.py**：`web_fetch` 增加 account_id 参数
- **SiteSessionsSection.tsx**：增加账号池管理 UI
- **browser_accounts 表**：新增，与 preferences 表同级

---

## 11. 未来演进

- **并行多账号**：基于 `MAX_BROWSER_SESSIONS=4` 的基础设施，为不同账号分配独立浏览器实例，实现真正的并行
- **跨机器同步**：加密的账号导出/导入功能
- **自动续期**：检测到账号凭据即将过期时自动触发重新登录
- **接力模板**：用户可保存多账号接力流程为模板，后续一键复用
