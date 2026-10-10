import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../shared/lib/i18n';
import { PageHeader } from '../../shared/ui/PageHeader';
import { Orchestration } from '../Orchestration';
import { Projects } from '../Projects';

vi.mock('../../widgets/orchestration/LaneBoard', () => ({
  LaneBoard: () => <div data-testid="lane-board-stub" />,
}));

vi.mock('../../features/orchestration/orchestrationClient', () => ({
  orchestrationClient: {
    createLane: vi.fn(),
  },
}));

describe('PageHeader 48px shell parity across secondary pages', () => {
  it('renders unified h-12 PageHeader on Orchestration page with title, subtitle, and create form', () => {
    render(
      <I18nProvider>
        <Orchestration />
      </I18nProvider>,
    );
    const header = screen.getByTestId('page-header');
    expect(header.className).toContain('h-12');
    expect(screen.getByTestId('orch-plan')).toBeTruthy();
    expect(screen.getByTestId('orch-submit')).toBeTruthy();
  });

  it('renders unified h-12 PageHeader on Projects page with title and subtitle', () => {
    render(
      <MemoryRouter>
        <I18nProvider>
          <Projects />
        </I18nProvider>
      </MemoryRouter>,
    );
    const header = screen.getByTestId('page-header');
    expect(header.className).toContain('h-12');
    expect(screen.getByTestId('project-workbench')).toBeTruthy();
  });

  it('supports custom testId override while preserving h-12 height and border-b shell', () => {
    render(
      <PageHeader
        title="模型目录"
        subtitle="128 款模型"
        testId="model-catalog-header"
        actions={<button type="button">刷新</button>}
      />,
    );
    const header = screen.getByTestId('model-catalog-header');
    expect(header.className).toContain('h-12');
    expect(header.className).toContain('border-b');
    expect(header.textContent).toContain('模型目录');
    expect(header.textContent).toContain('128 款模型');
  });
});
