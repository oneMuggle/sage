// src/widgets/orchestration/LaneDetailDrawer.tsx
/**
 * Lane detail drawer — slides in from the right when a lane card is clicked
 * on the LaneBoard. Shows:
 * - Lane header (id, agent, status)
 * - Delivery package (A4): acceptance state, worktree path, acceptance checks
 *   (parsed from the lane.acceptance.completed event), merge/audit info
 * - Decision zone for succeeded-but-undecided lanes: reason input + Accept /
 *   Reject buttons wired to laneBoardStore.decide().
 *
 * Degradation: acceptance-check loading failure only empties that section —
 * it never blocks the decision zone.
 */
import { useEffect, useState } from 'react';

import { useLaneBoardStore } from '../../entities/orchestration/laneBoardStore';
import { orchestrationClient } from '../../shared/api/orchestrationClient';
import type { Lane, LaneEvent } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

interface AcceptanceCheckView {
  name: string;
  passed: boolean;
  skipped: boolean;
  summary: string;
}

interface MergeInfoView {
  code: string;
  branch: string;
  mergeHead: string;
  filesChanged: string[];
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is string => typeof v === 'string');
}

function parseChecks(event: LaneEvent | undefined): AcceptanceCheckView[] | null {
  if (!event) return null;
  const raw: unknown = event.metadata.checks;
  if (!Array.isArray(raw)) return null;
  // 名为 diff 的是产物摘要项，归摘要段独立展示，不进检查列表。
  return raw
    .map((c) => {
      const item: Record<string, unknown> =
        typeof c === 'object' && c !== null ? (c as Record<string, unknown>) : {};
      return {
        name: typeof item.name === 'string' ? item.name : '?',
        passed: item.passed === true,
        skipped: item.skipped === true,
        summary: typeof item.summary === 'string' ? item.summary : '',
      };
    })
    .filter((c) => c.name !== 'diff');
}

function parseMergeInfo(metadata: Record<string, unknown>): MergeInfoView | null {
  const raw: unknown = metadata.merge;
  if (typeof raw !== 'object' || raw === null) return null;
  const m = raw as Record<string, unknown>;
  if (typeof m.code !== 'string') return null;
  return {
    code: m.code,
    branch: typeof m.branch === 'string' ? m.branch : '',
    mergeHead: typeof m.merge_head === 'string' ? m.merge_head : '',
    filesChanged: toStringArray(m.files_changed),
  };
}

/**
 * A4: 产物摘要 —— acceptance 事件中名为 diff 的 check 恒跑
 * `git diff --stat`，其 summary 即文件级变更统计。缺席返回 ''。
 */
function parseDiffSummary(event: LaneEvent | undefined): string {
  if (!event) return '';
  const raw: unknown = event.metadata.checks;
  if (!Array.isArray(raw)) return '';
  for (const c of raw) {
    if (typeof c !== 'object' || c === null) continue;
    const item = c as Record<string, unknown>;
    if (item.name === 'diff' && typeof item.summary === 'string' && item.summary !== '') {
      return item.summary;
    }
  }
  return '';
}

interface LaneDetailDrawerProps {
  /** Lane to display (usually selected from laneBoardStore by the parent) */
  lane: Lane | null;
  /** Currently visible (controlled by parent) */
  open: boolean;
  /** Called when the drawer should close */
  onClose: () => void;
}

