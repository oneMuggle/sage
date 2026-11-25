# 文献站点 profile 示例模板

此目录存放**示例**站点 profile，**不参与运行时自动加载**。要启用某个站点：

```bash
mkdir -p ~/.sage/literature_sites
cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/
```

或复制到 `<项目>/.sage/literature_sites/`（仅该项目生效）。

加载优先级：`backend/literature/sites/`(builtin) < `~/.sage/literature_sites/`(用户) < `<项目>/.sage/literature_sites/`(项目)，后者覆盖前者。

验证：`python -m backend.literature.cli validate-profile --path ~/.sage/literature_sites/xueshu789.yaml`；
列出已加载站点：`python -c "from backend.literature.profile_store import get_default_store as g; print(g().list_ids())"`。

## xueshu789 实测要点（2026-11-22）

- 卡号+密码登录，成功后 URL 进 `/dbList/`，标题不含「登录」。
- `/dbItem/3` 可用（重定向 `http://82.157.23.222:5888/kns8s/defaultresult/index`）；`/dbItem/1` 代理报错；`/dbItem/2` 触发知网滑块验证。
- 搜索框 placeholder 含「检索词」，Enter 提交，约 5 秒出结果。
- 结果条目链接指向 `doDownload?url=...`，操作列「下载 / 原版阅读 / CNKI AI阅读」。
- 下载：`a.downloadlink` 真实 href 还带 `&ddata=<文件名>|<库>|<题名>|<库>|<hash>`；点击该元素经 `oversea.cnki.net/docdown/fulltext/download` 落盘 PDF（实测 787KB/26 页）。**不要**用快照里截断的 `doDownload?url=...` 直连（缺 `ddata` 报「参数错误」）。
- 下载完成后新标签可能显示 CNKI「页面不存在」，PDF 已落盘，以浏览器下载目录为准。
- 合规：仅本人账号/机构授权；不绕过付费墙；验证码/滑块交还用户。
