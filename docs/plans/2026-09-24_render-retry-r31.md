# 网页访问 Round 31：渲染分支瞬时 5xx 单次重试（2026-09-24）

- **上游文档**：Round 5 §AB5（静态路径重试语义）；Round 22-27 渲染链
- **范围**：后端 only（web_render.py + test_web_render_events.py）

## 0. 结论速览

静态路径有 AB5（5xx/429 重试 + Retry-After），渲染分支对瞬时上游错误
（CDN 502/504 等）没有任何兜底——模型虽然能看到 rendered_status >= 500
（R22 起），但每次重试都要一轮工具往返。R31 给 `render_page` 加自动
**单次**整链重试。

## 设计

- `render_page` 增内部旗标 `_retried`（防无限递归）；
- 主文档状态 >= 500（事件或 Navigation Timing 取得）且未重试过 →
  整链重跑一次：换标签页重走 createTarget → cookie 注入 → 导航 →
  就绪等待 → 读取 → 回写；
- 403 反爬盾页**不重试**（持续态；Round 5 口径"不无限重试"）；
- 重试仍 5xx → 如实返回第二次结果 + note（`render_retried`）；
  重试自身抛错 → 保留首次结果 + note（`render_retry_failed`）；
- `_retried=True` 的内部调用不进入 web_tool 结果契约（note 字段经
  web_tool `content.update` 自动透出）。
