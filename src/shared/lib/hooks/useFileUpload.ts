import { useState, useCallback, useRef, useEffect } from 'react';

/** r75/r76: 聊天文档附件支持的扩展名（Chat.tsx 上传白名单与 ChatInput
 * 提示条件共用，避免两处口径漂移）。
 * 2026-10-13: 扩展覆盖常见编程语言、配置、数据格式，与后端
 * ALLOWED_TEXT_EXTENSIONS + ALLOWED_DOC_EXTENSIONS 同口径。 */
export const CHAT_DOCUMENT_EXTENSIONS = new Set([
  // 基础文本
  'txt',
  'md',
  'csv',
  // 编程语言
  'py',
  'js',
  'ts',
  'jsx',
  'tsx',
  'java',
  'go',
  'rs',
  'rb',
  'php',
  'c',
  'cpp',
  'h',
  'hpp',
  'cs',
  'swift',
  'kt',
  'scala',
  'r',
  // 前端
  'html',
  'css',
  'scss',
  'less',
  'vue',
  'svelte',
  // 数据/配置
  'json',
  'yaml',
  'yml',
  'xml',
  'toml',
  'ini',
  'cfg',
  'conf',
  // 脚本/构建
  'sh',
  'bash',
  'bat',
  'ps1',
  'sql',
  'makefile',
  'cmake',
  'gradle',
  // 特殊命名
  'dockerfile',
  'gitignore',
  'properties',
  // 日志
  'log',
  // 二进制文档（需后端解析）
  'pdf',
  'docx',
  'xlsx',
]);
/** r78: 文件选择器 accept 提示（与 CHAT_DOCUMENT_EXTENSIONS 同口径）。
 * 仅列最常见的扩展名以保持对话框简洁，实际验证由后端完成。 */
export const CHAT_DOCUMENT_ACCEPT = [
  '.txt',
  '.md',
  '.csv',
  '.pdf',
  '.docx',
  '.xlsx',
  '.json',
  '.yaml',
  '.yml',
  '.xml',
  '.html',
  '.css',
  '.py',
  '.js',
  '.ts',
  '.jsx',
  '.tsx',
  '.java',
  '.go',
  '.rs',
  '.sh',
  '.bash',
  '.bat',
  '.sql',
  '.log',
  '.ini',
  '.cfg',
  '.conf',
  '.toml',
].join(',');

// P2 (2026-11-04): 前端预检硬限制 —— 与后端 `MAX_ATTACHMENT_SIZE` / 注入循环
// `[:10]` 同口径；在 selection 阶段就拒绝，而不是上传后才 toast。
export const MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024; // 25 MB
export const MAX_ATTACHMENT_COUNT = 10;

/**
 * P2: 预检单个文件是否可加入附件列表。
 *
 * - 大小 > 25MB → 'oversize'
 * - 非图片且扩展名不在 `CHAT_DOCUMENT_EXTENSIONS` → 'unsupported'
 * - 同名文件已存在 → 'duplicate'（调用方决定是否替换）
 */
export function preflightAttachment(
  file: File,
  existing: ReadonlyArray<{ name: string }>,
  kind: 'file' | 'image',
  totalCount: number,
):
  | { ok: true }
  | {
      ok: false;
      reason: 'oversize' | 'unsupported' | 'duplicate' | 'count_exceeded';
    } {
  if (totalCount >= MAX_ATTACHMENT_COUNT) return { ok: false, reason: 'count_exceeded' };
  if (file.size > MAX_ATTACHMENT_SIZE) return { ok: false, reason: 'oversize' };
  if (kind === 'file') {
    const ext = (file.name.split('.').pop() ?? '').toLowerCase();
    if (!ext || !CHAT_DOCUMENT_EXTENSIONS.has(ext)) {
      return { ok: false, reason: 'unsupported' };
    }
  } else if (!file.type.startsWith('image/')) {
    return { ok: false, reason: 'unsupported' };
  }
  if (existing.some((e) => e.name === file.name)) {
    return { ok: false, reason: 'duplicate' };
  }
  return { ok: true };
}

