// src/widgets/chat/MarkdownImage.tsx
//
// P1 (UI 优化方案 2026-09-13): markdown 图片的自定义渲染 ——
// 此前走 react-markdown 默认 <img>：加载期零反馈、失败无占位、点击无放大。
// - 加载骨架 + onload 渐入（opacity transition）
// - 失败占位
// - 点击进统一 Lightbox（缩放/平移）
// - /api/v1/media/* 路径: Electron 下 <img> 无法携带 local-auth Bearer 头，
//   走 fetchMediaBlobUrl（IPC relay 注入 token）换 blob: URL（与
//   MediaAttachment 同一通道）；浏览器 dev 无 bridge 时回退直连。

import { useEffect, useState } from 'react';

import { fetchMediaBlobUrl, revokeMediaBlobUrl } from '../../shared/api/mediaApi';
import { buildLocalImageSrc } from '../../shared/lib/localImageSrc';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';
import { Lightbox } from '../../shared/ui';

type LoadStatus = 'loading' | 'loaded' | 'error';

export function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  // P9: 工作区绑定（用于相对路径 → 绝对路径拼接）
  const workspacePath = useCurrentWorkspace();

  const isLocalMedia = typeof src === 'string' && src.startsWith('/api/');
  useEffect(() => {
    if (!isLocalMedia || !src) return;
    const mediaId = src.split('/').filter(Boolean).pop() ?? '';
    if (!window.electronAPI?.backendRequest || !mediaId) return;
    let cancelled = false;
    fetchMediaBlobUrl(mediaId)
      .then((u) => {
        if (!cancelled) setBlobUrl(u);
      })
      .catch(() => {
        if (!cancelled) setBlobUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isLocalMedia, src]);

  // blob URL 释放，避免内存泄漏
  useEffect(() => {
    return () => {
      if (blobUrl) revokeMediaBlobUrl(blobUrl);
    };
  }, [blobUrl]);

  if (!src) return null;
  // P9: 本地路径转 sage-file:// URL（主进程校验工作区包含 + 扩展名白名单）
  const resolved = buildLocalImageSrc(blobUrl ?? src, workspacePath) || src;

  return (
    <span className="relative inline-block align-top my-1">
      {status === 'loading' && (
        <span
          data-testid="markdown-image-skeleton"
          className="flex w-64 h-40 rounded bg-bg-subtle border border-border animate-pulse items-center justify-center text-xs text-muted"
        >
          加载图片…
        </span>
      )}
      {status === 'error' ? (
        <span
          data-testid="markdown-image-error"
          className="flex w-64 h-24 rounded bg-bg-subtle border border-border items-center justify-center text-xs text-muted"
        >
          图片加载失败
        </span>
      ) : (
        <img
          src={resolved}
          alt={alt ?? ''}
          draggable={false}
          data-testid="markdown-image"
          onLoad={() => setStatus('loaded')}
          onError={() => setStatus('error')}
          // 未加载完成时绝对定位叠在骨架上（透明），加载后渐入并撑开布局
          className={`max-w-full rounded border border-border cursor-zoom-in transition-opacity duration-300 ${
            status === 'loaded' ? 'opacity-100' : 'absolute inset-0 opacity-0'
          }`}
          onClick={() => setLightboxOpen(true)}
        />
      )}
      {lightboxOpen && status === 'loaded' && (
        <Lightbox src={resolved} alt={alt} onClose={() => setLightboxOpen(false)} />
      )}
    </span>
  );
}
