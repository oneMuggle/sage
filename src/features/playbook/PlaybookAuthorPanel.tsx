/**
 * PlaybookAuthorPanel — AI 定制规程的输入、生成结果与绑定动作。
 */
import type { PlaybookAuthorPreview } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookAuthorPanelProps {
  notes: string;
  onNotesChange: (value: string) => void;
  onAuthor: () => void;
  authoring: boolean;
  authorResult: PlaybookAuthorPreview | null;
  onBindAuthored: () => void;
  bindingAuthored: boolean;
}

export function PlaybookAuthorPanel({
  notes,
  onNotesChange,
  onAuthor,
  authoring,
  authorResult,
  onBindAuthored,
  bindingAuthored,
}: PlaybookAuthorPanelProps) {
  const { t } = usePlaybookI18n();
  return (
    <div className="space-y-2 rounded-md border border-border p-2">
      <div className="text-xs text-muted-foreground">{t('playbook.author.hint')}</div>
      <textarea
        value={notes}
        onChange={(event) => onNotesChange(event.target.value)}
        aria-label={t('playbook.author.placeholder')}
        placeholder={t('playbook.author.placeholder')}
        rows={2}
        className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
        data-testid="playbook-author-notes"
      />
      <Button
        size="sm"
        variant="secondary"
        onClick={onAuthor}
        disabled={authoring}
        data-testid="playbook-author-btn"
      >
        {authoring ? t('playbook.author.generating') : t('playbook.author.generate')}
      </Button>
      {authorResult && (
        <div className="space-y-1 text-xs">
          <div className="font-medium text-foreground">{authorResult.playbook.name}</div>
          <div className="text-muted-foreground">
            {authorResult.rationale}
            {authorResult.source === 'deterministic' ? t('playbook.author.fallback') : ''}
          </div>
          <Button
            size="sm"
            variant="primary"
            onClick={onBindAuthored}
            disabled={bindingAuthored}
            data-testid="playbook-bind-authored"
          >
            {bindingAuthored ? t('playbook.author.binding') : t('playbook.author.bind')}
          </Button>
        </div>
      )}
    </div>
  );
}

export default PlaybookAuthorPanel;
