import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../features/project-type', () => ({
  GovernanceRulesPanel: () => <div data-testid="rules-panel" />,
  GitStatusWidget: () => <div data-testid="git-widget" />,
  WikiGenerationPanel: () => <div data-testid="wiki-panel" />,
}));
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
  newAllowedPath: '',
  setNewAllowedPath: vi.fn(),
  savingPaths: false,
  addAllowedPath: vi.fn(),
  quickAddPresetPath: vi.fn(),
  removeAllowedPath: vi.fn(),
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
  it('defaults to the rules sub-tab', () => {
    renderSection();
    expect(screen.getByTestId('rules-panel')).toBeInTheDocument();
  });

  it('switches to materials and renders git + wiki for git projects', () => {
    renderSection();
    fireEvent.click(screen.getByTestId('governance-knowledge-materials'));
    expect(screen.getByTestId('materials-panel')).toBeInTheDocument();
    expect(screen.getByTestId('git-widget')).toBeInTheDocument();
    expect(screen.getByTestId('wiki-panel')).toBeInTheDocument();
  });

  it('switches to the profile sub-tab', () => {
    renderSection();
    fireEvent.click(screen.getByTestId('governance-knowledge-profile'));
    expect(screen.getByTestId('profile-panel')).toHaveTextContent('1');
  });
});
