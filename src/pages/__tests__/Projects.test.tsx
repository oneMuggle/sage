import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../shared/lib/i18n', () => ({ useI18n: () => ({ locale: 'en' }) }));
const { props } = vi.hoisted(() => ({ props: vi.fn() }));
vi.mock('../../widgets/sidebar/sections/ProjectSection', () => ({
  ProjectSection: (value: unknown) => {
    props(value);
    return <div data-testid="projects-existing-api-view" />;
  },
}));
import { Projects } from '../Projects';
describe('project workbench', () => {
  it('uses the existing project view with a spacious presentation', () => {
    render(
      <MemoryRouter>
        <Projects />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('project-workbench')).toBeInTheDocument();
    expect(props).toHaveBeenCalledWith(
      expect.objectContaining({ presentation: 'workbench', collapsed: false }),
    );
    expect(screen.getByText(/folder binding still controls file access/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'New deliverable' }));
  });
});
