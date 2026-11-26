/**
 * RuleExtractionDraft — the draft review panel for extracted rules.
 *
 * Replaces the old "extract and immediately persist" flow. Shows all
 * extracted rules with confidence indicators, lets the user select/edit/
 * delete individual rules, resolve conflicts, then commit the final set.
 *
 * Phase 3 additions: confidence filter + bulk select (M20), manual rule
 * creation (M15), and committing into an existing rule group with a
 * same-name merge preview (M17/M18).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { officeRulesApi } from '../../../shared/api/officeRulesApi';
import type { WireCommitRuleItem, WireRuleGroup } from '../../../shared/api/types';

import { RuleConflictResolver } from './RuleConflictResolver';
import { RuleDraftCard } from './RuleDraftCard';
import { RuleRefinePanel } from './RuleRefinePanel';
import { useRuleDraftStore } from './ruleDraftStore';

export interface RuleExtractionDraftProps {
  onCommitted: (groupId: string, count: number) => void;
}

type ConfidenceFilter = 'all' | 'high' | 'medium' | 'low';

const FILTER_LABELS: Record<ConfidenceFilter, string> = {
  all: '全部',
  high: '高置信度',
  medium: '中置信度',
  low: '低置信度',
};

function matchesFilter(confidence: number, filter: ConfidenceFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'high') return confidence >= 0.8;
  if (filter === 'medium') return confidence >= 0.5 && confidence < 0.8;
  return confidence < 0.5;
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
  const selectByConfidence = useRuleDraftStore((state) => state.selectByConfidence);
  const updateRule = useRuleDraftStore((state) => state.updateRule);
  const removeRule = useRuleDraftStore((state) => state.removeRule);
  const addRule = useRuleDraftStore((state) => state.addRule);
  const reset = useRuleDraftStore((state) => state.reset);

  const [groupName, setGroupName] = useState('');
  const [committing, setCommitting] = useState(false);
  const [filter, setFilter] = useState<ConfidenceFilter>('all');
  const [groups, setGroups] = useState<WireRuleGroup[]>([]);
  const [targetGroupId, setTargetGroupId] = useState('');
  // Manual-add form (M15)
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSeverity, setNewSeverity] = useState<'error' | 'warning' | 'info'>('warning');
  const [newDescription, setNewDescription] = useState('');

  useEffect(() => {
    if (sourceName) {
      const dot = sourceName.lastIndexOf('.');
      const base = dot > 0 ? sourceName.slice(0, dot) : sourceName;
      setGroupName(`${base} · 抽取的规则`);
    }
  }, [sourceName]);

  // Load rule groups once the panel opens, for the "commit into existing group" picker.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    officeRulesApi
      .listGroups()
      .then((list) => {
        if (!cancelled) setGroups(list);
      })
      .catch(() => {
        // Group loading is best-effort; the new-group path still works.
        if (!cancelled) setGroups([]);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const targetGroup = useMemo(
    () => groups.find((group) => group.id === targetGroupId) ?? null,
    [groups, targetGroupId],
  );
  const existingNames = useMemo(
    () => new Set(targetGroup ? targetGroup.rules.map((rule) => rule.name) : []),
    [targetGroup],
  );

  const visibleRules = rules.filter((rule) => matchesFilter(rule.confidence, filter));
  const selectedRules = rules.filter((rule) => rule.selected);
  const selectedCount = selectedRules.length;
  // Merge preview: committing into an existing group skips same-name rules.
  const skippedCount = targetGroup
    ? selectedRules.filter((rule) => existingNames.has(rule.name)).length
    : 0;
  const toAddRules = targetGroup
    ? selectedRules.filter((rule) => !existingNames.has(rule.name))
    : selectedRules;

  const handleCommit = useCallback(async () => {
    if (selectedCount === 0) {
      toast.warning('请至少选择一条规则');
      return;
    }
    if (!targetGroupId && !groupName.trim()) {
      toast.warning('请输入规则组名称');
      return;
    }
    if (targetGroupId && toAddRules.length === 0) {
      toast.warning('选中规则均已存在于该规则组（同名跳过），没有可新增的规则');
      return;
    }
    setCommitting(true);
    try {
      const wireRules: WireCommitRuleItem[] = toAddRules.map((r) => ({
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
        group_name: targetGroup ? targetGroup.name : groupName.trim(),
        rules: wireRules,
        target_group_id: targetGroupId || null,
      });
      const target = targetGroup ? `「${targetGroup.name}」` : `「${groupName.trim()}」`;
      const skippedNote = skippedCount > 0 ? `，跳过 ${skippedCount} 条同名规则` : '';
      toast.success(
        targetGroup
          ? `已向${target}新增 ${result.rules_created} 条规则${skippedNote}`
          : `已创建${target}，共 ${result.rules_created} 条规则`,
      );
      reset();
      onCommitted(result.group_id, result.rules_created);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`提交失败: ${message}`);
    } finally {
      setCommitting(false);
    }
  }, [
    selectedCount,
    groupName,
    targetGroupId,
    targetGroup,
    toAddRules,
    skippedCount,
    reset,
    onCommitted,
  ]);

  const handleAddManualRule = () => {
    const name = newName.trim();
    if (!name) {
      toast.warning('请输入规则名称');
      return;
    }
    addRule({
      name,
      kind: 'custom',
      params: {},
      category: 'custom',
      severity: newSeverity,
      confidence: 1.0,
      sourceExcerpt: '手动添加',
      conflictGroup: null,
      suggestedCheckMode: 'ai',
      suggestedAiPrompt: `检查文档是否满足规则「${name}」${newDescription ? `：${newDescription}` : ''}`,
      suggestedType: 'custom',
      suggestedScope: 'body',
      description: newDescription,
    });
    setNewName('');
    setNewDescription('');
    setNewSeverity('warning');
    setShowAddForm(false);
  };

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
              {/* Toolbar: bulk select + confidence filter (M20) */}
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                <button type="button" onClick={selectAll} className="text-primary hover:underline">
                  全选
                </button>
                <span className="text-muted">|</span>
                <button type="button" onClick={deselectAll} className="text-muted hover:underline">
                  全不选
                </button>
                <span className="text-muted">|</span>
                <button
                  type="button"
                  onClick={() => selectByConfidence(0.8)}
                  className="text-primary hover:underline"
                  data-testid="rule-draft-select-high"
                >
                  仅选高置信度
                </button>
                <span className="text-muted">|</span>
                <label className="ml-auto flex items-center gap-1 text-muted">
                  筛选
                  <select
                    value={filter}
                    onChange={(e) => setFilter(e.target.value as ConfidenceFilter)}
                    className="rounded border border-border bg-surface px-1 py-0.5 text-xs"
                    data-testid="rule-draft-confidence-filter"
                  >
                    {(Object.keys(FILTER_LABELS) as ConfidenceFilter[]).map((key) => (
                      <option key={key} value={key}>
                        {FILTER_LABELS[key]}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  onClick={() => setShowAddForm((value) => !value)}
                  className="text-primary hover:underline"
                  data-testid="rule-draft-add-toggle"
                >
                  + 手动添加
                </button>
              </div>

              {/* Manual add form (M15) */}
              {showAddForm && (
                <div
                  className="mb-2 space-y-1.5 rounded-md border border-border bg-surface px-3 py-2"
                  data-testid="rule-draft-add-form"
                >
                  <div className="flex items-center gap-1.5">
                    <input
                      type="text"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      placeholder="规则名称（必填）"
                      className="flex-1 rounded border border-border bg-bg px-2 py-1 text-xs"
                      data-testid="rule-draft-add-name"
                    />
                    <select
                      value={newSeverity}
                      onChange={(e) => setNewSeverity(e.target.value as typeof newSeverity)}
                      className="rounded border border-border bg-bg px-1 py-1 text-xs"
                    >
                      <option value="error">error</option>
                      <option value="warning">warning</option>
                      <option value="info">info</option>
                    </select>
                  </div>
                  <textarea
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                    placeholder="规则说明（可选）"
                    rows={2}
                    className="w-full resize-none rounded border border-border bg-bg px-2 py-1 text-xs"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleAddManualRule}
                      className="rounded bg-primary px-2.5 py-1 text-xs text-white hover:bg-primary/90"
                      data-testid="rule-draft-add-confirm"
                    >
                      添加
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowAddForm(false)}
                      className="text-xs text-muted hover:underline"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}

              {/* Conflicts */}
              <RuleConflictResolver conflicts={conflicts} rules={rules} onToggle={toggleSelect} />

              {/* Rule list */}
              <div className="mt-2 space-y-1.5">
                {rules.length === 0 ? (
                  <div className="py-8 text-center text-sm text-muted">
                    未抽取到规则。可以检查文档内容，或用右侧 AI 精炼补充规则。
                  </div>
                ) : visibleRules.length === 0 ? (
                  <div className="py-8 text-center text-sm text-muted">当前筛选下没有规则。</div>
                ) : (
                  visibleRules.map((rule) => (
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
          <div className="flex flex-wrap items-center gap-3">
            {targetGroupId && skippedCount > 0 && (
              <span className="text-ui-2xs text-yellow-700" data-testid="rule-draft-merge-preview">
                将新增 {toAddRules.length} 条，跳过 {skippedCount} 条同名规则
              </span>
            )}
            <select
              value={targetGroupId}
              onChange={(e) => setTargetGroupId(e.target.value)}
              className="rounded border border-border bg-surface px-2 py-1.5 text-xs"
              data-testid="rule-draft-target-group"
              aria-label="提交到"
            >
              <option value="">提交到：新建规则组</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  提交到：{group.name}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={targetGroup ? targetGroup.name : groupName}
              onChange={(e) => setGroupName(e.target.value)}
              disabled={Boolean(targetGroup)}
              placeholder="规则组名称"
              className="min-w-[10rem] flex-1 rounded border border-border bg-surface px-3 py-1.5 text-sm disabled:opacity-60"
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
              确认落盘 ({targetGroup ? toAddRules.length : selectedCount})
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
