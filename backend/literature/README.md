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

## 设计规则

- 站点差异只写在这里或 skill 的 `references/`，禁止写进 pipeline 代码。
- 选择器未实测前用空字符串 + `status: draft`，由"录制模式"补齐。
- 第三方站点默认 `compliance.default_enabled: false`，用户显式启用。
- 不代填密码、不导出 cookie、不绕过付费墙；验证码交还用户。
- `home_url` 与渲染出的检索 URL 必须落在 `domains` 内（含子域名），防止
  profile 把请求指向任意主机。

## xueshu789 已实测事实

- 卡号 + 密码登录，成功后 URL 进入 `/dbList/`，标题不再包含「登录」。
- 站内为知网代理检索，行尾下载入口为 `a.downloadlink`；下载后校验 `%PDF-` 与题名。
- 搜索 URL 模板与结果字段选择器仍待"录制模式"实测补齐（当前 `status: draft`）。
