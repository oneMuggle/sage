# 169 · 渲染器 CSP 与高保真预览

> 面向开发者的实现说明。核心结论：打包版渲染层注入的生产 CSP 只放行它能识别的协议，Office 高保真预览若走 `fetch(data:)` 或把 `data:` URL 直接塞进 iframe，就会在安装包里被 Chromium 拦截，而开发模式（Vite dev server）不注入 CSP，所以本地永远测不出来。

## 1. 背景与问题现象

文档工作台与聊天产物面板提供两条「高保真」通路：

| 文档类型 | 高保真渲染 | 依赖 |
| --- | --- | --- |
| Word（`.docx`） | `docx-preview` 在渲染进程直接解析 docx 二进制 | `src/features/office/DocxNativePreview.tsx` 的 `renderDocxDataUrl` |
| Excel / PPT（`.xlsx` / `.pptx`） | 后端转 PDF → 前端把 PDF 以 `blob:` URL 喂给 Chromium 内置 viewer 的 `<iframe>` | `src/features/office/OfficePreviewPanel.tsx` |
| PDF 源文件 | 直接起后端 `/office/pdf/data` → 同样以 `blob:` URL 进 `<iframe>` | 同上 |

这三条通路的共同输入都是后端返回的 `data:…;base64,…` 字符串（`backend/api/office_routes.py` 的 `/office/word/data`、`/office/pdf/data`，以及 `office_lifecycle_routes.py` 的 `/office/pdf-preview`）。

故障表现具有强迷惑性：

- **开发模式一切正常**：`npm run dev` 下 Word 高保真可渲染、Excel/PPT/PDF 的 iframe 正常显示。
- **打包版一律失效**：Word 高保真渲染失败后静默回落到结构化视图；Excel/PPT/PDF 的 `<iframe>` 空白。
- **横跨 Win7 / Win10 安装包**：不是单个平台的环境问题。

根因不在业务代码，而在构建期注入的 CSP 与这两类 URL 的协议放行规则不匹配。

## 2. 根因：`cspInjectionPlugin` 的指令缺失

生产 CSP 由 `vite.config.ts` 里的 `cspInjectionPlugin()` 生成。它不是独立插件包，而是定义在 Vite 配置内的一个 `Plugin` 对象：

- `name: 'sage:csp-injection'`
- `apply: 'build'` —— **仅生产构建生效**，dev server 不注入（Vite HMR / React refresh 需要宽松策略），这正是「开发正常、打包失效」的原因。
- 通过 `transformIndexHtml` 在 `<head>` 后插入 `<meta http-equiv="Content-Security-Policy" content="…">`。
- `script-src` 的 `'sha256-*'` 由构建时对 `index.html` 中的内联脚本（主题 boot 脚本）逐个 `sha256` 计算，增删内联脚本无需手工维护哈希。
- 插件只在桌面构建启用：`plugins: [react(), ...(isWeb ? [] : [cspInjectionPlugin()])]`；`--mode web` 的网页产物不带这条 CSP。

### 2.1 完整指令表（修复后现状）

| 指令 | 值 | 说明 |
| --- | --- | --- |
| `default-src` | `'self' file:` | 兜底。`file://` 页面里 `'self'` 不匹配 `file:` 子资源，必须显式列 |
| `script-src` | `'self' file: <sha256…>` | 内联脚本按构建时哈希放行 |
| `style-src` | `'self' file: 'unsafe-inline'` | 允许内联样式 |
| `img-src` | `'self' file: data: blob: https: http:` | 图片本就放行 `data:` / `blob:`，远程 markdown 图也放行 |
| `font-src` | `'self' file: data:` | |
| `connect-src` | `'self' file: ws://localhost:* ws://127.0.0.1:* http://127.0.0.1:* http://localhost:*` | **刻意不含 `data:`**；生产渲染层经 IPC relay 访问后端，仅保留 loopback |
| `frame-src` | `'self' file: sage-preview: blob:` | `sage-preview:` 为 HTML 预览独立源；`blob:` 为 Office 高保真 PDF iframe |
| `object-src` | `'none'` | |
| `base-uri` | `'none'` | |
| `form-action` | `'none'` | |

### 2.2 两处与高保真预览直接相关的缺口

