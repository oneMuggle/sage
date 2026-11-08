import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { officeGenerateApi } from '../../shared/api/officeGenerateApi';
import type {
  OfficeDocType,
  OfficeDocumentSummary,
  OfficeGenerateResult,
  OfficeTemplateChatMessage,
  OfficeTemplateMeta,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';
import { useTaskCenterStore } from '../task-center/taskCenterStore';

import { TemplateLibrary } from './TemplateLibrary';
import { officeDocumentPath } from './officeDocumentPath';
import { pollOfficeProgress } from './officeProgress';

const TASK_ID = 'office:generate';

const DOC_TYPES: OfficeDocType[] = ['word', 'ppt', 'excel', 'pdf'];

const MODE_KEYS = {
  nl: 'office.generate.workspace.mode.nl',
  reference: 'office.generate.workspace.mode.reference',
  template: 'office.generate.workspace.mode.template',
  iterate: 'office.generate.workspace.mode.iterate',
} as const;

export type GenerateWorkspaceMode = keyof typeof MODE_KEYS;

export interface GenerateWorkspaceProps {
  workspacePath: string;
  documents: OfficeDocumentSummary[];
  onGenerated?: () => void | Promise<void>;
  onOpenDocument?: (docId: string) => void | Promise<void>;
}

const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

export function GenerateWorkspace({
  workspacePath,
  documents,
  onGenerated,
  onOpenDocument,
}: GenerateWorkspaceProps) {
  const { t } = useI18n();
  const registerTask = useTaskCenterStore((s) => s.registerTask);
  const finishTask = useTaskCenterStore((s) => s.finishTask);

  const [mode, setMode] = useState<GenerateWorkspaceMode>('nl');
  const [docType, setDocType] = useState<OfficeDocType>('word');
  const [instruction, setInstruction] = useState('');
  const [referenceIds, setReferenceIds] = useState<string[]>([]);
  const [iterateId, setIterateId] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<OfficeTemplateMeta | null>(null);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<OfficeTemplateChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<OfficeGenerateResult | null>(null);

  const wordDocuments = useMemo(
    () =>
      documents.filter(
        (doc) => doc.doc_type === 'word' && doc.archived_at === null && officeDocumentPath(doc),
      ),
    [documents],
  );

  const toggleReference = (id: string) => {
    setReferenceIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const validationError = (): string | null => {
    if (mode === 'template') {
      if (!selectedTemplate) return t('office.generate.workspace.missingTemplate');
      if (!chatInput.trim()) return t('office.generate.workspace.missingInstruction');
      return null;
    }
    if (mode === 'iterate' && !iterateId) {
      return t('office.generate.workspace.missingSource');
    }
    if (!instruction.trim()) return t('office.generate.workspace.missingInstruction');
    return null;
  };

  const callGenerate = async (taskId: string): Promise<OfficeGenerateResult> => {
    if (mode === 'template') {
      const template = selectedTemplate as OfficeTemplateMeta;
      const messages: OfficeTemplateChatMessage[] = [
        ...chatMessages,
        { role: 'user', content: chatInput.trim() },
      ];
      const res = await officeGenerateApi.generateFromTemplateChat({
        task_id: taskId,
        workspace_path: workspacePath,
        messages,
        ...(template.source === 'builtin'
          ? { template_id: template.id }
          : { workspace_template: template.filename }),
      });
      setChatMessages([
        ...messages,
        { role: 'assistant', content: `${t('office.generate.success')} ${res.filename}` },
      ]);
      setChatInput('');
      return res;
    }

    if (mode === 'iterate') {
      const source = documents.find((doc) => doc.id === iterateId);
      const sourcePath = source ? officeDocumentPath(source) : null;
      if (!sourcePath) throw new Error(t('office.generate.workspace.sourceEmpty'));
      return officeGenerateApi.iterateDocument({
        task_id: taskId,
        workspace_path: workspacePath,
        source_path: sourcePath,
        instruction: instruction.trim(),
      });
    }

    const referencePaths =
      mode === 'reference'
        ? documents
            .filter((doc) => referenceIds.includes(doc.id))
            .map((doc) => officeDocumentPath(doc))
            .filter((path): path is string => path !== null)
        : [];

    return officeGenerateApi.generateFromNl({
      task_id: taskId,
      workspace_path: workspacePath,
      instruction: instruction.trim(),
      doc_type: docType,
      ...(referencePaths.length > 0 ? { reference_paths: referencePaths } : {}),
    });
  };

  const handleSubmit = async () => {
    const error = validationError();
    if (error) {
      toast.error(error);
      return;
    }
    if (!workspacePath) {
      toast.error(t('office.picker.noWorkspace'));
      return;
    }

    const taskId = crypto.randomUUID();
    setBusy(true);
    setResult(null);
    registerTask(TASK_ID, 'office', t('office.generate.workspace.generating'));
    const stopPoll = pollOfficeProgress(taskId, (tick) =>
      useTaskCenterStore.getState().updateTask(TASK_ID, {
        phase: tick.stage ?? undefined,
        percent: tick.percent,
      }),
    );

    let res: OfficeGenerateResult | null = null;
    try {
      res = await callGenerate(taskId);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.generate.failed')}: ${msg}`);
    } finally {
      stopPoll();
      finishTask(TASK_ID);
      setBusy(false);
    }

    if (res) {
      setResult(res);
      toast.success(`${t('office.generate.success')} ${res.filename}`);
      // Parent refresh failures must not be reported as a generation failure.
      void Promise.resolve()
        .then(() => onGenerated?.())
        .catch(() => undefined);
    }
  };

  return (
    <div data-testid="office-generate-workspace" className="grid grid-cols-1 gap-6 lg:grid-cols-5">
      <section className="space-y-4 lg:col-span-2" data-testid="office-generate-workspace-form">
        <h2 className="text-sm font-medium text-text">{t('office.generate.workspace.title')}</h2>

        <div
          role="tablist"
          className="flex flex-wrap gap-1 rounded border border-border bg-bg-subtle p-1"
        >
          {(Object.keys(MODE_KEYS) as GenerateWorkspaceMode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              data-testid={`office-generate-workspace-mode-${m}`}
              className={`rounded px-2.5 py-1 text-xs ${
                mode === m ? 'bg-primary/10 text-primary' : 'text-text-secondary hover:bg-bg-hover'
              }`}
              onClick={() => setMode(m)}
            >
              {t(MODE_KEYS[m])}
            </button>
          ))}
        </div>

        {mode === 'template' ? (
          <TemplateLibrary
            workspacePath={workspacePath}
            selectedId={selectedTemplate?.id ?? null}
            onSelect={setSelectedTemplate}
          />
        ) : null}

        {mode === 'nl' || mode === 'reference' ? (
          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">
              {t('office.generate.workspace.docType')}
            </span>
            <select
              className={inputClass}
              value={docType}
              data-testid="office-generate-workspace-doc-type"
              onChange={(e) => setDocType(e.target.value as OfficeDocType)}
            >
              {DOC_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`office.generate.docType.${type}`)}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {mode === 'reference' ? (
          <div className="space-y-1">
            <span className="text-xs text-text-secondary">
              {t('office.generate.workspace.references')}
            </span>
            {wordDocuments.length === 0 ? (
              <p
                className="text-xs text-muted"
                data-testid="office-generate-workspace-references-empty"
              >
                {t('office.generate.workspace.referencesEmpty')}
              </p>
            ) : (
              <ul className="space-y-1">
                {wordDocuments.map((doc) => (
                  <li key={doc.id}>
                    <label className="flex items-center gap-2 text-sm text-text">
                      <input
                        type="checkbox"
                        data-testid={`office-generate-workspace-ref-${doc.id}`}
                        checked={referenceIds.includes(doc.id)}
                        onChange={() => toggleReference(doc.id)}
                      />
                      {doc.generated_filename}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {mode === 'iterate' ? (
          <div className="space-y-1">
            <span className="text-xs text-text-secondary">
              {t('office.generate.workspace.sourceDoc')}
            </span>
            {wordDocuments.length === 0 ? (
              <p
                className="text-xs text-muted"
                data-testid="office-generate-workspace-source-empty"
              >
                {t('office.generate.workspace.sourceEmpty')}
              </p>
            ) : (
              <ul className="space-y-1">
                {wordDocuments.map((doc) => (
                  <li key={doc.id}>
                    <label className="flex items-center gap-2 text-sm text-text">
                      <input
                        type="radio"
                        name="office-iterate-source"
                        data-testid={`office-generate-workspace-iterate-${doc.id}`}
                        checked={iterateId === doc.id}
                        onChange={() => setIterateId(doc.id)}
                      />
                      {doc.generated_filename}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {mode === 'template' ? (
          <div className="space-y-2">
            <ul className="space-y-1 text-sm text-text">
              {chatMessages.map((msg, index) => (
                <li key={index} className={msg.role === 'assistant' ? 'text-muted' : ''}>
                  {msg.content}
                </li>
              ))}
            </ul>
            <input
              className={inputClass}
              placeholder={t('office.generate.workspace.chatPlaceholder')}
              value={chatInput}
              data-testid="office-generate-workspace-chat-input"
              onChange={(e) => setChatInput(e.target.value)}
            />
          </div>
        ) : (
          <label className="block space-y-1">
            <span className="text-xs text-text-secondary">
              {t('office.generate.workspace.instruction')}
            </span>
            <textarea
              className={`${inputClass} min-h-[120px]`}
              placeholder={t('office.generate.workspace.instructionPlaceholder')}
              value={instruction}
              data-testid="office-generate-workspace-instruction"
              onChange={(e) => setInstruction(e.target.value)}
            />
          </label>
        )}

        <button
          type="button"
          className="rounded bg-primary px-3 py-1.5 text-sm text-text-inverse hover:bg-primary-hover disabled:opacity-50"
          data-testid="office-generate-workspace-submit"
          disabled={busy}
          onClick={() => void handleSubmit()}
        >
          {busy ? t('office.generate.workspace.generating') : t('office.generate.workspace.submit')}
        </button>
      </section>

      <aside
        className="space-y-2 rounded-lg border border-border bg-surface p-4 lg:col-span-3"
        data-testid="office-generate-workspace-result"
      >
        <h3 className="text-sm font-medium text-text">
          {t('office.generate.workspace.resultTitle')}
        </h3>
        {result ? (
          <div className="space-y-1 text-sm">
            <p
              className="font-medium text-text"
              data-testid="office-generate-workspace-result-filename"
            >
              {result.filename}
            </p>
            <p className="text-xs tabular-nums text-muted">{result.file_size_bytes} B</p>
            <button
              type="button"
              className="text-xs text-primary hover:underline"
              data-testid="office-generate-workspace-result-open"
              onClick={() => void onOpenDocument?.(result.summary.id)}
            >
              {t('office.generate.workspace.open')}
            </button>
          </div>
        ) : (
          <p className="text-xs text-muted" data-testid="office-generate-workspace-result-empty">
            {t('office.generate.workspace.resultEmpty')}
          </p>
        )}
      </aside>
    </div>
  );
}
