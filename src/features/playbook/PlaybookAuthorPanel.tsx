/**
 * PlaybookAuthorPanel — AI 定制规程的输入、生成结果与绑定动作。
 */
import type { PlaybookAuthorPreview } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

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
  return (
    <div className="space-y-2 rounded-md border border-border p-2">
      <div className="text-xs text-muted-foreground">
        不确定怎么划分阶段？让 AI 根据项目生成一份草案。
      </div>
      <textarea
        value={notes}
        onChange={(event) => onNotesChange(event.target.value)}
        placeholder="补充要求（可选）：资助方、必须交付的材料、时间节点…"
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
        {authoring ? '生成中…' : 'AI 定制规程'}
      </Button>
      {authorResult && (
        <div className="space-y-1 text-xs">
          <div className="font-medium text-foreground">{authorResult.playbook.name}</div>
          <div className="text-muted-foreground">
            {authorResult.rationale}
            {authorResult.source === 'deterministic' ? '（未配置 LLM，已降级）' : ''}
          </div>
          <Button
            size="sm"
            variant="primary"
            onClick={onBindAuthored}
            disabled={bindingAuthored}
            data-testid="playbook-bind-authored"
          >
            {bindingAuthored ? '绑定中…' : '绑定生成的规程'}
          </Button>
        </div>
      )}
    </div>
  );
}

export default PlaybookAuthorPanel;
