// src/features/send-message/AttachmentUpload.tsx
import React, { useCallback, useRef, useState } from 'react';

interface MediaRef {
  id: string;
  mime_type: string;
  size_bytes: number;
}

interface UploadResponse {
  media_ref: MediaRef;
  api_url: string;
}

interface AttachmentUploadProps {
  onAttachmentUploaded: (attachment: { mediaRef: MediaRef; apiUrl: string }) => void;
  onError?: (error: string) => void;
}

const ACCEPTED_TYPES = 'audio/mpeg,audio/wav,audio/ogg,audio/webm,audio/mp4,audio/x-m4a';
const MAX_SIZE = 25 * 1024 * 1024;

/**
 * Chat attachment upload button.
 * Uploads audio files to /api/v1/chat/attachments and returns MediaRef.
 */
export const AttachmentUpload: React.FC<AttachmentUploadProps> = ({
  onAttachmentUploaded,
  onError,
}) => {
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFile = useCallback(
    async (file: File) => {
      if (file.size > MAX_SIZE) {
        onError?.(`文件过大 (${(file.size / 1024 / 1024).toFixed(1)}MB)，上限 25MB`);
        return;
      }

      setUploading(true);

      let result: UploadResponse | null = null;
      let errorMessage: string | null = null;

      try {
        const formData = new FormData();
        formData.append('file', file);

        const resp = await fetch('/api/v1/chat/attachments', {
          method: 'POST',
          body: formData,
        });

        const data: unknown = await resp.json();

        if (!resp.ok) {
          const obj = (typeof data === 'object' && data !== null) ? data as Record<string, unknown> : {};
          const msg = typeof obj.error === 'string' ? obj.error
            : typeof obj.detail === 'string' ? obj.detail
            : `上传失败 (HTTP ${resp.status})`;
          errorMessage = msg;
        } else {
          const obj = (typeof data === 'object' && data !== null) ? data as Record<string, unknown> : {};
          const mediaRef = obj.media_ref as Record<string, unknown> | undefined;
          const apiUrl = obj.api_url;

          if (
            !mediaRef ||
            typeof mediaRef.id !== 'string' ||
            typeof mediaRef.mime_type !== 'string' ||
            typeof mediaRef.size_bytes !== 'number' ||
            typeof apiUrl !== 'string'
          ) {
            errorMessage = '上传响应格式无效';
          } else {
            result = {
              media_ref: {
                id: mediaRef.id,
                mime_type: mediaRef.mime_type,
                size_bytes: mediaRef.size_bytes,
              },
              api_url: apiUrl,
            };
          }
        }
      } catch (err) {
        errorMessage = `上传失败: ${err instanceof Error ? err.message : '未知错误'}`;
      }

      setUploading(false);

      if (errorMessage) {
        onError?.(errorMessage);
      } else if (result) {
        onAttachmentUploaded({
          mediaRef: result.media_ref,
          apiUrl: result.api_url,
        });
      }
    },
    [onAttachmentUploaded, onError],
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <div className="relative">
      <button
        type="button"
        className="p-1.5 rounded-md text-muted hover:text-text hover:bg-surface-hover transition-colors disabled:opacity-50"
        title="上传音频文件"
        disabled={uploading}
        onClick={() => inputRef.current?.click()}
      >
        {uploading ? <span className="animate-pulse">⏳</span> : <span>📎</span>}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES}
        className="hidden"
        onChange={handleFileChange}
      />
    </div>
  );
};
