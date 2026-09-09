/**
 * OfficeGenerateForm — generate PPT/Word/Excel from structured input (Task 20).
 *
 * Three sub-forms (one per format) sharing a common submit button. Output
 * displayed below with size + path.
 *
 * Office parity batch 3 (item 3.2): the Word tab gained a mode toggle —
 * 自由创建 (the original structured form) vs 从模板创建 (template picker).
 * The picker lists builtin + workspace templates (GET /office/templates),
 * renders one dynamic input per placeholder and creates the document via
 * POST /office/templates/instantiate. The backend persists a document
 * row, so the parent refreshes the list on success (same onGenerated
 * contract as the free-form path).
 *
 * Round 3 (N2): the mode toggle now covers the PPT and Excel tabs too.
 * The template list is fetched once per workspace and shared by all
 * three tabs, filtered client-side by the tab's doc_type (the backend
 * list endpoint returns every kind). The default filename for a picked
 * template carries the doc-type extension (.docx/.xlsx/.pptx).
 */

import { FileSpreadsheet, FileText, FileType, LayoutTemplate, Presentation, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type {
  OfficeDocType,
  OfficeTemplateMeta,
  OfficeTemplatePlaceholder,
  PdfPageSize,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface OfficeGenerateFormProps {
  workspacePath: string;
  /**
   * Called after a successful generate so the parent can refresh the
   * document list. Without this, generated docs don't appear in history
   * until the next manual refresh (HIGH #6 in AI review). Also fired by
   * the template path (item 3.2) — instantiate persists a row too.
   */
  onGenerated?: () => void | Promise<void>;
}

type GenerateMode = 'freeform' | 'template';
/** Tabs that carry the free-form/template toggle (round-3 N2). */
type TemplateModeType = Exclude<OfficeDocType, 'pdf'>;
type TemplateLoadState = 'idle' | 'loading' | 'ready' | 'error';

/** File extension per template doc_type (round-3 N2). */
const TEMPLATE_EXT: Record<OfficeTemplateMeta['doc_type'], string> = {
  word: 'docx',
  excel: 'xlsx',
  ppt: 'pptx',
};

interface GenerateResult {
  path: string;
  sizeBytes: number;
  /** Template path only (item 3.2) — placeholders the template still holds. */
  unfilled?: string[];
}

/** `周报-2026-09-10.docx` style default for a freshly picked template. */
function defaultTemplateFilename(
  templateName: string,
  docType: OfficeTemplateMeta['doc_type'],
): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${templateName}-${yyyy}-${mm}-${dd}.${TEMPLATE_EXT[docType]}`;
}

export function OfficeGenerateForm({ workspacePath, onGenerated }: OfficeGenerateFormProps) {
  const { t } = useI18n();
  const [docType, setDocType] = useState<OfficeDocType>('ppt');
  const [filename, setFilename] = useState('my-document');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<GenerateResult | null>(null);

  // PPT
  const [pptTitle, setPptTitle] = useState('Slide 1');
  const [pptBullets, setPptBullets] = useState('First point\nSecond point');

  // Word — free-form
  const [wordTitle, setWordTitle] = useState('Document Title');
  const [wordBody, setWordBody] = useState('First paragraph of the document.');

  // Template mode, one entry per OOXML tab (round-3 N2 generalized the
  // batch-3 word-only toggle).
  const [modes, setModes] = useState<Record<TemplateModeType, GenerateMode>>({
    ppt: 'freeform',
    word: 'freeform',
    excel: 'freeform',
  });
  const [templates, setTemplates] = useState<OfficeTemplateMeta[]>([]);
  const [templateLoad, setTemplateLoad] = useState<TemplateLoadState>('idle');
  const [selectedTemplate, setSelectedTemplate] = useState<OfficeTemplateMeta | null>(null);
  const [templateData, setTemplateData] = useState<Record<string, string>>({});

  // Excel
  const [sheetName, setSheetName] = useState('Sheet1');
  const [sheetHeaders, setSheetHeaders] = useState('Name,Age,City');
  const [sheetRows, setSheetRows] = useState('Alice,30,Beijing\nBob,25,Shanghai');

  // PDF (parity batch 1, item 1.2) — backend page_size values are the
  // reportlab literals "A4" / "Letter" / "Legal" (backend/office/pdf.py:187).
  const [pdfTitle, setPdfTitle] = useState('');
  const [pdfParagraphs, setPdfParagraphs] = useState('First paragraph of the document.');
  const [pdfPageSize, setPdfPageSize] = useState<PdfPageSize>('A4');

  // Item 3.2: templates are workspace-scoped — drop any loaded list and
  // the selection when the workspace changes so a stale pick can't be
  // instantiated against the wrong workspace. Also resets every tab's
  // mode (round-3 N2: one entry per OOXML tab).
  useEffect(() => {
    setModes({ ppt: 'freeform', word: 'freeform', excel: 'freeform' });
    setTemplates([]);
    setTemplateLoad('idle');
    setSelectedTemplate(null);
    setTemplateData({});
  }, [workspacePath]);

  const loadTemplates = useCallback(async () => {
    setTemplateLoad('loading');
    try {
      const res = await officeApi.listTemplates(workspacePath);
      setTemplates(res.templates);
      setTemplateLoad('ready');
    } catch {
      setTemplates([]);
      setTemplateLoad('error');
    }
  }, [workspacePath]);

  const switchDocType = (type: OfficeDocType) => {
    setDocType(type);
    // A template pick is doc-type-specific — switching tabs drops the
    // selection (and its composed data) in the same state update so no
    // render ever exposes the wrong-type template to the submit path.
    setSelectedTemplate(null);
    setTemplateData({});
  };

  const switchMode = (type: TemplateModeType, mode: GenerateMode) => {
    setModes((prev) => ({ ...prev, [type]: mode }));
    // Fetch lazily on first entry so the free-form path costs nothing.
    // The list is fetched once per workspace and shared by all tabs —
    // the backend returns every doc_type and the picker filters.
    if (mode === 'template' && templateLoad === 'idle') {
      void loadTemplates();
    }
  };

  const pickTemplate = (tpl: OfficeTemplateMeta) => {
    setSelectedTemplate(tpl);
    setTemplateData({});
    setFilename(defaultTemplateFilename(tpl.name, tpl.doc_type));
  };

  const setPlaceholderValue = (name: string, value: string) => {
    setTemplateData((prev) => ({ ...prev, [name]: value }));
  };

  const handleInstantiate = async () => {
    if (!selectedTemplate) {
      toast.error(t('office.template.selectFirst'));
      return;
    }
    if (!filename.trim()) {
      toast.error(t('office.generate.filenameRequired'));
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      // Image placeholders never contribute text (office.template.hint.image);
      // blanks are skipped server-side and reported via unfilled_placeholders.
      const data: Record<string, string> = {};
      for (const ph of selectedTemplate.placeholders) {
        if (ph.type === 'image') continue;
        const value = (templateData[ph.name] ?? '').trim();
        if (value) data[ph.name] = value;
      }
      const out = await officeApi.instantiateTemplate({
        workspace_path: workspacePath,
        ...(selectedTemplate.source === 'workspace'
          ? { workspace_template: selectedTemplate.filename ?? selectedTemplate.id }
          : { template_id: selectedTemplate.id }),
        filename: filename.trim(),
        data,
      });
      setResult({
        path: out.output_path,
        sizeBytes: out.file_size_bytes,
        unfilled: out.unfilled_placeholders,
      });
      toast.success(`${t('office.template.success')} ${out.filename}`);
      // Same HIGH #6 contract as the free-form path: the instantiate
      // route persists a document row, so refresh the list.
      if (onGenerated) {
        await onGenerated();
      }
      // Clear the form: blank placeholder fields + default filename.
      setTemplateData({});
      setFilename('my-document');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.template.failed')}: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const handleGenerate = async () => {
    // Round-3 N2: the template path now serves ppt/word/excel alike —
    // `selectedTemplate` is guaranteed to match the active tab because
    // switchDocType clears it on every tab change.
    if (docType !== 'pdf' && modes[docType] === 'template') {
      await handleInstantiate();
      return;
    }
    if (!filename.trim()) {
      toast.error(t('office.generate.filenameRequired'));
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      let out: { output_path: string; filename: string; file_size_bytes: number };
      if (docType === 'ppt') {
        const bullets = pptBullets
          .split('\n')
          .map((b) => b.trim())
          .filter(Boolean);
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
      } else if (docType === 'pdf') {
        const paragraphs = pdfParagraphs
          .split('\n')
          .map((p) => p.trim())
          .filter(Boolean);
        out = await officeApi.generatePdf({
          workspace_path: workspacePath,
          filename,
          pages: [{ title: pdfTitle.trim() || null, paragraphs }],
          page_size: pdfPageSize,
        });
      } else {
        const headers = sheetHeaders
          .split(',')
          .map((h) => h.trim())
          .filter(Boolean);
        const rows = sheetRows.split('\n').map((r) => r.split(',').map((c) => c.trim()));
        out = await officeApi.generateExcel({
          workspace_path: workspacePath,
          filename,
          sheets: [{ name: sheetName, headers, rows }],
        });
      }
      setResult({ path: out.output_path, sizeBytes: out.file_size_bytes });
      toast.success(`${t('office.generate.success')} ${out.filename}`);
      // HIGH FIX: notify parent so it can refresh the document list.
      if (onGenerated) {
        await onGenerated();
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.generate.failed')}: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const inputClass =
    'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

  /** One dynamic field per template placeholder (item 3.2 field rules). */
  const renderPlaceholderField = (ph: OfficeTemplatePlaceholder) => {
    const value = templateData[ph.name] ?? '';
    if (ph.type === 'image') {
      return (
        <div key={ph.name} data-testid={`office-template-field-${ph.name}`}>
          <label className="block text-xs text-muted mb-1">{ph.name}</label>
          <p className="text-xs text-muted bg-bg-subtle border border-border rounded px-2 py-1.5">
            {t('office.template.hint.image')}
          </p>
        </div>
      );
    }
    const isLongForm = ph.type === 'table' || ph.type === 'rich_text';
    return (
      <div key={ph.name} data-testid={`office-template-field-${ph.name}`}>
        <label className="block text-xs text-muted mb-1">{ph.name}</label>
        {isLongForm ? (
          <textarea
            value={value}
            onChange={(e) => setPlaceholderValue(ph.name, e.target.value)}
            rows={3}
            className={inputClass}
            data-testid={`office-template-input-${ph.name}`}
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => setPlaceholderValue(ph.name, e.target.value)}
            placeholder={ph.type === 'date' ? t('office.template.hint.date') : undefined}
            className={inputClass}
            data-testid={`office-template-input-${ph.name}`}
          />
        )}
        {(ph.type === 'table' || ph.type === 'rich_text') && (
          <p className="text-xs text-muted mt-0.5">{t('office.template.hint.rich')}</p>
        )}
        {ph.type === 'date' && (
          <p className="text-xs text-muted mt-0.5">{t('office.template.hint.date')}</p>
        )}
        {ph.description && <p className="text-xs text-muted mt-0.5">{ph.description}</p>}
      </div>
    );
  };

  /** Free-form structured fields for one OOXML tab (Phase 1.4 originals). */
  const renderFreeformFields = (type: TemplateModeType) => {
    if (type === 'word') {
      return (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">
              {t('office.generate.wordTitle')}
            </label>
            <input
              type="text"
              value={wordTitle}
              onChange={(e) => setWordTitle(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">
              {t('office.generate.wordBody')}
            </label>
            <textarea
              value={wordBody}
              onChange={(e) => setWordBody(e.target.value)}
              rows={3}
              className={inputClass}
            />
          </div>
        </div>
      );
    }
    if (type === 'ppt') {
      return (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">{t('office.generate.pptTitle')}</label>
            <input
              type="text"
              value={pptTitle}
              onChange={(e) => setPptTitle(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">
              {t('office.generate.pptBullets')}
            </label>
            <textarea
              value={pptBullets}
              onChange={(e) => setPptBullets(e.target.value)}
              rows={3}
              className={inputClass}
            />
          </div>
        </div>
      );
    }
    return (
      <div className="space-y-2">
        <div>
          <label className="block text-xs text-muted mb-1">{t('office.generate.sheetName')}</label>
          <input
            type="text"
            value={sheetName}
            onChange={(e) => setSheetName(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">{t('office.generate.sheetHeaders')}</label>
          <input
            type="text"
            value={sheetHeaders}
            onChange={(e) => setSheetHeaders(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">{t('office.generate.sheetRows')}</label>
          <textarea
            value={sheetRows}
            onChange={(e) => setSheetRows(e.target.value)}
            rows={3}
            className={inputClass}
          />
        </div>
      </div>
    );
  };

  /**
   * Template picker for one OOXML tab (item 3.2; round-3 N2 extends it
   * beyond Word). The fetched list covers every doc_type — filter to the
   * tab's kind so a word template can never be instantiated from the
   * excel tab (and vice versa). The dynamic fields render only for a
   * pick matching the tab (switchDocType clears cross-tab picks anyway).
   */
  const renderTemplatePicker = (type: TemplateModeType) => {
    const visibleTemplates = templates.filter((tpl) => tpl.doc_type === type);
    return (
      <div className="space-y-2" data-testid="office-template-picker">
        <div className="text-xs text-muted">{t('office.template.pickTitle')}</div>

        {templateLoad === 'loading' && (
          <p className="text-xs text-muted" data-testid="office-template-loading">
            {t('office.template.loading')}
          </p>
        )}

        {templateLoad === 'error' && (
          <div className="space-y-1" data-testid="office-template-error">
            <p className="text-xs text-error">{t('office.template.loadFailed')}</p>
            <button
              type="button"
              onClick={() => void loadTemplates()}
              className="px-2 py-1 text-xs border border-border rounded text-text-secondary hover:bg-bg-hover"
            >
              {t('office.template.retry')}
            </button>
          </div>
        )}

        {templateLoad === 'ready' && visibleTemplates.length === 0 && (
          <p className="text-xs text-muted" data-testid="office-template-empty">
            {t('office.template.empty')}
          </p>
        )}

        {templateLoad === 'ready' &&
          visibleTemplates.map((tpl) => (
            <button
              key={`${tpl.source}-${tpl.id}`}
              type="button"
              onClick={() => pickTemplate(tpl)}
              data-testid={`office-template-option-${tpl.id}`}
              className={[
                'w-full text-left px-3 py-2 rounded border text-sm',
                selectedTemplate?.id === tpl.id && selectedTemplate.source === tpl.source
                  ? 'border-primary bg-primary/10'
                  : 'border-border hover:bg-bg-hover',
              ].join(' ')}
            >
              <span className="flex items-center gap-2 flex-wrap">
                <span className="font-medium text-text">{tpl.name}</span>
                <span
                  data-testid="office-template-source"
                  className={[
                    'px-1.5 py-0.5 rounded text-xs',
                    tpl.source === 'builtin'
                      ? 'bg-primary/10 text-primary'
                      : 'bg-bg-hover text-text-secondary border border-border',
                  ].join(' ')}
                >
                  {tpl.source === 'builtin'
                    ? t('office.template.source.builtin')
                    : t('office.template.source.workspace')}
                </span>
              </span>
              {tpl.description && (
                <span className="block text-xs text-muted mt-0.5">{tpl.description}</span>
              )}
            </button>
          ))}

        {selectedTemplate && selectedTemplate.doc_type === type && (
          <div className="space-y-2 pt-1" data-testid="office-template-fields">
            {selectedTemplate.placeholders.map((ph) => renderPlaceholderField(ph))}
          </div>
        )}
      </div>
    );
  };

  /** Mode toggle + free-form/template sections for one OOXML tab (N2). */
  const renderModeSection = (type: TemplateModeType) => {
    if (docType !== type) return null;
    return (
      <div className="space-y-2" data-testid={`office-${type}-form`}>
        {/* item 3.2 + round-3 N2 mode toggle: 自由创建 | 从模板创建 */}
        <div className="flex gap-2">
          {(
            [
              ['freeform', t('office.template.modeFreeform')],
              ['template', t('office.template.modeTemplate')],
            ] as [GenerateMode, string][]
          ).map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              onClick={() => switchMode(type, mode)}
              data-testid={`office-${type}-mode-${mode}`}
              className={[
                'flex items-center gap-1.5 px-3 py-1.5 rounded text-sm border',
                modes[type] === mode
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border text-text-secondary hover:bg-bg-hover',
              ].join(' ')}
            >
              {mode === 'template' && <LayoutTemplate className="w-3.5 h-3.5" />}
              {label}
            </button>
          ))}
        </div>

        {modes[type] === 'freeform' && renderFreeformFields(type)}

        {modes[type] === 'template' && renderTemplatePicker(type)}
      </div>
    );
  };

  // Round-3 N2: the template path serves ppt/word/excel alike; pdf has
  // no template mode.
  const templateModeActive = docType !== 'pdf' && modes[docType] === 'template';

  return (
    <div className="space-y-3 p-4 border border-border rounded-lg bg-bg-subtle">
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-primary" />
        <h2 className="text-sm font-medium text-text">{t('office.generate.title')}</h2>
      </div>

      <div className="flex gap-2">
        {(['ppt', 'word', 'excel', 'pdf'] as OfficeDocType[]).map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => switchDocType(type)}
            className={[
              'flex items-center gap-1.5 px-3 py-1.5 rounded text-sm border',
              docType === type
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border text-text-secondary hover:bg-bg-hover',
            ].join(' ')}
          >
            {type === 'ppt' && <Presentation className="w-3.5 h-3.5" />}
            {type === 'word' && <FileText className="w-3.5 h-3.5" />}
            {type === 'excel' && <FileSpreadsheet className="w-3.5 h-3.5" />}
            {type === 'pdf' && <FileType className="w-3.5 h-3.5" />}
            {type.toUpperCase()}
          </button>
        ))}
      </div>

      <div>
        <label className="block text-xs text-muted mb-1">{t('office.generate.filename')}</label>
        <input
          type="text"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
          className={inputClass}
          placeholder={t('office.generate.filenamePlaceholder')}
          data-testid="office-generate-filename"
        />
      </div>

      {/* OOXML tabs share the free-form/template toggle (round-3 N2);
          each call renders only when it is the active tab. */}
      {renderModeSection('ppt')}
      {renderModeSection('word')}
      {renderModeSection('excel')}

      {docType === 'pdf' && (
        <div className="space-y-2">
          <div>
            <label className="block text-xs text-muted mb-1">{t('office.generate.pdfTitle')}</label>
            <input
              type="text"
              value={pdfTitle}
              onChange={(e) => setPdfTitle(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">
              {t('office.generate.pdfParagraphs')}
            </label>
            <textarea
              value={pdfParagraphs}
              onChange={(e) => setPdfParagraphs(e.target.value)}
              rows={3}
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-muted mb-1">
              {t('office.generate.pdfPageSize')}
            </label>
            <select
              value={pdfPageSize}
              onChange={(e) => setPdfPageSize(e.target.value as PdfPageSize)}
              className={inputClass}
            >
              <option value="A4">A4</option>
              <option value="Letter">Letter</option>
              <option value="Legal">Legal</option>
            </select>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => void handleGenerate()}
        disabled={busy}
        className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover disabled:opacity-50"
        data-testid="office-generate-submit"
      >
        {busy
          ? templateModeActive
            ? t('office.template.creating')
            : t('office.generate.generating')
          : templateModeActive
            ? t('office.template.create')
            : `${t('office.generate.button')} ${docType.toUpperCase()}`}
      </button>

      {result && (
        <div className="text-xs text-muted bg-surface border border-border rounded p-2">
          <div>
            {t('office.generate.outputPath')} <code className="text-text">{result.path}</code>
          </div>
          <div>
            {t('office.generate.size')} {(result.sizeBytes / 1024).toFixed(1)} KB
          </div>
          {result.unfilled && result.unfilled.length > 0 && (
            <div data-testid="office-template-unfilled">
              {t('office.template.unfilled')}: {result.unfilled.join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