1. **`connect-src` 缺 `data:`**：`fetch('data:…')` 属于网络请求，受 `connect-src` 约束。旧代码 `renderDocxDataUrl` 用 `const response = await fetch(dataUrl)` 解码 docx，打包版直接抛 `Failed to fetch`，被 `catch` 后回落结构化视图。
2. **`frame-src` 缺 `blob:`**：Excel/PPT 的 office→PDF 结果与 PDF 原文都以 `blob:` URL 作为 `<iframe src>`，被 `default-src` 的默认规则拦截，表现为空白 iframe。

两者是同一次修复（`fix/office-csp-docx-fidelity`）发现的：`frame-src` 通过显式追加 `blob:` 解决；`connect-src` 则**没有**加 `data:`，而是从源头去掉 `fetch(data:)` 依赖，改为本地解码（见第 4 节），让 CSP 继续保持「生产渲染层不应直连」的收紧姿态。

> 相关提交：`release/win7` 侧 #3101（`a81bce410`），`main` 侧同步 #3102（`df2b47f39`）。`frame-src` 的 `blob:` 在提交注释中标注为 2026-11-17，与 `sage-preview:`（2026-11-04 引入）并列。

## 3. 修复：本地解码 + `frame-src` 放行 `blob:`

修复分两半，分别对应上一节的两处缺口。

### 3.1 CSP 侧

`vite.config.ts` 的 `frame-src` 追加 `blob:`：

```ts
"frame-src 'self' file: sage-preview: blob:",
```

`connect-src` 维持原样（不含 `data:`）。原因：blob URL 与创建方同源，放行 `blob:` 的风险等同于放行自身内容；而 `connect-src` 放开 `data:` 会让渲染层获得一条本不需要的本地数据读取通道，因此选择在代码侧消除 `fetch(data:)`。

### 3.2 代码侧

`DocxNativePreview.renderDocxDataUrl` 不再 `fetch` data URL，改用共享 helper `dataUrlToBlob` 本地解码：

```ts
// 修复前
const response = await fetch(dataUrl);
const blob = await response.blob();

// 修复后
const blob = dataUrlToBlob(dataUrl);
```

`dataUrlToBlob` 是同步函数，手写解析 data URL，不经过 fetch，也不依赖 `URL.createObjectURL`，因此在 Node / jsdom / 浏览器三处行为一致。

### 3.3 失败诊断透传

打包版没有 devtools，旧代码的 `catch` 把错误吞掉，用户只看到回落视图。现在 `DocxNativePreview` 的 `onError` 签名从 `() => void` 改为 `(detail?: string) => void`，把错误详情一路带到父级的回落 toast（`OfficePreviewPanel` 的 `fallbackToStructured(notify, detail)` 用 `description` 展示）。

## 4. `dataUrlToBlob` 与 blob URL 链路

实现位置：`src/features/office/officePreviewBlobUrl.ts`。这个文件是为把逻辑从 `OfficePreviewPanel` 拆出、压住架构行数上限而独立的，对外导出三个函数。

### 4.1 `dataUrlToBlob(dataUrl): Blob`

```ts
const match = /^data:([^;,]*)(;base64)?,(.*)$/s.exec(dataUrl);
if (!match) throw new Error(`invalid data URL: ${dataUrl.slice(0, 60)}`);
const mime = match[1] || 'application/octet-stream';
const bytes =
  match[2] === ';base64'
    ? Uint8Array.from(atob(match[3]), (c) => c.charCodeAt(0))
    : new TextEncoder().encode(decodeURIComponent(match[3]));
return new Blob([bytes], { type: mime });
```

要点：

- **两种编码都支持**：`;base64` 走 `atob`，非 base64 走 `decodeURIComponent` + `TextEncoder`。
- **MIME 缺省兜底**为 `application/octet-stream`。
- **非法输入直接抛错**（`invalid data URL`），由调用方决定是否回落结构化视图，不静默产出空 Blob。
- 不 `fetch`：既绕开生产 CSP 的 `connect-src` 限制，也统一了 jsdom / 老 Chromium 对 `fetch('data:…')` 的不一致行为。

### 4.2 `dataUrlToBlobUrl(dataUrl): Promise<string>`

```ts
return URL.createObjectURL(dataUrlToBlob(dataUrl));
```

供需要 `blob:` URL 的调用方（iframe）使用。

### 4.3 `safeRevokeBlobUrl(url)`

仅当字符串以 `blob:` 开头时才 `URL.revokeObjectURL`，避免对非 blob 字符串误调用。

### 4.4 调用方

