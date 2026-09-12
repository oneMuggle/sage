// src/features/send-message/AttachmentUpload.tsx
import React, { useCallback, useRef, useState } from 'react';

interface AttachmentUploadProps {
  onAttachmentUploaded: (attachment: { mediaRef: any; apiUrl: string }) => void;
  onError?: (error: string) => void;
}

const ACCEPTED_TYPES = 'audio/mpeg,audio/wav,audio/ogg,audio/webm,audio/mp4,audio/x-m4a';
const MAX_SIZE = 25 * 1024 * 1024;

/**
 * Chat attachment upload button with drag-and-drop support.
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
      try {
        const formData = new FormData();
        formData.append('file', file);

        const resp = await fetch('/api/v1/chat/attachments', {
          method: 'POST',
          body: formData,
        });

        const data = await resp.json();
        if (data.error) {
          onError?.(data.error);
          return;
        }

        onAttachmentUploaded({
          mediaRef: data.media_ref,
          apiUrl: data.api_url,
        });
      } catch (err) {
        onError?.(`上传失败: ${err instanceof Error ? err.message : '未知错误'}`);
      } finally {
        setUploading(false);
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
        {uploading ? (
          <span className="animate-pulse">⏳</span>
        ) : (
          <span>📎</span>
        )}
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
