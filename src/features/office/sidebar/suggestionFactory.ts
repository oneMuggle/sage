import type { SuggestionCardData } from '../../../entities/office/officeWorkspaceStore';
import type { AiReviewIssue } from '../../../shared/api/officeSpecTypes';

export function suggestionFromRewrite(params: {
  paraIndex: number;
  originalText: string;
  suggestedText: string;
  comment?: string;
}): SuggestionCardData {
  return {
    id: `sg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    paraIndex: params.paraIndex,
    severity: 'info',
    originalText: params.originalText,
    suggestedText: params.suggestedText,
    ...(params.comment ? { ruleName: params.comment } : {}),
    applied: 'pending',
  };
}

export function toReviseIssue(suggestion: SuggestionCardData): AiReviewIssue {
  return {
    id: suggestion.id,
    severity: suggestion.severity,
    category: 'ai_rewrite',
    message: suggestion.ruleName ?? 'AI 改写',
    suggestion: suggestion.suggestedText,
    rationale: '',
    expected: suggestion.suggestedText,
    actual: suggestion.originalText,
    fixable: true,
    location: {
      paragraph_index: suggestion.paraIndex,
      paragraph_text: suggestion.originalText,
    },
    source: {
      kind: 'llm',
      spec_id: null,
      spec_name: null,
      rule_id: null,
      rule_pack_id: null,
    },
  };
}
