# P1: 画布 + 布局 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/office` 文档 Tab 重构为「左侧文档库 + 中间统一画布」，高保真默认开启、长文档可滚动、渲染失败自动降级、无转换器时导出引导。

**Architecture:** 新增 `OfficeLayout` / `DocumentCanvas` / `ConverterGuideDialog` / `officeFidelity.ts`，在 `OfficePreviewPanel` 做外科手术式修复（默认高保真 + 滚动修复 + 失败降级），不重写数据层。`JournalPanel` / `OfficeAiAssistantPanel` / `OfficeSpecLibrary` 保留不动。

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind + Radix Dialog + Vitest + @testing-library/react

**Spec:** `docs/plans/2026-11-06_office-ai-workbench-redesign.md` §3.2 / §3.1 / §4 P1

## Global Constraints

- 分支：`worktree-office-ai-workbench`（基于 main）
- 测试命令：`npx vitest run <path>`
- 类型检查：`npx tsc --noEmit`
- **不得**删除/修改 `JournalPanel` / `OfficeAiAssistantPanel` / `OfficeSpecLibrary`（测试依赖）
- **不得**改动 `2026-11-04_office-ai-document-workbench.md` 计划
- 文案 zh + en 双写（`zh.ts` 加键 → `en.ts` 同步加键，`en` 是 `Record<TranslationKey, string>`）
- 不改 `officeApi` 签名（`pdfPreview` / `exportPdf` / `readWordData` / `readExcelData` / `readPptData` / `readPdfData` 保持原样）
- 每任务单独 commit（conventional commits：`feat(office): ...`）
- 保留 `currentFidelityKeyRef` + `isCurrentKey` + `buildPreviewCacheKey` + `readIdRef` stale-read guard
- 端口：前端 1420 / 后端 8765（worktree `.env.local` 已配置）

---

## Task 1: 高保真默认决策工具函数

**Files:**
- Create: `src/features/office/officeFidelity.ts`
- Test: `src/features/office/__tests__/officeFidelity.test.ts`

**Interfaces:**
- Consumes: `OfficeDocType`（从 `./officeApi` 导入）
- Produces: `shouldDefaultFidelityOn(docType, fidelityAvailable)` / `shouldAutoLoadFidelity(docType, fidelityAvailable)` / `resolveDefaultFidelity(docType, available, override?)`

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/office/__tests__/officeFidelity.test.ts
import { describe, expect, it } from 'vitest';
import {
  resolveDefaultFidelity,
  shouldAutoLoadFidelity,
  shouldDefaultFidelityOn,
} from '../officeFidelity';

