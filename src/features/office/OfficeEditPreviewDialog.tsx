/**
 * OfficeEditPreviewDialog — 编辑预览 (item 2.5, office parity batch 2;
 * apply loop closed in round 2, item R1).
 *
 * Compose a simple edit for the document currently shown in the preview
 * panel, dry-run it against POST /office/update/preview (which applies
 * the ops to a temp COPY — the source file is never touched) and render
 * the resulting change list as a red/green diff.
 *
 * Per doc type (F2, office-p0: the op-kind selector exposes more of the
 * backend op surface; the default kind per type keeps parity-batch-2 UX):
 *   Word : replace_text {find, replace}          (default)
 *        | append_paragraphs {paragraphs:[{text, heading?}]}
 *        | set_table_cell {table_index, row, col, text}
 *        | delete_paragraph {find, all?}
 *   Excel: set_cells     {sheet, cells:[{addr, value}]}   (default)
 *        | append_rows   {sheet, rows:[[..],..]}
 *   PPT  : set_slide_title {index (0-based, from a 1-based input), title} (default)
 *        | set_slide_bullets {index, bullets}
 *        | set_slide_notes   {index, notes}
 *        | append_slide      {title, bullets?, notes?}
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
import { diffSpans } from '../../shared/lib/textDiff';

export type OfficeEditPreviewPhase = 'compose' | 'previewing' | 'result' | 'applying' | 'applied';

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

export type WordEditKind =
  | 'replace_text'
  | 'append_paragraphs'
  | 'set_table_cell'
  | 'delete_paragraph'
  | 'add_comment'
  | 'set_paragraph_style'
  | 'delete_comment';
export type ExcelEditKind = 'set_cells' | 'append_rows';
export type PptEditKind =
  | 'set_slide_title'
  | 'set_slide_bullets'
  | 'set_slide_notes'
  | 'append_slide';

interface ComposeState {
  // op-kind selectors (default per type keeps the batch-2 single-op UX)
  wordKind: WordEditKind;
  excelKind: ExcelEditKind;
  pptKind: PptEditKind;
  // word replace_text
  find: string;
  replace: string;
  // word append_paragraphs
  paragraphsText: string;
  paraHeading: '' | 'h1' | 'h2' | 'h3';
  // word set_table_cell
  tableIndex: string;
  tableRow: string;
  tableCol: string;
  tableText: string;
  // word delete_paragraph
  deleteFind: string;
  deleteAll: boolean;
  // word add_comment
  commentText: string;
  commentAuthor: string;
  // word set_paragraph_style
  styleMatch: string;
  styleIndex: string;
  styleFontSize: string;
  styleBold: boolean;
  styleItalic: boolean;
  styleColor: string;
  styleAlign: string;
  // word delete_comment
  commentId: string;
  // excel set_cells
  sheet: string;
  cell: string;
  value: string;
  // excel append_rows
  rowsText: string;
  // ppt set_slide_title
  slideNumber: string;
  slideTitle: string;
  // ppt set_slide_bullets / set_slide_notes
  bulletsText: string;
  notesText: string;
  // ppt append_slide
  appendTitle: string;
  appendNotes: string;
}

const INITIAL_COMPOSE: ComposeState = {
  wordKind: 'replace_text',
  excelKind: 'set_cells',
  pptKind: 'set_slide_title',
  find: '',
  replace: '',
  paragraphsText: '',
  paraHeading: '',
  tableIndex: '0',
  tableRow: '',
  tableCol: '',
  tableText: '',
  deleteFind: '',
  deleteAll: false,
  commentText: '',
  commentAuthor: '',
  styleMatch: '',
  styleIndex: '',
  styleFontSize: '',
  styleBold: false,
  styleItalic: false,
  styleColor: '',
  styleAlign: '',
  commentId: '',
  sheet: '',
  cell: '',
  value: '',
  rowsText: '',
  slideNumber: '1',
  slideTitle: '',
  bulletsText: '',
  notesText: '',
  appendTitle: '',
  appendNotes: '',
};

/** 非空行列表 — textarea 多行输入 → string[]（去首尾空白、丢空行）。 */
function linesOf(text: string): string[] {
  return text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean);
}

