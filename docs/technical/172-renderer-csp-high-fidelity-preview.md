# 172 渲染器 CSP 与高保真文档预览

> 适用范围：Electron 桌面端渲染进程的内容安全策略（CSP）、文档工作台与聊天预览的高保真渲染链路，以及与 `webPreferences` 的配合。Web 模式的构建差异见 [154 Web 兜底模式](./154-web-fallback-mode.md)。

---

## 1. 概览

Sage 的渲染层会展示 Markdown、KaTeX、Shiki、docx 解析结果、用户 HTML 等不可信内容，因此在生产构建中额外注入一层 CSP，并让文档高保真预览按内容类型走不同通道：

| 内容 | 高保真通道 | 关键约束 |
| --- | --- | --- |
| Word（.docx） | `docx-preview` 在渲染进程解析二进制，输出 DOM | 不依赖 `fetch(data:)`，渲染后做 DOM 消毒 |
| Excel / PPT | 后端转换为 PDF → `blob:` URL → `<iframe>` | `frame-src` 需放行 `blob:` |
| PDF 源文件 | 原始 PDF → `blob:` URL → `<iframe>` | 同上 |
| HTML | `sage-preview://` 独立源 `<iframe>`，无桥时退回 `srcDoc` | `frame-src` 需放行 `sage-preview:` |

CSP 与文档预览是两条互相影响的链路：CSP 决定浏览器允许加载哪些 iframe / 连接 / 内联脚本；预览实现则必须选择与 CSP 相容的 URL 形态（`blob:`、独立 scheme、本地解码），否则会出现「开发模式正常、安装包异常」的差异。

---

## 2. CSP 的来源与生效范围

CSP 由 `vite.config.ts` 中的 `cspInjectionPlugin()` 生成：

- 插件声明 `apply: 'build'`，只在构建阶段通过 `transformIndexHtml` 钩子改写 HTML；
- 在 `<head>` 后插入 `<meta http-equiv="Content-Security-Policy" content="...">`；
- Web 模式（`vite build --mode web`）不挂载该插件（`isWeb ? [] : [cspInjectionPlugin()]`），因此 `dist-web` 没有 CSP；
- `script-src` 中的 `'sha256-*'` 哈希在构建时扫描 HTML 内的内联脚本逐个计算，避免手工维护；
- 生产窗口以 `file://` 加载 `dist/index.html`；开发窗口加载 `VITE_DEV_SERVER_URL`，未设置时为 `http://localhost:${VITE_DEV_PORT ?? 1420}`。

各环境的实际状态：

| 场景 | CSP | 页面来源 |
| --- | --- | --- |
| `npm run dev` + Electron dev | 无 | Vite dev server（`VITE_DEV_SERVER_URL` 或 `http://localhost:<VITE_DEV_PORT>`） |
| `npm run build` + Electron 安装包 | 有（meta） | `file://.../dist/index.html` |
| `npm run build:web` | 无 | FastAPI 挂载的 `dist-web/` |

开发模式不注入 CSP 是有意为之：Vite HMR 与 React refresh 需要更宽松的策略。这也是「开发正常、打包异常」类问题的常见来源——排查生产问题时不能以开发模式的行为为准。

`pet.html` 同样参与构建，因此也走 HTML 入口的 CSP 注入流程；其脚本均为外部 module，不产生内联哈希。

---

## 3. 关键指令与放行项

生产构建注入的完整策略：

```text
default-src 'self' file:;
script-src 'self' file: <sha256 hashes>;
style-src 'self' file: 'unsafe-inline';
img-src 'self' file: data: blob: https: http:;
font-src 'self' file: data:;
connect-src 'self' file: ws://localhost:* ws://127.0.0.1:* http://127.0.0.1:* http://localhost:*;
frame-src 'self' file: sage-preview: blob:;
object-src 'none';
base-uri 'none';
form-action 'none'
```

逐项说明：

