import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { RightPanel } from '../RightPanel';

const mocks = vi.hoisted(() => ({
  wikiState: {
    selectedFile: null as string | null,
    fileContent: '',
    project: { id: 'p', name: 'P', path: '/proj' },
  },
  researchState: { panelOpen: true, setPanelOpen: vi.fn() },
  getPreference: vi.fn(),
}));

vi.mock('../../../entities/wiki/store', () => ({
  useWikiStore: (select: (s: typeof mocks.wikiState) => unknown) => select(mocks.wikiState),
}));
vi.mock('../../../entities/wiki/research-store', () => {
  const hook = (select: (s: typeof mocks.researchState) => unknown) => select(mocks.researchState);
  hook.getState = () => mocks.researchState;
  return { useResearchStore: hook };
});
vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: { modelSelections: { chatModel: { modelId: 'model' } }, endpoints: [] },
  }),
}));
vi.mock('../../../entities/setting/types', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../entities/setting/types')>();
  return {
    ...actual,
    resolveEndpoint: () => ({ baseUrl: 'https://example.test', apiKey: 'k' }),
  };
});
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: { getPreference: mocks.getPreference },
}));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.researchState.panelOpen = true;
});

it('mounts Deep Research when a Tavily key is configured', async () => {
  mocks.getPreference.mockResolvedValue(JSON.stringify({ tavily_key: 'tvly-x' }));

  render(<RightPanel />);

  expect(await screen.findByText(/Deep Research/)).toBeInTheDocument();
  expect(screen.queryByText(/配置 Tavily API Key/)).not.toBeInTheDocument();

  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AI agents' } });
  expect(screen.getByRole('button', { name: '开始研究' })).toBeEnabled();
});

it('disables research and explains how to configure the key when missing', async () => {
  mocks.getPreference.mockResolvedValue(JSON.stringify({ tavily_key: '' }));

  render(<RightPanel />);

  expect(await screen.findByText(/配置 Tavily API Key/)).toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'AI agents' } });
  expect(screen.getByRole('button', { name: '开始研究' })).toBeDisabled();
});