| 调用方 | 使用 | 输入 | 去向 |
| --- | --- | --- | --- |
| `DocxNativePreview.renderDocxDataUrl` | `dataUrlToBlob` | `/office/word/data` 的 docx `data:` URL | `docx-preview` 的 `renderAsync(blob, …)`，渲染进 div（非 iframe） |
| `DocxBlobPreview`（聊天产物面板，`FileContentRenderer` 引入） | 复用 `renderDocxDataUrl` | artifact content 的 docx `data:` URL | 同上 |
| `OfficePreviewPanel.loadFidelity` | `dataUrlToBlobUrl` | `/office/pdf-preview` 的 PDF `data:` URL | `fidelityUrl` → 高保真 `<iframe data-testid="office-preview-fidelity-iframe">` |
| `OfficePreviewPanel.handleToggleOriginalPdf` | `dataUrlToBlobUrl` | `/office/pdf/data` 的 PDF `data:` URL | `originalPdfUrl` → PDF 原文 `<iframe data-testid="office-pdf-original-frame">` |

`OfficePreviewPanel` 在切换文档与卸载时用 `safeRevokeBlobUrl` 释放旧的 blob URL（通过 ref 读取最新值，避免闭包捕获过期 state）。

Word 路径不使用 iframe，因此只受 `connect-src`（现已不依赖）影响；Excel/PPT/PDF 路径使用 iframe，直接受 `frame-src` 约束。

## 5. 影响面与回归验证

### 5.1 影响面

- **Word 高保真**：`/office` 页与聊天产物面板共用 `renderDocxDataUrl`，一处修复两条链路同时受益。
- **Excel / PPT 高保真**：office→PDF 转出的 `blob:` URL 依赖 `frame-src blob:`。
- **PDF 原文预览**：`/office/pdf/data` 的 `blob:` URL 同样依赖 `frame-src blob:`。
- **未受影响**：图片预览（`img-src` 本就含 `data:` / `blob:`）、HTML 产物预览（独立 `sage-preview:` scheme）、网页回退模式（`--mode web` 不注入该 CSP）。

### 5.2 回归验证

| 测试文件 | 锁定的行为 |
| --- | --- |
| `src/features/office/__tests__/officePreviewBlobUrl.test.ts` | base64 / percent 编码解码、缺省 MIME、非法输入抛错、`dataUrlToBlobUrl` 包一层 `createObjectURL` |
| `src/features/office/__tests__/DocxNativePreview.test.tsx` | `renderDocxDataUrl — production CSP compatibility`：`fetch` 被 spy 为必定 reject，仍能渲染成功，且断言 `fetch` 未被调用、传给 `renderAsync` 的是正确 MIME 的 `Blob`；另一例断言失败详情经 `onError(detail)` 透出 |
| `src/features/office/__tests__/OfficePreviewPanel.test.tsx` | 高保真 iframe / PDF 原文 iframe 的 `src` 与显隐 |

因为 dev 不注入 CSP，上述 bug 无法在开发模式复现；验证必须跑生产构建产物（`npm run build` 后加载 `dist/`），或依赖上述单测锁住「不依赖 `fetch(data:)`」这一不变式。

## 6. 相关文件

| 路径 | 职责 |
| --- | --- |
| `vite.config.ts` | `cspInjectionPlugin()`：生产 CSP 指令表（`connect-src` / `frame-src` 等） |
| `src/features/office/officePreviewBlobUrl.ts` | `dataUrlToBlob` / `dataUrlToBlobUrl` / `safeRevokeBlobUrl` |
| `src/features/office/DocxNativePreview.tsx` | `renderDocxDataUrl`（Word 高保真渲染 + 消毒）、错误详情透传 |
| `src/features/office/DocxBlobPreview.tsx` | 聊天产物面板的 Word 高保真容器，复用 `renderDocxDataUrl` |
| `src/features/office/OfficePreviewPanel.tsx` | 高保真 iframe / PDF 原文 iframe、blob URL 生命周期与回落 toast |
| `src/widgets/chat/preview/FileContentRenderer.tsx` | 产物侧引入 `DocxBlobPreview` |
| `backend/api/office_routes.py` | `/office/word/data`、`/office/pdf/data`（20MB 上限，返回 `data:…;base64,…`） |
| `backend/api/office_lifecycle_routes.py` | `/office/pdf-preview`（office→PDF 转换结果） |
| `electron/commandRoutes/office.ts` | IPC → HTTP 路径映射（`office_word_data` / `office_pdf_data` / `office_pdf_preview`） |
