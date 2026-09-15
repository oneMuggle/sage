/**
 * OfficeEditPreviewDialog — 编辑预览 (item 2.5, office parity batch 2;
 * apply loop closed in round 2, item R1).
 *
 * Compose a simple edit for the document currently shown in the preview
 * panel, dry-run it against POST /office/update/preview (which applies
 * the ops to a temp COPY — the source file is never touched) and render
 * the resulting change list as a red/green diff.
 *
 * Per doc type (parity scope for this dialog):
 *   Word : replace_text  {find, replace}
 *   Excel: set_cells     {sheet, cells:[{addr, value}]}
 *   PPT  : set_slide_title {index (0-based, from a 1-based input), title}
 *
 * Apply semantics (round 2, R1): after a successful preview (result.ok)
 * the dialog offers 确认应用 — a deliberate secondary confirm step
 * between "generating a diff" and "writing the file". Confirming POSTs
 * the SAME ops to /office/doc/{doc_id}/update. Success renders the
 * self-check summary line (e.g. 段落 3 · 表格 1), toasts, and fires
 * `onApplied` so the parent refreshes the document list + preview.
 * Batch 2 shipped preview-only with an "apply in chat" notice; that
 * notice is gone now that the apply route exists.
 *
 * State machine: compose → previewing → result (ok | rejected)
 *   → applying → applied.
 * Preview failures toast and return to compose; apply failures toast
 * and return to result so the user can retry the same ops.
 */

import { CheckCircle2, Pencil, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDiffPreviewChange,
  OfficeDocUpdateResponse,
  OfficeDocumentSummary,
  OfficeUpdateOp,
  OfficeUpdatePreviewResult,
} from '../../shared/api/types';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

export type OfficeEditPreviewPhase =
  | 'compose'
  | 'previewing'
  | 'result'
  | 'applying'
  | 'applied';

export interface OfficeEditPreviewDialogProps {
  workspacePath: string;
  /** The document the edit targets (doc_id resolution on the backend). */
  doc: OfficeDocumentSummary;
  /** Excel sheet names for the sheet selector (from the read result). */
  sheetNames?: string[];
  /**
   * Fired once the update route confirmed the apply (round 2, R1). The
   * parent refreshes the document list and re-reads the preview — the
   * managed file's bytes changed under it.
   */
  onApplied?: (docId: string) => void;
  onClose: () => void;
}

interface ComposeState {
  // word replace_text
  find: string;
  replace: string;
  // excel set_cells
  sheet: string;
  cell: string;
  value: string;
  // ppt set_slide_title
  slideNumber: string;
  slideTitle: string;
}

const INITIAL_COMPOSE: ComposeState = {
  find: '',
  replace: '',
  sheet: '',
  cell: '',
  value: '',
  slideNumber: '1',
  slideTitle: '',
};

// Pure op builder exported next to the dialog so tests + callers share
// one shape (same pattern as useI18n in shared/lib/i18n/index.tsx).
// eslint-disable-next-line react-refresh/only-export-components
export function buildUpdateOps(
  docType: OfficeDocumentSummary['doc_type'],
  state: ComposeState,
): OfficeUpdateOp[] | null {
  if (docType === 'word') {
    const find = state.find.trim();
    if (!find) return null;
    return [{ op: 'replace_text', find, replace: state.replace }];
  }
  if (docType === 'excel') {
    const sheet = state.sheet.trim();
    const addr = state.cell.trim();
    const value = state.value.trim();
    if (!sheet || !addr || !value) return null;
    return [{ op: 'set_cells', sheet, cells: [{ addr, value }] }];
  }
  if (docType === 'ppt') {
    const n = Number(state.slideNumber);
    const title = state.slideTitle.trim();
    if (!Number.isInteger(n) || n < 1 || !title) return null;
    // The UI is 1-based for humans; the backend op index is 0-based
    // (matching read_ppt slide.index).
    return [{ op: 'set_slide_title', index: n - 1, title }];
  }
  return null; // pdf is not editable via this dialog
}

