/**
 * SkillDraftDetail — TDD scaffold (PR-3 of skill-draft-ux-closure).
 *
 * The component lives at `../SkillDraftDetail` (does NOT exist yet — this
 * file is the RED phase). Behavior contracts covered here:
 *
 *   - Renders draft name + trigger_type badge
 *   - Renders description + when_to_use
 *   - Renders full SKILL.md content via MarkdownPreview
 *   - Approve / Reject / Cancel buttons fire onApprove/onReject/onClose
 *   - Renders nothing when `draft === null`
 *
 * The plan's original snippet used a non-existent Dialog API; we target
 * behavior with `screen.getByRole` / `getByText` / `getByTestId` queries
 * that don't depend on Radix internals, so the assertions stay valid
 * regardless of the actual Dialog wrapper shape (see ledger ruling on
 * the Radix-style `Dialog / DialogContent / DialogTitle` API).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SkillDraft } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import SkillDraftDetail from '../SkillDraftDetail';

// --------------- mocks --------------- //
//
// `MarkdownPreview` renders `react-markdown`, which is heavyweight and
// pulls in remark/rehype internals we don't need for these behavior
// tests. Replace it with a thin stand-in that exposes the raw markdown
// so we can assert the content reaches the preview, and add a testid
// so tests can target it without relying on its DOM structure.
vi.mock('../../wiki/MarkdownPreview', () => ({
  default: ({ content }: { content: string }) => (
    <div data-testid="markdown-preview">{content}</div>
  ),
}));

// --------------- helpers --------------- //

const makeDraft = (overrides: Partial<SkillDraft> = {}): SkillDraft => ({
  id: 'draft-1',
  name: 'test-skill',
  description: 'test description',
  when_to_use: 'when testing the skill',
  content:
    '# Test Skill\n\n## 步骤\n\n1. Step 1\n\n## 触发条件\n\nWhen testing\n\n## 示例\n\nExample',
  trigger_type: 'complex_turn',
  source_session_id: 'session-abc',
  source_context: {},
  status: 'pending',
  created_at: 1700000000000,
  ...overrides,
});

function renderDetail(
  draft: SkillDraft | null,
  onApprove = vi.fn(),
  onReject = vi.fn(),
  onClose = vi.fn(),
) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SkillDraftDetail
        draft={draft}
        onApprove={onApprove}
        onReject={onReject}
        onClose={onClose}
      />
    </I18nProvider>,
  );
}

// --------------- tests --------------- //

describe('SkillDraftDetail component', () => {
  it('renders draft name + trigger_type badge', () => {
    const draft = makeDraft();
    renderDetail(draft);

    expect(screen.getByText('test-skill')).toBeInTheDocument();
    expect(screen.getByText('complex_turn')).toBeInTheDocument();
  });

  it('renders description + when_to_use', () => {
    const draft = makeDraft();
    renderDetail(draft);

    expect(screen.getByText('test description')).toBeInTheDocument();
    expect(screen.getByText(/when testing the skill/)).toBeInTheDocument();
  });

  it('renders markdown content via MarkdownPreview', () => {
    const draft = makeDraft();
    renderDetail(draft);

    // The mock exposes the raw markdown so we can verify the component
    // forwards `draft.content` to the preview component unchanged.
    const preview = screen.getByTestId('markdown-preview');
    expect(preview).toBeInTheDocument();
    expect(preview.textContent).toBe(draft.content);
    expect(screen.getByText(/# Test Skill/)).toBeInTheDocument();
  });

  it('calls onApprove + onClose when Approve button clicked', () => {
    const draft = makeDraft();
    const onApprove = vi.fn();
    const onClose = vi.fn();
    renderDetail(draft, onApprove, vi.fn(), onClose);

    const approveBtn = screen.getByRole('button', { name: /批准/i });
    fireEvent.click(approveBtn);

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onApprove).toHaveBeenCalledWith(draft);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onReject + onClose when Reject button clicked', () => {
    const draft = makeDraft();
    const onReject = vi.fn();
    const onClose = vi.fn();
    renderDetail(draft, vi.fn(), onReject, onClose);

    const rejectBtn = screen.getByRole('button', { name: /拒绝/i });
    fireEvent.click(rejectBtn);

    expect(onReject).toHaveBeenCalledTimes(1);
    expect(onReject).toHaveBeenCalledWith(draft);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Cancel button clicked', () => {
    const draft = makeDraft();
    const onClose = vi.fn();
    renderDetail(draft, vi.fn(), vi.fn(), onClose);

    const cancelBtn = screen.getByRole('button', { name: /取消/i });
    fireEvent.click(cancelBtn);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('does not render draft content when draft is null', () => {
    renderDetail(null);

    expect(screen.queryByText('test-skill')).toBeNull();
    expect(screen.queryByText('test description')).toBeNull();
    expect(screen.queryByTestId('markdown-preview')).toBeNull();
  });
});