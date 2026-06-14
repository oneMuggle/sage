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
    isDragOver,
  };
}
