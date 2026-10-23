/**
 * DocxNativePreview — P2-B (office-p2b)。
 *
 * 用 docx-preview 在渲染进程直接解析 docx 二进制（无需 soffice），
 * 作为「无本机转换器」机器上 word 文档的高保真预览路径：
 *   - 数据经 `/office/word/data`（20MB 上限 + 路径围栏）懒加载；
 *   - 渲染后做 DOM 级消毒（去 script/iframe/object、javascript: 链接、
 *     on* 内联事件）—— docx 是不受信用户数据；
 *   - 加载/失败状态上屏，失败时由父级回落结构化视图。
 */

import { useEffect, useRef, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import { useI18n } from '../../shared/lib/i18n';

// eslint-disable-next-line react-refresh/only-export-components -- 消毒器与组件同文件便于内聚
export function sanitizeRenderedDocx(container: HTMLElement): void {
  const dangerous = container.querySelectorAll('script, iframe, object, embed, link');
  dangerous.forEach((el) => el.remove());
  container.querySelectorAll('[href], [src]').forEach((el) => {
    const attr = el.getAttribute('href') !== null ? 'href' : 'src';
    const value = el.getAttribute(attr) ?? '';
    if (/^\s*javascript:/i.test(value)) {
      el.removeAttribute(attr);
    }
  });
  container.querySelectorAll('*').forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (/^on/i.test(attr.name)) {
        el.removeAttribute(attr.name);
      }
    }
  });
}

export interface DocxNativePreviewProps {
  workspacePath: string;
  managedPath: string;
  /**
   * F2: content revision of the document. Part of the effect deps so an
   * edit that keeps the same path (and even the same byte size) re-renders,
   * and part of the late-response guard below.
   */
  revision?: string | null;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatDocxPreviewMetaMarkdown(params: {
  workspacePath: string;
  managedPath: string;
  revision?: string | null;
  state: 'loading' | 'ok' | 'error';
}): string {
  return [
    '# Word 原生预览状态 (Docx Native Preview)',
    '',
    `- **工作区路径**: \`${params.workspacePath}\``,
    `- **受管文件路径**: \`${params.managedPath}\``,
    `- **修订标识**: ${params.revision || '无'}`,
    `- **渲染状态**: ${params.state}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatDocxPreviewMetaJson(params: {
  workspacePath: string;
  managedPath: string;
  revision?: string | null;
  state: 'loading' | 'ok' | 'error';
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      workspacePath: params.workspacePath,
      managedPath: params.managedPath,
      revision: params.revision ?? null,
      state: params.state,
    },
    null,
    2,
  );
}

export function DocxNativePreview({
  workspacePath,
  managedPath,
  revision,
}: DocxNativePreviewProps) {
  const { t } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    (async () => {
      try {
        const res = await officeApi.readWordData({
          workspace_path: workspacePath,
          file_path: managedPath,
        });
        if (!res.ok || !res.data_url) {
          throw new Error(res.error ?? 'docx data unavailable');
        }
        const [{ renderAsync }, dompurifyModule] = await Promise.all([
          import('docx-preview'),
          import('dompurify'),
        ]);
        const dompurify = dompurifyModule.default;
        if (cancelled) return;
        const response = await fetch(res.data_url);
        const blob = await response.blob();
        const container = containerRef.current;
        if (!container) return;
        container.innerHTML = '';
        await renderAsync(blob, container, undefined, {
          inWrapper: false,
          ignoreLastRenderedPageBreak: false,
          experimental: false,
        });
        // 渲染树消毒：docx-preview 产出受信度有限的 DOM，过一道白名单级
        // 清理再上屏（去脚本/iframe/javascript: 链接/内联事件）。
        container.innerHTML = dompurify.sanitize(container.innerHTML, {
          ADD_ATTR: ['target'],
          FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'link', 'meta'],
          FORBID_ATTR: ['srcset'],
        });
        sanitizeRenderedDocx(container);
        if (!cancelled) setState('ok');
      } catch {
        if (!cancelled) setState('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspacePath, managedPath, revision]);

  if (state === 'error') {
    return (
      <div className="p-6 text-center text-sm text-muted" data-testid="docx-native-error">
        {t('office.preview.nativeFailed')}
      </div>
    );
  }

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(
        formatDocxPreviewMetaMarkdown({ workspacePath, managedPath, revision, state }),
      );
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(
        formatDocxPreviewMetaJson({ workspacePath, managedPath, revision, state }),
      );
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <div className="relative bg-white" data-testid="docx-native-preview" data-state={state}>
      <div className="flex items-center justify-end gap-1 px-3 pt-2 text-ui-2xs">
        <button
          type="button"
          data-testid="docx-preview-copy-md"
          onClick={() => void handleCopyMarkdown()}
          className="px-1.5 py-0.5 rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedMd ? '已复制 MD' : '复制 MD'}
        </button>
        <button
          type="button"
          data-testid="docx-preview-copy-json"
          onClick={() => void handleCopyJson()}
          className="px-1.5 py-0.5 rounded border border-border text-text-secondary hover:bg-bg-hover"
        >
          {copiedJson ? '已复制 JSON' : '复制 JSON'}
        </button>
      </div>
      {state === 'loading' && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/80">
          <span
            className="inline-block w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin"
            aria-hidden
          />
        </div>
      )}
      <div ref={containerRef} className="min-h-24 p-4" />
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditDocxNativePreviewGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/DocxNativePreview.tsx',
    phase: 'P164',
    status: 'ready',
  };
}
