// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { PlaybookClassificationPanel } from '../PlaybookClassificationPanel';
import { PlaybookSpecEditor } from '../PlaybookSpecEditor';

describe('playbook i18n (en)', () => {
  it('classifications render English copy under an English provider', () => {
    render(
      <I18nProvider defaultLocale="en">
        <PlaybookClassificationPanel
          classification={[
            {
              from: '开题报告.md',
              to: '01_开题/开题报告.md',
              artifact_id: 'proposal_report',
              label: '开题报告',
              stage_id: 'proposal',
              reason: 'reason',
            },
          ]}
          unclassified={[
            {
              path: '论文初稿.docx',
              suggested_to: '03_成果/论文初稿.docx',
              confidence: 0.83,
              reason: 'reason',
            },
          ]}
          undoAvailable={{ at: 1793500000000, count: 2 }}
          busy={null}
          onAction={vi.fn()}
          onBatchMove={vi.fn()}
          onUndo={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.getByText('Classification suggestions (confirm each)')).toBeInTheDocument();
    expect(screen.getByText('Unknown files (suggested classification)')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Move selected (0)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo last batch move \(2\)/ })).toBeInTheDocument();
  });

  it('editor accessible names are translated', () => {
    render(
      <I18nProvider defaultLocale="en">
        <PlaybookSpecEditor
          spec={
            {
              id: 'p',
              name: 'Playbook',
              description: '',
              stages: [
                {
                  id: 's1',
                  label: 'Stage',
                  order: 1,
                  objective: '',
                  artifacts: [],
                  exit_criteria: [],
                  rules: [],
                  recommended_milestones: [],
                },
              ],
              directory_layout: [],
              global_rules: [],
              todos: [],
              ai_guidance: {},
              meta: {},
              applies_to: { project_types: [], sub_types: [] },
              schema_version: '1.0',
            } as never
          }
          saving={false}
          error={null}
          onSave={vi.fn()}
          onCancel={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.getByRole('group', { name: 'Stage 1' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Stage 1 name' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add artifact' })).toBeInTheDocument();
  });
});
