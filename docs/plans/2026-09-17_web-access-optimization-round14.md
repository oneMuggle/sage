# 网页访问能力优化 Round 14：浏览器健康自检 + 凭据 UI header 新增（2026-09-17）

- **上游文档**：Round 9（诊断端点模式）、Round 12（凭据 UI/REST）、本会话分析（win7 Chrome 109 老化监控 + 凭据 UI header 入口两项缺口）
- **范围**：main 与 release/win7 双分支（后端小路由 + 前端小区块）

## 0. 结论速览

补齐两个用户可见缺口：① **浏览器健康自检**——设置页能看到 Sage 用的哪个浏览器、版本多新；win7（Chrome 109 封顶）版本老化时明示警告（分析阶段识别的 win7 专项缺口落地）。② **header 型凭据新增入口**——Round 12 的凭据 UI 只能看/删 cookie 凭据，Bearer/API key 型凭据仍只能靠对话设置；补 REST + 表单。

| 项 | 内容 | 批次 |
| --- | --- | --- |
| H1 | `GET /api/v1/diagnostic/browser`：浏览器发现 + 版本 + UA 声明版本 + 过旧警告 | 批次 1 |
| C1 | `POST /api/v1/web-access/credentials/header`：save_header_credential REST | 批次 1 |
| C2 | NetworkTab：header 凭据新增表单 + 浏览器健康显示 + i18n | 批次 2 |
| T | 契约测试 + CHANGELOG | 批次 2 |

## 1. 设计

- **H1**（diagnostic_routes.py，对齐 search-engines 模式）：复用 `discover_browser_executable()` +
  `http_factory._probe_chrome_major()`；响应 `{browser_found, executable, chrome_major,
  ua_declared_major, warning}`——`chrome_major` 是本地真实版本，`ua_declared_major` 是
  出网 UA 声明版本（http_factory.chrome_major_version，探测值低于 126 兜底）；win7
  Chrome 109 场景 warning="本机浏览器版本较旧（Chrome <120），部分站点可能拒绝访问，
  可用 SAGE_BROWSER_PATH 指定新内核"。阈值常量 `OLD_BROWSER_MAJOR = 120`。
- **C1**：POST body `{domain, header_name, value}` → `save_header_credential(domain,
  {name: value})`（vault 的名/值校验原样生效）；成功 `{ok: true}`，非法 422。
- **C2**：NetworkTab 凭据区块顶部加浏览器健康小字（拉 H1）；header 新增表单
  （domain/header 名/值三输入 + 保存按钮，走 C1）。

## 2. 双分支

后端两个小改动 + 前端 src/ 三文件，cherry-pick 零预期冲突；CHANGELOG 手工合入。