| 指令 | 值 | 原因 |
| --- | --- | --- |
| `default-src` | `'self' file:` | `file://` 页面的 `'self'` 不匹配 `file:` 子资源，必须显式列出 |
| `script-src` | `'self' file:` + 内联脚本哈希 | 禁止 `'unsafe-inline'`；主题启动、token 引导等内联脚本用哈希放行（旧浏览器兜底脚本的哈希匹配存在边界，见第 7 节） |
| `style-src` | `'self' file: 'unsafe-inline'` | React `style` 属性、KaTeX/Shiki 等会生成内联样式 |
| `img-src` | `'self' file: data: blob: https: http:` | Markdown 远程图片、data URL 缩略图与 blob 图片 |
| `font-src` | `'self' file: data:` | 内嵌字体与打包字体 |
| `connect-src` | `'self' file:` + loopback HTTP/WS | 生产渲染层主要经 IPC relay 访问后端；保留 loopback 直连以防未知路径静默破裂，收紧留给后续评审 |
| `frame-src` | `'self' file: sage-preview: blob:` | HTML 预览独立源与 Office/PDF 的 blob iframe，详见第 4 节 |
| `object-src` | `'none'` | 禁止 `<object>` / `<embed>` 插件内容 |
| `base-uri` | `'none'` | 防止注入 `<base>` 劫持相对 URL |
| `form-action` | `'none'` | 禁止表单提交跳转 |

`frame-src` 的两项扩展都对应具体回归：

- `sage-preview:`（2026-11-04）：HTML 预览改用独立 scheme，避免 `srcDoc` 继承渲染层 CSP；
- `blob:`（2026-11-17）：Office→PDF 转换结果与 PDF 原文预览以 blob URL 喂给 Chromium PDF viewer；缺失时打包版 iframe 空白。blob URL 与创建方同源，风险等同于应用自身内容。

---

## 4. 高保真文档预览的渲染路径

### 4.1 Word：docx-preview 直接渲染 DOM

Word 高保真不经过 iframe。`DocxNativePreview` 调用 `officeApi.readWordData()` 取得 `data:...;base64,...`，再交给共享入口 `renderDocxDataUrl()`：

1. `dataUrlToBlob(dataUrl)` 手工解析 data URL（base64 → `Uint8Array` → `Blob`），**不使用 `fetch(dataUrl)`**；
2. `docx-preview` 的 `renderAsync(blob, container, ...)` 在渲染进程解析 docx 并输出 DOM；
3. `DOMPurify.sanitize()` 配置 `FORBID_TAGS: ['script','iframe','object','embed','link','meta']`、`FORBID_ATTR: ['srcset']`，并放行 `target`；
4. `sanitizeRenderedDocx()` 再做一层 DOM 清理：移除危险标签、`javascript:` 链接与 `on*` 内联事件；
5. `annotateParagraphIndexes()` 写入段落锚点，供审校定位。

之所以必须本地解码：生产 CSP 的 `connect-src` 不含 `data:`，`fetch('data:...')` 只在打包版被拦截，开发模式（无 CSP）无法复现。该问题曾表现为 Word 高保真在安装包中一律 `Failed to fetch` 并回落结构化视图。

渲染失败时，错误详情经 `onError(detail)` 传给父级，父级回落结构化视图并显示 toast；打包版没有 DevTools，详情必须由 UI 透出。聊天产物面板的 `DocxBlobPreview` 复用同一条 `renderDocxDataUrl()` 链路，因此自动获得相同行为。

### 4.2 Excel / PPT / PDF：data URL 转 blob URL 后进 iframe

Excel/PPT 的高保真路径是「office→PDF 转换」：

1. `officeApi.pdfPreview()` 请求后端转换，返回 `{ ok, data_url }`，其中 `data_url` 为 `data:application/pdf;base64,...`；
2. `dataUrlToBlobUrl()` 本地解码并 `URL.createObjectURL()` 生成 `blob:` URL；
3. `<iframe src={blobUrl}>` 交给 Chromium 内置 PDF viewer；
4. 切换文档或卸载时用 `safeRevokeBlobUrl()` 释放（仅对 `blob:` 前缀生效）。

PDF 源文件走 `/office/pdf/data` 取得同样的 data URL，再经相同转换进入 iframe。选择 blob 而不是直接把 data URL 交给 iframe，是因为 Chromium PDF viewer 对 data URL 支持不稳定（典型表现为空白或触发下载），blob URL 才可靠；同时 CSP 的 `frame-src` 也只放行了 `blob:`。

该路径的 iframe 未设置 `sandbox`，因为内容是同源 blob、由 Chromium PDF viewer 渲染；安全边界依赖 PDF viewer 与 blob 的同源语义。

