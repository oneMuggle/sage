/**
 * Orchestration page — goal input + planner-driven lane creation (M5)
 * on top of the LaneBoard widget.
 */
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useLaneBoardStore } from '../entities/orchestration/laneBoardStore';
import { useI18n } from '../shared/lib/i18n';
import { LaneBoard } from '../widgets/orchestration/LaneBoard';

export function Orchestration() {
  const { t } = useI18n();
  const createLane = useLaneBoardStore((s) => s.createLane);
  const [goal, setGoal] = useState('');
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    const trimmed = goal.trim();
    if (!trimmed || creating) return;
    setCreating(true);
    try {
      const created = await createLane(trimmed);
      setGoal('');
      toast.success(
        t('orchestration.toast.create_success').replace('{count}', String(created.lanes.length)),
      );
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t('orchestration.toast.create_fail')}: ${message}`);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <header className="mb-4">
          <h1 className="text-2xl font-semibold">{t('orchestration.title')}</h1>
          <p className="text-xs text-text-secondary mt-1">{t('orchestration.subtitle')}</p>
        </header>

        <form
          className="flex items-center gap-2 mb-4"
          onSubmit={(e) => {
            e.preventDefault();
            void handleCreate();
          }}
        >
          <input
            type="text"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder={t('orchestration.goal_placeholder')}
            aria-label={t('orchestration.goal_placeholder')}
            className="flex-1 px-3 py-1.5 text-sm bg-bg-surface border border-border rounded-radius-sm focus:outline-none focus:border-primary"
          />
          <button
            type="submit"
            disabled={creating || goal.trim().length === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>{creating ? t('orchestration.creating') : t('orchestration.create')}</span>
          </button>
        </form>

        <LaneBoard />
      </div>
    </div>
  );
}
