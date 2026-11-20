/**
 * DesignExportPanel — 导出 PDF / PPTX / ZIP / HTML。
 */
import { Download, Loader2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { exportArtifact } from '../../entities/design/designApi';
import type { ExportFormat } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

interface DesignExportPanelProps {
  projectId: string;
  hasArtifact: boolean;
}

const FORMATS: ExportFormat[] = ['pdf', 'pptx', 'zip', 'html'];

const MIME: Record<ExportFormat, string> = {
  pdf: 'application/pdf',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  zip: 'application/zip',
  html: 'text/html;charset=utf-8',
};

function downloadHtml(html: string, filename: string): void {
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadBase64(base64: string, filename: string, mime: string): void {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function DesignExportPanel({ projectId, hasArtifact }: DesignExportPanelProps) {
  const { t } = useI18n();
  const [running, setRunning] = useState<ExportFormat | null>(null);

  const handleExport = async (format: ExportFormat) => {
    setRunning(format);
    try {
      const result = await exportArtifact(projectId, format, true);
      if (!result.ok) {
        throw new Error(result.error ?? result.format);
      }
      let displayed = format.toUpperCase();
      if (format === 'html' && result.html_content) {
        displayed = `design-${projectId}.html`;
        downloadHtml(result.html_content, displayed);
      } else if (result.content_base64 && result.filename) {
        displayed = result.filename;
        downloadBase64(result.content_base64, result.filename, MIME[format]);
      } else if (!result.file_path) {
        throw new Error(result.format);
      }
      toast.success(t('design.export.success').replace('{name}', displayed));
    } catch (err) {
      toast.error(
        t('design.export.failed').replace(
          '{error}',
          err instanceof Error ? err.message : String(err),
        ),
      );
    } finally {
      setRunning(null);
    }
  };

  return (
    <div
      className="flex items-center gap-1.5"
      title={hasArtifact ? undefined : t('design.export.needsArtifact')}
    >
      <span className="text-ui-xs text-text-secondary">{t('design.export.title')}</span>
      {FORMATS.map((format) => (
        <button
          key={format}
          type="button"
          disabled={!hasArtifact || running !== null}
          onClick={() => void handleExport(format)}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-ui-xs hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {running === format ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Download className="w-3 h-3" />
          )}
          {t(`design.export.${format}`)}
        </button>
      ))}
    </div>
  );
}