### 4.3 HTML：sage-preview:// 独立源

HTML 预览此前使用 `srcDoc` 内联在渲染层 iframe 中。`srcdoc` 文档**继承父文档 CSP**，而生产 CSP 的 `script-src` 没有 `'unsafe-inline'`、也没有 https 源，导致预览页的内联脚本与 CDN 脚本在安装包中全部被拦截，只剩静态排版。

现在的实现：

- 渲染层经 `window.electronAPI.preview.publish(html)` 把 HTML 投递给主进程；
- 主进程注册 `sage-preview` scheme（`standard`、`secure`、`supportFetchAPI`、`corsEnabled`），在内存注册表中保存内容，返回 `sage-preview://<id>/index.html`；
- 协议处理器只应答 `GET` / `HEAD` 的 `/` 与 `/index.html`，其余路径 404，响应带 `Cache-Control: no-store`；注册表最多保留 32 份，超出按插入顺序淘汰；
- IPC 仅接受受信任的渲染窗口；兼容档位 L1 及以上（`compatAppFeatures.previewHost === false`）不注册协议与 IPC；
- `<iframe sandbox="allow-scripts" referrerPolicy="no-referrer">`，没有 `allow-same-origin`，预览文档运行在 opaque origin，拿不到应用 cookie / storage / DOM；
- 该独立源的响应**没有 CSP 头**，页面内脚本按预览内容自由执行；隔离依赖 iframe sandbox 与默认拒绝的权限策略；
- Web / jsdom 环境没有 preload 桥，`HtmlPreviewHost` 退回 `srcDoc`。

错误桥（`htmlPreviewBridge.ts`）只注入到「渲染副本」：在 `<head>` 内加一段 ES5 内联脚本，监听 `error` / `unhandledrejection` / `console.error` 并通过 `postMessage` 回传；复制与下载仍使用用户原文，不包含桥接脚本。

### 4.4 路径汇总

| 场景 | 前端入口 | URL 形态 | 依赖的 CSP 指令 |
| --- | --- | --- | --- |
| Word 工作台 | `DocxNativePreview` | 本地解码为 Blob，无 URL 加载 | `connect-src` 不含 `data:` 也不受影响 |
| Word 产物 | `DocxBlobPreview` | 同上 | 同上 |
| Excel / PPT 高保真 | `OfficePreviewPanel` | `blob:` iframe | `frame-src blob:` |
| PDF 原文开关 | `OfficePreviewPanel` | `blob:` iframe | `frame-src blob:` |
| HTML 预览 | `HtmlPreviewHost` | `sage-preview://` iframe，或 `srcDoc` | `frame-src sage-preview:` |
| 聊天附件 PDF | `MediaPdfPreview` | 媒体 blob → iframe | `frame-src blob:` |

---

## 5. 与 Electron webPreferences 的关系

CSP 是渲染层的内容约束，和 Electron 的进程/窗口隔离是相互独立的防线。主窗口的关键配置（`electron/main.ts`）：

| 配置 | 值 | 说明 |
| --- | --- | --- |
| `contextIsolation` | `true` | 渲染层与 preload 隔离 |
| `nodeIntegration` | `false` | 渲染层无 Node |
| `sandbox` | `!NEEDS_NO_SANDBOX` | 旧版 Windows（Win7/8）或 `SAGE_NO_SANDBOX=1` 时关闭 |
| `preload` | `preload.js` | 只使用 `contextBridge` / `ipcRenderer`，满足 sandboxed preload 约束 |
| `backgroundThrottling` | `false` | 后台 SSE / 倒计时不被节流 |

旧版 Windows 上还会追加 `--no-sandbox` 命令行开关（同时关闭 GPU 相关能力）；现代平台恢复 Chromium sandbox。代码中没有设置 `webSecurity: false`，也没有关闭 `contextIsolation` 或开启 `nodeIntegration`。

其他配套加固：

- `installPermissionPolicy()` 对 default session 默认拒绝权限，仅放行 `clipboard-read`、`clipboard-sanitized-write`、`notifications`；
- `webContentsHardening` 拒绝 `<webview>` 挂载、默认拒绝弹窗并把 http(s) 链接交给系统浏览器；arena token 分区的受限弹窗强制 `sandbox` / `contextIsolation` / 无 Node / 无 preload；
- 独立 artifact 窗口使用 `sandbox: true`、`contextIsolation: true`、`nodeIntegration: false`，加载本地 HTML 文件。

