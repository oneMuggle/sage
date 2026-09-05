import type { SkillDraft } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';
// `MarkdownPreview` lives at `widgets/wiki/MarkdownPreview.tsx` and is
// exported as a named function. The PR-3 vitest mock (see
// `__tests__/SkillDraftDetail.test.tsx`), however, exposes it as a
// `default` export. Import it as default so both the locked test mock
// and the real module (which also re-exports `MarkdownPreview` as
// default) work without touching the test or the test seam.
import MarkdownPreview from '../wiki/MarkdownPreview';

interface SkillDraftDetailProps {
  draft: SkillDraft | null;
  onApprove: (draft: SkillDraft) => void;
  onReject: (draft: SkillDraft) => void;
  onClose: () => void;
}

/** Local placeholder substitution (matches Chat.tsx:20 / SkillDraftList.tsx:16 pattern). */
function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

/**
 * SkillDraftDetail — modal preview of a skill draft's full SKILL.md content.
 *
 * Renders the draft's metadata (name, trigger_type, description, when_to_use)
 * and the full content via MarkdownPreview. Provides Approve / Reject / Cancel
 * buttons in the footer.
 *
 * Used by SkillDraftList (PR-3 UX closure).
 */
export default function SkillDraftDetail({
  draft,
  onApprove,
  onReject,
  onClose,
}: SkillDraftDetailProps) {
  const { t } = useI18n();

  if (!draft) return null;

  return (
    <Dialog open={!!draft} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle className="text-lg">{draft.name}</DialogTitle>
            <span className="text-xs text-muted px-1.5 py-0.5 bg-bg-muted rounded">
              {draft.trigger_type}
            </span>
          </div>
          <DialogDescription>{draft.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="text-sm">
            <strong className="text-text">
              {fill(t('skill_draft.when_to_use'), { text: '' }).replace(/: ?$/, ':')}
            </strong>{' '}
            {draft.when_to_use}
          </div>

          <div className="border-t pt-4">
            <MarkdownPreview content={draft.content} />
          </div>
        </div>

        <div className="flex items-center gap-2 justify-end border-t pt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border hover:bg-bg-hover transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => {
              onReject(draft);
              onClose();
            }}
            className="px-3 py-1.5 text-xs rounded-radius-sm bg-error/10 text-error hover:bg-error/20 transition-colors"
          >
            {t('skill_draft.reject')}
          </button>
          <button
            type="button"
            onClick={() => {
              onApprove(draft);
              onClose();
            }}
            className="px-3 py-1.5 text-xs rounded-radius-sm bg-success/10 text-success hover:bg-success/20 transition-colors"
          >
            {t('skill_draft.approve')}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
