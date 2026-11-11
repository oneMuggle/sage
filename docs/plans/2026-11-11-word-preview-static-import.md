# 2026-11-11 Word 高保真预览修复：静态导入替代动态导入

## 背景与目标

**问题**：Win7 安装包中文档工作台的 Word 高保真预览不可用，但开发模式正常。

**根因分析**：`DocxNativePreview.tsx` 中 `renderDocxDataUrl()` 使用动态 `import('docx-preview')` 和 `import('dompurify')`。
在生产构建（asar 打包）中，Vite 的代码分割将这些库分到独立 chunk，
运行时动态导入可能因 asar 路径解析问题或 CSP 限制而失败。错误被静默捕获后回退到结构化视图，
用户看不到详细错误信息。

**目标**：将动态导入改为静态导入，彻底消除生产环境中的 chunk 加载问题；同时增强错误诊断日志。

## 涉及的文件与模块

| 文件 | 改动 |
|------|------|
| `src/features/office/DocxNativePreview.tsx` | 静态导入 docx-preview + dompurify；增强错误日志 |

> `DocxBlobPreview.tsx` 不直接使用动态导入，它通过调用 `renderDocxDataUrl()` 复用同一条渲染链路，修复 DocxNativePreview.tsx 后自动受益。

## 技术方案

### 改动前（动态导入）

```typescript
// renderDocxDataUrl 内部 (lines 60-82)
const [{ renderAsync }, dompurifyModule] = await Promise.all([
  import('docx-preview'),
  import('dompurify'),
]);
```

### 改动后（静态导入）

```typescript
// 文件顶部
import { renderAsync } from 'docx-preview';
import DOMPurify from 'dompurify';

// renderDocxDataUrl 简化 —— 去掉 await Promise.all 动态加载
export async function renderDocxDataUrl(container: HTMLElement, dataUrl: string): Promise<void> {
  const response = await fetch(dataUrl);
  const blob = await response.blob();
  container.innerHTML = '';
  await renderAsync(blob, container, undefined, {
    inWrapper: false,
    ignoreLastRenderedPageBreak: false,
    experimental: false,
  });
  container.innerHTML = DOMPurify.sanitize(container.innerHTML, {
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'link', 'meta'],
    FORBID_ATTR: ['srcset'],
  });
  sanitizeRenderedDocx(container);
  annotateParagraphIndexes(container);
}
```

### 增强错误诊断

在 `DocxNativePreview` 组件的 `useEffect` catch 块中增加错误日志：

```typescript
catch (err) {
  console.error('[DocxNativePreview] render failed:', {
    error: err instanceof Error ? err.message : String(err),
    workspacePath,
    managedPath,
  });
  if (!cancelled) {
    setState('error');
    onError?.();
  }
}
```

## 实施步骤

- [x] M1：修改 `DocxNativePreview.tsx` — 静态导入 + 错误日志
- [x] M2：运行 TypeScript 类型检查 — 确保导入语法正确
- [x] M3：运行 Vitest 测试 — 确保不破坏现有功能（5 files, 49 tests passed）
- [x] M4：构建验证 — `npm run build` 成功（33.35s）

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| 主 bundle 体积增加 | 首屏加载稍慢 | docx-preview ~200KB gzipped，Word 预览场景必要 |
| 静态导入类型不匹配 | 编译错误 | M2 类型检查覆盖 |
| 测试用例 mock 依赖动态导入行为 | 测试失败 | M3 测试覆盖 |

## 依赖

无新依赖。`docx-preview@0.3.5` 和 `dompurify@3.4.15` 已在 `package.json` 中声明。
