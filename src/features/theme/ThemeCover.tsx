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

export function ThemeCover({
  src,
  alt,
  gradientFrom = DEFAULT_FROM,
  gradientTo = DEFAULT_TO,
  ...rest
}: ThemeCoverProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div
        data-testid="theme-cover-fallback"
        className="w-full h-full flex items-center justify-center rounded-t-radius-md"
        style={{
          background: `linear-gradient(135deg, ${gradientFrom}, ${gradientTo})`,
        }}
      />
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      onError={() => setFailed(true)}
      className="w-full h-full object-cover rounded-t-radius-md"
      {...rest}
    />
  );
}
