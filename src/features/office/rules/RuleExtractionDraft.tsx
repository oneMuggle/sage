/**
 * RuleExtractionDraft — the draft review panel for extracted rules.
 *
 * Replaces the old "extract and immediately persist" flow. Shows all
 * extracted rules with confidence indicators, lets the user select/edit/
 * delete individual rules, resolve conflicts, then commit the final set.
 */

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { officeRulesApi } from '../../../shared/api/officeRulesApi';
import type { WireCommitRuleItem } from '../../../shared/api/types';

import { RuleConflictResolver } from './RuleConflictResolver';
import { RuleDraftCard } from './RuleDraftCard';
import { RuleRefinePanel } from './RuleRefinePanel';
import { useRuleDraftStore } from './ruleDraftStore';

export interface RuleExtractionDraftProps {
  onCommitted: (groupId: string, count: number) => void;
}

export function RuleExtractionDraft({ onCommitted }: RuleExtractionDraftProps) {
  const isOpen = useRuleDraftStore((state) => state.isOpen);
  const isLoading = useRuleDraftStore((state) => state.isLoading);
  const error = useRuleDraftStore((state) => state.error);
  const rules = useRuleDraftStore((state) => state.rules);
  const conflicts = useRuleDraftStore((state) => state.conflicts);
  const warnings = useRuleDraftStore((state) => state.warnings);
  const sourceName = useRuleDraftStore((state) => state.sourceName);
  const close = useRuleDraftStore((state) => state.close);
  const toggleSelect = useRuleDraftStore((state) => state.toggleSelect);
  const selectAll = useRuleDraftStore((state) => state.selectAll);
  const deselectAll = useRuleDraftStore((state) => state.deselectAll);
  const updateRule = useRuleDraftStore((state) => state.updateRule);
  const removeRule = useRuleDraftStore((state) => state.removeRule);
  const reset = useRuleDraftStore((state) => state.reset);

  const [groupName, setGroupName] = useState('');
  const [committing, setCommitting] = useState(false);

  useEffect(() => {
    if (sourceName) {
      const dot = sourceName.lastIndexOf('.');
      const base = dot > 0 ? sourceName.slice(0, dot) : sourceName;
      setGroupName(`${base} · 抽取的规则`);
    }
  }, [sourceName]);

  const selectedRules = rules.filter((r) => r.selected);
  const selectedCount = selectedRules.length;

  const handleCommit = useCallback(async () => {
    if (selectedCount === 0) {
      toast.warning('请至少选择一条规则');
      return;
    }
    if (!groupName.trim()) {
      toast.warning('请输入规则组名称');
      return;
    }
    setCommitting(true);
    try {
      const wireRules: WireCommitRuleItem[] = selectedRules.map((r) => ({
        name: r.name,
        type: r.suggestedType as WireCommitRuleItem['type'],
        severity: r.severity as WireCommitRuleItem['severity'],
        scope: r.suggestedScope as WireCommitRuleItem['scope'],
        description: r.description,
        check_mode: r.suggestedCheckMode as WireCommitRuleItem['check_mode'],
        ai_prompt: r.suggestedAiPrompt,
        enabled: true,
        structured_params: r.params,
        confidence: r.confidence,
        source_excerpt: r.sourceExcerpt,
      }));
      const result = await officeRulesApi.commitRules({
        group_name: groupName.trim(),
        rules: wireRules,
      });
      toast.success(`已创建 ${result.rules_created} 条规则`);
      reset();
      onCommitted(result.group_id, result.rules_created);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`提交失败: ${message}`);
    } finally {
      setCommitting(false);
    }
  }, [selectedRules, selectedCount, groupName, reset, onCommitted]);

  const handleClose = () => {
    if (rules.length > 0 && rules.some((r) => r.dirty || !r.selected)) {
      if (!window.confirm('有未提交的修改，确定关闭吗？')) return;
    }
    close();
    reset();
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 pt-[5vh] pb-10"
      data-testid="rule-extraction-draft"
    >
      <div className="mx-auto w-full max-w-5xl rounded-xl border border-border bg-bg shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold">📄 规则抽取预览 — {sourceName || '当前文档'}</h2>
            <p className="mt-0.5 text-xs text-muted">
              共 {rules.length} 条规则，已选 {selectedCount} 条。
              勾选要保留的规则，取消不需要的，或用右侧 AI 精炼补充修改，然后确认落盘。
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="rounded p-1 text-muted hover:bg-bg-hover"
            aria-label="关闭"
          >
            ✕
          </button>
        </div>

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="border-b border-border bg-yellow-50/50 px-4 py-2">
            {warnings.map((w, i) => (
              <div key={i} className="text-ui-2xs text-yellow-700">
                ⚠️ {w}
              </div>
            ))}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="border-b border-border bg-red-50/50 px-4 py-2">
            <div className="text-ui-2xs text-red-600">❌ {error}</div>
          </div>
        )}

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted">
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
            正在抽取规则...
          </div>
        )}

        {/* Content: rule list + AI refine panel */}
        {!isLoading && (
          <div className="grid max-h-[62vh] grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px]">
            <div className="overflow-y-auto border-b border-border px-4 py-3 md:border-b-0 md:border-r">
              {/* Toolbar */}
              <div className="mb-2 flex items-center gap-2">
                <button
                  type="button"
                  onClick={selectAll}
                  className="text-xs text-primary hover:underline"
                >
                  全选
                </button>
                <span className="text-xs text-muted">|</span>
                <button
                  type="button"
                  onClick={deselectAll}
                  className="text-xs text-muted hover:underline"
                >
                  全不选
                </button>
              </div>

              {/* Conflicts */}
              <RuleConflictResolver conflicts={conflicts} rules={rules} onToggle={toggleSelect} />

              {/* Rule list */}
              <div className="mt-2 space-y-1.5">
                {rules.length === 0 ? (
                  <div className="py-8 text-center text-sm text-muted">
                    未抽取到规则。可以检查文档内容，或用右侧 AI 精炼补充规则。
                  </div>
                ) : (
                  rules.map((rule) => (
                    <RuleDraftCard
                      key={rule.tempId}
                      rule={rule}
                      onToggle={toggleSelect}
                      onUpdate={updateRule}
                      onRemove={removeRule}
                    />
                  ))
                )}
              </div>
            </div>

            <div className="h-[46vh] md:h-auto">
              <RuleRefinePanel />
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="border-t border-border px-4 py-3">
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={groupName}
              onChange={(e) => setGroupName(e.target.value)}
              placeholder="规则组名称"
              className="flex-1 rounded border border-border bg-surface px-3 py-1.5 text-sm"
            />
            <button
              type="button"
              onClick={() => void handleCommit()}
              disabled={committing || selectedCount === 0 || isLoading}
              className="inline-flex items-center gap-1.5 rounded bg-primary px-4 py-1.5 text-sm text-white hover:bg-primary/90 disabled:opacity-50"
            >
              {committing && (
                <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent" />
              )}
              确认落盘 ({selectedCount})
            </button>
            <button
              type="button"
              onClick={handleClose}
              disabled={committing}
              className="rounded border border-border px-3 py-1.5 text-sm text-text-secondary hover:bg-bg-hover"
            >
              取消
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
