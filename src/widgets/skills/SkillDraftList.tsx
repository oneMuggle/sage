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
import { useI18n } from '../../shared/lib/i18n';

import SkillDraftDetail from './SkillDraftDetail';

/** t() 结果是静态模板，这里做最小占位符替换（i18n 无内置插值）。 */
function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

const POLL_INTERVAL_MS = 10000;

const SkillDraftList: React.FC = () => {
  const [drafts, setDrafts] = useState<SkillDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedDraft, setSelectedDraft] = useState<SkillDraft | null>(null);

  const { t } = useI18n();

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
        setSelectedDraft(null);
        toast.success(fill(t('skill_draft.approved'), { name: draft.name }));
      } catch (err) {
        toast.error(fill(t('skill_draft.approve_failed'), { error: (err as Error).message }));
      }
    },
    [t],
  );

  const handleReject = useCallback(
    async (draft: SkillDraft) => {
      try {
        await skillDraftsApi.reject(draft.id);
        setDrafts((prev) => prev.filter((d) => d.id !== draft.id));
        setSelectedDraft(null);
        toast.success(fill(t('skill_draft.rejected'), { name: draft.name }));
      } catch (err) {
        toast.error(fill(t('skill_draft.reject_failed'), { error: (err as Error).message }));
      }
    },
    [t],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <p className="text-muted">{t('skill_draft.loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <p className="text-error">{fill(t('skill_draft.load_failed'), { error })}</p>
        <button
          type="button"
          onClick={fetchDrafts}
          className="px-3 py-1.5 text-sm rounded-radius-sm bg-primary text-white hover:bg-primary/90"
        >
          {t('skill_draft.retry')}
        </button>
      </div>
    );
  }

  if (drafts.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-muted">{t('skill_draft.no_drafts')}</p>
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
            <strong className="text-text">
              {t('skill_draft.when_to_use').replace(/: ?\{text\}$/, ':')}
            </strong>{' '}
            {draft.when_to_use}
          </p>
          <div className="mt-auto pt-2">
            <button
              type="button"
              onClick={() => setSelectedDraft(draft)}
              aria-label={`${t('skill_draft.preview')} ${draft.name}`}
              className="w-full px-3 py-1.5 text-xs rounded-radius-sm bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
            >
              {t('skill_draft.preview')}
            </button>
          </div>
        </div>
      ))}
      <SkillDraftDetail
        draft={selectedDraft}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelectedDraft(null)}
      />
    </div>
  );
};

export default SkillDraftList;
