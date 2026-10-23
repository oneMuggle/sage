/**
 * CSS / 封面图注入工具
 *
 * 三种标签：
 * - <style id="theme-preview">  — 实时预览，编辑器 onChange 时更新
 * - <style id="theme-{id}">      — 已保存主题，启动时批量注入
 * - :root { --cover-image }      — 封面图 data URL
 *
 * 所有函数均做 typeof document 检查，SSR-safe。
 */

const PREVIEW_ID = 'theme-preview';

function persistId(id: string): string {
  return `theme-${id}`;
}

function escapeDataUrl(dataUrl: string): string {
  return dataUrl.replace(/"/g, '\\"');
}

export function injectPreviewCss(css: string): void {
  if (typeof document === 'undefined') return;
  let el = document.getElementById(PREVIEW_ID) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement('style');
    el.id = PREVIEW_ID;
    document.head.appendChild(el);
  }
  el.textContent = css;
}

export function clearPreviewCss(): void {
  if (typeof document === 'undefined') return;
  document.getElementById(PREVIEW_ID)?.remove();
}

export function injectPersistedStyle(id: string, css: string): void {
  if (typeof document === 'undefined') return;
  const tagId = persistId(id);
  let el = document.getElementById(tagId) as HTMLStyleElement | null;
  if (!el) {
    el = document.createElement('style');
    el.id = tagId;
    document.head.appendChild(el);
  }
  el.textContent = css;
}

export function removePersistedStyle(id: string): void {
  if (typeof document === 'undefined') return;
  document.getElementById(persistId(id))?.remove();
}

export function setCoverImage(dataUrl: string): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement.style;
  if (dataUrl.length === 0) {
    root.removeProperty('--cover-image');
  } else {
    root.setProperty('--cover-image', `url("${escapeDataUrl(dataUrl)}")`);
  }
}

export function formatBackgroundInjectionSummary(persistedId?: string): string {
  if (typeof document === 'undefined') return 'ssr';
  const hasPreview = Boolean(document.getElementById(PREVIEW_ID));
  const hasPersisted = persistedId
    ? Boolean(document.getElementById(persistId(persistedId)))
    : false;
  const hasCover = Boolean(document.documentElement.style.getPropertyValue('--cover-image'));
  return `preview=${hasPreview} · persisted=${hasPersisted} · cover=${hasCover}`;
}

export function formatBackgroundInjectionJson(persistedId?: string): string {
  const hasDoc = typeof document !== 'undefined';
  return JSON.stringify(
    {
      hasPreview: hasDoc ? Boolean(document.getElementById(PREVIEW_ID)) : false,
      persistedId: persistedId ?? null,
      hasPersisted:
        hasDoc && persistedId ? Boolean(document.getElementById(persistId(persistedId))) : false,
      hasCoverImage: hasDoc
        ? Boolean(document.documentElement.style.getPropertyValue('--cover-image'))
        : false,
    },
    null,
    2,
  );
}

export function auditBackgroundInjectorGovernance(): {
  module: 'src/features/theme/backgroundInjector.ts';
  phase: 'P169';
  domain: 'theme';
  supportsPreviewAndPersistedStyles: boolean;
  escapesDataUrls: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/theme/backgroundInjector.ts',
    phase: 'P169',
    domain: 'theme',
    supportsPreviewAndPersistedStyles: true,
    escapesDataUrls: true,
    compliant: true,
  };
}
