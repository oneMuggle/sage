/**
 * RuleDraftCard — one draft rule item in the extraction review list.
 *
 * Shows confidence badge, structured params, source excerpt, and
 * inline edit / delete actions.
 */

import { useState } from 'react';

import type { DraftRule } from './ruleDraftStore';

export interface RuleDraftCardProps {
  rule: DraftRule;
  onToggle: (tempId: string) => void;
  onUpdate: (tempId: string, patch: Partial<DraftRule>) => void;
  onRemove: (tempId: string) => void;
}

function confidenceLevel(c: number): 'high' | 'medium' | 'low' {
  if (c >= 0.8) return 'high';
  if (c >= 0.5) return 'medium';
  return 'low';
}

const CONFIDENCE_STYLES: Record<string, string> = {
  high: 'bg-green-500/20 text-green-700 border-green-300',
  medium: 'bg-yellow-500/20 text-yellow-700 border-yellow-300',
  low: 'bg-red-500/20 text-red-700 border-red-300',
};

const CONFIDENCE_DOT: Record<string, string> = {
  high: 'bg-green-500',
  medium: 'bg-yellow-500',
  low: 'bg-red-500',
};

function formatParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(', ');
}

export function RuleDraftCard({ rule, onToggle, onUpdate, onRemove }: RuleDraftCardProps) {
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(rule.name);
  const level = confidenceLevel(rule.confidence);

  const handleSave = () => {
    onUpdate(rule.tempId, { name: editName.trim() || rule.name });
    setEditing(false);
  };

  const handleCancel = () => {
    setEditName(rule.name);
    setEditing(false);
  };

  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        rule.selected ? 'border-border bg-surface' : 'border-border/50 bg-surface/50 opacity-60'
      } ${rule.dirty ? 'ring-1 ring-primary/30' : ''}`}
      data-testid={`rule-draft-card-${rule.tempId}`}
    >
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={rule.selected}
          onChange={() => onToggle(rule.tempId)}
          className="mt-1 shrink-0"
          aria-label={`选择规则 ${rule.name}`}
        />
        <span
          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${CONFIDENCE_DOT[level]}`}
          title={`置信度 ${Math.round(rule.confidence * 100)}%`}
        />

        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex items-center gap-1.5">
              <input
                type="text"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSave();
                  if (e.key === 'Escape') handleCancel();
                }}
                className="flex-1 rounded border border-border bg-bg px-2 py-0.5 text-sm"
                autoFocus
              />
              <button
                type="button"
                onClick={handleSave}
                className="text-xs text-primary hover:underline"
              >
                保存
              </button>
              <button
                type="button"
                onClick={handleCancel}
                className="text-xs text-muted hover:underline"
              >
                取消
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">{rule.name}</span>
              <span className="text-ui-xs text-muted font-mono">{rule.kind}</span>
              <span
                className={`rounded border px-1 py-0.5 text-ui-xs ${CONFIDENCE_STYLES[level]}`}
              >
                {Math.round(rule.confidence * 100)}%
              </span>
            </div>
          )}

          <div className="mt-0.5 text-xs text-text-secondary">{formatParams(rule.params)}</div>

          {rule.sourceExcerpt && (
            <div className="mt-1 text-ui-2xs text-muted italic truncate" title={rule.sourceExcerpt}>
              来源：{rule.sourceExcerpt}
            </div>
          )}

          {rule.conflictGroup && (
            <div className="mt-1 text-ui-2xs text-yellow-600">
              ⚠️ 与其他规则存在冲突（{rule.conflictGroup}）
            </div>
          )}
        </div>

        <div className="shrink-0 flex items-center gap-1">
          {!editing && (
            <button
              type="button"
              onClick={() => {
                setEditName(rule.name);
                setEditing(true);
              }}
              className="rounded px-1.5 py-0.5 text-ui-2xs text-text-secondary hover:bg-bg-hover"
              title="编辑规则名称"
            >
              编辑
            </button>
          )}
          <button
            type="button"
            onClick={() => onRemove(rule.tempId)}
            className="rounded px-1.5 py-0.5 text-ui-2xs text-red-500 hover:bg-red-50"
            title="从草稿中删除"
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}
