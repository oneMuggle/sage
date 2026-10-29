import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useWikiStore } from '../../../entities/wiki/store';
import { I18nProvider } from '../../../shared/lib/i18n';
import type { FileNode } from '../../../shared/types/wiki';
import { WikiFileTree } from '../WikiFileTree';

const api = vi.hoisted(() => ({
  listDirectory: vi.fn(),
  readFile: vi.fn(),
  writeFile: vi.fn(),
  deleteFile: vi.fn(),
  renameFile: vi.fn(),
  graph: vi.fn(),
  confirmDialog: vi.fn(),
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../shared/api-client/wiki', () => ({
  wikiListDirectory: api.listDirectory,
  wikiReadFile: api.readFile,
  wikiWriteFile: api.writeFile,
  wikiDeleteFile: api.deleteFile,
  wikiRenameFile: api.renameFile,
  getWikiGraph: api.graph,
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: api.confirmDialog,
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: api.copyToClipboard,
}));

const tree: FileNode[] = [
  {
    name: 'guide',
    path: 'guide',
    is_dir: true,
    children: [{ name: 'setup.md', path: 'guide/setup.md', is_dir: false }],
  },
  { name: 'index.md', path: 'index.md', is_dir: false },
];

function node(path: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-path="${path}"]`);
  if (!el) throw new Error(`missing node ${path}`);
  return el;
}

function renderTree() {
  return render(
    <I18nProvider defaultLocale="zh">
      <WikiFileTree />
    </I18nProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listDirectory.mockResolvedValue(tree);
  useWikiStore.setState({
    project: { id: 'p-1', name: 'Wiki', path: '/tmp/wiki' },
    fileTree: tree,
    selectedFile: null,
    fileContent: '',
    isLoading: false,
    error: null,
  });
});

describe('WikiFileTree — context menu', () => {
  it('shows file actions and copies the path', async () => {
    renderTree();

    fireEvent.contextMenu(node('index.md'), { clientX: 4, clientY: 4 });

    expect(await screen.findByRole('menuitem', { name: '打开' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: '重命名' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('menuitem', { name: '复制路径' }));
    expect(api.copyToClipboard).toHaveBeenCalledWith('index.md', expect.any(Object));
  });

  it('shows new-file action on directories and creates a markdown file inline', async () => {
    api.writeFile.mockResolvedValueOnce(undefined);
    renderTree();

    fireEvent.contextMenu(node('guide'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '新建文件' }));

    const input = screen.getByTestId('wiki-new-file-input');
    fireEvent.change(input, { target: { value: 'install' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(api.writeFile).toHaveBeenCalledWith('guide/install.md', '# install\n\n', '/tmp/wiki'),
    );
  });

  it('renames a file inline', async () => {
    api.renameFile.mockResolvedValueOnce(undefined);
    renderTree();

    fireEvent.contextMenu(node('index.md'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '重命名' }));

    const input = screen.getByTestId('wiki-rename-input');
    fireEvent.change(input, { target: { value: 'home.md' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(api.renameFile).toHaveBeenCalledWith('index.md', 'home.md', '/tmp/wiki'),
    );
  });

  it('deletes only after the confirmation dialog resolves true', async () => {
    api.deleteFile.mockResolvedValueOnce(undefined);
    api.confirmDialog.mockResolvedValueOnce(false);
    renderTree();

    fireEvent.contextMenu(node('index.md'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除…' }));

    await waitFor(() => expect(api.confirmDialog).toHaveBeenCalledTimes(1));
    expect(api.deleteFile).not.toHaveBeenCalled();

    api.confirmDialog.mockResolvedValueOnce(true);
    fireEvent.contextMenu(node('index.md'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '删除…' }));

    await waitFor(() => expect(api.deleteFile).toHaveBeenCalledWith('index.md', '/tmp/wiki'));
  });
});
