/**
 * ProjectBootstrapPanel — AI initialization suggestions for a project.
 *
 * M2 (2026-11-03): two-step flow so the UI can show real progress:
 *   1. deterministic scan (fast, no LLM) — renders scan results immediately
 *   2. AI suggestions (LLM-backed, slower) — shows elapsed time and an
 *      explicit fallback notice when the LLM is unavailable.
 *
 * Everything is opt-in and applied in one idempotent call; the panel never
 * writes anything by itself.
 */
import { AlertCircle, CheckCircle2, GitBranch, Loader2, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api/projectApi';
import type {
  BootstrapApplyResult,
  BootstrapScanSection,
  BootstrapSuggestionSet,
} from '../../shared/api/projectApi';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';

export interface ProjectBootstrapPanelProps {
  projectId: string;
  onApplied?: (result: BootstrapApplyResult) => void;
}

type BootstrapPhase = 'scanning' | 'suggesting' | 'ready' | 'error';

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function ProjectBootstrapPanel({ projectId, onApplied }: ProjectBootstrapPanelProps) {
  const [scan, setScan] = useState<BootstrapScanSection | null>(null);
  const [projectName, setProjectName] = useState('');
  const [suggestions, setSuggestions] = useState<BootstrapSuggestionSet | null>(null);
  const [phase, setPhase] = useState<BootstrapPhase>('scanning');
  const [llmAvailable, setLlmAvailable] = useState(false);
  const [llmError, setLlmError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BootstrapApplyResult | null>(null);

  const [acceptSageMd, setAcceptSageMd] = useState(false);
  const [acceptRules, setAcceptRules] = useState<Set<number>>(new Set());
  const [acceptMilestones, setAcceptMilestones] = useState<Set<number>>(new Set());
  const [acceptGitInit, setAcceptGitInit] = useState(false);
  const [acceptCheckpoint, setAcceptCheckpoint] = useState(true);

  const load = useCallback(
    async (useLlm: boolean) => {
      setError(null);
      setResult(null);
      setSuggestions(null);
      setScan(null);
      setLlmError(null);
      setElapsedSec(0);
      setPhase('scanning');
      try {
        const scanResult = await projectApi.bootstrapScan(projectId);
        setScan(scanResult.scan);
        setProjectName(scanResult.project.name);
        setPhase('suggesting');
        const suggestResult = await projectApi.bootstrapSuggest(projectId, useLlm);
        setSuggestions(suggestResult.suggestions);
        setLlmAvailable(suggestResult.llmAvailable);
        setLlmError(suggestResult.llmError);
        setAcceptSageMd(!suggestResult.suggestions.sageMd.exists);
        setAcceptRules(new Set(suggestResult.suggestions.rules.map((_, index) => index)));
        setAcceptMilestones(
          new Set(suggestResult.suggestions.milestones.map((_, index) => index)),
        );
        setAcceptGitInit(suggestResult.suggestions.gitInit.recommended);
        setPhase('ready');
      } catch (err) {
        setError(errorMessage(err));
        setPhase('error');
      }
    },
    [projectId],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  // Elapsed timer for the AI suggestion step (a real wait, not a fake bar).
  useEffect(() => {
    if (phase !== 'suggesting') return;
    const timer = window.setInterval(() => setElapsedSec((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  /** After applying, refresh only the deterministic scan (existing counts). */
  const refreshScan = async () => {
    try {
      const scanResult = await projectApi.bootstrapScan(projectId);
      setScan(scanResult.scan);
    } catch {
      // keep previous scan; apply result is still shown
    }
  };

  const toggleIndex = (
    setter: React.Dispatch<React.SetStateAction<Set<number>>>,
    index: number,
  ) => {
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const handleApply = async () => {
    if (!scan || !suggestions || applying) return;
    setApplying(true);
    setError(null);
    try {
      const applied = await projectApi.bootstrapApply(projectId, {
        metadata: {
          description: scan.techStack.length
            ? `${projectName || '项目'}（${scan.techStack.slice(0, 4).join(' / ')}）`
            : undefined,
          projectType: (scan.level1Type as never) ?? undefined,
          projectSubType: scan.subType,
        },
        sageMd: acceptSageMd,
        sageMdContent: suggestions.sageMd.content,
        rules: suggestions.rules
          .filter((_, index) => acceptRules.has(index))
          .map((rule) => ({
            category: rule.category,
            content: rule.content,
            triggerPattern: rule.triggerPattern,
            priority: rule.priority,
          })),
        milestones: suggestions.milestones
          .filter((_, index) => acceptMilestones.has(index))
          .map((item) => ({
            title: item.title,
            description: item.description,
            stage: item.stage,
            estimatedDays: item.estimatedDays,
          })),
        gitInit: acceptGitInit,
        initialCheckpoint: acceptCheckpoint,
      });
      setResult(applied);
      onApplied?.(applied);
      await refreshScan();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setApplying(false);
    }
  };

  if (phase === 'scanning' || (!scan && phase !== 'error')) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg border border-border bg-card p-4 text-xs text-muted-foreground"
        data-testid="project-bootstrap-loading"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        第 1 步 / 共 2 步 · 正在扫描项目文件…
      </div>
    );
  }

  if (phase === 'error' || !scan) {
    return (
      <div
        className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive"
        data-testid="project-bootstrap-error"
      >
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="space-y-1">
          <div>{error || '扫描失败'}</div>
          <div className="flex gap-2">
            <Button size="sm" variant="secondary" onClick={() => void load(true)}>
              重试（调用 AI）
            </Button>
            <Button size="sm" variant="ghost" onClick={() => void load(false)}>
              仅扫描（不调用 AI）
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const scanSummary = (
    <div className="flex flex-wrap gap-2 text-ui-2xs text-muted-foreground">
      <span>
        类型：{scan.level1Type ?? '未分类'}
        {scan.subType ? ` / ${scan.subType}` : ''}
      </span>
      {scan.techStack.length > 0 && <span>技术栈：{scan.techStack.slice(0, 5).join('、')}</span>}
      <span>源文件：{scan.sourceFiles.reduce((sum, item) => sum + item.count, 0)} 个</span>
      <span className="inline-flex items-center gap-1">
        <GitBranch className="h-3 w-3" />
        {scan.git.isRepo ? `Git（${scan.git.dirtyFiles} 个未提交）` : '未启用 Git'}
      </span>
    </div>
  );

  if (phase === 'suggesting' || !suggestions) {
    return (
      <div
        className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4"
        data-testid="project-bootstrap-panel"
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-primary" />
          AI 初始化建议
        </div>
        {scanSummary}
        <div
          className="flex items-center gap-2 rounded-md border border-border bg-card p-3 text-xs text-muted-foreground"
          data-testid="project-bootstrap-suggesting"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          第 2 步 / 共 2 步 · AI 正在分析项目并生成建议（已用时 {elapsedSec}s，通常 10–30 秒）
        </div>
      </div>
    );
  }

  return (
    <div
      className="space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-4"
      data-testid="project-bootstrap-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="h-4 w-4 text-primary" />
          AI 初始化建议
          <Badge variant={llmAvailable ? 'default' : 'secondary'}>
            {llmAvailable ? 'AI 分析' : '本地推荐模板'}
          </Badge>
        </div>
        <Button size="sm" variant="ghost" onClick={() => void load(true)}>
          重新扫描
        </Button>
      </div>

      {scanSummary}

      {llmError && (
        <div
          className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2 text-ui-2xs text-amber-700 dark:text-amber-300"
          data-testid="bootstrap-llm-fallback"
        >
          {llmError}
        </div>
      )}

      <div className="space-y-2 rounded-md border border-border bg-card p-3">
        <div className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={acceptGitInit}
            disabled={!scan.git.gitAvailable || scan.git.isRepo}
            onChange={(e) => setAcceptGitInit(e.target.checked)}
            data-testid="bootstrap-git-init"
            className="mt-0.5 h-3.5 w-3.5"
          />
          <div className="space-y-0.5">
            <div className="font-medium text-foreground">启用 Git 追踪</div>
            <div className="text-muted-foreground">{suggestions.gitInit.reason}</div>
            {!scan.git.gitAvailable && (
              <div className="text-amber-600">本机未检测到 Git，建议使用内置快照。</div>
            )}
          </div>
        </div>
      </div>

      <div className="space-y-2 rounded-md border border-border bg-card p-3">
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={acceptSageMd}
            disabled={suggestions.sageMd.exists}
            onChange={(e) => setAcceptSageMd(e.target.checked)}
            data-testid="bootstrap-sage-md"
            className="mt-0.5 h-3.5 w-3.5"
          />
          <div className="space-y-1">
            <div className="font-medium text-foreground">
              生成项目说明（SAGE.md）
              {suggestions.sageMd.exists && (
                <span className="ml-1 text-muted-foreground">（已存在，不覆盖）</span>
              )}
            </div>
            <div className="text-muted-foreground">{suggestions.sageMd.rationale}</div>
            <details className="text-muted-foreground">
              <summary className="cursor-pointer text-primary">预览草稿</summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono text-ui-2xs">
                {suggestions.sageMd.content}
              </pre>
            </details>
          </div>
        </label>
      </div>

      {suggestions.rules.length > 0 && (
        <div
          className="space-y-1.5 rounded-md border border-border bg-card p-3"
          data-testid="bootstrap-rules"
        >
          <div className="text-xs font-medium text-foreground">
            推荐规则（{acceptRules.size}/{suggestions.rules.length}）
          </div>
          {suggestions.rules.map((rule, index) => (
            <label key={`${rule.key}-${index}`} className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={acceptRules.has(index)}
                onChange={() => toggleIndex(setAcceptRules, index)}
                data-testid={`bootstrap-rule-${index}`}
                className="mt-0.5 h-3.5 w-3.5"
              />
              <div>
                <div className="font-medium text-foreground">{rule.label || rule.key}</div>
                <div className="text-muted-foreground">{rule.reason || rule.content}</div>
              </div>
            </label>
          ))}
        </div>
      )}

      {suggestions.milestones.length > 0 && (
        <div
          className="space-y-1.5 rounded-md border border-border bg-card p-3"
          data-testid="bootstrap-milestones"
        >
          <div className="text-xs font-medium text-foreground">
            推荐里程碑（{acceptMilestones.size}/{suggestions.milestones.length}）
          </div>
          {suggestions.milestones.map((item, index) => (
            <label key={`${item.title}-${index}`} className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={acceptMilestones.has(index)}
                onChange={() => toggleIndex(setAcceptMilestones, index)}
                data-testid={`bootstrap-milestone-${index}`}
                className="mt-0.5 h-3.5 w-3.5"
              />
              <div>
                <div className="font-medium text-foreground">{item.title}</div>
                <div className="text-muted-foreground">{item.description}</div>
              </div>
            </label>
          ))}
        </div>
      )}

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={acceptCheckpoint}
          onChange={(e) => setAcceptCheckpoint(e.target.checked)}
          data-testid="bootstrap-checkpoint"
          className="h-3.5 w-3.5"
        />
        应用后创建一次基线快照
      </label>

      {suggestions.firstPrompt && (
        <div className="rounded-md bg-muted/50 p-2 text-ui-2xs text-muted-foreground">
          首次会话将建议：{suggestions.firstPrompt}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void handleApply()} disabled={applying}>
          {applying ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
          )}
          {applying ? '应用中…' : '应用选中的建议'}
        </Button>
        {result && (
          <span className="text-ui-2xs text-emerald-600" data-testid="bootstrap-result">
            已应用 {result.applied.length} 项
            {result.skipped.length > 0 ? ` · 跳过 ${result.skipped.length} 项` : ''}
            {result.errors.length > 0 ? ` · ${result.errors.length} 项失败` : ''}
          </span>
        )}
      </div>

      {result && result.errors.length > 0 && (
        <div className="space-y-1 text-ui-2xs text-amber-700">
          {result.errors.map((item, index) => (
            <div key={`${item.item}-${index}`}>
              {item.item}: {item.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
