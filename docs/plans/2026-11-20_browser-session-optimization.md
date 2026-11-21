# 浏览器会话优化方案

> **日期**: 2026-11-20  
> **分支**: `feat/browser-session-settings` → `release/win7`  
> **状态**: 已完成（2026-11-20 双分支 PR 前准备完毕）

## 背景与目标

### 现状问题

当前 Sage 的受控浏览器功能存在以下限制：

1. **硬编码上限**: `MAX_BROWSER_SESSIONS = 4` 写死在 `backend/tools/browser_cdp.py`
2. **无可见性**: 用户不知道当前使用了几个实例，直到触发上限报错
3. **无命名能力**: 多账号场景下无法区分哪个是哪个
4. **回收策略单一**: 达到上限只能手动关闭，无自动 LRU 回收

### 用户场景

**多账号接力流程**：一个网页流程需要多个用户账号接力完成（如：账号A提交 → 账号B审核 → 账号C批准）。用户希望：
- 同时保持多个账号的登录状态
- 快速在账号间切换
- 清楚地知道每个会话对应哪个账号

### 目标

| 优先级 | 功能 | 目标 |
|--------|------|------|
| P0 | 可调上限 | 用户可在 2-8 间调整最大并发实例数 |
| P1 | 状态栏显示 | 实时显示 `n/max 实例使用中` |
| P2 | 会话命名 | 给浏览器会话起名 + 快速切换面板 |
| P3 | LRU 回收 | 达到上限时自动关闭最久未使用的实例 |

## 涉及的文件与模块

### 后端

| 文件 | 变更 |
|------|------|
| `backend/tools/browser_cdp.py` | `MAX_BROWSER_SESSIONS` 改为动态读取 settings |
| `backend/api/settings_models.py` | 新增 `browser.maxSessions` / `browser.lruEvict` 字段 |
| `backend/data/settings_canonicalizer.py` | 新增 `LEGAL_BROWSER_KEYS` |
| `backend/api/routes/settings.py` | 新增浏览器设置 API |
| `backend/tools/browser_cdp.py` | `BrowserSession` 新增 `name` / `last_used_at` 字段 |

### 前端

| 文件 | 变更 |
|------|------|
| `src/pages/settings/BrowserSettingsSection.tsx` | 添加上限滑块 + LRU 开关 |
| `src/shared/api/browserSettingsClient.ts` | 新增设置 API 调用 |
| `src/components/Statusbar/BrowserSessionIndicator.tsx` | 新增（状态栏指示器） |
| `src/components/Browser/BrowserSessionPanel.tsx` | 新增（会话命名 + 切换面板） |
| `src/shared/types/browser.ts` | 新增会话类型定义 |
| `src/shared/i18n/locales/*.json` | 新增 i18n 键 |

## 技术方案

### P0: 可调上限

**后端**:

```python
# backend/tools/browser_cdp.py
def get_max_sessions() -> int:
    """从 settings 读取上限，回退到默认值 4"""
    try:
        from backend.data.settings_repo import load_settings
        settings = load_settings()
        browser_cfg = settings.get("browser", {})
        value = browser_cfg.get("maxSessions", 4)
        # 安全边界
        return max(2, min(8, int(value)))
    except Exception:
        return 4  # 降级默认

# 原 MAX_BROWSER_SESSIONS 常量保留为 DEFAULT
DEFAULT_MAX_BROWSER_SESSIONS = 4
```

**前端设置控件**:

```tsx
// src/pages/settings/BrowserSettingsSection.tsx
<Slider
  min={2} max={8} step={1}
  value={maxSessions}
  onChange={setMaxSessions}
/>
<div className="flex justify-between text-xs text-muted">
  <span>2 (低内存)</span>
  <span>4 (推荐)</span>
  <span>8 (高性能)</span>
</div>
```

**设置存储**:

```json
{
  "browser": {
    "maxSessions": 4,
    "lruEvict": false
  }
}
```

### P1: 状态栏显示

**后端 API**:

```python
# GET /api/v1/browser/status
@router.get("/browser/status")
async def get_browser_status():
    manager = get_session_manager()
    sessions = manager.list_sessions()
    return {
        "active": len([s for s in sessions if s.is_alive()]),
        "max": get_max_sessions(),
        "sessions": [
            {
                "id": s.browser_id,
                "name": s.name,
                "url": s.current_url,
                "last_used_at": s.last_used_at.isoformat(),
            }
            for s in sessions
        ]
    }
```

**前端轮询**:

```tsx
// src/components/Statusbar/BrowserSessionIndicator.tsx
function BrowserSessionIndicator() {
  const [status, setStatus] = useState({ active: 0, max: 4 });
  
  useEffect(() => {
    const interval = setInterval(async () => {
      const res = await fetchBrowserStatus();
      setStatus(res);
    }, 5000); // 5秒轮询
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="flex items-center gap-1 text-xs text-muted">
      <Globe className="w-3 h-3" />
      <span>{status.active}/{status.max}</span>
    </div>
  );
}
```

