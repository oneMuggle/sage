import { useState, useCallback } from 'react';

export interface AttachedFile {
  name: string;
  size: number;
  type: string;
  dataUrl?: string;
}

interface UseFileUploadReturn {
  files: AttachedFile[];
  images: AttachedFile[];
  addFile: (file: File) => void;
  addImage: (file: File) => void;
  removeFile: (index: number) => void;
  removeImage: (index: number) => void;
  clearAll: () => void;
  handleDrop: (e: React.DragEvent) => void;
  handleDragOver: (e: React.DragEvent) => void;
  /** U13: 剪贴板粘贴图片（无图片时放行为默认粘贴文本） */
  handlePaste: (e: React.ClipboardEvent) => void;
  isDragOver: boolean;
}

export function useFileUpload(): UseFileUploadReturn {
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const [images, setImages] = useState<AttachedFile[]>([]);
  const [isDragOver, setIsDragOver] = useState(false);

  const addFile = useCallback((file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      setFiles((prev) => [
        ...prev,
        { name: file.name, size: file.size, type: file.type, dataUrl: reader.result as string },
      ]);
    };
    reader.readAsDataURL(file);
  }, []);

  const addImage = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) return;
    const reader = new FileReader();
    reader.onload = () => {
      setImages((prev) => [
        ...prev,
        { name: file.name, size: file.size, type: file.type, dataUrl: reader.result as string },
      ]);
    };
    reader.readAsDataURL(file);
  }, []);

  const removeFile = useCallback((index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const removeImage = useCallback((index: number) => {
    setImages((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearAll = useCallback(() => {
    setFiles([]);
    setImages([]);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      const droppedFiles = Array.from(e.dataTransfer.files);
      droppedFiles.forEach((file) => {
        if (file.type.startsWith('image/')) {
          addImage(file);
        } else {
          addFile(file);
        }
      });
    },
    [addFile, addImage],
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  // U13 (对标增强第二轮批次 B): 剪贴板粘贴图片 — 与拖放/按钮上传同管道
  // (G6 images 附件)。剪贴板无图片时不 preventDefault,保持默认文本粘贴。
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData?.items ?? []);
      const imageFiles = items
        .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (imageFiles.length === 0) return;
      e.preventDefault();
      imageFiles.forEach((file) => addImage(file));
    },
    [addImage],
  );

  return {
    files,
    images,
    addFile,
    addImage,
    removeFile,
    removeImage,
    clearAll,
    handleDrop,
    handleDragOver,
    handlePaste,
    isDragOver,
  };
}
