/**
 * entities/wiki/store 测试
 *
 * 验证 Zustand store 的核心 action：
 *   - setProject 重置文件树/选中/内容
 *   - loadFileTree 成功 / 无 project no-op / 错误时写 error
 *   - openFile 写入 fileContent
 *   - saveFile 调用 wikiWriteFile + reload tree
 *   - deleteFile 清空选中文件 + 触发 tree reload
 *   - 各 setter 工作正常
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { FileNode, WikiProject } from '../../../shared/types/wiki';
import { useWikiStore } from '../store';

// Mock api-client：useWikiStore 通过这层访问 invoke
const listDir = vi.fn();
const readFile = vi.fn();
const writeFile = vi.fn();
const deleteFile = vi.fn();

// vi.mock 被 hoist 到 import 之上，因此即使 useWikiStore 已在顶部 import，
// 它持有的 wiki api-client 引用仍指向下面的 mock。
vi.mock('../../../shared/api-client/wiki', () => ({
  wikiListDirectory: (...args: unknown[]) => listDir(...args),
  wikiReadFile: (...args: unknown[]) => readFile(...args),
  wikiWriteFile: (...args: unknown[]) => writeFile(...args),
  wikiDeleteFile: (...args: unknown[]) => deleteFile(...args),
}));

const fakeProject: WikiProject = {
  id: 'p1',
  path: '/tmp/wiki',
  name: 'test-wiki',
};

const fakeTree: FileNode[] = [{ name: 'a.md', path: 'a.md', is_dir: false }];

beforeEach(() => {
  listDir.mockReset();
  readFile.mockReset();
  writeFile.mockReset();
  deleteFile.mockReset();
  useWikiStore.setState({
    project: null,
    fileTree: [],
    selectedFile: null,
    fileContent: '',
    activeView: 'browser',
    isLoading: false,
    error: null,
  });
});

describe('useWikiStore', () => {
  it('setProject resets file tree and selection', () => {
    useWikiStore.setState({
      fileTree: fakeTree,
      selectedFile: 'a.md',
      fileContent: 'hello',
    });
    useWikiStore.getState().setProject(fakeProject);
    const s = useWikiStore.getState();
    expect(s.project).toEqual(fakeProject);
    expect(s.fileTree).toEqual([]);
    expect(s.selectedFile).toBeNull();
    expect(s.fileContent).toBe('');
  });

  it('loadFileTree no-ops when project is null', async () => {
    await useWikiStore.getState().loadFileTree();
    expect(listDir).not.toHaveBeenCalled();
  });

  it('loadFileTree populates tree when project is set', async () => {
    listDir.mockResolvedValueOnce(fakeTree);
    useWikiStore.setState({ project: fakeProject });

    await useWikiStore.getState().loadFileTree();

    expect(listDir).toHaveBeenCalledWith('', '/tmp/wiki');
    expect(useWikiStore.getState().fileTree).toEqual(fakeTree);
    expect(useWikiStore.getState().isLoading).toBe(false);
  });

  it('openFile sets selectedFile + fileContent', async () => {
    readFile.mockResolvedValueOnce('file body');
    useWikiStore.setState({ project: fakeProject });

    await useWikiStore.getState().openFile('a.md');

    expect(readFile).toHaveBeenCalledWith('a.md', '/tmp/wiki');
    expect(useWikiStore.getState().selectedFile).toBe('a.md');
    expect(useWikiStore.getState().fileContent).toBe('file body');
  });

  it('saveFile writes then refreshes the tree', async () => {
    writeFile.mockResolvedValueOnce(undefined);
    listDir.mockResolvedValueOnce(fakeTree);
    useWikiStore.setState({ project: fakeProject });

    await useWikiStore.getState().saveFile('a.md', 'updated');

    expect(writeFile).toHaveBeenCalledWith('a.md', 'updated', '/tmp/wiki');
    expect(listDir).toHaveBeenCalledTimes(1);
    expect(useWikiStore.getState().fileContent).toBe('updated');
  });

  it('deleteFile clears selectedFile when deleting the active file', async () => {
    deleteFile.mockResolvedValueOnce(undefined);
    listDir.mockResolvedValueOnce([]);
    useWikiStore.setState({
      project: fakeProject,
      selectedFile: 'a.md',
      fileContent: 'something',
    });

    await useWikiStore.getState().deleteFile('a.md');

    expect(deleteFile).toHaveBeenCalledWith('a.md', '/tmp/wiki');
    expect(useWikiStore.getState().selectedFile).toBeNull();
    expect(useWikiStore.getState().fileContent).toBe('');
  });

  it('loadFileTree records error message on failure', async () => {
    listDir.mockRejectedValueOnce(new Error('disk gone'));
    useWikiStore.setState({ project: fakeProject });

    await useWikiStore.getState().loadFileTree();

    expect(useWikiStore.getState().error).toMatch(/加载文件树失败/);
    expect(useWikiStore.getState().isLoading).toBe(false);
  });

  it('setters mutate the right slice', () => {
    const s = useWikiStore.getState();
    s.setSelectedFile('b.md');
    expect(useWikiStore.getState().selectedFile).toBe('b.md');

    s.setFileContent('xyz');
    expect(useWikiStore.getState().fileContent).toBe('xyz');

    s.setActiveView('search');
    expect(useWikiStore.getState().activeView).toBe('search');

    s.setLoading(true);
    expect(useWikiStore.getState().isLoading).toBe(true);

    s.setError('oops');
    expect(useWikiStore.getState().error).toBe('oops');
  });
});
