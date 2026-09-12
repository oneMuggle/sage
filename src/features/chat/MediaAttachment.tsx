// src/features/chat/MediaAttachment.tsx
import React, { useState } from 'react';

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
 * - image/* → <img> with click-to-zoom
 * - audio/* → <audio controls>
 * - fallback → download link
 */
export const MediaAttachment: React.FC<MediaAttachmentProps> = ({ url, mimeType, caption }) => {
  const [zoomed, setZoomed] = useState(false);

  if (mimeType.startsWith('image/')) {
    return (
      <>
        <div className="my-2">
          <img
            src={url}
            alt={caption || 'Generated image'}
            className="max-w-sm rounded-lg cursor-pointer hover:opacity-90 transition-opacity"
            onClick={() => setZoomed(true)}
          />
          {caption && <p className="text-xs text-muted mt-1">{caption}</p>}
        </div>
        {zoomed && (
          <div
            className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
            onClick={() => setZoomed(false)}
          >
            <img
              src={url}
              alt={caption || 'Generated image'}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        )}
      </>
    );
  }

  if (mimeType.startsWith('audio/')) {
    return (
      <div className="my-2">
        <audio controls src={url} className="max-w-sm w-full">
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
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm text-accent hover:underline"
      >
        📎 {caption || 'Download media'}
      </a>
    </div>
  );
};
