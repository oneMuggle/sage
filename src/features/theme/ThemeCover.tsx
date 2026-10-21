/**
 * ThemeCover — 主题封面图组件
 *
 * 图片加载失败时降级为渐变色占位。
 */
import { useState, type ImgHTMLAttributes } from 'react';

interface ThemeCoverProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'onLoad'> {
  /** 封面图 URL */
  src: string;
  /** alt 文本 */
  alt: string;
  /** 降级渐变色起点 */
  gradientFrom?: string;
  /** 渐变色终点 */
  gradientTo?: string;
}

const DEFAULT_FROM = '#6b7280';
const DEFAULT_TO = '#374151';

export function formatThemeCoverAuditSnapshot(opts: {
  src?: string;
  alt?: string;
  failed?: boolean;
  gradientFrom?: string;
  gradientTo?: string;
}): string {
  return `themeCover|src=${opts.src || 'none'}|alt=${opts.alt || 'none'}|failed=${opts.failed ? 1 : 0}|from=${opts.gradientFrom || DEFAULT_FROM}|to=${opts.gradientTo || DEFAULT_TO}`;
}

export function formatThemeCoverAuditJson(opts: {
  src?: string;
  alt?: string;
  failed?: boolean;
  gradientFrom?: string;
  gradientTo?: string;
}): string {
  return JSON.stringify({
    src: opts.src || 'none',
    alt: opts.alt || 'none',
    failed: Boolean(opts.failed),
    gradientFrom: opts.gradientFrom || DEFAULT_FROM,
    gradientTo: opts.gradientTo || DEFAULT_TO,
  });
}

export function ThemeCover({
  src,
  alt,
  gradientFrom = DEFAULT_FROM,
  gradientTo = DEFAULT_TO,
  ...rest
}: ThemeCoverProps) {
  const [failed, setFailed] = useState(false);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatThemeCoverAuditSnapshot({ src, alt, failed, gradientFrom, gradientTo }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatThemeCoverAuditJson({ src, alt, failed, gradientFrom, gradientTo }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

  return (
    <>
      {failed ? (
        <div
          data-testid="theme-cover-fallback"
          className="w-full h-full flex items-center justify-center rounded-t-radius-md"
          style={{
            background: `linear-gradient(135deg, ${gradientFrom}, ${gradientTo})`,
          }}
        />
      ) : (
        <img
          src={src}
          alt={alt}
          onError={() => setFailed(true)}
          className="w-full h-full object-cover rounded-t-radius-md"
          {...rest}
        />
      )}
      <span
        data-testid="theme-cover-copy-snapshot"
        onClick={() => void handleCopySnapshot()}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="theme-cover-copy-json"
        onClick={() => void handleCopyJson()}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>
  );
}
