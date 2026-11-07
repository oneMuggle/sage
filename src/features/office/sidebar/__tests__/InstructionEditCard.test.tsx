import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SuggestionCardData } from '../../../../entities/office/officeWorkspaceStore';
import { InstructionEditCard } from '../InstructionEditCard';

vi.mock('../../../../shared/lib/i18n', () => ({
  useI18n: () => ({
    t: (key: string) => {
      if (key === 'office.ai.audit.paragraph') return '第 {index} 段';
      return key;
    },
    locale: 'zh',
    setLocale: vi.fn(),
  }),
}));

const suggestions: SuggestionCardData[] = [
  {
    id: 'sg-1',
    paraIndex: 0,
    severity: 'info',
    originalText: 'first',
    suggestedText: 'fixed first',
    applied: 'pending',
  },
  {
    id: 'sg-2',
    paraIndex: 2,
    severity: 'warning',
    originalText: 'second',
    suggestedText: 'fixed second',
    applied: 'pending',
  },
  {
    id: 'sg-3',
    paraIndex: 4,
    severity: 'error',
    originalText: 'third',
    suggestedText: 'fixed third',
    applied: 'skipped',
  },
];

function renderCard(overrides: Partial<React.ComponentProps<typeof InstructionEditCard>> = {}) {
  const onApply = vi.fn();
  const onSkip = vi.fn();
  const onApplyAll = vi.fn();
  const utils = render(
    <InstructionEditCard
      messageId="msg-1"
      suggestions={suggestions}
      busy={false}
      onApply={onApply}
      onSkip={onSkip}
      onApplyAll={onApplyAll}
      {...overrides}
    />,
  );
  return { ...utils, onApply, onSkip, onApplyAll };
}

describe('InstructionEditCard', () => {
  it('renders paragraph number, original and suggested text per card', () => {
    renderCard();
    expect(screen.getByText('第 1 段')).toBeTruthy();
    expect(screen.getByText('第 3 段')).toBeTruthy();
    expect(screen.getByText('第 5 段')).toBeTruthy();
    expect(screen.getByText('first')).toBeTruthy();
    expect(screen.getByText('fixed first')).toBeTruthy();
    expect(screen.getByText('fixed second')).toBeTruthy();
  });

  it('marks the original text as deleted and the suggestion as inserted', () => {
    renderCard();
    const deleted = screen.getByText('first');
    const inserted = screen.getByText('fixed first');
    expect(deleted.tagName).toBe('DEL');
    expect(inserted.tagName).toBe('INS');
  });

  it('forwards apply and skip clicks with the card payload', () => {
    const { onApply, onSkip } = renderCard();

    fireEvent.click(screen.getByTestId('office-ai-instruction-edit-apply-sg-1'));
    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply).toHaveBeenCalledWith('msg-1', suggestions[0]);

    fireEvent.click(screen.getByTestId('office-ai-instruction-edit-skip-sg-2'));
    expect(onSkip).toHaveBeenCalledTimes(1);
    expect(onSkip).toHaveBeenCalledWith('msg-1', 'sg-2');
  });

  it('disables every button when busy is true', () => {
    renderCard({ busy: true });
    const applyButtons = screen.getAllByTestId(/office-ai-instruction-edit-apply-/);
    const skipButtons = screen.getAllByTestId(/office-ai-instruction-edit-skip-/);
    for (const button of [...applyButtons, ...skipButtons]) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
  });

  it('renders apply-all while at least one card is still pending', () => {
    const allPending = suggestions.map((suggestion) => ({
      ...suggestion,
      applied: 'pending' as const,
    }));
    const { onApplyAll: allOn, rerender } = renderCard({ suggestions: allPending });
    expect(screen.getByTestId('office-ai-audit-apply-all')).toBeTruthy();

    fireEvent.click(screen.getByTestId('office-ai-audit-apply-all'));
    expect(allOn).toHaveBeenCalledWith('msg-1');

    // R25: a single pending card still exposes apply-all.
    const onePending: SuggestionCardData[] = [
      { ...suggestions[0], applied: 'pending' },
      { ...suggestions[1], applied: 'skipped' },
      { ...suggestions[2], applied: 'skipped' },
    ];
    rerender(
      <InstructionEditCard
        messageId="msg-1"
        suggestions={onePending}
        busy={false}
        onApply={vi.fn()}
        onSkip={vi.fn()}
        onApplyAll={vi.fn()}
      />,
    );
    expect(screen.getByTestId('office-ai-audit-apply-all')).toBeTruthy();

    // R25: nothing pending left — apply-all disappears.
    rerender(
      <InstructionEditCard
        messageId="msg-1"
        suggestions={suggestions.map((suggestion) => ({
          ...suggestion,
          applied: 'applied' as const,
        }))}
        busy={false}
        onApply={vi.fn()}
        onSkip={vi.fn()}
        onApplyAll={vi.fn()}
      />,
    );
    expect(screen.queryByTestId('office-ai-audit-apply-all')).toBeNull();
  });

  it('disables apply-all while busy', () => {
    const allPending = suggestions.map((suggestion) => ({
      ...suggestion,
      applied: 'pending' as const,
    }));
    renderCard({ suggestions: allPending, busy: true });
    expect((screen.getByTestId('office-ai-audit-apply-all') as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it('does not render apply-all when onApplyAll is not provided', () => {
    const allPending = suggestions.map((suggestion) => ({
      ...suggestion,
      applied: 'pending' as const,
    }));
    renderCard({ suggestions: allPending, onApplyAll: undefined });
    expect(screen.queryByTestId('office-ai-audit-apply-all')).toBeNull();
  });
});
