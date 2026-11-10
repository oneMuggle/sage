/**
 * 文件引用管理器 (P5, 2026-11-05 项目管理增强, 设计 §9 / §10)。
 *
 * 列出项目的文件引用、新建 (file / directory) 引用、删除引用、重新扫描项目
 * 目录以发现新符号链接。v1 语义：引用只放行读取，不放行写入（见
 * ``backend/tools/base.py`` 第 3 层）。
 *
 * 表单字段与设计 §9.6 对齐：别名 / 项目内位置 (rel_path) / 目标路径 (target_path) /
 * 类型 (file | directory)。
 */

import { FolderPlus, RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi, type ProjectReference } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select/Select';

export interface ReferenceManagerProps {
  projectId: string;
  className?: string;
}

type ReferenceKind = 'file' | 'directory';

interface ReferenceFormState {
  relPath: string;
  targetPath: string;
  kind: ReferenceKind;
  aliasName: string;
}

const EMPTY_FORM: ReferenceFormState = {
  relPath: '',
  targetPath: '',
  kind: 'directory',
  aliasName: '',
};

function formatCreatedAt(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  try {
    return new Date(ms).toISOString().replace('T', ' ').slice(0, 16);
  } catch {
    return '—';
  }
}

export function ReferenceManager({ projectId, className }: ReferenceManagerProps) {
  const { t } = useI18n();
  const [references, setReferences] = useState<ProjectReference[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<ReferenceFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [scanning, setScanning] = useState(false);

  const kindLabel = useCallback(
    (kind: ProjectReference['kind']): string => {
      switch (kind) {
        case 'file':
          return t('governance.files.create.kind.file');
        case 'symlink':
          return t('governance.files.create.kind.symlink');
        default:
          return t('governance.files.create.kind.directory');
      }
    },
    [t],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await projectApi.listReferences(projectId);
      setReferences(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const handleCreate = useCallback(async () => {
    const relPath = form.relPath.trim();
    const targetPath = form.targetPath.trim();
    if (!relPath || !targetPath) {
      return;
    }
    setSubmitting(true);
    try {
      const aliasName = form.aliasName.trim() || undefined;
      await projectApi.createReference(projectId, {
        relPath,
        targetPath,
        kind: form.kind,
        aliasName,
      });
      setForm(EMPTY_FORM);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }, [form, projectId, reload]);

  const handleDelete = useCallback(
    async (ref: ProjectReference) => {
      const ok = await confirmDialog({
        title: t('governance.files.confirm.title'),
        message: `「${ref.aliasName}」(${ref.relPath}) ${t('governance.files.confirm.messageTail')}`,
        confirmLabel: t('governance.files.confirm.delete'),
        danger: true,
      });
      if (!ok) return;
      try {
        await projectApi.deleteReference(projectId, ref.id);
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [projectId, reload, t],
  );

  const handleScan = useCallback(async () => {
    setScanning(true);
    try {
      await projectApi.scanProject(projectId);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setScanning(false);
    }
  }, [projectId, reload]);

  return (
    <div className={className ?? 'space-y-4'} data-testid="reference-manager">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">
          {t('governance.files.subtitle')}
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={handleScan}
          disabled={scanning}
          data-testid="reference-scan-button"
        >
          <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${scanning ? 'animate-spin' : ''}`} />
          {scanning ? t('governance.files.scan.busy') : t('governance.files.scan.idle')}
        </Button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
          data-testid="reference-error"
        >
          {error}
        </div>
      )}

      {/* Create form */}
      <div
        className="space-y-2 rounded-lg border border-border bg-card/50 p-3"
        data-testid="reference-create-form"
      >
        <div className="flex items-center gap-2">
          <FolderPlus className="h-4 w-4 text-muted-foreground" />
          <div className="text-sm font-medium">{t('governance.files.create.title')}</div>
        </div>
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">{t('governance.files.create.relPath')}</span>
            <input
              value={form.relPath}
              onChange={(e) => setForm((prev) => ({ ...prev, relPath: e.target.value }))}
              placeholder="data/cases"
              className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              data-testid="reference-input-rel-path"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">{t('governance.files.create.targetPath')}</span>
            <input
              value={form.targetPath}
              onChange={(e) => setForm((prev) => ({ ...prev, targetPath: e.target.value }))}
              placeholder="/home/user/external/cases"
              className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              data-testid="reference-input-target-path"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">{t('governance.files.create.alias')}</span>
            <input
              value={form.aliasName}
              onChange={(e) => setForm((prev) => ({ ...prev, aliasName: e.target.value }))}
              placeholder="cases"
              className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
              data-testid="reference-input-alias"
            />
          </label>
          <div className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">{t('governance.files.create.kind')}</span>
            <Select
              value={form.kind}
              onValueChange={(value) =>
                setForm((prev) => ({ ...prev, kind: value as ReferenceKind }))
              }
            >
              <SelectTrigger
                aria-label={t('governance.files.create.kind')}
                data-testid="reference-input-kind"
                className="h-8 w-full px-2 text-sm"
              >
                <SelectValue>
                  {form.kind === 'file'
                    ? t('governance.files.create.kind.file')
                    : t('governance.files.create.kind.directory')}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="directory">
                  {t('governance.files.create.kind.directory')}
                </SelectItem>
                <SelectItem value="file">{t('governance.files.create.kind.file')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={submitting || !form.relPath.trim() || !form.targetPath.trim()}
            data-testid="reference-create-button"
          >
            {submitting
              ? t('governance.files.create.submitting')
              : t('governance.files.create.submit')}
          </Button>
        </div>
      </div>

      {/* List */}
      <div className="space-y-1.5" data-testid="reference-list">
        {loading && references.length === 0 && (
          <div className="text-xs text-muted-foreground">{t('governance.files.list.loading')}</div>
        )}
        {!loading && references.length === 0 && (
          <div
            className="rounded-md border border-dashed border-border p-4 text-xs text-muted-foreground"
            data-testid="reference-list-empty"
          >
            {t('governance.files.list.empty')}
          </div>
        )}
        {references.map((ref) => (
          <div
            key={ref.id}
            className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2"
            data-testid={`reference-row-${ref.id}`}
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{ref.aliasName}</span>
                <span className="rounded-sm bg-muted px-1.5 py-0.5 text-ui-xs text-muted-foreground">
                  {kindLabel(ref.kind)}
                </span>
                <span className="truncate text-xs text-muted-foreground" title={ref.relPath}>
                  {ref.relPath}
                </span>
              </div>
              <div
                className="truncate text-xs text-muted-foreground"
                title={ref.targetPath}
                data-testid="reference-target"
              >
                → {ref.targetPath}
              </div>
              <div className="text-ui-xs text-muted-foreground/70">
                {t('governance.files.row.created')} {formatCreatedAt(ref.createdAt)}
              </div>
            </div>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void handleDelete(ref)}
              data-testid={`reference-delete-${ref.id}`}
            >
              <Trash2 className="h-3.5 w-3.5 text-destructive" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