### P2: 会话命名 + 切换面板

**数据模型扩展**:

```python
# backend/tools/browser_cdp.py
class BrowserSession:
    browser_id: str
    name: Optional[str] = None  # 用户给的名称
    last_used_at: datetime = field(default_factory=datetime.now)
    # ...
```

**API**:

```python
# PATCH /api/v1/browser/{browser_id}
@router.patch("/browser/{browser_id}")
async def update_browser_session(browser_id: str, body: UpdateSessionBody):
    """更新会话名称"""
    manager = get_session_manager()
    session = manager.get(browser_id)
    if session and body.name is not None:
        session.name = body.name
    return {"success": True}
```

**前端面板**:

```
┌─────────────────────────────────────────────────────┐
│  浏览器会话                          [+ 新建]         │
├─────────────────────────────────────────────────────┤
│  🟢 账号A - 审核员   example.com/review  2分钟前 ◄──┤
│  🟢 账号B - 提交者   example.com/submit  5分钟前    │
│  ⚪ 临时会话         example.com         1小时前     │
└─────────────────────────────────────────────────────┘
      点击切换 / 右键重命名 / 长按关闭
```

### P3: LRU 自动回收

**策略**:

```python
def _evict_lru_if_needed(self) -> bool:
    """达到上限时，关闭最久未使用的实例"""
    if self._counted_locked() < get_max_sessions():
        return False
    
    # 找最久未使用的
    candidates = [
        (sid, s) for sid, s in self._sessions.items()
        if s.is_alive() 
        and sid != EXTENSION_BROWSER_ID
        and getattr(s, "browser_type", None) != BrowserType.EMBEDDED
    ]
    if not candidates:
        return False
    
    # 按 last_used_at 升序
    oldest_id, oldest = min(candidates, key=lambda x: x[1].last_used_at)
    
    # 回收
    self._sessions.pop(oldest_id, None)
    _terminate_session(oldest)
    logger.info("LRU 回收浏览器会话: %s", oldest_id)
    return True
```

## 实施步骤

- [x] **步骤 1**: 后端 - `get_max_sessions()` 函数 + 单元测试
- [x] **步骤 2**: 后端 - settings 模型扩展 (`browser.maxSessions` / `browser.lruEvict`)
- [x] **步骤 3**: 后端 - `BrowserSession` 增加 `name` / `last_used_at` 字段
- [x] **步骤 4**: 后端 - 新增 `/api/v1/browser/status` API
- [x] **步骤 5**: 后端 - 新增 `PATCH /api/v1/browser/{id}` API
- [x] **步骤 6**: 后端 - LRU 回收逻辑
- [x] **步骤 7**: 前端 - 设置页滑块 + LRU 开关
- [x] **步骤 8**: 前端 - `browserSettingsClient.ts` API 封装
- [x] **步骤 9**: 前端 - `BrowserSessionStatus` 标题栏组件（P1 状态 + P2 面板合并）
- [x] **步骤 10**: 前端 - 会话命名 + 重命名 + 快速绑定（P2 面板内）
- [x] **步骤 11**: 前端 - i18n 键值（中/英双覆盖）
- [x] **步骤 12**: 单元测试（15 项 `test_browser_session_settings.py` 全绿）
- [ ] **步骤 13**: 文档更新 (`docs/technical/` + `docs/user-manual/`) — 下一步

## 风险评估与依赖

### 风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 用户设置过高的上限导致 OOM | 中 | 硬限制 2-8 范围，UI 提示内存影响 |
| Pydantic v1/v2 兼容 | 低 | 沿用现有 `*_compat` 函数模式 |
| 多账号切换时 cookie 泄漏 | 低 | 每个会话独立 user-data-dir，已隔离 |
| 状态栏轮询增加后端负载 | 低 | 5 秒间隔 + 仅桌面端轮询 |

### 依赖

- 无外部依赖
- 与现有 `browser_cdp.py` 会话管理逻辑兼容

## 测试计划

### 单元测试

```python
# test_browser_session_settings.py
def test_get_max_sessions_default():
    assert get_max_sessions() == 4

def test_get_max_sessions_clamped():
    # 设置 10 → 返回 8
    # 设置 1 → 返回 2

def test_lru_eviction():
    # 创建 4 个会话，再创建第 5 个 → 最久未用的被回收

def test_session_naming():
    # 创建会话 → 设置名称 → 获取 → 验证名称
```

### 集成测试

1. 设置页调整上限 → 立即生效
2. 状态栏显示正确的活跃数
3. 会话命名持久化
4. LRU 回收触发时日志记录

## 参考

- [主流 AI 浏览器应用对比](https://www.firecrawl.dev/blog/best-browser-agents)
- Launch Browser Agent: 10 并发 / 15 分钟超时
- Claude Code 多 Agent: 单进程 20-50 上下文