export interface AttachedFile {
  name: string;
  size: number;
  type: string;
  dataUrl?: string;
  /**
   * P1 (2026-11-04): 选中即上传得到的 media id（Electron 环境）。
   * 无 electronAPI 时保持 undefined，由发送路径兜底上传（向后兼容）。
   */
  mediaId?: string;
  /** P1: 上传状态；无 electronAPI 时停留在 'ready'。 */
  status?: 'reading' | 'ready' | 'uploading' | 'uploaded' | 'failed';
  /** P1: 上传失败原因（仅 status='failed' 时）。 */
  reason?: string;
  /** P1: 内部标识，用于异步上传完成时精确更新对应条目。 */
  id?: string;
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

  // P2 (2026-11-04): preflight 需要在 addFile/addImage 内读取"当前"条数,
  // 而 setState 是异步的, 直接读 state 会拿到闭包里的陈旧值 ——
  // 用 ref 保存最新值, 供 preflight 同步查询。
  const filesRef = useRef<AttachedFile[]>([]);
  const imagesRef = useRef<AttachedFile[]>([]);
  useEffect(() => {
    filesRef.current = files;
  }, [files]);
  useEffect(() => {
    imagesRef.current = images;
  }, [images]);

  /** 新建一个 status='ready' 的占位条目（dataUrl 异步回填）。 */
  const makeReadyStub = (file: File): AttachedFile => ({
    id: crypto.randomUUID(),
    name: file.name,
    size: file.size,
    type: file.type,
    status: 'ready',
  });

  /** 触发 P1 选中即上传（仅 Electron 环境）；失败时把该条目标为 failed。 */
  const startEagerUpload = (
    file: File,
    id: string,
    setTarget: React.Dispatch<React.SetStateAction<AttachedFile[]>>,
  ) => {
    const upload = window.electronAPI?.media?.uploadAttachment;
    if (!upload) return;
    const contentType = file.type || 'application/octet-stream';
    setTarget((prev) => prev.map((f) => (f.id === id ? { ...f, status: 'uploading' } : f)));
    void (async () => {
      try {
        const buffer = await file.arrayBuffer();
        const res = (await upload(buffer, file.name, contentType)) as
          | { media_ref?: { id?: string } }
          | undefined;
        const mediaId = res?.media_ref?.id;
        if (!mediaId) throw new Error('上传响应缺少 media_ref.id');
        setTarget((prev) =>
          prev.map((f) => (f.id === id ? { ...f, status: 'uploaded', mediaId } : f)),
        );
      } catch (err) {
        setTarget((prev) =>
          prev.map((f) =>
            f.id === id
              ? {
                  ...f,
                  status: 'failed',
                  reason: err instanceof Error ? err.message : String(err),
                }
              : f,
          ),
        );
      }
    })();
  };

