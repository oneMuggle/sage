import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDesignStore } from '../../../entities/design/designStore';
import { DesignTweaksPanel } from '../DesignTweaksPanel';

vi.mock('../../../shared/lib/i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe('DesignTweaksPanel', () => {
  const updateTweaksLocal = vi.fn();
  const persistTweaks = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    updateTweaksLocal.mockClear();
    persistTweaks.mockClear();
    useDesignStore.setState({
      tweaks: {},
      systems: [
        {
          id: 'minimal',
          name: 'Minimal',
          description: '',
          category: 'general',
          tokens_css:
            ':root{--color-accent:#1a56db;--border-radius:4px;' +
            '--font-size-base:16px;--space-4:16px;}',
          design_md: '',
        },
      ],
      currentProject: {
        id: 'p1',
        name: 'P',
        kind: 'deck',
        system_id: 'minimal',
        template_id: 't',
        brief: '',
        status: 'complete',
        created_at: '2026-11-20T00:00:00Z',
        updated_at: '2026-11-20T00:00:00Z',
      },
      updateTweaksLocal,
      persistTweaks,
    } as never);
  });

  it('renders control values from the design system tokens', () => {
    render(<DesignTweaksPanel projectId="p1" />);
    expect(screen.getByLabelText('design.tweaks.accent')).toHaveValue('#1a56db');
    expect((screen.getByLabelText('design.tweaks.radius') as HTMLInputElement).value).toBe('4');
  });

  it('updates local tweaks when the accent changes', () => {
    render(<DesignTweaksPanel projectId="p1" />);
    fireEvent.change(screen.getByLabelText('design.tweaks.accent'), {
      target: { value: '#ff0000' },
    });
    expect(updateTweaksLocal).toHaveBeenCalledWith({ accent: '#ff0000' });
  });

  it('reset clears all overrides', () => {
    render(<DesignTweaksPanel projectId="p1" />);
    fireEvent.click(screen.getByRole('button', { name: 'design.tweaks.reset' }));
    expect(updateTweaksLocal).toHaveBeenCalledWith({
      accent: null,
      radius: null,
      font_size: null,
      density: null,
    });
  });
});