// Pure op builder exported next to the dialog so tests + callers share
// one shape (same pattern as useI18n in shared/lib/i18n/index.tsx).
// eslint-disable-next-line react-refresh/only-export-components
export function buildUpdateOps(
  docType: OfficeDocumentSummary['doc_type'],
  state: ComposeState,
): OfficeUpdateOp[] | null {
  if (docType === 'word') {
    if (state.wordKind === 'append_paragraphs') {
      const lines = linesOf(state.paragraphsText);
      if (!lines.length) return null;
      const heading = state.paraHeading;
      return [
        {
          op: 'append_paragraphs',
          paragraphs: lines.map((text) => (heading ? { text, heading } : { text })),
        },
      ];
    }
    if (state.wordKind === 'set_table_cell') {
      const tableIndex = Number(state.tableIndex || '0');
      const row = Number(state.tableRow);
      const col = Number(state.tableCol);
      const text = state.tableText;
      if (!Number.isInteger(tableIndex) || tableIndex < 0) return null;
      if (!Number.isInteger(row) || row < 0) return null;
      if (!Number.isInteger(col) || col < 0) return null;
      if (!text) return null;
      return [{ op: 'set_table_cell', table_index: tableIndex, row, col, text }];
    }
    if (state.wordKind === 'add_comment') {
      const find = state.deleteFind.trim();
      const comment = state.commentText.trim();
      if (!find || !comment) return null;
      const op: OfficeUpdateOp = { op: 'add_comment', find, comment };
      if (state.commentAuthor.trim()) op.author = state.commentAuthor.trim();
      return [op];
    }
    if (state.wordKind === 'set_paragraph_style') {
      const match = state.styleMatch.trim();
      const indexRaw = state.styleIndex.trim();
      if (!match && !indexRaw) return null;
      const op: OfficeUpdateOp = { op: 'set_paragraph_style' };
      if (match) op.match = match;
      if (indexRaw) {
        const index = Number(indexRaw);
        if (!Number.isInteger(index) || index < 0) return null;
        op.index = index;
      }
      const fontSize = Number(state.styleFontSize.trim());
      if (state.styleFontSize.trim() && Number.isFinite(fontSize) && fontSize > 0) {
        op.font_size = fontSize;
      }
      if (state.styleBold) op.bold = true;
      if (state.styleItalic) op.italic = true;
      if (state.styleColor.trim()) op.color = state.styleColor.trim();
      if (state.styleAlign) op.align = state.styleAlign;
      // 至少一个样式属性才构成有效编辑
      if (Object.keys(op).length <= 2) return null;
      return [op];
    }
    if (state.wordKind === 'delete_comment') {
      const id = state.commentId.trim();
      if (!id) return null;
      return [{ op: 'delete_comment', comment_id: id }];
    }
    if (state.wordKind === 'delete_paragraph') {
      const find = state.deleteFind.trim();
      if (!find) return null;
      const op: OfficeUpdateOp = { op: 'delete_paragraph', find };
      if (state.deleteAll) op.all = true;
      return [op];
    }
    const find = state.find.trim();
    if (!find) return null;
    return [{ op: 'replace_text', find, replace: state.replace }];
  }
  if (docType === 'excel') {
    const sheet = state.sheet.trim();
    if (state.excelKind === 'append_rows') {
      const rows = linesOf(state.rowsText).map((line) =>
        // 一行一条记录；单元格以逗号/中文逗号/Tab 分隔
        line.split(/[,，\t]/).map((c) => c.trim()),
      );
      if (!sheet || !rows.length) return null;
      return [{ op: 'append_rows', sheet, rows }];
    }
    const addr = state.cell.trim();
    const value = state.value.trim();
    if (!sheet || !addr || !value) return null;
    return [{ op: 'set_cells', sheet, cells: [{ addr, value }] }];
  }
  if (docType === 'ppt') {
    if (state.pptKind === 'append_slide') {
      const title = state.appendTitle.trim();
      const bullets = linesOf(state.bulletsText);
      const notes = state.appendNotes.trim();
      if (!title && !bullets.length && !notes) return null;
      const op: OfficeUpdateOp = { op: 'append_slide', title, bullets };
      if (notes) op.notes = notes;
      return [op];
    }
    const n = Number(state.slideNumber);
    if (!Number.isInteger(n) || n < 1) return null;
    // The UI is 1-based for humans; the backend op index is 0-based
    // (matching read_ppt slide.index).
    const index = n - 1;
    if (state.pptKind === 'set_slide_bullets') {
      const bullets = linesOf(state.bulletsText);
      if (!bullets.length) return null;
      return [{ op: 'set_slide_bullets', index, bullets }];
    }
    if (state.pptKind === 'set_slide_notes') {
      const notes = state.notesText.trim();
      if (!notes) return null;
      return [{ op: 'set_slide_notes', index, notes }];
    }
    const title = state.slideTitle.trim();
    if (!title) return null;
    return [{ op: 'set_slide_title', index, title }];
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

  const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

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
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.wordKind}
                    onChange={(e) => setField('wordKind')(e.target.value as WordEditKind)}
                    className={inputClass}
                    data-testid="office-edit-word-kind"
                  >
                    <option value="replace_text">{t('office.edit.kindReplaceText')}</option>
                    <option value="append_paragraphs">
                      {t('office.edit.kindAppendParagraphs')}
                    </option>
                    <option value="set_table_cell">{t('office.edit.kindSetTableCell')}</option>
                    <option value="delete_paragraph">{t('office.edit.kindDeleteParagraph')}</option>
                    <option value="add_comment">{t('office.edit.kindAddComment')}</option>
                    <option value="set_paragraph_style">{t('office.edit.kindSetStyle')}</option>
                    <option value="delete_comment">{t('office.edit.kindDeleteComment')}</option>
                  </select>
                </div>
                {compose.wordKind === 'replace_text' && (
                  <>
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
                  </>
                )}
                {compose.wordKind === 'append_paragraphs' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.paragraphs')}
                      </label>
                      <textarea
                        value={compose.paragraphsText}
                        onChange={(e) => setField('paragraphsText')(e.target.value)}
                        rows={4}
                        className={inputClass}
                        data-testid="office-edit-paragraphs"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.paraHeading')}
                      </label>
                      <select
                        value={compose.paraHeading}
                        onChange={(e) =>
                          setField('paraHeading')(e.target.value as ComposeState['paraHeading'])
                        }
                        className={inputClass}
                        data-testid="office-edit-para-heading"
                      >
                        <option value="">{t('office.edit.headingNone')}</option>
                        <option value="h1">h1</option>
                        <option value="h2">h2</option>
                        <option value="h3">h3</option>
                      </select>
                    </div>
                  </>
                )}
                {compose.wordKind === 'set_table_cell' && (
                  <>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableIndex')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableIndex}
                          onChange={(e) => setField('tableIndex')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-index"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableRow')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableRow}
                          onChange={(e) => setField('tableRow')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-row"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.tableCol')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.tableCol}
                          onChange={(e) => setField('tableCol')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-table-col"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.tableText')}
                      </label>
                      <input
                        type="text"
                        value={compose.tableText}
                        onChange={(e) => setField('tableText')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-table-text"
                      />
                    </div>
                  </>
                )}
                {compose.wordKind === 'set_paragraph_style' && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleMatch')}
                        </label>
                        <input
                          type="text"
                          value={compose.styleMatch}
                          onChange={(e) => setField('styleMatch')(e.target.value)}
                          placeholder={t('office.edit.styleMatchPlaceholder')}
                          className={inputClass}
                          data-testid="office-edit-style-match"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleIndex')}
                        </label>
                        <input
                          type="number"
                          min={0}
                          value={compose.styleIndex}
                          onChange={(e) => setField('styleIndex')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-index"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleFontSize')}
                        </label>
                        <input
                          type="number"
                          min={1}
                          value={compose.styleFontSize}
                          onChange={(e) => setField('styleFontSize')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-font-size"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleColor')}
                        </label>
                        <input
                          type="text"
                          value={compose.styleColor}
                          onChange={(e) => setField('styleColor')(e.target.value)}
                          placeholder="FF0000"
                          className={inputClass}
                          data-testid="office-edit-style-color"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.styleAlign')}
                        </label>
                        <select
                          value={compose.styleAlign}
                          onChange={(e) => setField('styleAlign')(e.target.value)}
                          className={inputClass}
                          data-testid="office-edit-style-align"
                        >
                          <option value="">{t('office.edit.headingNone')}</option>
                          <option value="left">left</option>
                          <option value="center">center</option>
                          <option value="right">right</option>
                          <option value="justify">justify</option>
                        </select>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <label className="flex items-center gap-2 text-xs text-text-secondary">
                        <input
                          type="checkbox"
                          checked={compose.styleBold}
                          onChange={(e) =>
                            setCompose((pr) => ({ ...pr, styleBold: e.target.checked }))
                          }
                          className="accent-primary"
                          data-testid="office-edit-style-bold"
                        />
                        {t('office.edit.styleBold')}
                      </label>
                      <label className="flex items-center gap-2 text-xs text-text-secondary">
                        <input
                          type="checkbox"
                          checked={compose.styleItalic}
                          onChange={(e) =>
                            setCompose((pr) => ({ ...pr, styleItalic: e.target.checked }))
                          }
                          className="accent-primary"
                          data-testid="office-edit-style-italic"
                        />
                        {t('office.edit.styleItalic')}
                      </label>
                    </div>
                  </>
                )}
                {compose.wordKind === 'delete_comment' && (
                  <div>
                    <label className="block text-xs text-muted mb-1">
                      {t('office.edit.commentId')}
                    </label>
                    <input
                      type="text"
                      value={compose.commentId}
                      onChange={(e) => setField('commentId')(e.target.value)}
                      placeholder={t('office.edit.commentIdPlaceholder')}
                      className={inputClass}
                      data-testid="office-edit-comment-id"
                    />
                  </div>
                )}
                {compose.wordKind === 'add_comment' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordFind')}
                      </label>
                      <input
                        type="text"
                        value={compose.deleteFind}
                        onChange={(e) => setField('deleteFind')(e.target.value)}
                        placeholder={t('office.edit.deleteFindPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-delete-find"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.commentText')}
                      </label>
                      <textarea
                        value={compose.commentText}
                        onChange={(e) => setField('commentText')(e.target.value)}
                        rows={3}
                        className={inputClass}
                        data-testid="office-edit-comment-text"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.commentAuthor')}
                      </label>
                      <input
                        type="text"
                        value={compose.commentAuthor}
                        onChange={(e) => setField('commentAuthor')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-comment-author"
                      />
                    </div>
                  </>
                )}
                {compose.wordKind === 'delete_paragraph' && (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.wordFind')}
                      </label>
                      <input
                        type="text"
                        value={compose.deleteFind}
                        onChange={(e) => setField('deleteFind')(e.target.value)}
                        placeholder={t('office.edit.deleteFindPlaceholder')}
                        className={inputClass}
                        data-testid="office-edit-delete-find"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-xs text-text-secondary">
                      <input
                        type="checkbox"
                        checked={compose.deleteAll}
                        onChange={(e) => setCompose((p) => ({ ...p, deleteAll: e.target.checked }))}
                        className="accent-primary"
                        data-testid="office-edit-delete-all"
                      />
                      {t('office.edit.deleteAll')}
                    </label>
                  </>
                )}
              </div>
            )}

            {doc.doc_type === 'excel' && (
              <div className="space-y-2" data-testid="office-edit-form-excel">
                <div>
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.excelKind}
                    onChange={(e) => setField('excelKind')(e.target.value as ExcelEditKind)}
                    className={inputClass}
                    data-testid="office-edit-excel-kind"
                  >
                    <option value="set_cells">{t('office.edit.kindSetCells')}</option>
                    <option value="append_rows">{t('office.edit.kindAppendRows')}</option>
                  </select>
                </div>
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
                {compose.excelKind === 'set_cells' && (
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
                )}
                {compose.excelKind === 'append_rows' && (
                  <div>
                    <label className="block text-xs text-muted mb-1">{t('office.edit.rows')}</label>
                    <textarea
                      value={compose.rowsText}
                      onChange={(e) => setField('rowsText')(e.target.value)}
                      rows={4}
                      className={inputClass}
                      data-testid="office-edit-rows"
                    />
                  </div>
                )}
              </div>
            )}

            {doc.doc_type === 'ppt' && (
              <div className="space-y-2" data-testid="office-edit-form-ppt">
                <div>
                  <label className="block text-xs text-muted mb-1">{t('office.edit.opKind')}</label>
                  <select
                    value={compose.pptKind}
                    onChange={(e) => setField('pptKind')(e.target.value as PptEditKind)}
                    className={inputClass}
                    data-testid="office-edit-ppt-kind"
                  >
                    <option value="set_slide_title">{t('office.edit.kindSetTitle')}</option>
                    <option value="set_slide_bullets">{t('office.edit.kindSetBullets')}</option>
                    <option value="set_slide_notes">{t('office.edit.kindSetNotes')}</option>
                    <option value="append_slide">{t('office.edit.kindAppendSlide')}</option>
                  </select>
                </div>
                {compose.pptKind === 'append_slide' ? (
                  <>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.appendTitle')}
                      </label>
                      <input
                        type="text"
                        value={compose.appendTitle}
                        onChange={(e) => setField('appendTitle')(e.target.value)}
                        className={inputClass}
                        data-testid="office-edit-append-title"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.bullets')}
                      </label>
                      <textarea
                        value={compose.bulletsText}
                        onChange={(e) => setField('bulletsText')(e.target.value)}
                        rows={3}
                        className={inputClass}
                        data-testid="office-edit-bullets"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-muted mb-1">
                        {t('office.edit.notes')}
                      </label>
                      <textarea
                        value={compose.appendNotes}
                        onChange={(e) => setField('appendNotes')(e.target.value)}
                        rows={2}
                        className={inputClass}
                        data-testid="office-edit-append-notes"
                      />
                    </div>
                  </>
                ) : (
                  <>
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
                    {compose.pptKind === 'set_slide_title' && (
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
                    )}
                    {compose.pptKind === 'set_slide_bullets' && (
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.bullets')}
                        </label>
                        <textarea
                          value={compose.bulletsText}
                          onChange={(e) => setField('bulletsText')(e.target.value)}
                          rows={4}
                          className={inputClass}
                          data-testid="office-edit-bullets"
                        />
                      </div>
                    )}
                    {compose.pptKind === 'set_slide_notes' && (
                      <div>
                        <label className="block text-xs text-muted mb-1">
                          {t('office.edit.notes')}
                        </label>
                        <textarea
                          value={compose.notesText}
                          onChange={(e) => setField('notesText')(e.target.value)}
                          rows={3}
                          className={inputClass}
                          data-testid="office-edit-notes"
                        />
                      </div>
                    )}
                  </>
                )}
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
                  {phase === 'applying' ? t('office.edit.applying') : t('office.edit.apply')}
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

// Round B P2: exported — the snapshot panel's 与当前版本对比 view renders
// the same red/green change rows (snapshot diff reuses DiffPreviewResult).
export function DiffChangeRow({ change }: { change: OfficeDiffPreviewChange }) {
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
            <div
              className="text-xs text-error bg-error/10 rounded px-2 py-1 break-all line-through decoration-error/60"
              data-testid="office-edit-before"
            >
              {/* P1-A: 字符级 diff —— 删除片段加深底色，公共部分不再陪染 */}
              {diffSpans(change.before ?? '', change.after ?? '').before.map((sp, si) =>
                sp.kind === 'del' ? (
                  <span key={si} className="bg-error/25 rounded-sm" data-testid="office-diff-del">
                    {sp.text}
                  </span>
                ) : (
                  <span key={si}>{sp.text}</span>
                ),
              )}
            </div>
          </div>
          <span className="text-muted text-xs" aria-hidden>
            →
          </span>
          <div className="min-w-0">
            <div className="text-xs text-muted">{t('office.edit.after')}</div>
            <div
              className="text-xs text-success bg-success/10 rounded px-2 py-1 break-all"
              data-testid="office-edit-after"
            >
              {diffSpans(change.before ?? '', change.after ?? '').after.map((sp, si) =>
                sp.kind === 'add' ? (
                  <span key={si} className="bg-success/25 rounded-sm" data-testid="office-diff-add">
                    {sp.text}
                  </span>
                ) : (
                  <span key={si}>{sp.text}</span>
                ),
              )}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}