  const addFile = useCallback((file: File) => {
    // P2 (2026-11-04): 预检 —— 大小/扩展名/数量/重复名在 selection 阶段就失败，
    // 用红标 chip 显示原因，而不是上传后才 toast。
    const current = [...filesRef.current, ...imagesRef.current];
    const check = preflightAttachment(file, current, 'file', current.length);
    if (!check.ok) {
      if (check.reason === 'duplicate') {
        // 同名文件替换 —— 主流应用行为。避免在 setState updater 内产生副作用
        // （StrictMode 会双调用 updater），FileReader 放在外面。
        const stub = makeReadyStub(file);
        setFiles((prev) => [...prev.filter((f) => f.name !== file.name), stub]);
        const reader = new FileReader();
        reader.onload = () => {
          setFiles((p) =>
            p.map((f) => (f.id === stub.id ? { ...f, dataUrl: reader.result as string } : f)),
          );
          startEagerUpload(file, stub.id as string, setFiles);
        };
        reader.readAsDataURL(file);
        return;
      }
      setFiles((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          name: file.name,
          size: file.size,
          type: file.type,
          status: 'failed',
          reason: check.reason,
        },
      ]);
      return;
    }
    const stub = makeReadyStub(file);
    setFiles((prev) => [...prev, stub]);
    const reader = new FileReader();
    reader.onload = () => {
      setFiles((prev) =>
        prev.map((f) => (f.id === stub.id ? { ...f, dataUrl: reader.result as string } : f)),
      );
      startEagerUpload(file, stub.id as string, setFiles);
    };
    reader.readAsDataURL(file);
  }, []);

  const addImage = useCallback((file: File) => {
    // 非图片静默忽略 —— 与旧实现一致（图片通道只接受 image/*）。
    if (!file.type.startsWith('image/')) return;
    const current = [...filesRef.current, ...imagesRef.current];
    const check = preflightAttachment(file, current, 'image', current.length);
    if (!check.ok) {
      if (check.reason === 'duplicate') {
        const stub = makeReadyStub(file);
        setImages((prev) => [...prev.filter((f) => f.name !== file.name), stub]);
        const reader = new FileReader();
        reader.onload = () => {
          setImages((p) =>
            p.map((f) => (f.id === stub.id ? { ...f, dataUrl: reader.result as string } : f)),
          );
        };
        reader.readAsDataURL(file);
        return;
      }
      setImages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          name: file.name,
          size: file.size,
          type: file.type,
          status: 'failed',
          reason: check.reason,
        },
      ]);
      return;
    }
    const stub = makeReadyStub(file);
    setImages((prev) => [...prev, stub]);
    const reader = new FileReader();
    reader.onload = () => {
      setImages((prev) =>
        prev.map((f) => (f.id === stub.id ? { ...f, dataUrl: reader.result as string } : f)),
      );
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
  // (G6 images 附件)。剪贴板无文件时不 preventDefault,保持默认文本粘贴。
  // P2 (2026-11-04): 扩展为粘贴任意文件（非图片走 addFile 文档通道）。
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = Array.from(e.clipboardData?.items ?? []);
      const pastedFiles = items
        .filter((item) => item.kind === 'file')
        .map((item) => item.getAsFile())
        .filter((file): file is File => file !== null);
      if (pastedFiles.length === 0) return;
      e.preventDefault();
      pastedFiles.forEach((file) => {
        if (file.type.startsWith('image/')) addImage(file);
        else addFile(file);
      });
    },
    [addFile, addImage],
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

export function formatFileUploadSummary(
  files: AttachedFile[] = [],
  images: AttachedFile[] = [],
  isDragOver = false,
): string {
  /* v8 ignore start */
  const safeFiles = Array.isArray(files) ? files : [];
  const safeImages = Array.isArray(images) ? images : [];
  const totalBytes = [...safeFiles, ...safeImages].reduce((acc, f) => acc + (f.size || 0), 0);
  const state = isDragOver ? 'drag-over' : 'idle';
  /* v8 ignore stop */
  return `upload: ${safeFiles.length} files · ${safeImages.length} images · ${totalBytes} B · ${state}`;
}

export function formatFileUploadJson(
  files: AttachedFile[] = [],
  images: AttachedFile[] = [],
  isDragOver = false,
): string {
  /* v8 ignore start */
  const safeFiles = Array.isArray(files) ? files : [];
  const safeImages = Array.isArray(images) ? images : [];
  const totalBytes = [...safeFiles, ...safeImages].reduce((acc, f) => acc + (f.size || 0), 0);
  /* v8 ignore stop */
  return JSON.stringify(
    {
      fileCount: safeFiles.length,
      imageCount: safeImages.length,
      totalBytes,
      isDragOver: Boolean(isDragOver),
      supportedExtensionCount: CHAT_DOCUMENT_EXTENSIONS.size,
    },
    null,
    2,
  );
}

export function auditUseFileUploadGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.hooks.use_file_upload.governance.v1',
      phase: 'P181',
      supportedExtensionCount: CHAT_DOCUMENT_EXTENSIONS.size,
      idleSummary: formatFileUploadSummary([], [], false),
    },
    null,
    2,
  );
}
