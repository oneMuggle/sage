import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as api from '../../../entities/design/designApi';
import { useDesignStore } from '../../../entities/design/designStore';
import { DesignCreateComposer } from '../DesignCreateComposer';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

vi.mock('../../../entities/design/designApi', () => ({
  extractOutline: vi.fn(),
  listOfficeSources: vi.fn(),
}));

describe('DesignCreateComposer', () => {
  beforeEach(() => {
    useDesignStore.setState({
      systems: [
        {
          id: 'minimal',
          name: 'Minimal',
          description: '',
          category: 'general',
          tokens_css: '',
          design_md: '',
        },
      ],
      templates: [
        {
          id: 'pitch-deck',
          name: 'Pitch',
          description: '',
          kind: 'deck',
          skill_md: '',
          assets: {},
        },
        {
          id: 'landing-page',
          name: 'Landing',
          description: '',
          kind: 'prototype',
          skill_md: '',
          assets: {},
        },
      ],
      createProject: vi.fn().mockResolvedValue({ id: 'p1' }),
      generate: vi.fn().mockResolvedValue(undefined),
    } as never);
  });

  it('creates and generates with a single brief (defaults omitted)', async () => {
    const onCreated = vi.fn();
    render(<DesignCreateComposer onCancel={() => {}} onCreated={onCreated} />);

    fireEvent.change(screen.getByLabelText('design.composer.brief'), {
      target: { value: '8 页投资人演示稿' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'design.composer.create' }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('p1'));
    expect(useDesignStore.getState().createProject).toHaveBeenCalledWith({
      name: undefined,
      kind: 'deck',
      system_id: undefined,
      template_id: undefined,
      brief: '8 页投资人演示稿',
    });
    expect(useDesignStore.getState().generate).toHaveBeenCalledWith('p1', '8 页投资人演示稿');
  });

  it('prefills kind and template when a preset chip is chosen', async () => {
    render(<DesignCreateComposer onCancel={() => {}} onCreated={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'design.preset.landing' }));
    fireEvent.change(screen.getByLabelText('design.composer.brief'), {
      target: { value: 'landing page for our SaaS' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'design.composer.create' }));

    await waitFor(() =>
      expect(useDesignStore.getState().createProject).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: 'prototype',
          template_id: 'landing-page',
        }),
      ),
    );
  });

  it('keeps the submit button disabled until a brief is entered', () => {
    render(<DesignCreateComposer onCancel={() => {}} onCreated={() => {}} />);
    expect(screen.getByRole('button', { name: 'design.composer.create' })).toBeDisabled();
  });

  it('imports an outline from a Word document in the office library', async () => {
    vi.mocked(api.listOfficeSources).mockResolvedValue([
      {
        doc_id: 'd1',
        doc_type: 'word',
        original_filename: '年度总结.docx',
        generated_filename: '年度总结.docx',
        created_at: 1760000000000,
        size_bytes: 2048,
      },
    ]);
    vi.mocked(api.extractOutline).mockResolvedValue({
      title: '年度总结',
      source_path: '/workspace/office/word/d1/年度总结.docx',
      slide_count: 3,
      outline_md: '# 第一节\n# 第二节',
    });

    render(<DesignCreateComposer onCancel={() => {}} onCreated={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'design.composer.pickFromLibrary' }));

    await waitFor(() => expect(screen.getByText('年度总结.docx')).toBeTruthy());
    fireEvent.click(screen.getByText('年度总结.docx'));

    await waitFor(() => expect(api.extractOutline).toHaveBeenCalledWith({ doc_id: 'd1' }));
    await waitFor(() =>
      expect(
        (screen.getByLabelText('design.composer.brief') as HTMLTextAreaElement).value,
      ).toContain('# 第一节'),
    );
  });
});
