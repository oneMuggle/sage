# Sage Browser Bridge

让 Sage 直接使用你**日常浏览器**里已经登录的标签页。适用于知网、校内数据库、
企业后台等需要扫码 / 短信 / 机构登录，且重登成本高的站点。

> 隐私边界：扩展只操作你**手动共享的那一个标签页**。共享期间浏览器顶部会显示
> 「Sage Browser Bridge started debugging this browser」信息条；随时点扩展图标
> →「停止共享」，或在 Sage 设置页撤销设备即可断开。密码、验证码、扫码始终只在
> 你的浏览器里完成，不经过 Sage 聊天或设置页。

## 安装（Chrome / Edge 109+）

1. 打开 `chrome://extensions/`（Edge 为 `edge://extensions/`），开启「开发者模式」。
2. 点击「加载已解压的扩展程序」，选择本目录：
   - 开发态：仓库内 `extension/agent-bridge`；
   - 安装包：Sage 安装目录下 `resources/extension/agent-bridge`
     （Sage 设置 → 网络 → 日常浏览器扩展 会显示实际路径）。
3. 扩展图标固定到工具栏。

## 配对

1. Sage → 设置 → 网络 → 「日常浏览器扩展」→「生成配对码」。
2. 点击扩展图标，粘贴后端地址（默认 `http://127.0.0.1:8765`，设置页会显示实际端口）
   与 10 位配对码，点「配对」。
3. 配对成功后设备会出现在 Sage 设置页，可随时撤销。

配对码 5 分钟内有效、只能使用一次；连续输错 5 次即作废，重新生成即可。

## 共享标签页

1. 在你日常浏览器中打开已登录的目标站点。
2. 点击扩展图标 →「共享此标签页」。首次共享某个网站时，浏览器会请求允许扩展
   访问该网站，请选择允许。
3. 回到 Sage 对话，直接让 agent 读取 / 操作该页面即可；现有
   `browser_navigate` / `browser_snapshot` / `browser_interact` /
   `browser_screenshot` / `browser_cookies` 会自动使用共享标签页。
4. 点击「停止共享」即断开；跨域跳转或关闭标签页也会自动停止。

## 保存登录状态

共享标签页时，点击扩展弹窗中的「保存登录状态到 Sage」：

- 只收集**当前标签页所属域名**的 Cookie 与当前 origin 的 localStorage；
- 经 Sage 后端加密写入本地凭据库，不返回聊天、不在设置页回显；
- 之后即使不共享标签页，Sage 的静态抓取 / JS 渲染通道也可以复用这份登录态。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 「无法附加到该标签页」 | 关闭该标签页的 DevTools 后重试（同一标签页只能有一个调试器） |
| 共享后立即提示已停止 | 页面跳转到了不同域名；回到目标站点重新共享 |
| Sage 提示「扩展已离线」 | 确认浏览器和扩展仍打开；扩展会每分钟自愈重连 |
| 设置页显示「需重新配对」 | 设备被撤销或凭据失效；重新生成配对码 |
| 多个浏览器同时共享 | 同一时间只允许一个共享标签页；先在另一个浏览器停止共享 |

## 权限说明

| 权限 | 用途 |
| --- | --- |
| `debugger` | 通过 Chrome DevTools Protocol 读取/操作共享标签页（会显示调试信息条） |
| `tabs` | 识别当前标签页与跨域跳转，及时停止共享 |
| `cookies` | 「保存登录状态」时读取当前站点 Cookie |
| `storage` | 保存配对凭据与共享状态（仅本机 `chrome.storage.local`） |
| `offscreen` | 在后台页面维持与 Sage 的长轮询（MV3 Service Worker 会被回收） |
| `alarms` | 每分钟看门狗，Service Worker 被回收后自动恢复 |
| `optional_host_permissions` | 仅在用户共享某个网站时按站点申请访问权限 |

扩展只连接 `127.0.0.1` / `localhost`，不上传任何数据到远程服务器。

## 开发与调试

- `chrome://extensions/` → 扩展详情 →「Service Worker」可打开后台控制台；
- `offscreen.html` 可在扩展详情页的「检查视图」中调试；
- 修改代码后点击扩展卡片的刷新按钮；
- 后端日志会记录设备配对、共享与会话保存（不记录设备 token / Cookie 值）。

## 协议

扩展每 20 秒向 Sage 后端发起一次长轮询（`POST /api/v1/web-access/extension/poll`），
取出 `{id, method, params}` 后通过 `chrome.debugger.sendCommand` 转发到共享标签页，
再把结果 POST 回 `/api/v1/web-access/extension/result`。后端将这些 CDP 方法映射为
一个 `BrowserSession(browser_type=external)`，因此现有浏览器工具无需改动。
