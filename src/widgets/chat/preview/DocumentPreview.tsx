// src/widgets/chat/preview/DocumentPreview.tsx
//
// Phase 2 (2026-09-25): ZCode 启发的文档预览 Tab。
// 复用已有的 Office 预览基础设施（DocxNativePreview / OfficePreviewPanel），
// 在右侧面板内预览工作区内文档（DOCX 高保真渲染，PDF/XLSX/PPTX 结构化渲染）。
//
// 数据源：file_path 为相对于 workspacePath 的路径（与 changes API 口径一致）。
// workspacePath 从 React Context（SessionWorkspaceProvider）读取，不额外传参。

import { FileText } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { DocxNativePreview } from '../../../features/office/DocxNativePreview';
import {
  OfficePreviewPanel,
  type OfficePreviewData,
} from '../../../features/office/OfficePreviewPanel';
import { officeApi } from '../../../shared/api/officeApi';
import type {
  OfficeExcelReadResult,
  OfficePdfReadResult,
  OfficePptReadResult,
} from '../../../shared/api/types';
import { useCurrentWorkspace } from '../../../shared/lib/workspaceContext';

interface DocumentPreviewProps {
  /** 相对工作区根的文件路径（与 changes API / FileChangeCard 口径一致） */
  filePath: string;
}

const DOCX_EXT = new Set(['docx']);
const PDF_EXT = new Set(['pdf']);
const XLSX_EXT = new Set(['xlsx', 'xls']);
const PPTX_EXT = new Set(['pptx', 'ppt']);
const PREVIEWABLE_EXT = new Set([...DOCX_EXT, ...PDF_EXT, ...XLSX_EXT, ...PPTX_EXT]);

function getExtension(filePath: string): string {
  const dot = filePath.lastIndexOf('.');
  return dot === -1 ? '' : filePath.slice(dot + 1).toLowerCase();
}

async function readOfficeFile(
  workspacePath: string,
  filePath: string,
  ext: string,
): Promise<OfficePreviewData> {
  if (PDF_EXT.has(ext)) {
    const data: OfficePdfReadResult = await officeApi.readPdf({
      workspace_path: workspacePath,
      file_path: filePath,
    });
    return { docType: 'pdf', data };
  }
  if (XLSX_EXT.has(ext)) {
    const data: OfficeExcelReadResult = await officeApi.readExcel({
      workspace_path: workspacePath,
      file_path: filePath,
    });
    return { docType: 'excel', data };
  }
  if (PPTX_EXT.has(ext)) {
    const data: OfficePptReadResult = await officeApi.readPpt({
      workspace_path: workspacePath,
      file_path: filePath,
    });
    return { docType: 'ppt', data };
  }
  throw new Error(`不支持的文件类型: .${ext}`);
}

export function DocumentPreview({ filePath }: DocumentPreviewProps) {
  const workspacePath = useCurrentWorkspace();
  const ext = getExtension(filePath);
  const [preview, setPreview] = useState<OfficePreviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspacePath) {
      setError('当前会话未绑定工作区，无法预览文档');
      setLoading(false);
      return;
    }
    if (!PREVIEWABLE_EXT.has(ext)) {
      setError(`不支持的文件类型: .${ext || '(无扩展名)'}`);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      if (DOCX_EXT.has(ext)) {
        // DOCX 走 DocxNativePreview（高保真渲染），此组件内部自管状态
        setPreview(null);
        setLoading(false);
        return;
      }
      const data = await readOfficeFile(workspacePath, filePath, ext);
      setPreview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [workspacePath, filePath, ext]);

  useEffect(() => {
    void load();
  }, [load]);

  // DOCX 走专用高保真渲染器（docx-preview 直接解析二进制）
  if (DOCX_EXT.has(ext) && workspacePath) {
    return (
      <div className="h-full overflow-auto" data-testid="document-preview-docx">
        <DocxNativePreview workspacePath={workspacePath} managedPath={filePath} />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-text-muted">加载中…</div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-sm text-text-muted">
        <FileText className="w-5 h-5" />
        <span>{error}</span>
        <button
          className="text-xs text-primary underline-offset-2 hover:underline"
          onClick={() => void load()}
        >
          重试
        </button>
      </div>
    );
  }

  if (!workspacePath) {
    return (
      <div className="flex flex-col items-center gap-2 py-8 text-sm text-text-muted">
        <FileText className="w-5 h-5" />
        <span>当前会话未绑定工作区，无法预览文档</span>
      </div>
    );
  }

  if (!preview) {
    return null;
  }

  return (
    <div className="h-full overflow-auto" data-testid="document-preview">
      <OfficePreviewPanel
        preview={preview}
        workspacePath={workspacePath}
        fidelityAvailable={false}
      />
    </div>
  );
}
