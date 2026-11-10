import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../features/project-type/StudioMaterialsAndProfilePanels', () => ({
  StudioMaterialsTabPanel: () => <div data-testid="materials-panel" />,
  StudioProfileTabPanel: ({ profileEntries }: { profileEntries: unknown[] }) => (
    <div data-testid="profile-panel">{profileEntries.length}</div>
  ),
}));

import { KnowledgeSection } from '../sections/KnowledgeSection';

const data = {
  project: {
    id: 'p-1',
    path: '/w/sage',
    name: 'Sage',
    vcsMode: 'git',
    allowedPaths: ['/w/shared/**'],
  },
  activeProjectType: 'coding',
  profileEntries: [{ id: 'm-1' }],
  profileCategory: 'convention',
  setProfileCategory: vi.fn(),
  profileDraft: '',
  setProfileDraft: vi.fn(),
  savingProfile: false,
  addProfileEntry: vi.fn(),
  deleteProfileEntry: vi.fn(),
  reload: vi.fn(),
} as never;

function renderSection() {
  return render(
    <MemoryRouter>
      <KnowledgeSection data={data} onStartSession={vi.fn()} />
    </MemoryRouter>,
  );
}

describe('KnowledgeSection', () => {
  it('defaults to the materials sub-tab', () => {
    renderSection();
    expect(screen.getByTestId('materials-panel')).toBeInTheDocument();
  });

  it('keeps git status and wiki generation out of the materials tab', () => {
    renderSection();
    fireEvent.click(screen.getByTestId('governance-knowledge-materials'));
    expect(screen.getByTestId('materials-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('git-widget')).toBeNull();
    expect(screen.queryByTestId('wiki-panel')).toBeNull();
  });

  it('switches to the profile sub-tab', () => {
    renderSection();
    fireEvent.click(screen.getByTestId('governance-knowledge-profile'));
    expect(screen.getByTestId('profile-panel')).toHaveTextContent('1');
  });

  it('no longer exposes a rules sub-tab', () => {
    renderSection();
    expect(screen.queryByTestId('governance-knowledge-rules')).toBeNull();
    expect(screen.getByTestId('governance-knowledge-materials')).toBeInTheDocument();
    expect(screen.getByTestId('governance-knowledge-profile')).toBeInTheDocument();
  });
});