在高保真预览链路上，CSP 主要补足两点：渲染层对 `docx` 解析出的 DOM、Markdown 渲染结果等不可信内容没有进程级隔离；Win7 上 Chromium sandbox 可能被关闭。因此生产 CSP 与 `contextIsolation`、权限默认拒绝一起构成纵深防御。

---

## 6. 安全权衡

- `style-src 'unsafe-inline'` 是实际需要：大量组件使用 `style` 属性，KaTeX/Shiki 也会产生内联样式。它放宽了样式注入面，但不影响脚本执行。
- `img-src` 放行 `https:` / `http:` 是为了保留 Markdown 远程图片；`script-src` 没有放行远程源。
- `connect-src` 保留 loopback HTTP/WS 是过渡性放宽；正常路径走 IPC relay。代码注释明确将收紧留给后续评审。
- 内联脚本哈希由构建自动计算，新增/删除 `index.html` 内联脚本无需手工维护。
- `sage-preview://` 文档没有 CSP，但运行在 `sandbox="allow-scripts"` 的 opaque origin，无法读取应用存储、Cookie 或 DOM；主进程只在受信任窗口发起 IPC 时发布内容。
- `blob:` iframe 与创建方同源，风险等同于应用自身内容；PDF 由 Chromium viewer 渲染，不执行页面脚本。
- Win7 / `SAGE_NO_SANDBOX=1` 会关闭 Chromium 进程沙箱，此时 CSP 与 `contextIsolation` 的重要性更高。

---

## 7. 已知限制

- **`frame-src` 未放行 `data:`**：聊天文件预览的 PDF 分支（`FileContentRenderer`）仍把后端返回的 `data:application/pdf;base64,...` 直接作为 iframe `src`。Office 与附件 PDF 路径已转 blob，但该分支在本工作树中未见转换，打包版存在被 CSP 拦截的风险。
- **低兼容档位下的 HTML 预览降级**：`previewHost` 在兼容档位 L1 及以上关闭，`sage-preview://` 的协议与 IPC 不注册；`HtmlPreviewHost` 仍能检测到 preload 桥，发布失败后退回 `srcDoc`，此时文档继承渲染层 CSP，内联脚本与 CDN 脚本会被拦截，预览退化为静态排版。
- **CSP 哈希对 `index.html` 注释敏感**：哈希扫描正则会把注释里的 `<script type=module>` 字面量当作内联脚本起点，导致后续「旧浏览器兜底」脚本的真实内容没有被单独哈希，生产 Chromium 中该兜底脚本会被拦截。只影响不支持 module 的旧浏览器提示逻辑，不影响主应用。
- **开发模式与 Web 模式没有 CSP**：这是构建策略的一部分；Web 部署如需收紧，应在反向代理或 FastAPI 层补安全响应头。
- **`connect-src` 仍允许 loopback 直连**：与「生产渲染层经 IPC relay」的现状相比属于冗余放行。

---

## 8. 排障速查

| 现象 | 常见原因 | 核对点 |
| --- | --- | --- |
| 开发正常，安装包 Word 高保真 `Failed to fetch` | `fetch('data:...')` 被 `connect-src` 拦截 | 确认走 `dataUrlToBlob()` 本地解码 |
| 安装包 Excel/PPT/PDF 预览 iframe 空白 | `frame-src` 缺 `blob:` | 检查构建产物 `dist/index.html` 的 meta CSP |
| 安装包 HTML 预览只剩静态排版 | 走了 `srcDoc` 回退，继承父 CSP | 检查 `previewHost` 兼容档位与 `window.electronAPI.preview` |
| HTML 预览脚本报错但无提示 | 错误桥未注入或消息被过滤 | 检查 `htmlPreviewBridge` 注入点与 `event.source` |
| PDF 直接以 data URL 预览被拦截 | `frame-src` 不含 `data:` | 改为 blob URL 后重试 |
| 只有打包版异常、DevTools 看不到日志 | 开发不注入 CSP，问题在生产才出现 | 直接检查 `dist/index.html` 的 CSP meta 与预览 URL 形态 |
