/**
 * WordTemplateFillDialog — M6e (office-word-template, §118)。
 *
 * 把后端已有的 Word 模板 Profile/填充能力接进文档库：选中模板（受管 Word
 * 文档或 `<workspace>/office/templates/*.docx`）→ `POST …/word/template/profile`
 * 分析槽位（内容控件 / 书签 / 占位符 / 图片）→ 填值后
 * `POST …/word/template/profile/fill` 在模板同目录产出 `<stem>-filled.docx`。
 *
 * 后端拒绝覆盖模板与已存在文件；成功后可通过 `onFilled` 把输出文件的绝对
 * 路径交给调用方导入文档库并预览。
 */

import { FileText } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import { officeWordTemplateApi } from '../../shared/api/officeWordTemplateApi';
import type {
  OfficeDocumentSummary,
  OfficeTemplateMeta,
  OfficeWordTemplateFillResult,
  OfficeWordTemplateProfileResult,
  OfficeWordTemplateSlot,
} from '../../shared/api/types';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import type { TranslationKey } from '../../shared/lib/i18n';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Modal } from '../../shared/ui/Modal';

import { officeDocumentRelativePath } from './officeDocumentPath';

export interface WordTemplateFillDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** 工作区绝对路径；null 时无法分析/填充。 */
  workspacePath: string | null;
  /** 候选文档（调用方负责过滤归档项；这里再筛 word）。 */
  documents: OfficeDocumentSummary[];
  /** 填充成功后回调输出文件的绝对路径（用于导入文档库并预览）。 */
  onFilled?: (absolutePath: string) => void | Promise<void>;
}

interface TemplateOption {
  key: string;
  label: string;
  /** 工作区相对路径（posix），与后端 profile/fill 的 template_path 一致。 */
  path: string;
}

const WORKSPACE_TEMPLATES_DIR = 'office/templates';

const KIND_I18N_KEYS: Record<string, TranslationKey> = {
  content_control: 'office.wordTemplate.kind.contentControl',
  bookmark: 'office.wordTemplate.kind.bookmark',
  placeholder: 'office.wordTemplate.kind.placeholder',
  jinja: 'office.wordTemplate.kind.jinja',
};

function fileStem(path: string): string {
  const name = path.slice(path.lastIndexOf('/') + 1);
  return name.replace(/\.[^.]+$/, '');
}

function documentLabel(doc: OfficeDocumentSummary): string {
  return doc.original_filename ?? doc.generated_filename;
}

