// src/features/chat/MediaAttachment.tsx
import React, { useState, useEffect } from 'react';

import { fetchMediaBlobUrl, resolveMediaUrl, revokeMediaBlobUrl } from '../../shared/api/mediaApi';
import { Lightbox } from '../../shared/ui';

interface MediaAttachmentProps {
  /** API URL like /api/v1/media/{id} */
  url: string;
  /** MIME type e.g. "image/png", "audio/mpeg" */
  mimeType: string;
  /** Optional alt text / caption */
  caption?: string;
}

/**
 * Renders a media attachment in chat messages.
 * - image/* → <img> with click-to-zoom (统一 Lightbox: 缩放/平移/ESC)
 * - audio/* → <audio controls>
 * - fallback → download link
 */
export const MediaAttachment: React.FC<MediaAttachmentProps> = ({ url, mimeType, caption }) => {
  const [zoomed, setZoomed] = useState(false);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  // P1: blob 拉取期间的加载骨架（Electron 走 IPC relay，可能有几百 ms 延迟）
  const [resolving, setResolving] = useState(false);

  // R22-D1: Electron 下 <img src>/<audio src> 无法携带 local-auth Bearer 头
  // → 生产中间件 401（媒体永远渲染失败）。改走 fetchMediaBlobUrl（IPC
  // relay 注入 token）拿 blob: URL；纯浏览器 dev（无 bridge）回退直连
  // URL（Vite proxy + dev 无鉴权）。
  useEffect(() => {
    let cancelled = false;
    const mediaId = url.split('/').filter(Boolean).pop() ?? '';
    const bridge = window.electronAPI?.backendRequest;
    if (bridge && mediaId) {
      setResolving(true);
      fetchMediaBlobUrl(mediaId, mimeType)
        .then((u) => {
          if (!cancelled) setBlobUrl(u);
        })
        .catch(() => {
          if (!cancelled) setBlobUrl(null);
        })
        .finally(() => {
          if (!cancelled) setResolving(false);
        });
    } else {
      setBlobUrl(null);
      setResolving(false);
    }
    return () => {
      cancelled = true;
    };
  }, [url, mimeType]);

  // 替换/卸载时释放 blob，避免内存泄漏
  useEffect(() => {
    return () => {
      if (blobUrl) revokeMediaBlobUrl(blobUrl);
    };
  }, [blobUrl]);

  const resolvedUrl = blobUrl ?? resolveMediaUrl(url);

  if (mimeType.startsWith('image/')) {
    return (
      <>
        <div className="my-2">
          {resolving && !blobUrl ? (
            // P1: 加载骨架占位（此前 blob 拉取期无任何反馈）
            <div
              data-testid="media-attachment-skeleton"
              className="w-64 h-40 rounded-lg bg-bg-subtle border border-border animate-pulse"
            />
          ) : (
            <img
              src={resolvedUrl}
              alt={caption || 'Generated image'}
              className="max-w-sm rounded-lg cursor-zoom-in hover:opacity-90 transition-opacity"
              onClick={() => setZoomed(true)}
            />
          )}
          {caption && <p className="text-xs text-muted mt-1">{caption}</p>}
        </div>
        {zoomed && (
          <Lightbox src={resolvedUrl} alt={caption || 'Generated image'} onClose={() => setZoomed(false)} />
        )}
      </>
    );
  }

  if (mimeType.startsWith('audio/')) {
    return (
      <div className="my-2">
        <audio controls src={resolvedUrl} className="max-w-sm w-full">
          Your browser does not support audio playback.
        </audio>
        {caption && <p className="text-xs text-muted mt-1">{caption}</p>}
      </div>
    );
  }

  // Fallback: download link
  return (
    <div className="my-2">
      <a
        href={resolvedUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm text-accent hover:underline"
      >
        📎 {caption || 'Download media'}
      </a>
    </div>
  );
};
