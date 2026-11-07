import { describe, expect, it } from 'vitest';

import { suggestionFromRewrite, toReviseIssue } from '../suggestionFactory';

describe('suggestionFactory', () => {
  it('builds a pending suggestion card', () => {
    const card = suggestionFromRewrite({
      paraIndex: 3,
      originalText: 'old',
      suggestedText: 'new',
      comment: '更通顺',
    });
    expect(card.paraIndex).toBe(3);
    expect(card.severity).toBe('info');
    expect(card.applied).toBe('pending');
    expect(card.ruleName).toBe('更通顺');
  });

  it('maps a suggestion to an AiReviewIssue accepted by /office/ai/revise', () => {
    const issue = toReviseIssue(
      suggestionFromRewrite({ paraIndex: 3, originalText: 'old', suggestedText: 'new' }),
    );
    expect(issue.actual).toBe('old');
    expect(issue.expected).toBe('new');
    expect(issue.suggestion).toBe('new');
    expect(issue.fixable).toBe(true);
    expect(issue.location).toEqual({ paragraph_index: 3, paragraph_text: 'old' });
    expect(issue.source.kind).toBe('llm');
  });
});
