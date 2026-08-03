/**
 * SkillDraftList — displays pending skill drafts with approve/reject actions.
 *
 * Polls `skillDraftsApi.list()` every 10s to refresh the draft list.
 * Each draft card shows the skill name, description, "when to use" guidance,
 * and provides Approve/Reject buttons.
 *
 * Used by the "Pending Drafts" tab on the Skills page (Task 11).
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { skillDraftsApi, type SkillDraft } from '../../shared/api';

const POLL_INTERVAL_MS = 10000;

const SkillDraftList: React.FC = () => {
  const [drafts, setDrafts] = useState<SkillDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDrafts = useCallback(async () => {
    try {
      const response = await skillDraftsApi.list('pending');
      setDrafts(response.drafts);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDrafts();
    const interval = window.setInterval(fetchDrafts, POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [fetchDrafts]);

  const handleApprove = useCallback(
    async (draft: SkillDraft) => {
      try {
        await skillDraftsApi.approve(draft.id);
        setDrafts((prev) => prev.filter((d) => d.id !== draft.id));
        toast.success(`已批准 ${draft.name}`);
      } catch (err) {
        toast.error(`批准失败: ${(err as Error).message}`);
      }
    },
    [],
  );

  const handleReject = useCallback(
    async (draft: SkillDraft) => {
      try {
        await skillDraftsApi.reject(draft.id);
        setDrafts((prev) => prev.filter((d) => d.id !== draft.id));
        toast.success(`已拒绝 ${draft.name}`);
      } catch (err) {
        toast.error(`拒绝失败: ${(err as Error).message}`);
      }
    },
    [],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-muted">加载草稿中...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <p className="text-error">加载失败: {error}</p>
        <button
          type="button"
          onClick={fetchDrafts}
          className="px-3 py-1.5 text-sm rounded-radius-sm bg-primary text-white hover:bg-primary/90"
        >
          重试
        </button>
      </div>
    );
  }

  if (drafts.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-muted">暂无待审草稿</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {drafts.map((draft) => (
        <div
          key={draft.id}
          className="p-4 border border-border rounded-radius-sm bg-surface flex flex-col gap-2"
        >
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-text">{draft.name}</h3>
            <span className="text-xs text-muted px-1.5 py-0.5 bg-bg-muted rounded">
              {draft.trigger_type}
            </span>
          </div>
          <p className="text-sm text-muted line-clamp-2">{draft.description}</p>
          <p className="text-xs text-muted">
            <strong className="text-text">何时使用:</strong> {draft.when_to_use}
          </p>
          <div className="flex items-center gap-2 mt-auto pt-2">
            <button
              type="button"
              onClick={() => handleApprove(draft)}
              aria-label={`Approve ${draft.name}`}
              className="flex-1 px-3 py-1.5 text-xs rounded-radius-sm bg-success/10 text-success hover:bg-success/20 transition-colors"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => handleReject(draft)}
              aria-label={`Reject ${draft.name}`}
              className="flex-1 px-3 py-1.5 text-xs rounded-radius-sm bg-error/10 text-error hover:bg-error/20 transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
};

export default SkillDraftList;