export function LaneDetailDrawer({ lane, open, onClose }: LaneDetailDrawerProps) {
  const { t } = useI18n();
  const decide = useLaneBoardStore((s) => s.decide);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checks, setChecks] = useState<AcceptanceCheckView[] | null>(null);
  // null = 加载中；'' = 无产物摘要。
  const [diffSummary, setDiffSummary] = useState<string | null>(null);

  const laneId = lane?.lane_id;

  useEffect(() => {
    if (!open || !laneId) return;
    let cancelled = false;
    setChecks(null);
    setDiffSummary(null);
    orchestrationClient
      .listLaneEvents(laneId)
      .then((events) => {
        if (cancelled) return;
        const acceptance = [...events]
          .reverse()
          .find((e) => e.event_type === 'lane.acceptance.completed');
        setChecks(parseChecks(acceptance) ?? []);
        setDiffSummary(parseDiffSummary(acceptance));
      })
      .catch(() => {
        if (!cancelled) {
          setChecks([]);
          setDiffSummary('');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, laneId]);

  if (!open || !lane) {
    return null;
  }

  const meta = lane.metadata ?? {};
  const acceptedAt = typeof meta.accepted_at === 'number' ? meta.accepted_at : null;
  const rejectedAt = typeof meta.rejected_at === 'number' ? meta.rejected_at : null;
  const warning = typeof meta.warning === 'string' && meta.warning !== '' ? meta.warning : null;
  const merge = parseMergeInfo(meta);
  // A4: 复核结论（dispatcher 写回 lane.metadata，见 _stamp_review_verdict）。
  const reviewVerdict = typeof meta.review_verdict === 'string' ? meta.review_verdict : null;
  const reviewCount =
    typeof meta.review_assertion_count === 'number' ? meta.review_assertion_count : null;
  const canDecide = lane.status === 'succeeded' && acceptedAt === null && rejectedAt === null;

  const handleDecision = async (decision: 'accept' | 'reject') => {
    setBusy(true);
    setError(null);
    try {
      await decide(lane.lane_id, decision, reason);
      setReason('');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-y-0 right-0 w-96 bg-bg-primary border-l border-border-primary shadow-lg z-50 flex flex-col"
      data-testid="lane-detail-drawer"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-primary">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-xs text-text-tertiary truncate">{lane.lane_id}</span>
          <span className="text-xs px-2 py-0.5 rounded bg-bg-hover text-text-secondary shrink-0">
            {lane.status}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-tertiary hover:text-text-primary"
          data-testid="drawer-close"
          aria-label={t('orchestration.drawer.close')}
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Delivery package */}
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="text-xs text-text-tertiary mb-2">{t('orchestration.drawer.delivery')}</div>
          <div className="flex items-center gap-2 mb-2" data-testid="acceptance-state">
            {acceptedAt !== null ? (
              <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                {t('orchestration.drawer.accepted')}
              </span>
            ) : rejectedAt !== null ? (
              <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">
                {t('orchestration.drawer.rejected')}
              </span>
            ) : (
              <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 text-yellow-800">
                {t('orchestration.drawer.acceptancePending')}
              </span>
            )}
          </div>
          <div className="text-xs text-text-secondary mb-1">
            {t('orchestration.drawer.worktree')}
          </div>
          {lane.worktree ? (
            <div className="font-mono text-xs truncate" title={lane.worktree}>
              {lane.worktree}
            </div>
          ) : (
            <div className="text-xs text-text-tertiary">
              {t('orchestration.drawer.noWorktree')}
            </div>
          )}
          {warning && (
            <div
              className="mt-2 text-xs text-yellow-700 bg-yellow-50 rounded px-2 py-1"
              data-testid="decision-warning"
            >
              {warning}
            </div>
          )}
          {merge && (
            <div className="mt-2 text-xs space-y-1" data-testid="merge-info">
              {merge.branch !== '' && (
                <div className="truncate" title={merge.branch}>
                  {t('orchestration.drawer.mergeBranch')}：{merge.branch}
                </div>
              )}
              {merge.mergeHead !== '' && (
                <div className="font-mono truncate" title={merge.mergeHead}>
                  {t('orchestration.drawer.mergeCommit')}：{merge.mergeHead.slice(0, 12)}
                </div>
              )}
              {merge.filesChanged.length > 0 && (
                <div>
                  <div className="text-text-tertiary">
                    {t('orchestration.drawer.filesChanged').replace(
                      '{n}',
                      String(merge.filesChanged.length),
                    )}
                  </div>
                  <ul className="font-mono truncate">
                    {merge.filesChanged.slice(0, 20).map((f) => (
                      <li key={f} className="truncate" title={f}>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Acceptance checks */}
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="text-xs text-text-tertiary mb-2">{t('orchestration.drawer.checks')}</div>
          {checks === null ? (
            <div className="text-xs text-text-tertiary">{t('orchestration.loading')}</div>
          ) : checks.length === 0 ? (
            <div className="text-xs text-text-tertiary" data-testid="acceptance-checks-empty">
              {t('orchestration.drawer.checksEmpty')}
            </div>
          ) : (
            <ul className="space-y-1" data-testid="acceptance-checks">
              {checks.map((c) => (
                <li key={c.name} className="text-xs flex items-start gap-2">
                  <span
                    className={
                      c.passed
                        ? 'text-green-600 shrink-0'
                        : c.skipped
                          ? 'text-text-tertiary shrink-0'
                          : 'text-red-600 shrink-0'
                    }
                  >
                    {c.passed ? '✓' : c.skipped ? '○' : '✗'}
                  </span>
                  <span className="min-w-0">
                    <span className="font-medium">{c.name}</span>
                    {c.summary !== '' && (
                      <span className="text-text-tertiary truncate block" title={c.summary}>
                        {c.summary}
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Review verdict (A4: dispatcher 写回，无复核则整段隐藏) */}
        {reviewVerdict !== null && (
          <div className="px-4 py-3 border-b border-border-primary">
            <div className="text-xs text-text-tertiary mb-2">
              {t('orchestration.drawer.review')}
            </div>
            <div className="flex items-center gap-2" data-testid="review-verdict">
              {reviewVerdict === 'pass' ? (
                <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                  {t('orchestration.drawer.reviewPass')}
                </span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded bg-red-100 text-red-800">
                  {t('orchestration.drawer.reviewFail')}
                </span>
              )}
              {reviewCount !== null && (
                <span className="text-xs text-text-secondary">
                  {t('orchestration.drawer.reviewAssertions').replace('{n}', String(reviewCount))}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Change summary (diff --stat from the acceptance event) */}
        <div className="px-4 py-3 border-b border-border-primary">
          <div className="text-xs text-text-tertiary mb-2">{t('orchestration.drawer.diff')}</div>
          {diffSummary === null ? (
            <div className="text-xs text-text-tertiary">{t('orchestration.loading')}</div>
          ) : diffSummary === '' ? (
            <div className="text-xs text-text-tertiary" data-testid="diff-empty">
              {t('orchestration.drawer.diffEmpty')}
            </div>
          ) : (
            <pre
              className="text-xs font-mono whitespace-pre-wrap max-h-48 overflow-y-auto bg-bg-subtle rounded px-2 py-1"
              data-testid="diff-summary"
            >
              {diffSummary}
            </pre>
          )}
        </div>

        {/* Lane meta */}
        <div className="px-4 py-3 text-xs text-text-secondary space-y-1">
          <div>
            {t('orchestration.lane.task')} {lane.task_id}
          </div>
          <div>
            {t('orchestration.lane.agent')} {lane.agent_id ?? '—'}
          </div>
          {lane.error && (
            <div className="text-red-600 truncate" title={lane.error}>
              {lane.error}
            </div>
          )}
        </div>
      </div>

      {/* Decision zone */}
      {canDecide && (
        <div className="px-4 py-3 border-t border-border-primary" data-testid="decision-zone">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('orchestration.drawer.reasonPlaceholder')}
            disabled={busy}
            className="w-full text-sm px-2 py-1.5 rounded border border-border-primary bg-bg-primary mb-2 disabled:opacity-50"
            data-testid="decision-reason"
          />
          {error && (
            <div className="text-xs text-red-600 mb-2" data-testid="decision-error">
              {error}
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleDecision('accept')}
              className="flex-1 text-sm px-3 py-1.5 rounded bg-primary text-white hover:opacity-90 disabled:opacity-50"
              data-testid="decision-accept"
            >
              {busy ? t('orchestration.drawer.deciding') : t('orchestration.drawer.accept')}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void handleDecision('reject')}
              className="flex-1 text-sm px-3 py-1.5 rounded border border-red-300 text-red-600 hover:bg-red-50 disabled:opacity-50"
              data-testid="decision-reject"
            >
              {busy ? t('orchestration.drawer.deciding') : t('orchestration.drawer.reject')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
