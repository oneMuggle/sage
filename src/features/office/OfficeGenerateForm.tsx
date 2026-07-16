/**
 * OfficeGenerateForm — generate PPT/Word/Excel from structured input (Task 20).
 *
 * Three sub-forms (one per format) sharing a common submit button. Output
 * displayed below with size + path.
 */

import { useState } from 'react';
import { FileSpreadsheet, FileText, Presentation, Sparkles } from 'lucide-react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeDocType } from '../../shared/api/types';

export interface OfficeGenerateFormProps {
  workspacePath: string;
}

export function OfficeGenerateForm({ workspacePath }: OfficeGenerateFormProps) {
  const [docType, setDocType] = useState<OfficeDocType>('ppt');
  const [filename, setFilename] = useState('my-document');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ path: string; sizeBytes: number } | null>(null);

  // PPT
  const [pptTitle, setPptTitle] = useState('Slide 1');
  const [pptBullets, setPptBullets] = useState('First point\nSecond point');

  // Word
  const [wordTitle, setWordTitle] = useState('Document Title');
  const [wordBody, setWordBody] = useState('First paragraph of the document.');

  // Excel
  const [sheetName, setSheetName] = useState('Sheet1');
  const [sheetHeaders, setSheetHeaders] = useState('Name,Age,City');
  const [sheetRows, setSheetRows] = useState('Alice,30,Beijing\nBob,25,Shanghai');

  const handleGenerate = async () => {
    if (!filename.trim()) {
      toast.error('请填写文件名');
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      let out: { output_path: string; filename: string; file_size_bytes: number };
      if (docType === 'ppt') {
        const bullets = pptBullets.split('\n').map((b) => b.trim()).filter(Boolean);
        out = await officeApi.generatePpt({
          workspace_path: workspacePath,
          filename,
          slides: [{ title: pptTitle, bullets }],
        });
      } else if (docType === 'word') {
        out = await officeApi.generateWord({
          workspace_path: workspacePath,
          filename,
          title: wordTitle,
          paragraphs: [{ text: wordBody }],
        });
      } else {
        const headers = sheetHeaders.split(',').map((h) => h.trim()).filter(Boolean);
        const rows = sheetRows
          .split('\n')
          .map((r) => r.split(',').map((c) => c.trim()));
        out = await officeApi.generateExcel({
          workspace_path: workspacePath,
          filename,
          sheets: [{ name: sheetName, headers, rows }],
        });
      }
      setResult({ path: out.output_path, sizeBytes: out.file_size_bytes });
      toast.success(`已生成 ${out.filename}`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`生成失败: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 p-4 border border-border rounded-lg bg-bg-subtle">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-primary" />
        <h2 className="text-sm font-medium text-text">生成新文档</h2>
      </div>

      <div className="flex gap-2">
        {(['ppt', 'word', 'excel'] as OfficeDocType[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setDocType(t)}
            className={[
              'flex items-center gap-1.5 px-3 py-1.5 rounded text-sm border',
              docType === t
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-text-secondary hover:bg-bg-hover',
            ].join(' ')}
          >
            {t === 'ppt' && <Presentation className="w-3.5 h-3.5" />}
            {t === 'word' && <FileText className="w-3.5 h-3.5" />}
            {t === 'excel' && <FileSpreadsheet className="w-3.5 h-3.5" />}
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      <div>
        <label className="block text-xs text-muted mb-1">文件名</label>
        <input
          type="text"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
          placeholder="my-document"
        />
      </div>

      {docType === 'ppt' && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">标题 (仅一张幻灯片)</label>
            <input
              type="text"
              value={pptTitle}
              onChange={(e) => setPptTitle(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">要点 (每行一个)</label>
            <textarea
              value={pptBullets}
              onChange={(e) => setPptBullets(e.target.value)}
              rows={3}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
        </div>
      )}

      {docType === 'word' && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">文档标题</label>
            <input
              type="text"
              value={wordTitle}
              onChange={(e) => setWordTitle(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">正文</label>
            <textarea
              value={wordBody}
              onChange={(e) => setWordBody(e.target.value)}
              rows={3}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
        </div>
      )}

      {docType === 'excel' && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">Sheet 名</label>
            <input
              type="text"
              value={sheetName}
              onChange={(e) => setSheetName(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">表头 (逗号分隔)</label>
            <input
              type="text"
              value={sheetHeaders}
              onChange={(e) => setSheetHeaders(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">数据行 (每行一个,逗号分隔字段)</label>
            <textarea
              value={sheetRows}
              onChange={(e) => setSheetRows(e.target.value)}
              rows={3}
              className="w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text"
            />
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => void handleGenerate()}
        disabled={busy}
        className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover disabled:opacity-50"
      >
        {busy ? '生成中...' : `生成 ${docType.toUpperCase()}`}
      </button>

      {result && (
        <div className="text-xs text-muted bg-surface border border-border rounded p-2">
          <div>已生成: <code className="text-text">{result.path}</code></div>
          <div>大小: {(result.sizeBytes / 1024).toFixed(1)} KB</div>
        </div>
      )}
    </div>
  );
}