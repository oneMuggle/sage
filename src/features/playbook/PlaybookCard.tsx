/**
 * PlaybookCard — 项目规程（阶段 / 完整性 / 建议动作 / 导出导入）。
 *
 * 数据来自 `/projects/{id}/playbook` 与 `/playbook/audit`。所有写操作
 * （绑定、创建目录/骨架、推进阶段、导入）都先由用户点击确认。
 */
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Download,
  Loader2,
  RefreshCw,
  Upload,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { playbookApi } from '../../shared/api/playbookApi';
import type {
  PlaybookAction,
  PlaybookAudit,
  PlaybookCurrent,
  PlaybookImportPreview,
  PlaybookSummary,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

export interface PlaybookCardProps {
  projectId: string;
  compact?: boolean;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function downloadText(filename: string, text: string, mime: string): void {
  if (typeof URL.createObjectURL !== 'function') return;
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

const ACTION_LABELS: Record<string, string> = {
  create_folder: '创建目录',
  create_doc_stub: '生成骨架',
  apply_rules: '写入规则',
  seed_milestones: '创建里程碑',
  add_todo: '转为待办',
  open_doc: '打开文档',
};

export function PlaybookCard({ projectId, compact = false }: PlaybookCardProps) {
  const [current, setCurrent] = useState<PlaybookCurrent | null>(null);
  const [builtins, setBuiltins] = useState<PlaybookSummary[]>([]);
  const [selectedPlaybook, setSelectedPlaybook] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dismissedDetected, setDismissedDetected] = useState(false);
  const [importPreview, setImportPreview] = useState<PlaybookImportPreview | null>(null);
  const [importEnvelope, setImportEnvelope] = useState<Record<string, unknown> | null>(null);
  const [importConflict, setImportConflict] = useState<'save_as_new' | 'merge' | 'replace'>(
    'save_as_new',
  );
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await playbookApi.getCurrent(projectId);
      setCurrent(data);
      if (!data.bound) {
        const list = await playbookApi.listBuiltin();
        setBuiltins(list);
        setSelectedPlaybook((prev) => prev || data.suggested?.id || list[0]?.id || '');
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
      const data = await playbookApi.bind(projectId, { playbookId: selectedPlaybook });
      setCurrent(data);
      setNotice('已绑定项目规程');
    });

  const handleRefreshAudit = () =>
    run('audit', async () => {
      const audit: PlaybookAudit = await playbookApi.audit(projectId);
      setCurrent((prev) => (prev ? { ...prev, audit } : prev));
      setNotice('完整性检查已刷新');
    });

  const handleAction = (action: PlaybookAction) =>
    run(action.type, async () => {
      const result = await playbookApi.applyActions(projectId, [action]);
      if (result.errors.length) {
        setError(result.errors.map((item) => item.message).join('；'));
        return;
      }
      setCurrent((prev) => (prev ? { ...prev, audit: result.audit ?? prev.audit } : prev));
      if (!result.audit) await refresh();
      setNotice(result.applied.length ? '已执行：' + result.applied.join('、') : '项目已是最新');
    });

  const handleConfirmStage = (stageId: string) =>
    run('stage', async () => {
      const data = await playbookApi.confirmStage(projectId, stageId);
      setCurrent(data);
      setDismissedDetected(true);
      setNotice('阶段已更新');
    });

  const handleExport = (format: 'json' | 'md') =>
    run('export-' + format, async () => {
      const result = await playbookApi.exportPlaybook(projectId, format);
      const text =
        typeof result.content === 'string'
          ? result.content
          : JSON.stringify(result.content, null, 2);
      downloadText(
        result.filename,
        text,
        format === 'md' ? 'text/markdown' : 'application/json',
      );
      setNotice('已导出：' + result.filename);
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
      setError('导入文件无效：' + errorMessage(err));
    }
  };

  const handleImportConfirm = () =>
    run('import', async () => {
      if (!importEnvelope) return;
      const data = await playbookApi.importPlaybook(
        importEnvelope,
        projectId,
        importConflict,
      );
      setCurrent(data);
      setImportPreview(null);
      setImportEnvelope(null);
      setNotice('规程已导入并绑定');
    });

  if (loading) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border border-border bg-card p-4 text-xs text-muted-foreground"
        data-testid="playbook-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        正在检查项目规程…
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
            重试
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
            <div className="text-sm font-medium text-foreground">项目规程</div>
            <div className="text-xs text-muted-foreground">
              为项目选择一套阶段与交付物要求；AI 会据此检查完整性。
            </div>
          </div>
        </div>
        {suggested && (
          <div className="rounded-md border border-primary/20 bg-primary/5 p-2 text-xs text-foreground">
            推荐：<span className="font-medium">{suggested.name}</span>
            <span className="ml-2 text-muted-foreground">{suggested.description}</span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="选择项目规程"
            value={selectedPlaybook}
            onChange={(event) => setSelectedPlaybook(event.target.value)}
            className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
          >
            {builtins.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}（{item.stage_count} 阶段）
              </option>
            ))}
          </select>
          <Button
            size="sm"
            variant="primary"
            disabled={!selectedPlaybook || busy === 'bind'}
            onClick={() => void handleBind()}
            data-testid="playbook-bind-btn"
          >
            {busy === 'bind' ? '绑定中…' : '绑定此规程'}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="mr-1 h-3.5 w-3.5" />
            导入规程文件
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
        {error && <div className="text-xs text-destructive">{error}</div>}
        {notice && <div className="text-xs text-primary">{notice}</div>}
      </div>
    );
  }

  const audit = current.audit;
  const stages = audit?.stages ?? [];
  const currentStage =
    stages.find((stage) => stage.id === audit?.current_stage) ?? stages[0];
  const detected = audit?.detected_stage;
  const detectedStage = detected?.id
    ? stages.find((stage) => stage.id === detected.id)
    : undefined;
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
            项目规程：{current.playbook?.name}
          </div>
          <div className="text-xs text-muted-foreground">
            v{current.version ?? 1} · {current.source ?? 'custom'}
            {current.playbook?.description ? ' · ' + current.playbook.description : ''}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void handleRefreshAudit()}
            disabled={busy === 'audit'}
            data-testid="playbook-refresh-audit"
          >
            <RefreshCw className="mr-1 h-3.5 w-3.5" />
            {busy === 'audit' ? '检查中…' : '检查完整性'}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void handleExport('json')}
            disabled={busy === 'export-json'}
          >
            <Download className="mr-1 h-3.5 w-3.5" />
            导出
          </Button>
          <Button size="sm" variant="secondary" onClick={() => void handleExport('md')}>
            导出手册
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="mr-1 h-3.5 w-3.5" />
            导入
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
      </div>

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
                <span className="text-[10px] opacity-70">{stage.progress}%</span>
              </div>
              {index < stages.length - 1 && (
                <span className="text-muted-foreground">→</span>
              )}
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
          整体完成度 {audit?.overall.progress ?? 0}%（{audit?.overall.required_done ?? 0}/
          {audit?.overall.required_total ?? 0}）
        </span>
      </div>

      {showDetected && detectedStage && (
        <div
          className="flex flex-wrap items-center gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300"
          data-testid="playbook-detected-stage"
        >
          <AlertCircle className="h-3.5 w-3.5" />
          <span>
            检测到可能已进入「{detectedStage.label}」阶段（置信度{' '}
            {Math.round((detected?.confidence ?? 0) * 100)}%）
          </span>
          <Button
            size="sm"
            variant="primary"
            onClick={() => void handleConfirmStage(detectedStage.id)}
            data-testid="playbook-confirm-stage"
          >
            确认推进
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setDismissedDetected(true)}
            data-testid="playbook-keep-stage"
          >
            保持当前
          </Button>
        </div>
      )}

      {currentStage && !compact && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-foreground">
            当前阶段：{currentStage.label}
            {currentStage.objective ? (
              <span className="ml-2 font-normal text-muted-foreground">
                {currentStage.objective}
              </span>
            ) : null}
          </div>
          {currentStage.remaining.length === 0 ? (
            <div className="flex items-center gap-1.5 text-xs text-emerald-600">
              <CheckCircle2 className="h-3.5 w-3.5" />
              本阶段必需要素已齐备
            </div>
          ) : (
            <ul className="space-y-1.5">
              {currentStage.remaining.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
                >
                  <span className="flex items-center gap-1.5 text-foreground">
                    <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                    待补：{item.label}
                  </span>
                  {item.missing_action && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void handleAction(item.missing_action as PlaybookAction)}
                      disabled={busy === item.missing_action.type}
                      data-testid={`playbook-missing-action-${item.id}`}
                    >
                      {ACTION_LABELS[item.missing_action.type] ?? '处理'}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {importPreview && (
        <div
          className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-xs"
          data-testid="playbook-import-preview"
        >
          <div className="font-medium text-foreground">
            导入预览：{importPreview.playbook.name}
          </div>
          <div className="text-muted-foreground">
            阶段 {importPreview.playbook.stages.length} 个 · 目录{' '}
            {importPreview.scaffold.directories.length} 个 · 导入不包含对方项目文件内容
          </div>
          {Object.entries(importPreview.diff).length > 0 && (
            <div className="text-muted-foreground">
              变更：
              {Object.entries(importPreview.diff)
                .filter(([, value]) => Array.isArray(value) && value.length > 0)
                .map(([key, value]) => `${key} ${(value as unknown[]).length} 项`)
                .join('，') || '无结构变更'}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="导入冲突策略"
              value={importConflict}
              onChange={(event) =>
                setImportConflict(event.target.value as 'save_as_new' | 'merge' | 'replace')
              }
              className="rounded-md border border-input bg-background px-2 py-1 text-xs"
            >
              <option value="save_as_new">另存为新规程</option>
              <option value="merge">合并到当前规程</option>
              <option value="replace">替换当前规程</option>
            </select>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void handleImportConfirm()}
              disabled={busy === 'import'}
              data-testid="playbook-import-confirm"
            >
              {busy === 'import' ? '导入中…' : '导入并绑定'}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setImportPreview(null);
                setImportEnvelope(null);
              }}
            >
              取消
            </Button>
          </div>
        </div>
      )}

      {(error || notice) && (
        <div className={`text-xs ${error ? 'text-destructive' : 'text-primary'}`}>
          {error || notice}
        </div>
      )}
    </div>
  );
}

export default PlaybookCard;
