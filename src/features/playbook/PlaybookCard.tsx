/**
 * PlaybookCard — 项目规程（阶段 / 完整性 / 建议动作 / 导出导入）。
 *
 * 数据来自 `/projects/{id}/playbook` 与 `/playbook/audit`。所有写操作
 * （绑定、创建目录/骨架、推进阶段、导入）都先由用户点击确认。
 */
import { AlertCircle, CheckCircle2, Circle, Loader2, Upload } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { playbookApi } from '../../shared/api/playbookApi';
import type {
  PlaybookAction,
  PlaybookAudit,
  PlaybookAuthorPreview,
  PlaybookCurrent,
  PlaybookImportPreview,
  PlaybookLibraryItem,
  PlaybookMove,
  PlaybookSpec,
  PlaybookSummary,
  PlaybookVersion,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { PlaybookAuthorPanel } from './PlaybookAuthorPanel';
import { PlaybookChecklist } from './PlaybookChecklist';
import { PlaybookClassificationPanel } from './PlaybookClassificationPanel';
import { PlaybookImportPreviewCard } from './PlaybookImportPreviewCard';
import { PlaybookLibraryPanel } from './PlaybookLibraryPanel';
import { PlaybookSpecEditor } from './PlaybookSpecEditor';
import { PlaybookToolbar } from './PlaybookToolbar';
import { PlaybookVersionsPanel } from './PlaybookVersionsPanel';
import { downloadPlaybookText } from './playbookDownload';
import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookCardProps {
  projectId: string;
  compact?: boolean;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function PlaybookCard({ projectId, compact = false }: PlaybookCardProps) {
  const { t, tf } = usePlaybookI18n();
  const [current, setCurrent] = useState<PlaybookCurrent | null>(null);
  const [builtins, setBuiltins] = useState<PlaybookSummary[]>([]);
  const [library, setLibrary] = useState<PlaybookLibraryItem[]>([]);
  const [selectedPlaybook, setSelectedPlaybook] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissedDetected, setDismissedDetected] = useState(false);
  const [authorNotes, setAuthorNotes] = useState('');
  const [authorResult, setAuthorResult] = useState<PlaybookAuthorPreview | null>(null);
  const [editingSpec, setEditingSpec] = useState(false);
  const [importPreview, setImportPreview] = useState<PlaybookImportPreview | null>(null);
  const [importEnvelope, setImportEnvelope] = useState<Record<string, unknown> | null>(null);
  const [importConflict, setImportConflict] = useState<'save_as_new' | 'merge' | 'replace'>(
    'save_as_new',
  );
  const [saveToLibrary, setSaveToLibrary] = useState(false);
  const [versions, setVersions] = useState<PlaybookVersion[]>([]);
  const [showVersions, setShowVersions] = useState(false);
  const [showLibrary, setShowLibrary] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await playbookApi.getCurrent(projectId);
      setCurrent(data);
      if (!data.bound) {
        const [list, items] = await Promise.all([
          playbookApi.listBuiltin(),
          playbookApi.listLibrary(),
        ]);
        setBuiltins(list);
        setLibrary(items);
        const defaultSelection = data.suggested?.id
          ? `builtin:${data.suggested.id}`
          : list[0]
            ? `builtin:${list[0].id}`
            : items[0]
              ? `library:${items[0].id}`
              : '';
        setSelectedPlaybook((prev) => prev || defaultSelection);
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const run = async (key: string, task: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await task();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const handleBind = () =>
    run('bind', async () => {
      const [kind, id] = selectedPlaybook.split(':', 2);
      const data =
        kind === 'library'
          ? await playbookApi.bind(projectId, { libraryId: id })
          : await playbookApi.bind(projectId, { playbookId: id });
      setCurrent(data);
      setNotice(t('playbook.notice.bound'));
    });

  const handleRefreshAudit = () =>
    run('audit', async () => {
      const audit: PlaybookAudit = await playbookApi.audit(projectId);
      setCurrent((prev) => (prev ? { ...prev, audit } : prev));
      setNotice(t('playbook.notice.auditRefreshed'));
    });

  const handleAiAudit = () =>
    run('audit-ai', async () => {
      const audit: PlaybookAudit = await playbookApi.auditAi(projectId);
      setCurrent((prev) => (prev ? { ...prev, audit } : prev));
      setNotice(
        audit.llm_available ? t('playbook.notice.aiDone') : t('playbook.notice.aiFallback'),
      );
    });

  const handleAction = (action: PlaybookAction) =>
    run(action.type, async () => {
      const result = await playbookApi.applyActions(projectId, [action]);
      if (result.errors.length) {
        setError(
          result.errors.map((item) => item.message).join(t('playbook.common.errorSeparator')),
        );
        return;
      }
      setCurrent((prev) => (prev ? { ...prev, audit: result.audit ?? prev.audit } : prev));
      if (!result.audit) await refresh();
      setNotice(
        result.applied.length
          ? tf('playbook.notice.executed', {
              items: result.applied.join(t('playbook.common.listSeparator')),
            })
          : t('playbook.notice.upToDate'),
      );
    });

  const handleBatchMove = (moves: PlaybookMove[]) =>
    run('batch-move', async () => {
      if (!moves.length) return;
      const result = await playbookApi.applyActions(projectId, [
        { type: 'batch_move', payload: { moves } },
      ]);
      if (result.errors.length) {
        setError(
          result.errors.map((item) => item.message).join(t('playbook.common.errorSeparator')),
        );
        return;
      }
      setCurrent((prev) => (prev ? { ...prev, audit: result.audit ?? prev.audit } : prev));
      if (!result.audit) await refresh();
      setNotice(tf('playbook.notice.batchMoved', { count: moves.length }));
    });

  const handleUndoBatch = () =>
    run('undo-batch', async () => {
      const result = await playbookApi.applyActions(projectId, [
        { type: 'undo_last_batch_move', payload: {} },
      ]);
      if (result.errors.length) {
        setError(
          result.errors.map((item) => item.message).join(t('playbook.common.errorSeparator')),
        );
        return;
      }
      setCurrent((prev) => (prev ? { ...prev, audit: result.audit ?? prev.audit } : prev));
      if (!result.audit) await refresh();
      setNotice(t('playbook.notice.undoBatch'));
    });

  const handleConfirmStage = (stageId: string) =>
    run('stage', async () => {
      const data = await playbookApi.confirmStage(projectId, stageId);
      setCurrent(data);
      setDismissedDetected(true);
      setNotice(t('playbook.notice.stageUpdated'));
    });

  const handleAuthor = () =>
    run('author', async () => {
      const result = await playbookApi.authorPreview(projectId, { notes: authorNotes });
      setAuthorResult(result);
      setNotice(result.rationale);
    });

  const handleBindAuthored = () =>
    run('bind-authored', async () => {
      if (!authorResult) return;
      const data = await playbookApi.bind(projectId, {
        spec: authorResult.playbook,
        source: 'ai-authored',
      });
      setCurrent(data);
      setNotice(t('playbook.notice.boundAuthored'));
    });

  const handleStartEdit = () => {
    if (!current?.playbook) return;
    setEditingSpec(true);
  };

  const handleSaveSpec = (spec: PlaybookSpec) =>
    run('save-spec', async () => {
      const data = await playbookApi.bind(projectId, {
        spec,
        source: 'custom',
      });
      setCurrent(data);
      setEditingSpec(false);
      setNotice(t('playbook.notice.specSaved'));
    });

  const handleExport = (format: 'json' | 'md' | 'agents') =>
    run('export-' + format, async () => {
      const result = await playbookApi.exportPlaybook(projectId, format);
      const text =
        typeof result.content === 'string'
          ? result.content
          : JSON.stringify(result.content, null, 2);
      downloadPlaybookText(
        result.filename,
        text,
        format === 'json' ? 'application/json' : 'text/markdown',
      );
      setNotice(tf('playbook.notice.exported', { filename: result.filename }));
    });

  const handleWikiExport = () =>
    run('wiki-export', async () => {
      const result = await playbookApi.exportToWiki(projectId);
      setNotice(
        result.created
          ? tf('playbook.notice.wikiCreated', { path: result.path })
          : tf('playbook.notice.wikiUpdated', { path: result.path }),
      );
    });

  const handleSaveToLibrary = () =>
    run('save-library', async () => {
      const exported = await playbookApi.exportPlaybook(projectId, 'json', true);
      const item = await playbookApi.saveLibrary(
        exported.content as Record<string, unknown>,
        'project',
      );
      setNotice(tf('playbook.notice.savedLibrary', { name: item.name }));
    });

  const handleWaive = (stageId: string, artifactId: string) =>
    run('waive', async () => {
      const key = `${stageId}.${artifactId}`;
      const waivers = Array.from(new Set([...(current?.state.waivers ?? []), key]));
      const data = await playbookApi.updateState(projectId, { waivers });
      setCurrent(data);
      setNotice(tf('playbook.notice.waived', { id: artifactId }));
    });

  const handleManualDone = (stageId: string, criterionId: string) =>
    run('manual-done', async () => {
      const key = `${stageId}.${criterionId}`;
      const manualDone = Array.from(new Set([...(current?.state.manual_done ?? []), key]));
      const data = await playbookApi.updateState(projectId, {
        manual_done: manualDone,
      });
      setCurrent(data);
      setNotice(tf('playbook.notice.manualDone', { id: criterionId }));
    });

  const handleSeedMilestones = () => {
    const milestones = (current?.playbook?.stages ?? []).flatMap((stage) =>
      (stage.recommended_milestones ?? [])
        .map((item) => ({
          title: String(item.title ?? ''),
          description: String(item.description ?? ''),
          stage: String(item.stage ?? stage.id),
        }))
        .filter((item) => item.title),
    );
    if (!milestones.length) {
      setNotice(t('playbook.notice.noMilestones'));
      return;
    }
    void run('seed-milestones', async () => {
      const result = await playbookApi.applyActions(projectId, [
        { type: 'seed_milestones', payload: { milestones } },
      ]);
      if (result.errors.length) {
        setError(
          result.errors.map((item) => item.message).join(t('playbook.common.errorSeparator')),
        );
        return;
      }
      setCurrent((prev) => (prev ? { ...prev, audit: result.audit ?? prev.audit } : prev));
      setNotice(t('playbook.notice.seeded'));
    });
  };

  const handleCleanupRules = () => {
    if (!window.confirm(t('playbook.confirm.cleanup'))) return;
    void run('cleanup-rules', async () => {
      const removed = await playbookApi.cleanupRules(projectId);
      setNotice(tf('playbook.notice.cleaned', { count: removed }));
    });
  };

  const handleUnbind = () => {
    if (!window.confirm(t('playbook.confirm.unbind'))) return;
    void run('unbind', async () => {
      const data = await playbookApi.unbind(projectId);
      setCurrent(data);
      setEditingSpec(false);
      setNotice(t('playbook.notice.unbound'));
    });
  };

  const handleLoadVersions = () =>
    run('versions', async () => {
      const list = await playbookApi.listVersions(projectId);
      setVersions(list);
      setShowVersions(true);
    });

  const handleFile = async (file: File) => {
    setError(null);
    try {
      const text = await file.text();
      const envelope = JSON.parse(text) as Record<string, unknown>;
      const preview = await playbookApi.importPreview(envelope, projectId);
      setImportEnvelope(envelope);
      setImportPreview(preview);
    } catch (err) {
      setError(tf('playbook.error.invalidImport', { message: errorMessage(err) }));
    }
  };

  const handleImportConfirm = () =>
    run('import', async () => {
      if (!importEnvelope) return;
      const data = await playbookApi.importPlaybook(
        importEnvelope,
        projectId,
        importConflict,
        saveToLibrary,
      );
      setCurrent(data);
      setImportPreview(null);
      setImportEnvelope(null);
      setSaveToLibrary(false);
      setNotice(t('playbook.notice.imported'));
    });

  if (loading) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border border-border bg-card p-4 text-xs text-muted-foreground"
        data-testid="playbook-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('playbook.card.loading')}
      </div>
    );
  }

  if (error && !current) {
    return (
      <div
        className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive"
        data-testid="playbook-error"
      >
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="space-y-1">
          <div>{error}</div>
          <Button size="sm" variant="secondary" onClick={() => void refresh()}>
            {t('playbook.card.retry')}
          </Button>
        </div>
      </div>
    );
  }

  if (!current) return null;

  if (!current.bound) {
    const suggested = current.suggested;
    return (
      <div
        className="space-y-3 rounded-lg border border-border bg-card p-4"
        data-testid="playbook-card"
      >
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-medium text-foreground">{t('playbook.card.title')}</div>
            <div className="text-xs text-muted-foreground">{t('playbook.card.subtitle')}</div>
          </div>
        </div>
        {suggested && (
          <div className="rounded-md border border-primary/20 bg-primary/5 p-2 text-xs text-foreground">
            {t('playbook.card.recommended')}
            <span className="font-medium">{suggested.name}</span>
            <span className="ml-2 text-muted-foreground">{suggested.description}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={t('playbook.card.selectLabel')}
            value={selectedPlaybook}
            onChange={(event) => setSelectedPlaybook(event.target.value)}
            className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
          >
            <optgroup label={t('playbook.card.builtinGroup')}>
              {builtins.map((item) => (
                <option key={item.id} value={`builtin:${item.id}`}>
                  {tf('playbook.card.optionLabel', {
                    name: item.name,
                    count: item.stage_count,
                  })}
                </option>
              ))}
            </optgroup>
            {library.length > 0 && (
              <optgroup label={t('playbook.card.libraryGroup')}>
                {library.map((item) => (
                  <option key={item.id} value={`library:${item.id}`}>
                    {tf('playbook.card.optionLabel', {
                      name: item.name,
                      count: item.stage_count,
                    })}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <Button
            size="sm"
            variant="primary"
            disabled={!selectedPlaybook || busy === 'bind'}
            onClick={() => void handleBind()}
            data-testid="playbook-bind-btn"
          >
            {busy === 'bind' ? t('playbook.card.binding') : t('playbook.card.bind')}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => fileInputRef.current?.click()}>
            <Upload className="mr-1 h-3.5 w-3.5" />
            {t('playbook.card.importFile')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShowLibrary((value) => !value)}
            data-testid="playbook-open-library-unbound"
          >
            {t('playbook.card.library')}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,.sageplaybook.json,application/json"
            className="hidden"
            data-testid="playbook-import-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
              event.target.value = '';
            }}
          />
        </div>
        <PlaybookAuthorPanel
          notes={authorNotes}
          onNotesChange={setAuthorNotes}
          onAuthor={() => void handleAuthor()}
          authoring={busy === 'author'}
          authorResult={authorResult}
          onBindAuthored={() => void handleBindAuthored()}
          bindingAuthored={busy === 'bind-authored'}
        />
        {importPreview && (
          <PlaybookImportPreviewCard
            preview={importPreview}
            conflict={importConflict}
            onConflictChange={setImportConflict}
            saveToLibrary={saveToLibrary}
            onSaveToLibraryChange={setSaveToLibrary}
            onConfirm={() => void handleImportConfirm()}
            onCancel={() => {
              setImportPreview(null);
              setImportEnvelope(null);
            }}
            importing={busy === 'import'}
          />
        )}
        {error && (
          <div role="status" aria-live="polite" className="text-xs text-destructive">
            {error}
          </div>
        )}
        {notice && (
          <div role="status" aria-live="polite" className="text-xs text-primary">
            {notice}
          </div>
        )}
      </div>
    );
  }

  const audit = current.audit;
  const stages = audit?.stages ?? [];
  const currentStage = stages.find((stage) => stage.id === audit?.current_stage) ?? stages[0];
  const detected = audit?.detected_stage;
  const detectedStage = detected?.id ? stages.find((stage) => stage.id === detected.id) : undefined;
  const showDetected =
    Boolean(detectedStage) &&
    detectedStage?.id !== audit?.current_stage &&
    (detected?.confidence ?? 0) >= 0.5 &&
    !dismissedDetected;

  return (
    <div
      className="space-y-4 rounded-lg border border-border bg-card p-4"
      data-testid="playbook-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-sm font-medium text-foreground">
            {tf('playbook.card.boundTitle', { name: current.playbook?.name ?? '' })}
          </div>
          <div className="text-xs text-muted-foreground">
            v{current.version ?? 1} · {current.source ?? 'custom'}
            {current.playbook?.description ? ' · ' + current.playbook.description : ''}
          </div>
        </div>
        <PlaybookToolbar
          busy={busy}
          hasPlaybook={Boolean(current.playbook)}
          onRefreshAudit={() => void handleRefreshAudit()}
          onAiAudit={() => void handleAiAudit()}
          onExport={(format) => void handleExport(format)}
          onWikiExport={() => void handleWikiExport()}
          onSaveToLibrary={() => void handleSaveToLibrary()}
          onToggleLibrary={() => setShowLibrary((value) => !value)}
          onEdit={handleStartEdit}
          onLoadVersions={() => void handleLoadVersions()}
          onSeedMilestones={handleSeedMilestones}
          onCleanupRules={handleCleanupRules}
          onUnbind={handleUnbind}
          onImportClick={() => fileInputRef.current?.click()}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,.sageplaybook.json,application/json"
          className="hidden"
          data-testid="playbook-import-input"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleFile(file);
            event.target.value = '';
          }}
        />
      </div>

      {editingSpec && current.playbook && (
        <PlaybookSpecEditor
          spec={current.playbook}
          saving={busy === 'save-spec'}
          error={error}
          onSave={(spec) => void handleSaveSpec(spec)}
          onCancel={() => setEditingSpec(false)}
        />
      )}

      {/* 阶段条 */}
      <div className="flex flex-wrap items-center gap-1.5" data-testid="playbook-stepper">
        {stages.map((stage, index) => {
          const isCurrent = stage.id === audit?.current_stage;
          const isDone = stage.progress >= 100;
          return (
            <div key={stage.id} className="flex items-center gap-1.5">
              <div
                className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs ${
                  isCurrent
                    ? 'border-primary/40 bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground'
                }`}
                data-testid={`playbook-stage-${stage.id}`}
              >
                {isDone ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <Circle className="h-3.5 w-3.5" />
                )}
                {stage.label}
                <span className="text-ui-2xs opacity-70">{stage.progress}%</span>
              </div>
              {index < stages.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${audit?.overall.progress ?? 0}%` }}
          />
        </div>
        <span>
          {tf('playbook.card.overall', {
            progress: audit?.overall.progress ?? 0,
            done: audit?.overall.required_done ?? 0,
            total: audit?.overall.required_total ?? 0,
          })}
        </span>
      </div>

      {showDetected && detectedStage && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300"
          data-testid="playbook-detected-stage"
        >
          <AlertCircle className="h-3.5 w-3.5" />
          <span>
            {tf('playbook.card.detected', {
              stage: detectedStage.label,
              confidence: Math.round((detected?.confidence ?? 0) * 100),
            })}
          </span>
          <Button
            size="sm"
            variant="primary"
            onClick={() => void handleConfirmStage(detectedStage.id)}
            data-testid="playbook-confirm-stage"
          >
            {t('playbook.card.confirmStage')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setDismissedDetected(true)}
            data-testid="playbook-keep-stage"
          >
            {t('playbook.card.keepStage')}
          </Button>
        </div>
      )}

      {!compact && (
        <>
          <PlaybookChecklist
            stage={currentStage}
            busy={busy}
            playbookName={current.playbook?.name ?? ''}
            onAction={(action) => void handleAction(action)}
            onWaive={(stageId, artifactId) => void handleWaive(stageId, artifactId)}
            onManualDone={(stageId, criterionId) => void handleManualDone(stageId, criterionId)}
          />
          <PlaybookClassificationPanel
            classification={audit?.classification_suggestions ?? []}
            unclassified={audit?.unclassified_files ?? []}
            undoAvailable={audit?.undo_available ?? null}
            busy={busy}
            onAction={(action) => void handleAction(action)}
            onBatchMove={(moves) => void handleBatchMove(moves)}
            onUndo={() => void handleUndoBatch()}
          />
        </>
      )}

      {importPreview && (
        <PlaybookImportPreviewCard
          preview={importPreview}
          conflict={importConflict}
          onConflictChange={setImportConflict}
          saveToLibrary={saveToLibrary}
          onSaveToLibraryChange={setSaveToLibrary}
          onConfirm={() => void handleImportConfirm()}
          onCancel={() => {
            setImportPreview(null);
            setImportEnvelope(null);
          }}
          importing={busy === 'import'}
        />
      )}

      {showVersions && (
        <PlaybookVersionsPanel versions={versions} onClose={() => setShowVersions(false)} />
      )}

      {showLibrary && <PlaybookLibraryPanel onClose={() => setShowLibrary(false)} />}

      {(error || notice) && (
        <div
          role="status"
          aria-live="polite"
          className={`text-xs ${error ? 'text-destructive' : 'text-primary'}`}
        >
          {error || notice}
        </div>
      )}
    </div>
  );
}

export default PlaybookCard;
