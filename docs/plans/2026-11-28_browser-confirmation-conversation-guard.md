# 浏览器确认项服务端按对话二次校验（多会话隔离 P2-1）

## 背景与目标

多会话隔离 P0/P1 已把「浏览器实例归属、租约、下载路由、状态轮询」按对话隔离，
但 `PendingConfirmation` 只记录 `session_id`（浏览器实例 id），REST 的列表与裁决
接口也不校验「这条确认属于哪个聊天对话」：

- `GET /browser/confirmations` 只按 `session_id` 过滤；
- `POST /browser/confirmations/{id}` 拿到 id 就能裁决；
- P1 只在前端按 `owner` 隐藏了其他对话的确认条，服务端仍缺纵深防御。

同时，HTTP 出网门禁（`web_fetch` / `http_download`）创建的确认项 `session_id`
为空串，前端按浏览器实例 id 轮询时永远看不到它们——本来应由右栏面板裁决的
站点授权确认因此成为「孤儿」。

本项在确认项上记录 `conversation_id`（创建时取当前工具上下文的聊天会话 id），
列表与裁决接口按该字段过滤/校验，并让前端以对话维度轮询，顺带恢复 HTTP 确认的
可见性。纯防守性改动，无 UX 变化。

## 涉及文件与模块

- `backend/services/browser_safety.py`：`PendingConfirmation.conversation_id`、
  `ConfirmationRegistry.create/list`、`to_public_dict`
- `backend/api/browser_use_routes.py`：列表接口 `conversation_id` 查询参数、
  裁决请求体 `conversation_id` + 归属校验
- `backend/tools/browser_tool.py`：站点门禁与敏感动作两处 `registry.create`
- `backend/tools/http_site_gate.py`：从工具上下文推导 `conversation_id`
- `src/shared/api/browserControlClient.ts`：列举/裁决传对话 id
- `src/features/browser/BrowserPanel.tsx`：按对话轮询与裁决
- 单测：`backend/tests/unit/test_browser_safety.py`、
  `backend/tests/api/test_browser_use_routes.py`、
  `src/features/browser/__tests__/BrowserPanel.test.tsx`
- 文档：`docs/technical/159-controlled-browser-use.md`
- 架构基线：`architecture-baseline.json`（`browser_tool.py` 行数补账）

## 技术方案

1. **数据模型**：`PendingConfirmation` 增加 `conversation_id: str = ""`；
   `create(..., conversation_id="")` 写入；`to_public_dict` 暴露该字段（非敏感）。
2. **过滤语义**：`list(session_id=None, conversation_id=None)`——给出
   `conversation_id` 时按对话过滤并优先于 `session_id`（同一对话可能同时拥有
   浏览器确认与 HTTP 确认，后者的 `session_id` 为空）；只给 `session_id` 时保持
   旧语义（P0/P1 兼容）。
3. **裁决校验**：请求体新增可选 `conversation_id`；待确认项带非空
   `conversation_id` 时必须与请求一致，否则返回 404 `confirmation_not_found`
   （不泄露存在性）。带空 `conversation_id` 的旧条目（REST/单测创建）维持兼容。
4. **创建点归属**：
   - `browser_tool._site_access_gate` 与敏感动作 create：`_current_owner()`
     （与审计 `conversation_id` 同口径）；
   - `http_site_gate.gate_http_url`：显式参数缺省时从
     `current_tool_context().session_id` 推导。
5. **前端**：`fetchPendingConfirmations(sessionId?, conversationId?)`；
   `resolveConfirmation(id, decision, conversationId?)`。`BrowserPanel` 在对话
   内有会话时同时传两者，无浏览器实例但有对话时仅按对话轮询（恢复 HTTP 确认
   可见性）；裁决时校验失败项不会展示。
6. **兼容性**：旧确认项（10 分钟 TTL 内）无 `conversation_id` 时前端回退按
   `session_id` 接受，裁决接口放行，滚动升级无感知。

## 实施步骤

- [x] 步骤 1：`browser_safety` 增加 `conversation_id` 字段、创建/列举过滤与序列化，
      补单测（按对话过滤、session 兼容、公开字段）
- [x] 步骤 2：REST 列表/裁决接口支持 `conversation_id` 并做归属校验，补 API 测试
      （匹配放行、缺失/不匹配 404、旧条目兼容）
- [x] 步骤 3：三处确认项创建点写入对话归属；`http_site_gate` 上下文推导 + 单测
- [x] 步骤 4：前端客户端与 `BrowserPanel` 按对话轮询/裁决，更新与新增组件测试
- [x] 步骤 5：技术手册 §159 补「确认项对话归属」小节；架构基线无需补账
      （`browser_tool.py` 当前 4259 行 ≤ 基线 4266，仍有余额）
- [ ] 步骤 6：ruff / pytest / vitest / architecture-check 全绿，提交开 PR
- [ ] 步骤 7：CI 绿后合并 main，cherry-pick 到 release/win7（pydantic 1.x 适配 +
      win7 文档 §162）并合并

## 风险评估与依赖

- **风险低**：无数据库结构变更；确认项为进程内注册表，TTL 600s，部署即生效。
- **兼容**：旧前端不传 `conversation_id` 时，对带归属的新条目会 404。桌面端
  前后端同包发布，无版本错配；仅开发期热更新可能短暂出现，可接受。
- **依赖**：无新增依赖；`current_tool_context` 在 executor 线程可读（P0 已验证
  `to_thread` 传播 ContextVar）。
- **真机**：本项无 Electron/分区行为变化，无需真机验收。