export function WordTemplateFillDialog({
  isOpen,
  onClose,
  workspacePath,
  documents,
  onFilled,
}: WordTemplateFillDialogProps) {
  const { t } = useI18n();
  const [templates, setTemplates] = useState<OfficeTemplateMeta[] | null>(null);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [templateKey, setTemplateKey] = useState('');
  const [profile, setProfile] = useState<OfficeWordTemplateProfileResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [outputName, setOutputName] = useState('');
  const [running, setRunning] = useState(false);
  const [fillError, setFillError] = useState<string | null>(null);
  const [result, setResult] = useState<OfficeWordTemplateFillResult | null>(null);
  const analyzeIdRef = useRef(0);
  const fillIdRef = useRef(0);

  const loadTemplates = useCallback(async () => {
    if (!workspacePath) return;
    const myId = ++analyzeIdRef.current;
    setLoadingTemplates(true);
    setTemplatesError(null);
    try {
      const response = await officeApi.listTemplates(workspacePath);
      if (myId !== analyzeIdRef.current) return;
      setTemplates(response.templates);
    } catch (e) {
      if (myId !== analyzeIdRef.current) return;
      setTemplatesError(e instanceof Error ? e.message : String(e));
    } finally {
      if (myId === analyzeIdRef.current) setLoadingTemplates(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    if (!isOpen) return;
    setTemplateKey('');
    setProfile(null);
    setAnalyzeError(null);
    setValues({});
    setOutputName('');
    setFillError(null);
    setResult(null);
    void loadTemplates();
    return () => {
      analyzeIdRef.current += 1;
      fillIdRef.current += 1;
    };
  }, [isOpen, loadTemplates]);

  const options = useMemo<TemplateOption[]>(() => {
    const docs = documents
      .filter((doc) => doc.doc_type === 'word' && doc.archived_at == null)
      .map((doc) => ({
        key: `doc:${doc.id}`,
        label: documentLabel(doc),
        path: officeDocumentRelativePath(doc),
      }));
    const tpls = (templates ?? [])
      .filter((tpl) => tpl.source === 'workspace' && tpl.doc_type === 'word' && tpl.filename)
      .map((tpl) => ({
        key: `tpl:${tpl.filename}`,
        label: tpl.name,
        path: `${WORKSPACE_TEMPLATES_DIR}/${tpl.filename}`,
      }));
    return [...docs, ...tpls];
  }, [documents, templates]);

  const selected = options.find((option) => option.key === templateKey) ?? null;

  const handleSelectTemplate = async (key: string) => {
    setTemplateKey(key);
    setProfile(null);
    setAnalyzeError(null);
    setValues({});
    setFillError(null);
    setResult(null);
    const option = options.find((candidate) => candidate.key === key) ?? null;
    setOutputName(option ? `${fileStem(option.path)}-filled.docx` : '');
    if (!option || !workspacePath) return;
    const myId = ++analyzeIdRef.current;
    setAnalyzing(true);
    try {
      const response = await officeWordTemplateApi.analyzeProfile({
        workspace_path: workspacePath,
        file_path: option.path,
      });
      if (myId !== analyzeIdRef.current) return;
      setProfile(response);
      setValues(Object.fromEntries(response.slots.map((slot) => [slot.name, ''])));
    } catch (e) {
      if (myId !== analyzeIdRef.current) return;
      const message = e instanceof Error ? e.message : String(e);
      setAnalyzeError(`${t('office.wordTemplate.analyzeFailed')}: ${message}`);
    } finally {
      if (myId === analyzeIdRef.current) setAnalyzing(false);
    }
  };

  const isSlotFilled = (slot: OfficeWordTemplateSlot) =>
    (values[slot.name] ?? '').trim().length > 0;

  const missingRequired = (profile?.slots ?? []).filter(
    (slot) => slot.required && !isSlotFilled(slot),
  );

  const canRun =
    workspacePath != null &&
    selected != null &&
    profile != null &&
    !analyzing &&
    !running &&
    outputName.trim().length > 0 &&
    missingRequired.length === 0;

  const handleFill = async () => {
    if (!canRun || !workspacePath || !profile || !selected) return;
    const data: Record<string, string> = {};
    const images: Record<string, string> = {};
    for (const slot of profile.slots) {
      const value = (values[slot.name] ?? '').trim();
      if (!value) continue;
      if (slot.type === 'image') {
        images[slot.name] = value;
      } else {
        data[slot.name] = value;
      }
    }
    const myId = ++fillIdRef.current;
    setRunning(true);
    setFillError(null);
    try {
      const response = await officeWordTemplateApi.fillProfile({
        workspace_path: workspacePath,
        template_path: selected.path,
        output_filename: outputName.trim(),
        data,
        ...(Object.keys(images).length > 0 ? { images } : {}),
      });
      if (myId !== fillIdRef.current) return;
      setResult(response);
    } catch (e) {
      if (myId !== fillIdRef.current) return;
      const message = e instanceof Error ? e.message : String(e);
      setFillError(`${t('office.wordTemplate.fillFailed')}: ${message}`);
    } finally {
      if (myId === fillIdRef.current) setRunning(false);
    }
  };

  const handleImport = async () => {
    if (!workspacePath || !result || !onFilled) return;
    const base = workspacePath.replace(/[\\/]+$/, '');
    try {
      await onFilled(`${base}/${result.output_path}`);
      onClose();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFillError(`${t('office.wordTemplate.fillFailed')}: ${message}`);
    }
  };

  const handleClose = () => {
    analyzeIdRef.current += 1;
    fillIdRef.current += 1;
    onClose();
  };

  const selectClass =
    'w-full rounded border border-border bg-ui-panel px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40';
  const inputClass =
    'w-full rounded border border-border bg-ui-panel px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40';

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={t('office.wordTemplate.title')}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={handleClose}>
            {t('office.wordTemplate.cancel')}
          </Button>
          <Button
            onClick={() => void handleFill()}
            disabled={!canRun}
            data-testid="office-word-template-run"
          >
            <FileText className="w-4 h-4 mr-2" />
            {running ? t('office.wordTemplate.running') : t('office.wordTemplate.run')}
          </Button>
        </div>
      }
    >
      <div className="space-y-3 text-sm" data-testid="office-word-template-dialog">
        {options.length === 0 ? (
          <p className="text-muted" data-testid="office-word-template-empty">
            {loadingTemplates ? t('office.wordTemplate.loading') : t('office.wordTemplate.empty')}
          </p>
        ) : (
          <label className="block space-y-1">
            <span className="text-xs text-muted">{t('office.wordTemplate.template')}</span>
            <select
              className={selectClass}
              value={templateKey}
              onChange={(event) => void handleSelectTemplate(event.target.value)}
              data-testid="office-word-template-select"
            >
              <option value="">{t('office.wordTemplate.select')}</option>
              {options.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        )}

        {templatesError && (
          <p
            className="text-xs text-danger break-all"
            data-testid="office-word-template-templates-error"
          >
            {t('office.template.loadFailed')}: {templatesError}
          </p>
        )}

        {analyzing && (
          <p className="text-xs text-muted" data-testid="office-word-template-analyzing">
            {t('office.wordTemplate.analyzing')}
          </p>
        )}

        {analyzeError && (
          <p
            className="text-xs text-danger break-all"
            data-testid="office-word-template-analyze-error"
          >
            {analyzeError}
          </p>
        )}

        {profile && (
          <>
            <p className="text-xs text-muted" data-testid="office-word-template-summary">
              {fillTemplate(t('office.wordTemplate.slotsTitle'), { count: profile.slots.length })}
            </p>
            {profile.slots.length === 0 ? (
              <p className="text-xs text-muted" data-testid="office-word-template-no-slots">
                {t('office.wordTemplate.noSlots')}
              </p>
            ) : (
              <div
                className="max-h-80 overflow-y-auto space-y-3 rounded border border-border bg-ui-panel px-3 py-2"
                data-testid="office-word-template-slots"
              >
                {profile.slots.map((slot) => (
                  <label key={`${slot.kind}:${slot.name}`} className="block space-y-1">
                    <span className="flex items-center gap-2 text-xs">
                      <span className="font-medium text-text">{slot.name}</span>
                      <span className="rounded bg-bg-subtle px-1.5 py-0.5 text-muted">
                        {t(KIND_I18N_KEYS[slot.kind] ?? 'office.wordTemplate.kind.other')}
                      </span>
                      {slot.required && (
                        <span className="text-danger" data-testid="office-word-template-required">
                          *{t('office.wordTemplate.required')}
                        </span>
                      )}
                    </span>
                    {slot.description && (
                      <span className="block text-xs text-muted">{slot.description}</span>
                    )}
                    <input
                      type="text"
                      className={inputClass}
                      value={values[slot.name] ?? ''}
                      placeholder={
                        slot.current_value
                          ? fillTemplate(t('office.wordTemplate.currentValueHint'), {
                              value: slot.current_value,
                            })
                          : slot.type === 'image'
                            ? t('office.wordTemplate.imageHint')
                            : ''
                      }
                      onChange={(event) =>
                        setValues((prev) => ({ ...prev, [slot.name]: event.target.value }))
                      }
                      data-testid={`office-word-template-slot-${slot.name}`}
                    />
                  </label>
                ))}
              </div>
            )}

            {profile.warnings.length > 0 && (
              <div className="text-xs text-muted" data-testid="office-word-template-warnings">
                <span className="font-medium">{t('office.wordTemplate.warnings')}: </span>
                {profile.warnings.map((warning) => warning.message || warning.code).join('; ')}
              </div>
            )}

            <label className="block space-y-1">
              <span className="text-xs text-muted">{t('office.wordTemplate.output')}</span>
              <input
                type="text"
                className={inputClass}
                value={outputName}
                onChange={(event) => setOutputName(event.target.value)}
                data-testid="office-word-template-output"
              />
            </label>
          </>
        )}

        {fillError && (
          <p
            className="text-xs text-danger break-all"
            data-testid="office-word-template-fill-error"
          >
            {fillError}
          </p>
        )}

        {result && (
          <div
            className="space-y-2 rounded border border-border bg-ui-panel px-3 py-2"
            data-testid="office-word-template-result"
          >
            <p
              className="text-xs font-medium text-text"
              data-testid="office-word-template-filled-count"
            >
              {fillTemplate(t('office.wordTemplate.filledCount'), { count: result.filled_count })}:{' '}
              <span className="font-mono">{result.output_path}</span>
            </p>
            {result.unfilled_slots.length > 0 && (
              <p className="text-xs text-muted">
                {t('office.wordTemplate.unfilled')}: {result.unfilled_slots.join('; ')}
              </p>
            )}
            {result.residual_placeholders.length > 0 && (
              <p className="text-xs text-muted">
                {t('office.wordTemplate.residual')}: {result.residual_placeholders.join('; ')}
              </p>
            )}
            {result.warnings.length > 0 && (
              <p className="text-xs text-muted">
                {t('office.wordTemplate.warnings')}:{' '}
                {result.warnings.map((warning) => warning.message || warning.code).join('; ')}
              </p>
            )}
            {onFilled && (
              <Button data-testid="office-word-template-import" onClick={() => void handleImport()}>
                {t('office.wordTemplate.importOpen')}
              </Button>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
