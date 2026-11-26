/**
 * ruleDraftStore — Zustand store for the extraction draft review workflow.
 *
 * Holds the draft rules returned by POST /rules/extract/draft, user edits,
 * and selection state, before the user commits them to the database.
 *
 * The draft is persisted to localStorage (M19) so a page refresh does not
 * lose unreviewed work; the modal itself stays closed after rehydration and
 * the rules tab shows a "resume draft" shortcut instead of auto-opening.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

import type {
  WireDraftConflict,
  WireDraftRuleItem,
  WireRefineAction,
} from '../../../shared/api/types/officeRulesTypes';

// ---------------------------------------------------------------------------
// Draft item shape (mutable copy of the wire item)
// ---------------------------------------------------------------------------

export interface DraftRule {
  tempId: string;
  name: string;
  kind: string;
  params: Record<string, unknown>;
  category: string;
  severity: string;
  confidence: number;
  sourceExcerpt: string;
  conflictGroup: string | null;
  suggestedCheckMode: string;
  suggestedAiPrompt: string;
  suggestedType: string;
  suggestedScope: string;
  description: string;
  /** Whether the user has selected this rule for commit. */
  selected: boolean;
  /** Whether the user has edited this rule since extraction. */
  dirty: boolean;
}

function fromWire(item: WireDraftRuleItem): DraftRule {
  return {
    tempId: item.temp_id,
    name: item.name,
    kind: item.kind,
    params: { ...item.params },
    category: item.category,
    severity: item.severity,
    confidence: item.confidence,
    sourceExcerpt: item.source_excerpt,
    conflictGroup: item.conflict_group ?? null,
    suggestedCheckMode: item.suggested_check_mode,
    suggestedAiPrompt: item.suggested_ai_prompt,
    suggestedType: item.suggested_type,
    suggestedScope: item.suggested_scope,
    description: item.description,
    selected: item.confidence >= 0.5,
    dirty: false,
  };
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export interface RuleDraftState {
  /** Whether the draft review panel is open. */
  isOpen: boolean;
  /** Loading state for the extraction request. */
  isLoading: boolean;
  /** Error message from the last extraction attempt. */
  error: string | null;
  /** Draft rules. */
  rules: DraftRule[];
  /** Conflicts from extraction. */
  conflicts: WireDraftConflict[];
  /** Non-fatal warnings from extraction. */
  warnings: string[];
  /** Source document filename for display. */
  sourceName: string;
  /** The workspace path the draft was extracted from (for commit). */
  workspacePath: string;
  /**
   * Instruction prefilled by a per-rule "AI 修改" shortcut. The refine panel
   * consumes it into its input box once and clears it.
   */
  pendingInstruction: string | null;

  open: (sourceName: string, workspacePath: string) => void;
  /** Reopen a persisted draft without discarding its rules. */
  resume: () => void;
  close: () => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setDraft: (
    rules: WireDraftRuleItem[],
    conflicts: WireDraftConflict[],
    warnings: string[],
  ) => void;
  toggleSelect: (tempId: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  /** Select only rules at or above `minConfidence`; deselect the rest. */
  selectByConfidence: (minConfidence: number) => void;
  updateRule: (tempId: string, patch: Partial<DraftRule>) => void;
  removeRule: (tempId: string) => void;
  addRule: (rule: Omit<DraftRule, 'tempId' | 'selected' | 'dirty'>) => void;
  /** Apply one validated AI refine action (add / modify / delete) to the draft. */
  applyRefineAction: (action: WireRefineAction) => void;
  setPendingInstruction: (instruction: string | null) => void;
  reset: () => void;
}

const initialState = {
  isOpen: false,
  isLoading: false,
  error: null,
  rules: [] as DraftRule[],
  conflicts: [] as WireDraftConflict[],
  warnings: [] as string[],
  sourceName: '',
  workspacePath: '',
  pendingInstruction: null as string | null,
};

let _nextTempId = 0;
function nextTempId(): string {
  _nextTempId += 1;
  return `manual_${_nextTempId}`;
}

export const useRuleDraftStore = create<RuleDraftState>()(
  persist(
    (set) => ({
      ...initialState,

      open: (sourceName, workspacePath) =>
        set({ ...initialState, isOpen: true, sourceName, workspacePath }),

      resume: () => set({ isOpen: true }),

      close: () => set({ isOpen: false }),

      setLoading: (loading) => set({ isLoading: loading }),

      setError: (error) => set({ error, isLoading: false }),

      setDraft: (rules, conflicts, warnings) =>
        set({
          isLoading: false,
          error: null,
          rules: rules.map(fromWire),
          conflicts,
          warnings,
        }),

      toggleSelect: (tempId) =>
        set((state) => ({
          rules: state.rules.map((r) =>
            r.tempId === tempId ? { ...r, selected: !r.selected } : r,
          ),
        })),

      selectAll: () =>
        set((state) => ({ rules: state.rules.map((r) => ({ ...r, selected: true })) })),

      deselectAll: () =>
        set((state) => ({ rules: state.rules.map((r) => ({ ...r, selected: false })) })),

      selectByConfidence: (minConfidence) =>
        set((state) => ({
          rules: state.rules.map((r) => ({ ...r, selected: r.confidence >= minConfidence })),
        })),

      updateRule: (tempId, patch) =>
        set((state) => ({
          rules: state.rules.map((r) =>
            r.tempId === tempId ? { ...r, ...patch, dirty: true } : r,
          ),
        })),

      removeRule: (tempId) =>
        set((state) => ({
          rules: state.rules.filter((r) => r.tempId !== tempId),
        })),

      addRule: (rule) =>
        set((state) => ({
          rules: [...state.rules, { ...rule, tempId: nextTempId(), selected: true, dirty: true }],
        })),

      applyRefineAction: (action) =>
        set((state) => {
          if (action.type === 'add' && action.rule) {
            const rule = action.rule;
            const newRule: DraftRule = {
              tempId: nextTempId(),
              name: rule.name,
              kind: rule.kind ?? 'custom',
              params: rule.params ?? {},
              category: rule.type ?? 'custom',
              severity: rule.severity ?? 'warning',
              confidence: 0.6,
              sourceExcerpt: 'AI 精炼新增',
              conflictGroup: null,
              suggestedCheckMode: 'ai',
              suggestedAiPrompt: rule.ai_prompt ?? `检查文档是否满足规则「${rule.name}」`,
              suggestedType: rule.type ?? 'custom',
              suggestedScope: rule.scope ?? 'body',
              description: rule.description ?? '',
              selected: true,
              dirty: true,
            };
            return { rules: [...state.rules, newRule] };
          }
          if (action.type === 'modify' && action.temp_id && action.patch) {
            const patch = action.patch;
            return {
              rules: state.rules.map((r) => {
                if (r.tempId !== action.temp_id) return r;
                const updated: DraftRule = { ...r, dirty: true };
                if (patch.name !== undefined) updated.name = patch.name;
                if (patch.params !== undefined) updated.params = patch.params;
                if (patch.severity !== undefined) updated.severity = patch.severity;
                if (patch.description !== undefined) updated.description = patch.description;
                if (patch.ai_prompt !== undefined) updated.suggestedAiPrompt = patch.ai_prompt;
                if (patch.type !== undefined) updated.suggestedType = patch.type;
                if (patch.scope !== undefined) updated.suggestedScope = patch.scope;
                return updated;
              }),
            };
          }
          if (action.type === 'delete' && action.temp_id) {
            return { rules: state.rules.filter((r) => r.tempId !== action.temp_id) };
          }
          return {};
        }),

      setPendingInstruction: (instruction) => set({ pendingInstruction: instruction }),

      reset: () => set(initialState),
    }),
    {
      name: 'sage-rule-draft-v1',
      // Transient state (open/loading/error/pending) is never persisted so a
      // refresh restores the draft data without popping the modal open.
      partialize: (state) => ({
        rules: state.rules,
        conflicts: state.conflicts,
        warnings: state.warnings,
        sourceName: state.sourceName,
        workspacePath: state.workspacePath,
      }),
    },
  ),
);
