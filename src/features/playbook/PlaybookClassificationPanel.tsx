/**
 * PlaybookClassificationPanel — 归类建议与未知文件的批量移动 / 撤销。
 *
 * 审计结果只提供建议；所有移动都必须由用户勾选并确认，撤销仅作用于
 * 最近一次批量移动。
 */
import { Undo2 } from 'lucide-react';
import { useState } from 'react';

import type {
  PlaybookAction,
  PlaybookClassificationSuggestion,
  PlaybookMove,
  PlaybookUnclassifiedFile,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

export interface PlaybookClassificationPanelProps {
  classification: PlaybookClassificationSuggestion[];
  unclassified: PlaybookUnclassifiedFile[];
  undoAvailable: { at: number; count: number } | null;
  busy: string | null;
  onAction: (action: PlaybookAction) => void;
  onBatchMove: (moves: PlaybookMove[]) => void;
  onUndo: () => void;
}

interface SelectableMove {
  key: string;
  move: PlaybookMove;
}

export function PlaybookClassificationPanel({
  classification,
  unclassified,
  undoAvailable,
  busy,
  onAction,
  onBatchMove,
  onUndo,
}: PlaybookClassificationPanelProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const moves: SelectableMove[] = [
    ...classification.map((item, index) => ({
      key: `move-${index}`,
      move: { from: item.from, to: item.to },
    })),
    ...unclassified.map((item, index) => ({
      key: `unknown-${index}`,
      move: { from: item.path, to: item.suggested_to },
    })),
  ];
  const chosen = moves.filter((item) => selected[item.key]);
  const allSelected = moves.length > 0 && chosen.length === moves.length;

  if (!classification.length && !unclassified.length && !undoAvailable) return null;

  const toggle = (key: string) => setSelected((prev) => ({ ...prev, [key]: !prev[key] }));

  const toggleAll = () =>
    setSelected(allSelected ? {} : Object.fromEntries(moves.map((item) => [item.key, true])));

  return (
    <div className="space-y-1.5" data-testid="playbook-classification">
      {classification.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-medium text-foreground">归类建议（需逐项确认）</div>
          <label className="flex items-center gap-1 text-ui-2xs text-muted-foreground">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              aria-label="全选归类建议"
              data-testid="playbook-select-all"
            />
            全选
          </label>
        </div>
      )}

      {classification.map((item, index) => {
        const key = `move-${index}`;
        return (
          <div
            key={`${item.from}-${item.to}`}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
          >
            <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(selected[key])}
                onChange={() => toggle(key)}
                aria-label={`选择 ${item.from}`}
                data-testid={`playbook-select-${key}`}
              />
              <span className="truncate" title={item.reason}>
                {item.from} → {item.to}
              </span>
            </span>
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                onAction({
                  type: 'move_file',
                  payload: { from: item.from, to: item.to },
                })
              }
              disabled={busy === 'move_file'}
              data-testid={`playbook-move-${item.artifact_id}`}
            >
              移动
            </Button>
          </div>
        );
      })}

      {unclassified.length > 0 && (
        <div className="space-y-1.5 pt-1" data-testid="playbook-unclassified">
          <div className="text-xs font-medium text-foreground">
            未知文件（建议归类，可批量移动）
          </div>
          {unclassified.map((item, index) => {
            const key = `unknown-${index}`;
            return (
              <div
                key={item.path}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-dashed border-border px-2 py-1.5 text-xs"
              >
                <span className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={Boolean(selected[key])}
                    onChange={() => toggle(key)}
                    aria-label={`选择 ${item.path}`}
                    data-testid={`playbook-select-${key}`}
                  />
                  <span className="truncate" title={item.reason}>
                    {item.path} → {item.suggested_to}
                    <span className="ml-1 text-ui-2xs opacity-70">
                      （建议 {Math.round(item.confidence * 100)}%）
                    </span>
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    onAction({
                      type: 'move_file',
                      payload: { from: item.path, to: item.suggested_to },
                    })
                  }
                  disabled={busy === 'move_file'}
                  data-testid={`playbook-move-unknown-${index}`}
                >
                  移动
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {moves.length > 0 && (
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              onBatchMove(chosen.map((item) => item.move));
              setSelected({});
            }}
            disabled={chosen.length === 0 || busy === 'batch-move'}
            data-testid="playbook-batch-move"
          >
            移动选中（{chosen.length}）
          </Button>
        )}
        {undoAvailable && (
          <Button
            size="sm"
            variant="secondary"
            onClick={onUndo}
            disabled={busy === 'undo-batch'}
            title={`最近一次批量移动：${new Date(undoAvailable.at).toLocaleString()}`}
            data-testid="playbook-undo-batch"
          >
            <Undo2 className="mr-1 h-3.5 w-3.5" />
            撤销上次批量移动（{undoAvailable.count}）
          </Button>
        )}
      </div>
    </div>
  );
}

export default PlaybookClassificationPanel;
