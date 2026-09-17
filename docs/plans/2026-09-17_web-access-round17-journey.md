# 网页访问 Round 17：登录态全链路 journey 集成测试（2026-09-17）

- **上游文档**：Round 10-15 互锁改动（AU5 注入 / AU3 自愈 / AU7 登录墙 / X2 net / per-host 指标）
- **范围**：纯测试轮（backend/tests/integration/test_web_access_journey.py）——把六轮互锁改动串成真实调用链，保护接缝不被后续轮次打破

## 覆盖的 journey

- **J1 cookie 桥全链路**：export 形态档案 → web_fetch 附加 Cookie（hop 头断言）→ 响应
  Set-Cookie 回写续期（vault 值断言 + note）→ per-host 指标记成功
- **J1b 过期档案**：全过期 → `credential_expired` 且不发请求
- **J2 渲染 + AU7 + AU3**：JS 壳渲染带凭据 → 渲染登录墙（AU7 标记）→ AU3 自愈重渲染
  → 成功正文 + `credential_auto_refreshed` note
- **J3 渲染失败**：RenderError 语义 + per-host 指标记 fail

实现口径：HTTP 层 respx；浏览器层 monkeypatch；vault / 指标 / 凭据解析走真实现 +
共享假 SettingsRepository（类属性存状态）。
