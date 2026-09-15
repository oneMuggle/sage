import { beforeEach, expect, it, vi } from 'vitest';

import { locateWikiCitation, wikiChatStream } from '../../api-client/wiki';

const { invoke, request } = vi.hoisted(() => ({ invoke: vi.fn(), request: vi.fn() }));
vi.mock('../desktopInvoke', () => ({ invoke }));
vi.mock('../backendRequest', () => ({ backendRequest: request }));
vi.mock('../demoFlag', () => ({ isDemoMode: () => false }));
beforeEach(() => vi.clearAllMocks());
const base = {
  query: 'test',
  projectPath: '/project',
  llmBaseUrl: '',
  llmApiKey: '',
  llmModel: 'model',
  embedBaseUrl: '',
  embedApiKey: '',
  embedModel: 'embed',
};
it.each([undefined, [], ['wiki/a.md']])(
  'preserves selected source semantics: %j',
  async (selectedPaths) => {
    await wikiChatStream({ ...base, selectedPaths });
    const payload = invoke.mock.calls[0][1];
    if (selectedPaths === undefined) expect(payload).not.toHaveProperty('selected_paths');
    else expect(payload.selected_paths).toEqual(selectedPaths);
  },
);
it('sends citation location coordinates and hash without model credentials', async () => {
  await locateWikiCitation('/project', {
    id: 'S1',
    path: 'wiki/a.md',
    title: 'A',
    excerpt: 'text',
    content_hash: 'hash',
    line_start: 1,
    line_end: 2,
  });
  expect(request).toHaveBeenCalledWith(
    expect.objectContaining({
      body: {
        project_path: '/project',
        path: 'wiki/a.md',
        content_hash: 'hash',
        line_start: 1,
        line_end: 2,
      },
    }),
  );
});