export function OfficeEditPreviewDialog({
  workspacePath,
  doc,
  sheetNames,
  onApplied,
  onClose,
}: OfficeEditPreviewDialogProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<OfficeEditPreviewPhase>('compose');
  const [compose, setCompose] = useState<ComposeState>(() => ({
    ...INITIAL_COMPOSE,
    sheet: sheetNames?.[0] ?? '',
  }));
  const [result, setResult] = useState<OfficeUpdatePreviewResult | null>(null);
  // The exact ops the successful preview dry-ran — the apply step must
  // POST the SAME ops, not a re-derived copy (compose state may look
  // identical, but storing the previewed ops makes that guarantee).
  const [previewedOps, setPreviewedOps] = useState<OfficeUpdateOp[] | null>(null);
  // Set once /office/doc/{id}/update confirmed the apply (round 2, R1).
  const [applied, setApplied] = useState<OfficeDocUpdateResponse | null>(null);

  const setField = (key: keyof ComposeState) => (value: string) =>
    setCompose((prev) => ({ ...prev, [key]: value }));

  const handlePreview = async () => {
    const ops = buildUpdateOps(doc.doc_type, compose);
    if (!ops) {
      toast.error(t('office.edit.required'));
      return;
    }
    setPhase('previewing');
    try {
      const res = await officeApi.previewUpdate({
        workspace_path: workspacePath,
        doc_id: doc.id,
        ops,
      });
      setResult(res);
      setPreviewedOps(ops);
      setPhase('result');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.edit.previewFailed')}: ${msg}`);
      setPhase('compose');
    }
  };

  // Round 2 (R1): apply the previewed ops for real. Only reachable from
  // the result phase with an ok preview — the button IS the secondary
  // confirm between "diff" and "write". Failures toast the backend
  // message and return to result so the user can retry.
  const handleApply = async () => {
    if (!previewedOps || phase !== 'result') return;
    setPhase('applying');
    try {
      const res = await officeApi.updateDocument({ doc_id: doc.id, ops: previewedOps });
      setApplied(res);
      setPhase('applied');
      toast.success(t('office.edit.applied'));
      onApplied?.(doc.id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.edit.applyFailed')}: ${msg}`);
      setPhase('result');
    }
  };

  const backToCompose = () => {
    setPhase('compose');
    setResult(null);
    setPreviewedOps(null);
    setApplied(null);
  };

  const inputClass =
    'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

  // Post-apply count line, e.g. "段落 3 · 表格 1" — empty when the
  // backend reports no counts at all.
  const selfCheckLine = applied ? formatSelfCheckSummary(applied.summary, t) : '';

  // The compose form stays mounted while previewing (fields must not
  // vanish if the preview call fails), so the compose branch covers both
  // phases and the button reflects the in-flight one.
  const showCompose = phase === 'compose' || phase === 'previewing';

  return (
    <div
      className="border border-border rounded-lg bg-surface overflow-hidden"
      data-testid="office-edit-preview-dialog"
      data-phase={phase}
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        <Pencil className="w-4 h-4" />
        <span className="font-medium text-sm">{t('office.edit.title')}</span>
        <span className="text-xs text-muted truncate">
          {doc.original_filename ?? doc.generated_filename}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto p-1 rounded text-muted hover:text-text hover:bg-bg-hover transition-colors"
          aria-label={t('office.edit.close')}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 space-y-3">
        {showCompose && (
          <>
            <p className="text-xs text-muted">{t('office.edit.composeHint')}</p>

            {doc.doc_type === 'word' && (
              <div className="space-y-2" data-testid="office-edit-form-word">
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.wordFind')}
                  </label>
                  <input
                    type="text"
                    value={compose.find}
                    onChange={(e) => setField('find')(e.target.value)}
                    placeholder={t('office.edit.wordFindPlaceholder')}
                    className={inputClass}
                    data-testid="office-edit-find"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.wordReplace')}
                  </label>
                  <input
                    type="text"
                    value={compose.replace}
                    onChange={(e) => setField('replace')(e.target.value)}
                    placeholder={t('office.edit.wordReplacePlaceholder')}
                    className={inputClass}
                    data-testid="office-edit-replace"
                  />
                </div>
              </div>
            )}

            {doc.doc_type === 'excel' && (
              <div className="space-y-2" data-testid="office-edit-form-excel">
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.excelSheet')}
                  </label>
                  {sheetNames && sheetNames.length > 0 ? (
                    <select
                      value={compose.sheet}
                      onChange={(e) => setField('sheet')(e.target.value)}
                      className={inputClass}
                      data-testid="office-edit-sheet"
                    >
                      {sheetNames.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={compose.sheet}
                      onChange={(e) => setField('sheet')(e.target.value)}
                      className={inputClass}
                      data-testid="office-edit-sheet"
                    />
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs text-muted mb-1">
                      {t('office.edit.excelCell')}
                    </label>
                    <input
                      type="text"
                      value={compose.cell}
                      onChange={(e) => setField('cell')(e.target.value)}
                      placeholder={t('office.edit.excelCellPlaceholder')}
                      className={inputClass}
                      data-testid="office-edit-cell"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-muted mb-1">
                      {t('office.edit.excelValue')}
                    </label>
                    <input
                      type="text"
                      value={compose.value}
                      onChange={(e) => setField('value')(e.target.value)}
                      placeholder={t('office.edit.excelValuePlaceholder')}
                      className={inputClass}
                      data-testid="office-edit-value"
                    />
                  </div>
                </div>
              </div>
            )}

            {doc.doc_type === 'ppt' && (
              <div className="space-y-2" data-testid="office-edit-form-ppt">
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.pptSlideNumber')}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={compose.slideNumber}
                    onChange={(e) => setField('slideNumber')(e.target.value)}
                    className={inputClass}
                    data-testid="office-edit-slide-number"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">
                    {t('office.edit.pptTitle')}
                  </label>
                  <input
                    type="text"
                    value={compose.slideTitle}
                    onChange={(e) => setField('slideTitle')(e.target.value)}
                    className={inputClass}
                    data-testid="office-edit-slide-title"
                  />
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={() => void handlePreview()}
              disabled={phase === 'previewing'}
              className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover disabled:opacity-50"
              data-testid="office-edit-preview-submit"
            >
              {phase === 'previewing' ? t('office.edit.previewing') : t('office.edit.preview')}
            </button>
          </>
        )}

        {(phase === 'result' || phase === 'applying' || phase === 'applied') && result && (
          <div className="space-y-3" data-testid="office-edit-result">
            {result.ok ? (
              <>
                <h3 className="text-sm font-medium text-text">{t('office.edit.changes')}</h3>
                {result.truncated && (
                  <p className="text-xs text-warning">{t('office.edit.truncated')}</p>
                )}
                {result.changes.length === 0 ? (
                  <p className="text-sm text-muted">{t('office.edit.noChanges')}</p>
                ) : (
                  <ul className="space-y-2">
                    {result.changes.map((change, i) => (
                      <DiffChangeRow key={i} change={change} />
                    ))}
                  </ul>
                )}
              </>
            ) : (
              <div
                className="px-3 py-2 bg-error/10 border border-error/30 rounded text-sm text-error"
                data-testid="office-edit-rejected"
              >
                <div className="font-medium">{t('office.edit.rejected')}</div>
                {result.error && <div className="mt-1 text-xs break-all">{result.error}</div>}
              </div>
            )}

            {/* Round 2 (R1): a successful preview unlocks the apply step.
                确认应用 is the deliberate secondary confirm between
                "diff on a temp copy" and "write the managed file". */}
            {result.ok && !applied && (
              <div className="space-y-2" data-testid="office-edit-apply-step">
                <p className="text-xs text-muted bg-bg-subtle border border-border rounded px-3 py-2">
                  {t('office.edit.applyHint')}
                </p>
                <button
                  type="button"
                  onClick={() => void handleApply()}
                  disabled={phase === 'applying'}
                  className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover disabled:opacity-50"
                  data-testid="office-edit-apply"
                >
                  {phase === 'applying'
                    ? t('office.edit.applying')
                    : t('office.edit.apply')}
                </button>
              </div>
            )}

            {/* Applied — success panel with the post-update self-check
                summary line (e.g. 段落 3 · 表格 1). The parent refreshes
                the document list + preview via onApplied. */}
            {applied && (
              <div
                className="px-3 py-2 bg-success/10 border border-success/30 rounded text-sm"
                data-testid="office-edit-applied"
              >
                <div className="flex items-center gap-1.5 font-medium text-success">
                  <CheckCircle2 className="w-4 h-4" />
                  {t('office.edit.applied')}
                </div>
                <div
                  className="mt-1 text-xs text-text-secondary"
                  data-testid="office-edit-self-check"
                >
                  {applied.self_check?.ok
                    ? t('office.edit.selfCheckOk')
                    : t('office.edit.selfCheckFailed')}
                  {selfCheckLine ? ` · ${selfCheckLine}` : ''}
                </div>
                {applied.self_check?.error && (
                  <div className="mt-1 text-xs text-warning break-all">
                    {applied.self_check.error}
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={backToCompose}
              disabled={phase === 'applying'}
              className="w-full px-4 py-2 border border-border rounded text-sm text-text-secondary hover:bg-bg-hover disabled:opacity-50"
              data-testid="office-edit-back"
            >
              {t('office.edit.preview')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Post-apply summary line (round 2, R1) — renders the refreshed document
 * metadata as a compact count list, e.g. "段落 3 · 表格 1". The backend's
 * self_check.summary is an opaque object, so the human-readable line is
 * built from the typed OfficeDocumentSummary instead. Only counts the
 * backend actually reports are included.
 */
function formatSelfCheckSummary(
  doc: OfficeDocumentSummary,
  t: (key: TranslationKey) => string,
): string {
  const meta = doc.metadata ?? { file_size_bytes: 0 };
  const parts: string[] = [];
  const push = (n: number | undefined, key: TranslationKey) => {
    if (typeof n === 'number' && Number.isFinite(n)) {
      parts.push(t(key).replace('{n}', String(n)));
    }
  };
  if (doc.doc_type === 'word') {
    push(meta.paragraph_count, 'office.edit.selfCheckParagraphs');
    push(meta.table_count, 'office.edit.selfCheckTables');
  } else if (doc.doc_type === 'excel') {
    push(meta.sheet_count, 'office.edit.selfCheckSheets');
  } else if (doc.doc_type === 'ppt') {
    push(meta.page_count, 'office.edit.selfCheckSlides');
  } else {
    push(meta.page_count, 'office.edit.selfCheckPages');
  }
  return parts.join(' · ');
}

function DiffChangeRow({ change }: { change: OfficeDiffPreviewChange }) {
  const { t } = useI18n();
  const hasDiff = change.before != null || change.after != null;
  return (
    <li className="border border-border rounded p-2 space-y-1.5" data-testid="office-edit-change">
      <div className="flex items-center gap-2 flex-wrap">
        <code className="px-1.5 py-0.5 rounded bg-primary/10 text-primary text-xs font-mono">
          {change.op}
        </code>
        {change.target && (
          <code className="text-xs text-muted font-mono break-all">{change.target}</code>
        )}
      </div>
      {change.summary && <p className="text-xs text-text-secondary">{change.summary}</p>}
      {hasDiff && (
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <div className="min-w-0">
            <div className="text-xs text-muted">{t('office.edit.before')}</div>
            <div className="text-xs text-error bg-error/10 rounded px-2 py-1 break-all line-through decoration-error/60">
              {change.before ?? ''}
            </div>
          </div>
          <span className="text-muted text-xs" aria-hidden>
            →
          </span>
          <div className="min-w-0">
            <div className="text-xs text-muted">{t('office.edit.after')}</div>
            <div className="text-xs text-success bg-success/10 rounded px-2 py-1 break-all">
              {change.after ?? ''}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}
