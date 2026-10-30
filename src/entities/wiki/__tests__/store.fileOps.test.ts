import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useWikiStore } from '../store';

const api = vi.hoisted(() => ({
  listDirectory: vi.fn(),
  readFile: vi.fn(),
  writeFile: vi.fn(),
  deleteFile: vi.fn(),
  renameFile: vi.fn(),
  graph: vi.fn(),
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  wikiListDirectory: api.listDirectory,
  wikiReadFile: api.readFile,
  wikiWriteFile: api.writeFile,
  wikiDeleteFile: api.deleteFile,
  wikiRenameFile: api.renameFile,
  getWikiGraph: api.graph,
}));

const project = { id: 'p-1', name: 'Wiki', path: '/tmp/wiki' };

beforeEach(() => {
  vi.clearAllMocks();
  api.listDirectory.mockResolvedValue([]);
  useWikiStore.setState({
    project,
    fileTree: [],
    selectedFile: null,
    fileContent: '',
    isLoading: false,
    error: null,
  });
});

describe('wiki store — file operations', () => {
  it('createFile writes a markdown stub under the directory and reloads the tree', async () => {
    api.writeFile.mockResolvedValueOnce(undefined);

    await useWikiStore.getState().createFile('guide', 'setup.md');

    expect(api.writeFile).toHaveBeenCalledWith('guide/setup.md', '# setup\n\n', '/tmp/wiki');
    expect(api.listDirectory).toHaveBeenCalledWith('', '/tmp/wiki');
  });

  it('createFile rejects empty names', async () => {
    await expect(useWikiStore.getState().createFile('', '   ')).rejects.toThrow('name required');
    expect(api.writeFile).not.toHaveBeenCalled();
  });

  it('renameFile keeps the directory and follows the selected file', async () => {
    api.renameFile.mockResolvedValueOnce(undefined);
    useWikiStore.setState({ selectedFile: 'guide/setup.md' });

    await useWikiStore.getState().renameFile('guide/setup.md', 'install.md');

    expect(api.renameFile).toHaveBeenCalledWith('guide/setup.md', 'guide/install.md', '/tmp/wiki');
    expect(useWikiStore.getState().selectedFile).toBe('guide/install.md');
  });

  it('renameFile is a no-op when the name is unchanged', async () => {
    await useWikiStore.getState().renameFile('a.md', 'a.md');
    expect(api.renameFile).not.toHaveBeenCalled();
  });

  it('deleteFile clears a selection nested inside a deleted directory', async () => {
    api.deleteFile.mockResolvedValueOnce(undefined);
    useWikiStore.setState({ selectedFile: 'guide/setup.md', fileContent: 'x' });

    await useWikiStore.getState().deleteFile('guide');

    expect(useWikiStore.getState().selectedFile).toBeNull();
    expect(useWikiStore.getState().fileContent).toBe('');
  });

  it('deleteFile surfaces failures to the caller', async () => {
    api.deleteFile.mockRejectedValueOnce(new Error('boom'));

    await expect(useWikiStore.getState().deleteFile('a.md')).rejects.toThrow('boom');
    expect(useWikiStore.getState().error).toMatch(/删除文件失败/);
  });
});
