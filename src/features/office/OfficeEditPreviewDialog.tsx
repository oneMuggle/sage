/**
 * OfficeEditPreviewDialog — 编辑预览 (item 2.5, office parity batch 2).
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
 * Apply semantics — IMPORTANT: the backend intentionally exposes NO
 * page-level apply-update HTTP route (real edits go through the
 * chat-driven office_update tool). The dialog therefore previews only
 * and says so via the `office.edit.applyInChat` notice instead of
 * offering an apply button.
 *
 * State machine: compose → previewing → result (ok | rejected).
 * Errors during the preview call surface as toasts and return to compose.
 */

import { Pencil, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDiffPreviewChange,
  OfficeDocumentSummary,
  OfficeUpdateOp,
  OfficeUpdatePreviewResult,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export type OfficeEditPreviewPhase = 'compose' | 'previewing' | 'result';

export interface OfficeEditPreviewDialogProps {
  workspacePath: string;
  /** The document the edit targets (doc_id resolution on the backend). */
  doc: OfficeDocumentSummary;
  /** Excel sheet names for the sheet selector (from the read result). */
  sheetNames?: string[];
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
  onClose,
}: OfficeEditPreviewDialogProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<OfficeEditPreviewPhase>('compose');
  const [compose, setCompose] = useState<ComposeState>(() => ({
    ...INITIAL_COMPOSE,
    sheet: sheetNames?.[0] ?? '',
  }));
  const [result, setResult] = useState<OfficeUpdatePreviewResult | null>(null);

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
      setPhase('result');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.edit.previewFailed')}: ${msg}`);
      setPhase('compose');
    }
  };

  const backToCompose = () => {
    setPhase('compose');
    setResult(null);
  };

  const inputClass =
    'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

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

        {phase === 'result' && result && (
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

            {/* No apply button on purpose: there is no page-level
                apply-update HTTP route — edits apply via chat. */}
            <p
              className="text-xs text-muted bg-bg-subtle border border-border rounded px-3 py-2"
              data-testid="office-edit-apply-notice"
            >
              {t('office.edit.applyInChat')}
            </p>

            <button
              type="button"
              onClick={backToCompose}
              className="w-full px-4 py-2 border border-border rounded text-sm text-text-secondary hover:bg-bg-hover"
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
