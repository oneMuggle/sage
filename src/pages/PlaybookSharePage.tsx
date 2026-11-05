/**
 * PlaybookSharePage — 分享链接落地页（2026-11-03）。
 *
 * 访问 /share/playbook/{token} → 预览规程内容 → 导入到选定项目或存入规程库。
 */
import { AlertTriangle, Download, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { usePlaybookI18n } from '../features/playbook/usePlaybookI18n';
import { playbookApi } from '../shared/api/playbookApi';
import type { PlaybookSharedPayload } from '../shared/api/playbookApi';
import { projectApi } from '../shared/api/projectApi';
import type { ProjectSummary } from '../shared/api/projectApiTypes';
import { Button } from '../shared/ui/Button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../shared/ui/Select/Select';

function ruleText(rule: Record<string, unknown>): string {
  const content = rule.content ?? rule.template_key ?? '';
  return typeof content === 'string' ? content : '';
}

export function PlaybookSharePage() {
  const { t, tf } = usePlaybookI18n();
  const { token = '' } = useParams<{ token: string }>();
  const navigate = useNavigate();

  const [payload, setPayload] = useState<PlaybookSharedPayload | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const result = await playbookApi.resolveShareToken(token);
        if (!cancelled) setPayload(result);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const list = await projectApi.list();
        if (!cancelled) setProjects(list);
      } catch {
        // 项目列表不可用时仅禁用导入，不影响预览。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const spec = payload?.spec;
  const rules = useMemo(() => {
    const stageRules = (spec?.stages ?? []).flatMap((stage) => stage.rules ?? []);
    return [...(spec?.global_rules ?? []), ...stageRules]
      .map((rule) => ruleText(rule))
      .filter((text) => text.length > 0);
  }, [spec]);

  const handleImport = useCallback(async () => {
    if (!payload || !projectId) {
      setError(t('playbook.sharePage.noProject'));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await playbookApi.bind(projectId, { spec: payload.spec, source: 'shared-link' });
      const name = projects.find((project) => project.id === projectId)?.name ?? projectId;
      setNotice(tf('playbook.sharePage.imported', { name }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [payload, projectId, projects, t, tf]);

  const handleSaveLibrary = useCallback(async () => {
    if (!payload) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const item = await playbookApi.saveLibrary(
        {
          format: 'sage.playbook',
          playbook: payload.spec,
          scaffold: { include: false, directories: [], documents: [] },
        },
        'shared',
      );
      setNotice(tf('playbook.sharePage.savedLibrary', { name: item.name }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [payload, t, tf]);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-4 p-6" data-testid="playbook-share-page">
      <div className="space-y-1">
        <h1 className="text-lg font-semibold text-foreground">{t('playbook.sharePage.title')}</h1>
        {payload && (
          <div className="text-xs text-muted-foreground">
            {tf('playbook.sharePage.expiresAt', {
              date: new Date(payload.expires_at).toLocaleDateString(),
            })}
          </div>
        )}
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('playbook.sharePage.loading')}
        </div>
      )}

      {!loading && error && !payload && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{t('playbook.sharePage.notFound')}</span>
        </div>
      )}

      {payload && spec && (
        <>
          <div className="space-y-3 rounded-md border border-border p-4">
            <div className="space-y-1">
              <div className="font-medium text-foreground">{payload.playbook_name}</div>
              {spec.description && (
                <div className="text-xs text-muted-foreground">{spec.description}</div>
              )}
            </div>

            <div className="space-y-2 text-xs">
              <div className="font-medium text-foreground">
                {tf('playbook.sharePage.stages', { count: spec.stages.length })}
              </div>
              <ul className="space-y-1 text-muted-foreground">
                {spec.stages.map((stage) => (
                  <li key={stage.id}>
                    {stage.order}. {stage.label}
                    {stage.artifacts.length > 0 && (
                      <span className="opacity-70">
                        {' — '}
                        {tf('playbook.sharePage.artifacts', { count: stage.artifacts.length })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>

            {rules.length > 0 && (
              <div className="space-y-1 text-xs">
                <div className="font-medium text-foreground">
                  {tf('playbook.sharePage.rules', { count: rules.length })}
                </div>
                <ul className="space-y-0.5 text-muted-foreground">
                  {rules.map((text, index) => (
                    <li key={index}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="space-y-3 rounded-md border border-border p-4">
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground">
                {t('playbook.sharePage.selectProject')}
              </div>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger data-testid="playbook-share-project-select">
                  <SelectValue placeholder={t('playbook.sharePage.selectProjectPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {projects.map((project) => (
                    <SelectItem key={project.id} value={project.id}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                onClick={() => void handleImport()}
                disabled={busy || projects.length === 0}
                data-testid="playbook-share-import"
              >
                {busy ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="mr-1 h-3.5 w-3.5" />
                )}
                {busy ? t('playbook.sharePage.importing') : t('playbook.sharePage.import')}
              </Button>
              <Button
                variant="secondary"
                onClick={() => void handleSaveLibrary()}
                disabled={busy}
                data-testid="playbook-share-save-library"
              >
                {t('playbook.sharePage.saveLibrary')}
              </Button>
            </div>
          </div>
        </>
      )}

      {(error && payload) || notice ? (
        <div
          role="status"
          aria-live="polite"
          className={`text-xs ${error && payload ? 'text-destructive' : 'text-primary'}`}
        >
          {error && payload ? error : notice}
        </div>
      ) : null}

      <div>
        <Button variant="secondary" onClick={() => navigate('/chat')}>
          {t('playbook.sharePage.backToChat')}
        </Button>
      </div>
    </div>
  );
}

export default PlaybookSharePage;
