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

## `detail.url_from`：从结果链接推导详情页 URL

有些站点的结果行链接不是详情页本身，而是跳转/代理地址，真正的详情页 URL 藏在某个查询参数里。
可在 `detail.url_from` 中声明式描述这一推导，检索指导会据此提示：读取 `selector` 命中元素的 `href`，
取查询参数 `param`，按 `decode` 解码后作为详情页 URL。适用于任何「链接套链接」的站点，不绑定具体站点。

```yaml
detail:
  url_from:
    selector: "a.downloadlink"   # 结果行中承载跳转链接的元素
    param: "url"                 # href 中藏着真实详情页 URL 的查询参数
    decode: base64               # none | base64 | url（默认 none）
  fields:
    abstract:
      selector: "#ChDivSummary"  # 详情页中摘要正文的元素
```

- `decode=base64`：参数值是目标 URL 的 base64 编码（xueshu789 即如此，解码后为 `kns.cnki.net/.../abstract?v=...`）。
- `decode=url`：参数值需先 URL 解码。
- `decode=none`：参数值本身就是目标 URL。

## `pdf.interstitial`：下载中间页 + 主机回退

有些站点的下载入口不是直接附件，而是先落到一个「准备中」中间页，再由页面 JS
跳到（可能带时效签名 token 的）最终下载地址；甚至最终地址的主机可能写错。用
`pdf.interstitial` 声明这种两段式下载：

```yaml
pdf:
  entry:
    selector: "a.downloadlink"
  interstitial:
    url_contains:                  # 必填：识别中间页/跳转页的 URL 子串
      - "cnki.net/docdown"
    host_fallbacks:                # 依次替换主机尝试；全部失败后回退原域
      - "kns.cnki.net"
    tab_timeout_s: 6               # 等待标签页出现并跳转完成的上限（秒）
    sleep_after_open_s: 2.5        # 打开入口后等待中间页自动跳转的时间（秒）
    attempt_timeout_s: 15          # 非最后一次主机尝试的等待下载上限（秒）
```

运行方式（`download_pdf` 自动选择）：读取入口元素完整 `href` → 新标签打开 →
等待 URL 命中 `url_contains` → 按 `host_fallbacks` 重写主机并逐个导航 → 下载落盘
并校验 `%PDF-` 与题名。**不要**手点站点 `window.open` 弹窗（对工具不可见）。

## xueshu789 实测要点（2026-11-26）

- 卡号+密码登录，成功后 URL 进 `/dbList/`，标题不含「登录」。
- `/dbItem/3` 可用（重定向 `http://82.157.23.222:5888/kns8s/defaultresult/index`）；`/dbItem/1` 代理报错；`/dbItem/2` 触发知网滑块验证。
- 搜索框 placeholder 含「检索词」，Enter 提交，约 5 秒出结果。
- 结果条目链接指向 `doDownload?url=...`，操作列「下载 / 原版阅读 / CNKI AI阅读」。
- 下载：`a.downloadlink` 真实 href 还带 `&ddata=<文件名>|<库>|<题名>|<库>|<hash>`；**不要**用快照里截断的 `doDownload?url=...` 直连（缺 `ddata` 报「参数错误」）。
- 2026-11-26 站点改为两段式下载：`doDownload` →「文献下载中」中间页（约 2s）→ `oversea.cnki.net/docdown/...`；国内库（CJFQ 等）在 oversea 网关 404。同一 token 换 `kns.cnki.net` 返回 PDF（实测 1,070,254B curl / 1,688,310B 浏览器落盘）——用 `pdf.interstitial.host_fallbacks: ["kns.cnki.net"]` 修复。
- 下载完成后中间页标签可能显示 CNKI「页面不存在」，以浏览器下载目录/返回值 `path` 为准。
- 合规：仅本人账号/机构授权；不绕过付费墙；验证码/滑块交还用户。
