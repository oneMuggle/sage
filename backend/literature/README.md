# 文献站点 profile（SiteProfile）

新增站点 = 新增一份 YAML，不改流水线代码。

## 三级目录（后者覆盖前者）

| 层 | 目录 |
|---|---|
| 内置 | `backend/literature/sites/*.yaml` |
| 用户 | `~/.sage/literature_sites/*.yaml`（可用 `SAGE_LITERATURE_SITES_DIR` 覆盖） |
| 项目 | `<workspace>/.sage/literature_sites/*.yaml` |

同 `id` 的 profile 以更高层为准，便于用户或项目覆盖随包配置。

## 必填字段

`id` / `display_name` / `home_url` / `domains` / `search.url_template`（含 `{query}`）。

## 可选字段

`access`（登录方式与登录态判定）、`search.wait_for`、`search.pagination`、
`search.result_fields`、`detail`、`pdf`、`rate_limit`、`compliance`、
`status`（`ready` / `draft`）、`last_verified_at`（`YYYY-MM-DD`）。

## 交互式检索（`search.mode: interactive`）

适合"入口页 → 点击/跳转 → 输入关键词 → Enter 提交"的站点：

```yaml
search:
  mode: interactive
  url_template: "https://example.org/entry"   # 入口页（无需 {query}）
  entry_url: "https://example.org/entry"
  entry_click: "检索入口"                     # 可选，点击入口按钮
  input_selectors:
    - "input[placeholder*='检索词']"
  submit_key: Enter
  wait_after_s: 5
  result_hint: 结果条目结构说明
```

`SageToolDriver`（`backend/literature/sage_driver.py`）把 driver 调用映射到
`sage.call("browser_*")`，可在 `execute_code` 中使用。

## 设计规则

- 站点差异只写在这里或 skill 的 `references/`，禁止写进 pipeline 代码。
- 选择器未实测前用空字符串 + `status: draft`，由"录制模式"补齐。
- 第三方站点默认 `compliance.default_enabled: false`，用户显式启用。
- 不代填密码、不导出 cookie、不绕过付费墙；验证码交还用户。
- `home_url` 与渲染出的检索 URL 必须落在 `domains` 内（含子域名），防止
  profile 把请求指向任意主机。

## xueshu789 已实测事实

- 卡号 + 密码登录，成功后 URL 进入 `/dbList/`，标题不再包含「登录」。
- `/dbItem/1` 代理报「出错啦」；`/dbItem/2` 触发知网滑块验证；`/dbItem/3` 可用，
  重定向到 `http://82.157.23.222:5888/kns8s/defaultresult/index`（「检索-中国知网」）。
- 搜索框 placeholder 含「检索词」；输入关键词后 Enter 提交，约 5 秒出结果。
- 结果条目的题名/作者/来源链接均指向 `https://www.xueshu789.cc/doDownload?url=...`；
  操作列有「下载 / 原版阅读 / CNKI AI阅读」。
- **下载链路未验证通过**：`doDownload` 新标签显示「参数错误」；profile 保持
  `status: draft`，下载需后续排查（POST/Referer/动态 token 等）。
