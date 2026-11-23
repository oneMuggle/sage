/**
 * OfficeCompareDialog — 文档库跨文档对比入口 (Office M6b).
 *
 * 让用户挑两份受管 Office 文档（word/excel/ppt/pdf），调用
 * `POST /api/v1/office/compare` 生成行级 diff 报告。后端的比较器按格式
 * 统一抽取正文/单元格/幻灯片文本后做 unified diff，返回的
 * `report_markdown` 直接交给共享 Markdown 渲染器展示。
 *
 * 传入的 documents 由调用方筛选（仅当前工作区、未归档）；路径统一用
 * `officeDocumentRelativePath()` 的工作区相对形式，与右栏预览一致。
 */

import { FileDiff } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';

import { officeCompareApi } from '../../shared/api/officeCompareApi';
import type { OfficeCompareResult, OfficeDocumentSummary } from '../../shared/api/types';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Modal } from '../../shared/ui/Modal';
import { Markdown } from '../../widgets/markdown';

import { officeDocumentRelativePath } from './officeDocumentPath';

export interface OfficeCompareDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** 工作区绝对路径；null 时无法发起对比。 */
  workspacePath: string | null;
  /** 候选文档（调用方负责过滤归档项）。 */
  documents: OfficeDocumentSummary[];
}

function documentLabel(doc: OfficeDocumentSummary): string {
  return doc.original_filename ?? doc.generated_filename;
}

export function OfficeCompareDialog({
  isOpen,
  onClose,
  workspacePath,
  documents,
}: OfficeCompareDialogProps) {
  const { t } = useI18n();
  const [leftId, setLeftId] = useState('');
  const [rightId, setRightId] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OfficeCompareResult | null>(null);
  const requestIdRef = useRef(0);

  const candidates = useMemo(() => documents.filter((doc) => doc.archived_at == null), [documents]);
  const leftDoc = candidates.find((doc) => doc.id === leftId) ?? null;
  const rightDoc = candidates.find((doc) => doc.id === rightId) ?? null;
  const sameDocument = leftDoc != null && leftDoc.id === rightDoc?.id;
  const canRun =
    workspacePath != null && leftDoc != null && rightDoc != null && !sameDocument && !running;

  const handleClose = () => {
    requestIdRef.current += 1;
    setRunning(false);
    onClose();
  };

  const handleRun = async () => {
    if (!canRun || !workspacePath || !leftDoc || !rightDoc) return;
    const myRequestId = ++requestIdRef.current;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const response = await officeCompareApi.compareDocuments({
        workspace_path: workspacePath,
        left_path: officeDocumentRelativePath(leftDoc),
        right_path: officeDocumentRelativePath(rightDoc),
      });
      if (myRequestId !== requestIdRef.current) return;
      setResult(response);
    } catch (e) {
      if (myRequestId !== requestIdRef.current) return;
      const message = e instanceof Error ? e.message : String(e);
      setError(`${t('office.compare.failed')}: ${message}`);
    } finally {
      if (myRequestId === requestIdRef.current) setRunning(false);
    }
  };

  const selectClass =
    'w-full rounded border border-border bg-ui-panel px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40';

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={t('office.compare.title')}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose}>
            {t('office.compare.cancel')}
          </Button>
          <Button
            onClick={() => void handleRun()}
            disabled={!canRun}
            data-testid="office-compare-run"
          >
            <FileDiff className="w-4 h-4 mr-2" />
            {running ? t('office.compare.running') : t('office.compare.run')}
          </Button>
        </div>
      }
    >
      <div className="space-y-3 text-sm" data-testid="office-compare-dialog">
        {candidates.length < 2 ? (
          <p className="text-muted">{t('office.compare.empty')}</p>
        ) : (
          <>
            <label className="block space-y-1">
              <span className="text-xs text-muted">{t('office.compare.left')}</span>
              <select
                className={selectClass}
                value={leftId}
                onChange={(event) => setLeftId(event.target.value)}
                data-testid="office-compare-left"
              >
                <option value="">{t('office.compare.select')}</option>
                {candidates.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {documentLabel(doc)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-muted">{t('office.compare.right')}</span>
              <select
                className={selectClass}
                value={rightId}
                onChange={(event) => setRightId(event.target.value)}
                data-testid="office-compare-right"
              >
                <option value="">{t('office.compare.select')}</option>
                {candidates.map((doc) => (
                  <option key={doc.id} value={doc.id}>
                    {documentLabel(doc)}
                  </option>
                ))}
              </select>
            </label>
            {sameDocument && (
              <p className="text-xs text-danger" data-testid="office-compare-same-doc">
                {t('office.compare.sameDoc')}
              </p>
            )}

            {error && (
              <p className="text-xs text-danger break-all" data-testid="office-compare-error">
                {error}
              </p>
            )}

            {result && (
              <div className="space-y-2" data-testid="office-compare-result">
                <p className="text-xs text-muted" data-testid="office-compare-summary">
                  {fillTemplate(t('office.compare.summary'), {
                    added: result.summary.added,
                    removed: result.summary.removed,
                    unchanged: result.summary.unchanged,
                  })}
                </p>
                {result.warnings.length > 0 && (
                  <div className="text-xs text-muted" data-testid="office-compare-warnings">
                    <span className="font-medium">{t('office.compare.warnings')}: </span>
                    {result.warnings
                      .map((warning) => warning.message ?? warning.code ?? '')
                      .filter(Boolean)
                      .join('; ')}
                  </div>
                )}
                <div className="max-h-80 overflow-y-auto rounded border border-border bg-ui-panel px-3 py-2">
                  <Markdown
                    content={result.report_markdown}
                    tier="minimal"
                    testId="office-compare-report"
                  />
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