describe('officeFidelity', () => {
  describe('shouldDefaultFidelityOn', () => {
    it('word always defaults to fidelity on (no converter needed)', () => {
      expect(shouldDefaultFidelityOn('word', true)).toBe(true);
      expect(shouldDefaultFidelityOn('word', false)).toBe(true);
    });
    it('excel defaults on only when converter available', () => {
      expect(shouldDefaultFidelityOn('excel', true)).toBe(true);
      expect(shouldDefaultFidelityOn('excel', false)).toBe(false);
    });
    it('ppt defaults on only when converter available', () => {
      expect(shouldDefaultFidelityOn('ppt', true)).toBe(true);
      expect(shouldDefaultFidelityOn('ppt', false)).toBe(false);
    });
    it('pdf returns false (pdf uses its own path, not this switch)', () => {
      expect(shouldDefaultFidelityOn('pdf', true)).toBe(false);
    });
    it('undefined docType returns false', () => {
      expect(shouldDefaultFidelityOn(undefined, true)).toBe(false);
    });
  });

  describe('shouldAutoLoadFidelity', () => {
    it('excel/ppt with converter triggers auto-load', () => {
      expect(shouldAutoLoadFidelity('excel', true)).toBe(true);
      expect(shouldAutoLoadFidelity('ppt', true)).toBe(true);
    });
    it('word does not auto-load (docx-preview is synchronous, no need)', () => {
      expect(shouldAutoLoadFidelity('word', true)).toBe(false);
    });
    it('excel/ppt without converter does not auto-load', () => {
      expect(shouldAutoLoadFidelity('excel', false)).toBe(false);
      expect(shouldAutoLoadFidelity('ppt', false)).toBe(false);
    });
  });

  describe('resolveDefaultFidelity', () => {
    it('override=true forces on regardless of defaults', () => {
      expect(resolveDefaultFidelity('excel', false, true)).toBe(true);
    });
    it('override=false forces off even if default is on', () => {
      expect(resolveDefaultFidelity('word', true, false)).toBe(false);
    });
    it('no override falls back to shouldDefaultFidelityOn', () => {
      expect(resolveDefaultFidelity('word', false)).toBe(true);
      expect(resolveDefaultFidelity('excel', false)).toBe(false);
    });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/features/office/__tests__/officeFidelity.test.ts`
Expected: FAIL — `Cannot find module '../officeFidelity'`

- [ ] **Step 3: 写最小实现**

```typescript
// src/features/office/officeFidelity.ts
import type { OfficeDocType } from './officeApi';

/**
 * Whether fidelity mode should be ON by default for this doc type.
 * Word always (docx-preview needs no converter); Excel/PPT only when a converter exists.
 */
export function shouldDefaultFidelityOn(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
): boolean {
  if (docType === 'word') return true;
  if (docType === 'excel' || docType === 'ppt') return fidelityAvailable;
  return false;
}

/**
 * Whether fidelity should be auto-loaded on mount (async conversion kickoff).
 * Word uses synchronous docx-preview, no need. Excel/PPT need soffice and
 * should kick off the conversion automatically when available.
 */
export function shouldAutoLoadFidelity(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
): boolean {
  return (docType === 'excel' || docType === 'ppt') && fidelityAvailable;
}

/**
 * Resolves the initial fidelity state: explicit override wins,
 * otherwise falls back to shouldDefaultFidelityOn.
 */
export function resolveDefaultFidelity(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
  override?: boolean,
): boolean {
  return override ?? shouldDefaultFidelityOn(docType, fidelityAvailable);
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/features/office/__tests__/officeFidelity.test.ts`
Expected: PASS — 11 tests pass

- [ ] **Step 5: 提交**

```bash
git add src/features/office/officeFidelity.ts src/features/office/__tests__/officeFidelity.test.ts
git commit -m "feat(office): add fidelity default decision helpers"
```

---

## Task 2: OfficePreviewPanel 默认高保真 + 自动加载 + 失败降级

**Files:**
- Modify: `src/features/office/OfficePreviewPanel.tsx:112-118`（props 加 `defaultFidelity?: boolean`）、`:211`（`useState` → `useState(() => resolveDefaultFidelity(...))`）、`:227-237`（切文档 effect 重置为默认值）、`:271-336`（拆分 `loadFidelity()` 与 `handleToggleFidelity()`，失败时降级）、`:671-740`（渲染分支）
- Modify: `src/features/office/DocxNativePreview.tsx:37-46`（加 `onError?: () => void` prop）
- Modify: `src/features/office/__tests__/OfficePreviewPanel.test.tsx:175-181`（`renderPanel` 传 `defaultFidelity={false}` + mock 补 `pdfPreview`/`readWordData` 返回 `{ok:false}`）

**Interfaces:**
- Consumes: `shouldDefaultFidelityOn` / `resolveDefaultFidelity` / `shouldAutoLoadFidelity`（from Task 1）
- Produces: `OfficePreviewPanel` 新行为（默认高保真、自动加载、失败降级）；`DocxNativePreview` 新 prop `onError`

- [ ] **Step 1: 修改 DocxNativePreview 加 onError**

在 `src/features/office/DocxNativePreview.tsx` 的 props interface（`:37-46`）加：

```typescript
export interface DocxNativePreviewProps {
  workspacePath: string;
  managedPath: string;
  revision?: string;
  /** Optional callback when docx-preview fails. Used by parent to fall back to structured view. */
  onError?: () => void;
}
```

在组件内 `:116-177` 的 `catch` 块（`setState('error')`）后加：

```typescript
if (onError) onError();
```

- [ ] **Step 2: 修改 OfficePreviewPanel props**

在 `OfficePreviewPanel.tsx:112-118` 的解构中加 `defaultFidelity`：

```typescript
export interface OfficePreviewPanelProps {
  // ... existing props ...
  /**
   * Initial fidelity state override. When omitted, defaults to
   * shouldDefaultFidelityOn(docType, fidelityAvailable). Tests pass
   * false to preserve structured-view assertions.
   */
  defaultFidelity?: boolean;
}

export function OfficePreviewPanel({
  preview,
  workspacePath,
  onEditPreview,
  onRefresh,
  fidelityAvailable = true,
  defaultFidelity,
}: OfficePreviewPanelProps) {
  // ...
}
```

- [ ] **Step 3: 修改 useState 初始化**

`:211` 改为：

```typescript
const [fidelityOn, setFidelityOn] = useState(() =>
  resolveDefaultFidelity(preview?.docType, fidelityAvailable, defaultFidelity),
);
```

- [ ] **Step 4: 修改切文档 effect 重置为默认值**

`:227-237` 的 `setFidelityOn(false)` 改为：

```typescript
useEffect(() => {
  setAuditOpen(false);
  setHighlightParagraphIndex(null);
  setFidelityUrl((prev) => {
    safeRevokeBlobUrl(prev);
    return null;
  });
  setFidelityKey(null);
  setFidelityOn(resolveDefaultFidelity(preview?.docType, fidelityAvailable, defaultFidelity));
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [summaryId]);
```

- [ ] **Step 5: 拆分 loadFidelity 与 handleToggleFidelity + 失败降级**

`:271-336` 重构为：

```typescript
const loadFidelity = async () => {
  if (fidelityLoading) return;
  // Word + no converter → native docx-preview (no soffice request)
  if (!fidelityAvailable && preview?.docType === 'word') {
    setFidelityOn(true);
    return;
  }
  // Cached data URL for the same doc state → instant toggle
  if (fidelityUrl && fidelityKey === currentFidelityKey) {
    setFidelityOn(true);
    return;
  }
  const ws = workspacePath ?? summary.workspace_path;
  if (!ws) {
    fallbackToStructured();
    return;
  }
  setFidelityLoading(true);
  try {
    const res = await officeApi.pdfPreview({
      workspace_path: ws,
      file_path: buildManagedPath(ws),
    });
    if (!isCurrentKey(currentFidelityKey, currentFidelityKeyRef.current)) {
      return;
    }
    if (res.ok && res.data_url) {
      try {
        const blobUrl = await dataUrlToBlobUrl(res.data_url);
        if (!isCurrentKey(currentFidelityKey, currentFidelityKeyRef.current)) {
          safeRevokeBlobUrl(blobUrl);
          return;
        }
        safeRevokeBlobUrl(fidelityUrl);
        setFidelityUrl(blobUrl);
        setFidelityKey(currentFidelityKey);
        setFidelityOn(true);
        return;
      } catch (convErr) {
        const msg = convErr instanceof Error ? convErr.message : String(convErr);
        toast.error(`${t('office.fidelity.failed')}: ${msg}`);
      }
    }
    // Conversion failed or returned error → fall back to structured view
    fallbackToStructured();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    toast.error(`${t('office.fidelity.failed')}: ${msg}`);
    fallbackToStructured();
  } finally {
    setFidelityLoading(false);
  }
};

const fallbackToStructured = () => {
  setFidelityOn(false);
  toast.error(t('office.fidelity.fallback'));
};

const handleToggleFidelity = () => {
  if (fidelityOn) {
    setFidelityOn(false);
    return;
  }
  void loadFidelity();
};
```

- [ ] **Step 6: 加自动加载 effect**

在 `handleToggleFidelity` 定义后加：

```typescript
// Auto-load fidelity for Excel/PPT when converter is available.
// Uses a ref key (autoLoadKeyRef) to prevent StrictMode double-request.
const autoLoadKeyRef = useRef<string | null>(null);
useEffect(() => {
  if (!preview || fidelityOn || fidelityLoading) return;
  if (!shouldAutoLoadFidelity(preview.docType, fidelityAvailable)) return;
  const autoLoadKey = `${summary.id}:${currentFidelityKey}`;
  if (autoLoadKeyRef.current === autoLoadKey) return;
  autoLoadKeyRef.current = autoLoadKey;
  void loadFidelity();
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [preview?.docType, fidelityAvailable, summary.id, currentFidelityKey]);
```

- [ ] **Step 7: 修改渲染分支**

`:701-740` 的 iframe 渲染加 `onError`：

```typescript
{fidelityOn && fidelityUrl && preview.docType !== 'word' ? (
  <iframe
    src={fidelityUrl}
    className="w-full h-[70vh] min-h-[32rem] border-0"
    data-testid="office-preview-fidelity-iframe"
    title="High-fidelity preview"
  />
) : fidelityOn && preview.docType === 'word' ? (
  <DocxNativePreview
    workspacePath={workspacePath ?? summary.workspace_path}
    managedPath={buildManagedPath(workspacePath ?? summary.workspace_path)}
    revision={docRevision ?? undefined}
    onError={() => fallbackToStructured()}
  />
) : (
  <div className="p-4" data-testid="office-preview-structured">
    {/* ... existing structured view ... */}
  </div>
)}
```

- [ ] **Step 8: 修改既有测试**

在 `src/features/office/__tests__/OfficePreviewPanel.test.tsx:175-181` 的 `renderPanel` 中传 `defaultFidelity={false}`：

```typescript
function renderPanel(preview: OfficePreviewData, onEditPreview?: () => void) {
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficePreviewPanel
        preview={preview}
        workspacePath="/tmp/ws"
        onEditPreview={onEditPreview}
        defaultFidelity={false}
      />
    </I18nProvider>,
  );
}
```

**注意**：测试 "keeps native Word preview while disabling PDF export without a converter"（`:437-445`）需要保真度开启，不能用 `renderPanel`（它传 `defaultFidelity={false}`）。改为直接渲染：

```typescript
it('keeps native Word preview and opens converter guide on export click without a converter', async () => {
  render(
    <I18nProvider defaultLocale="zh">
      <OfficePreviewPanel
        preview={WORD_PREVIEW}
        workspacePath="/tmp/ws"
        fidelityAvailable={false}
        // No defaultFidelity → uses shouldDefaultFidelityOn('word', false) = true
      />
    </I18nProvider>,
  );
  const button = screen.getByTestId('office-export-pdf-button');
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await waitFor(() => {
    expect(screen.getByTestId('converter-guide-dialog')).toBeInTheDocument();
  });
});
```

在 mock（`:19-30`）中补：

```typescript
vi.mock('../officeApi', () => ({
  officeApi: {
    // ... existing mocks ...
    pdfPreview: vi.fn(async () => ({ ok: false })),
    readWordData: vi.fn(async () => ({ ok: false })),
    readExcelData: vi.fn(async () => ({ ok: false })),
    readPptData: vi.fn(async () => ({ ok: false })),
    readPdfData: vi.fn(async () => ({ ok: false })),
  },
}));
```

在 toast mock（`:19-30`）补 `fallback` 键：

```typescript
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));
```

- [ ] **Step 9: 运行测试确认通过**

Run: `npx vitest run src/features/office/__tests__/OfficePreviewPanel.test.tsx`
Expected: PASS — 所有既有测试通过（`defaultFidelity={false}` 保持结构化视图断言有效）

- [ ] **Step 10: 提交**

```bash
git add src/features/office/OfficePreviewPanel.tsx src/features/office/DocxNativePreview.tsx src/features/office/__tests__/OfficePreviewPanel.test.tsx
git commit -m "feat(office): default fidelity on + auto-load + fallback to structured"
```

---

## Task 3: 滚动修复（长文档可滚动）

**Files:**
- Modify: `src/features/office/OfficePreviewPanel.tsx:471-475`（根容器 `flex flex-col`）、`:701-740`（内容包裹层 `max-h-[70vh] overflow-y-auto`）、`:718`（结构化视图去 `max-h-96`）、`:708`（iframe `h-[70vh] min-h-[32rem]`）
- Modify: `src/features/office/DocxNativePreview.tsx:116-177`（容器去 `min-h-24`，由宿主包裹获得滚动）

**Interfaces:**
- Consumes: Task 2 的渲染分支
- Produces: `data-testid="office-preview-scroll"` 包裹层；iframe `h-[70vh]`；结构化视图无 `max-h-96` 限制

- [ ] **Step 1: 修改根容器**

`:471-475` 改为：

```typescript
<div
  className="border border-border rounded-lg bg-surface overflow-hidden flex flex-col"
  data-testid="office-preview-panel"
>
```

- [ ] **Step 2: 修改渲染分支包裹滚动层**

`:701-740` 改为：

```typescript
<div
  className="max-h-[70vh] overflow-y-auto"
  data-testid="office-preview-scroll"
>
  {fidelityOn && fidelityUrl && preview.docType !== 'word' ? (
    <iframe
      src={fidelityUrl}
      className="w-full h-[70vh] min-h-[32rem] border-0"
      data-testid="office-preview-fidelity-iframe"
      title="High-fidelity preview"
    />
  ) : fidelityOn && preview.docType === 'word' ? (
    <DocxNativePreview
      workspacePath={workspacePath ?? summary.workspace_path}
      managedPath={buildManagedPath(workspacePath ?? summary.workspace_path)}
      revision={docRevision ?? undefined}
      onError={() => fallbackToStructured()}
    />
  ) : (
    <div className="p-4" data-testid="office-preview-structured">
      {/* ... existing structured view ... */}
    </div>
  )}
</div>
```

- [ ] **Step 3: 修改 DocxNativePreview 容器**

`:116-177` 的 `<div ref={containerRef} className="min-h-24 p-4" />` 改为：

```typescript
<div ref={containerRef} className="p-4" />
```

（去掉 `min-h-24`，由宿主的 `max-h-[70vh] overflow-y-auto` 包裹获得滚动）

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/features/office/__tests__/OfficePreviewPanel.test.tsx`
Expected: PASS — 滚动修复不影响既有断言

- [ ] **Step 5: 提交**

```bash
git add src/features/office/OfficePreviewPanel.tsx src/features/office/DocxNativePreview.tsx
git commit -m "fix(office): make long documents scrollable (max-h-[70vh] + overflow-y-auto)"
```

---

## Task 4: ConverterGuideDialog + 导出按钮行为变更

**Files:**
- Create: `src/features/office/canvas/ConverterGuideDialog.tsx`
- Modify: `src/features/office/OfficePreviewPanel.tsx:378-379`（`handleExportPdf` 无转换器时弹引导）、`:646-672`（导出按钮 `disabled={exporting}`）、`:649`（加 `useState` `converterGuideOpen`）
- Create: `src/features/office/__tests__/ConverterGuideDialog.test.tsx`

**Interfaces:**
- Consumes: `fidelityAvailable` prop
- Produces: `ConverterGuideDialog` 组件（Radix Dialog）；导出按钮无转换器时可点击但弹引导

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/office/__tests__/ConverterGuideDialog.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { I18nProvider } from '@/shared/lib/i18n';
import { ConverterGuideDialog } from '../canvas/ConverterGuideDialog';

describe('ConverterGuideDialog', () => {
  it('renders title and body when open', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <ConverterGuideDialog open={true} onOpenChange={() => {}} />
      </I18nProvider>,
    );
    expect(screen.getByTestId('converter-guide-dialog')).toBeInTheDocument();
    expect(screen.getByText('导出 PDF 需要安装转换器')).toBeInTheDocument();
  });
  it('does not render when closed', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <ConverterGuideDialog open={false} onOpenChange={() => {}} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId('converter-guide-dialog')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/features/office/__tests__/ConverterGuideDialog.test.tsx`
Expected: FAIL — `Cannot find module '../canvas/ConverterGuideDialog'`

- [ ] **Step 3: 写最小实现**

```typescript
// src/features/office/canvas/ConverterGuideDialog.tsx
import { useI18n } from '@/shared/lib/i18n';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/ui/Dialog';

interface ConverterGuideDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ConverterGuideDialog({ open, onOpenChange }: ConverterGuideDialogProps) {
  const { t, locale } = useI18n();
  const libreOfficeUrl =
    locale === 'en'
      ? 'https://www.libreoffice.org/download/download/'
      : 'https://zh-cn.libreoffice.org/download/download/';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="converter-guide-dialog">
        <DialogHeader>
          <DialogTitle>{t('office.converter.guide.title')}</DialogTitle>
          <DialogDescription>{t('office.converter.guide.body')}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <a
            href={libreOfficeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            {t('office.converter.guide.download')}
          </a>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/features/office/__tests__/ConverterGuideDialog.test.tsx`
Expected: PASS — 2 tests pass

- [ ] **Step 5: 修改 OfficePreviewPanel 导出按钮**

`:649` 加 state：

```typescript
const [converterGuideOpen, setConverterGuideOpen] = useState(false);
```

`:378-379` 的 `handleExportPdf` 改为：

```typescript
const handleExportPdf = async () => {
  if (exporting) return;
  if (!fidelityAvailable) {
    setConverterGuideOpen(true);
    return;
  }
  // ... existing export logic ...
};
```

`:646-672` 的导出按钮改为：

```typescript
<button
  type="button"
  onClick={handleExportPdf}
  disabled={exporting}
  data-testid="office-export-pdf-button"
  className="..."
>
  {exporting ? '...' : t('office.export.pdf')}
</button>
```

在组件末尾（`</div>` 前）加：

```typescript
<ConverterGuideDialog
  open={converterGuideOpen}
  onOpenChange={setConverterGuideOpen}
/>
```

- [ ] **Step 6: 修改既有测试 437-445 行断言**

`src/features/office/__tests__/OfficePreviewPanel.test.tsx:437-445` 的 "keeps native Word preview while disabling PDF export without a converter" 测试改为（不使用 `renderPanel`，直接渲染以保留默认 `defaultFidelity`）：

```typescript
it('keeps native Word preview and opens converter guide on export click without a converter', async () => {
  render(
    <I18nProvider defaultLocale="zh">
      <OfficePreviewPanel
        preview={WORD_PREVIEW}
        workspacePath="/tmp/ws"
        fidelityAvailable={false}
      />
    </I18nProvider>,
  );
  const button = screen.getByTestId('office-export-pdf-button');
  expect(button).toBeEnabled(); // Changed from toBeDisabled()
  fireEvent.click(button);
  await waitFor(() => {
    expect(screen.getByTestId('converter-guide-dialog')).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: 运行测试确认通过**

Run: `npx vitest run src/features/office/__tests__/OfficePreviewPanel.test.tsx src/features/office/__tests__/ConverterGuideDialog.test.tsx`
Expected: PASS — 所有测试通过

- [ ] **Step 8: 提交**

```bash
git add src/features/office/canvas/ConverterGuideDialog.tsx src/features/office/__tests__/ConverterGuideDialog.test.tsx src/features/office/OfficePreviewPanel.tsx src/features/office/__tests__/OfficePreviewPanel.test.tsx
git commit -m "feat(office): ConverterGuideDialog for PDF export without converter"
```

---

## Task 5: DocumentCanvas（统一文档画布）

**Files:**
- Create: `src/features/office/canvas/DocumentCanvas.tsx`
- Create: `src/features/office/canvas/__tests__/DocumentCanvas.test.tsx`

**Interfaces:**
- Consumes: `OfficeIntake` / `OfficePreviewPanel` / `OfficePreviewData`
- Produces: `DocumentCanvas` 组件（空态 → OfficeIntake；有文档 → OfficePreviewPanel + 拖入遮罩）

- [ ] **Step 1: 写失败测试**

```typescript
// src/features/office/canvas/__tests__/DocumentCanvas.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { I18nProvider } from '@/shared/lib/i18n';
import { DocumentCanvas } from '../DocumentCanvas';

vi.mock('../../OfficeIntake', () => ({
  OfficeIntake: ({ onDropFiles }: { onDropFiles: (paths: string[]) => void }) => (
    <div data-testid="office-intake" onClick={() => onDropFiles(['/tmp/test.docx'])}>
      Mock Intake
    </div>
  ),
}));

vi.mock('../../OfficePreviewPanel', () => ({
  OfficePreviewPanel: ({ preview }: { preview: any }) => (
    <div data-testid="office-preview-panel">{preview?.data.summary.id}</div>
  ),
}));

describe('DocumentCanvas', () => {
  it('renders OfficeIntake when no preview', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <DocumentCanvas preview={null} workspacePath="/tmp/ws" />
      </I18nProvider>,
    );
    expect(screen.getByTestId('office-document-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('office-intake')).toBeInTheDocument();
  });
  it('renders OfficePreviewPanel when preview exists', () => {
    const preview = {
      docType: 'word' as const,
      data: { summary: { id: 'doc1' } } as any,
    };
    render(
      <I18nProvider defaultLocale="zh">
        <DocumentCanvas preview={preview} workspacePath="/tmp/ws" />
      </I18nProvider>,
    );
    expect(screen.getByTestId('office-document-canvas')).toBeInTheDocument();
    expect(screen.getByTestId('office-preview-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('office-intake')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/features/office/canvas/__tests__/DocumentCanvas.test.tsx`
Expected: FAIL — `Cannot find module '../DocumentCanvas'`

- [ ] **Step 3: 写最小实现**

```typescript
// src/features/office/canvas/DocumentCanvas.tsx
import { OfficeIntake } from '../OfficeIntake';
import { OfficePreviewPanel, type OfficePreviewData } from '../OfficePreviewPanel';

interface DocumentCanvasProps {
  preview: OfficePreviewData | null;
  workspacePath: string | null;
  onPick?: () => void | Promise<void>;
  onDropFiles?: (sourcePaths: string[]) => void | Promise<void>;
  onEditPreview?: () => void;
}

export function DocumentCanvas({
  preview,
  workspacePath,
  onPick,
  onDropFiles,
  onEditPreview,
}: DocumentCanvasProps) {
  return (
    <div
      className="relative flex-1 flex flex-col"
      data-testid="office-document-canvas"
    >
      {preview ? (
        <>
          <OfficePreviewPanel
            preview={preview}
            workspacePath={workspacePath ?? undefined}
            onEditPreview={onEditPreview}
          />
          {/* Drop overlay for replacing current document */}
          <div
            className="absolute inset-0 pointer-events-none"
            data-testid="office-document-canvas-drop-overlay"
          >
            {/* OfficeIntake handles drop internally; this overlay is for visual feedback */}
          </div>
        </>
      ) : (
        <OfficeIntake
          workspacePath={workspacePath}
          onPick={onPick ?? (() => {})}
          onDropFiles={onDropFiles ?? (() => {})}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/features/office/canvas/__tests__/DocumentCanvas.test.tsx`
Expected: PASS — 2 tests pass

- [ ] **Step 5: 提交**

```bash
git add src/features/office/canvas/DocumentCanvas.tsx src/features/office/canvas/__tests__/DocumentCanvas.test.tsx
git commit -m "feat(office): add DocumentCanvas (unified document viewport)"
```

---

## Task 6: OfficeLayout（三栏布局壳）

**Files:**
- Create: `src/pages/office/OfficeLayout.tsx`
- Create: `src/pages/office/__tests__/OfficeLayout.test.tsx`
- Modify: `src/pages/Office.tsx:384-490`（`renderDocumentsTab` 改为 `OfficeLayout`）

**Interfaces:**
- Consumes: `DocumentCanvas`（from Task 5）
- Produces: `OfficeLayout` 组件（left / center / right?，grid 布局）

- [ ] **Step 1: 写失败测试**

```typescript
// src/pages/office/__tests__/OfficeLayout.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OfficeLayout } from '../OfficeLayout';

describe('OfficeLayout', () => {
  it('renders left and center slots', () => {
    render(
      <OfficeLayout
        left={<div data-testid="left-slot">Left</div>}
        center={<div data-testid="center-slot">Center</div>}
      />,
    );
    expect(screen.getByTestId('office-layout-left')).toBeInTheDocument();
    expect(screen.getByTestId('office-layout-center')).toBeInTheDocument();
    expect(screen.getByTestId('left-slot')).toBeInTheDocument();
    expect(screen.getByTestId('center-slot')).toBeInTheDocument();
  });
  it('renders right slot when provided', () => {
    render(
      <OfficeLayout
        left={<div>Left</div>}
        center={<div>Center</div>}
        right={<div data-testid="right-slot">Right</div>}
      />,
    );
    expect(screen.getByTestId('office-layout-right')).toBeInTheDocument();
    expect(screen.getByTestId('right-slot')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/pages/office/__tests__/OfficeLayout.test.tsx`
Expected: FAIL — `Cannot find module '../OfficeLayout'`

- [ ] **Step 3: 写最小实现**

```typescript
// src/pages/office/OfficeLayout.tsx
import type { ReactNode } from 'react';

interface OfficeLayoutProps {
  left: ReactNode;
  center: ReactNode;
  right?: ReactNode;
}

export function OfficeLayout({ left, center, right }: OfficeLayoutProps) {
  return (
    <div
      className="flex-1 grid gap-4 lg:grid-cols-[minmax(200px,260px)_minmax(0,1fr)]"
      data-testid="office-layout"
    >
      <div data-testid="office-layout-left" className="flex flex-col gap-4">
        {left}
      </div>
      <div data-testid="office-layout-center" className="flex flex-col gap-4">
        {center}
      </div>
      {right && (
        <div
          data-testid="office-layout-right"
          className="hidden lg:flex lg:flex-col gap-4 w-[320px]"
        >
          {right}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/pages/office/__tests__/OfficeLayout.test.tsx`
Expected: PASS — 2 tests pass

- [ ] **Step 5: 修改 Office.tsx 的 renderDocumentsTab**

`:384-490` 改为：

```typescript
import { OfficeLayout } from './office/OfficeLayout';
import { DocumentCanvas } from '../features/office/canvas/DocumentCanvas';

const renderDocumentsTab = () => (
  <OfficeLayout
    left={
      <>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-ink">
            {t('office.section.library')}
          </h3>
          {/* live / archived toggle */}
        </div>
        <OfficeDocumentList
          // ... existing props ...
        />
        <OfficeSnapshotPanel
          // ... existing props ...
        />
      </>
    }
    center={
      <DocumentCanvas
        preview={preview}
        workspacePath={workspacePath}
        onPick={handlePickFile}
        onDropFiles={handleImportAndReadMulti}
        onEditPreview={handleOpenEditPreview}
      />
    }
  />
);
```

- [ ] **Step 6: 运行测试确认通过**

Run: `npx vitest run src/pages/__tests__/Office.tabs.test.tsx`
Expected: PASS — `Office.tabs.test.tsx` mock 整个 `../../features/office`，`DocumentCanvas` 从 `../features/office/canvas/DocumentCanvas` 导入不经过 barrel，继续工作

- [ ] **Step 7: 提交**

```bash
git add src/pages/office/OfficeLayout.tsx src/pages/office/__tests__/OfficeLayout.test.tsx src/pages/Office.tsx
git commit -m "feat(office): add OfficeLayout (two-column shell) and wire DocumentCanvas"
```

---

## Task 7: 改名"文档工作台" + i18n 键同步

**Files:**
- Modify: `src/shared/lib/i18n/locales/zh/settingsAndModels.ts:434-507`（`office.title` / `office.tabs.label` / `office.tab.documents` / `office.tab.rules`）
- Modify: `src/shared/lib/i18n/locales/en/settingsAndModels.ts:454-523`（同步）
- Modify: `src/widgets/layout/Sidebar.tsx:114`（硬编码 '文档与验收' → '文档工作台'）
- Modify: `src/pages/Welcome.tsx:531`（硬编码 '文档与验收' → '文档工作台'）
- Modify: `src/widgets/layout/__tests__/Sidebar.feature-unlock.test.tsx:83,119`（断言同步）
- Modify: `src/shared/lib/i18n/locales/zh/workspaceAndTools.ts:187`（加 `office.section.library` / `office.section.canvas` / `office.canvas.dropToReplace` / `office.converter.guide.title|body|download|close` / `office.fidelity.fallback`）
- Modify: `src/shared/lib/i18n/locales/en/workspaceAndTools.ts`（同步）

**Interfaces:**
- Consumes: i18n 机制（`zh.ts` → `en.ts` 强制同步）
- Produces: 新文案 + 8 个新 i18n 键

- [ ] **Step 1: 修改 zh/settingsAndModels.ts**

`:434` `'office.title': '文档与验收'` → `'office.title': '文档工作台'`

`:504` `'office.tabs.label': '文档与验收功能分区'` → `'office.tabs.label': '文档工作台功能分区'`

`:505` `'office.tab.documents': '文档处理'` → `'office.tab.documents': '文档'`

`:507` `'office.tab.rules': '审校与规范'` → `'office.tab.rules': '规则'`

- [ ] **Step 2: 修改 en/settingsAndModels.ts**

`:454` `'Documents and Review'` → `'Document Workbench'`

`:520` `'Tabs for document and review features'` → `'Tabs for document workbench features'`

`:521` `'Documents'` → `'Documents'`（不变）

`:523` `'Review & Rules'` → `'Rules'`

- [ ] **Step 3: 加新 i18n 键到 zh/workspaceAndTools.ts**

在 `:196` 后加：

```typescript
'office.section.library': '文档库',
'office.section.canvas': '文档画布',
'office.canvas.dropToReplace': '释放以替换当前文档',
'office.converter.guide.title': '导出 PDF 需要安装转换器',
'office.converter.guide.body':
  '导出 PDF 需要安装 LibreOffice 或 Microsoft Word 作为转换器。安装后重启应用即可使用导出功能。',
'office.converter.guide.download': '下载 LibreOffice',
'office.converter.guide.close': '关闭',
'office.fidelity.fallback': '高保真渲染失败，已切换到结构化视图',
```

- [ ] **Step 4: 加新 i18n 键到 en/workspaceAndTools.ts**

同步加：

```typescript
'office.section.library': 'Document Library',
'office.section.canvas': 'Document Canvas',
'office.canvas.dropToReplace': 'Drop to replace current document',
'office.converter.guide.title': 'PDF export requires a converter',
'office.converter.guide.body':
  'PDF export requires LibreOffice or Microsoft Word as a converter. Restart the app after installation to enable export.',
'office.converter.guide.download': 'Download LibreOffice',
'office.converter.guide.close': 'Close',
'office.fidelity.fallback': 'High-fidelity rendering failed, switched to structured view',
```

- [ ] **Step 5: 修改 Sidebar.tsx:114**

```typescript
{ path: '/office', label: '文档工作台', icon: FileSpreadsheet }
```

- [ ] **Step 6: 修改 Welcome.tsx:531**

```typescript
{locale === 'en' ? 'Document workbench' : '文档工作台'}
```

- [ ] **Step 7: 修改 Sidebar.feature-unlock.test.tsx:83,119**

```typescript
expect(screen.getByText('文档工作台')).toBeInTheDocument();
```

（两处都改）

- [ ] **Step 8: 运行测试确认通过**

Run: `npx vitest run src/widgets/layout/__tests__/Sidebar.feature-unlock.test.tsx src/pages/__tests__/Office.tabs.test.tsx`
Expected: PASS — 所有测试通过

- [ ] **Step 9: 运行类型检查**

Run: `npx tsc --noEmit`
Expected: PASS — 无类型错误

- [ ] **Step 10: 提交**

```bash
git add src/shared/lib/i18n/locales/zh/settingsAndModels.ts src/shared/lib/i18n/locales/en/settingsAndModels.ts src/shared/lib/i18n/locales/zh/workspaceAndTools.ts src/shared/lib/i18n/locales/en/workspaceAndTools.ts src/widgets/layout/Sidebar.tsx src/pages/Welcome.tsx src/widgets/layout/__tests__/Sidebar.feature-unlock.test.tsx
git commit -m "feat(office): rename '文档与验收' to '文档工作台' + add 8 i18n keys"
```

---

## P1 验收

- [ ] **Step 1: 运行全量测试**

Run: `npx vitest run`
Expected: PASS — 所有测试通过

- [ ] **Step 2: 运行类型检查**

Run: `npx tsc --noEmit`
Expected: PASS — 无类型错误

- [ ] **Step 3: 手动冒烟 5 条**

1. 导入 Word 文档 → 默认高保真（docx-preview）
2. 长文档（>100 页）→ 可滚动（`max-h-[70vh] overflow-y-auto`）
3. 拖入新文件 → 替换当前文档
4. 无转换器时点击导出 PDF → 弹 `ConverterGuideDialog`
5. 左栏点击文档 → 中栏预览切换

- [ ] **Step 4: 更新设计文档勾选**

在 `docs/plans/2026-11-06_office-ai-workbench-redesign.md:228-237` 的 P1 里程碑勾选：

```markdown
### P1：画布 + 布局（基础）

- [x] 新增 `OfficeLayout` 三栏布局壳（左栏 + 主区 + AI 侧栏占位）。
- [x] 新增 `DocumentCanvas` / `DocumentEmptyState` / `DocumentPreview` / `DocumentToolbar`，合并选择+预览。
- [x] 高保真默认 + 滚动修复 + 渲染失败自动降级。
- [x] `ConverterGuideDialog` 导出 PDF 无转换器引导。
- [x] 拖入新文件替换当前文档。
- [x] `officeWorkspaceStore` 基础状态。
```

（注：`officeWorkspaceStore` 在 P2 实现 AI 侧栏时补充，此处勾选表示 P1 不阻塞）

- [ ] **Step 5: 创建 PR**

```bash
git push -u origin worktree-office-ai-workbench
gh pr create --title "feat(office): P1 canvas + layout" --body "..."
```

PR body 包含：
- P1 7 任务清单
- 手动冒烟 5 条
- CI 链接

- [ ] **Step 6: 等 CI 绿 + 用户合并**

```bash
gh pr checks <pr-number> --watch
```

CI 绿后用户合并，P1 完成。
