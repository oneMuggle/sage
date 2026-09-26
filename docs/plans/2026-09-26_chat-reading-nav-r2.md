# 对话阅读体验第二轮：P1 / P2（方案登记）

> 日期: 2026-09-26 · 目标分支: `main` → cherry-pick `release/win7`

按 `AGENTS.md`「spec 先行」要求在 `docs/plans/` 登记本批次。完整方案、代码证据、设计、
验证与进度日志见 `docs/mcp-chat-reading-nav-optimization.md` §10。

| 批次 | 编号 | 内容 |
| --- | --- | --- |
| P1 | B1 | 消息朗读（Web Speech API，Windows 使用本地语音） |
| P1 | B2 | 截断提示 + 继续生成（`finish_reason` 透传并落库） |
| P1 | B3 | 搜索命中词高亮（CSS Custom Highlight API） |
| P1 | B4 | 会话内查找（聊天页 `Ctrl+F`；`Ctrl+Shift+F` 聚焦会话搜索） |
| P2 | C1 | 生成速度统计（首字延迟、tokens/s；流式计时并落库） |
| P2 | C2 | 回答版本切换（最后一轮原位重新生成，旧回答存入 `message_versions`，`‹ 2/3 ›` 切换） |
| P2 | C3 | 端点离线提示（按失败事件的错误类型判定，标题栏下方全局提示条） |

## 交付

| 批次 | `main` | `release/win7` |
| --- | --- | --- |
| P1（B1–B4） | [#1619](https://github.com/oneMuggle/sage/pull/1619) → `a3c16668e` | [#1622](https://github.com/oneMuggle/sage/pull/1622) → `315fdebca` |
| P2（C1–C3） | [#1625](https://github.com/oneMuggle/sage/pull/1625) → `91dbb9420` | [#1627](https://github.com/oneMuggle/sage/pull/1627) → `8a8e5af9d` |

进度日志与交付记录见 `docs/mcp-chat-reading-nav-optimization.md` §10.7、§10.8。
