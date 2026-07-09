import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { WikiProjectPicker } from '../WikiProjectPicker';

const mockSelectDirectory = vi.fn();
const mockCheckWikiProject = vi.fn();
const mockGetRecent = vi.fn();
const mockRecordRecent = vi.fn();
const mockCreate = vi.fn();
const mockOpen = vi.fn();
const mockListDir = vi.fn();

vi.mock('../../../shared/api-client/wiki', () => ({
  checkWikiProject: (...a: unknown[]) => mockCheckWikiProject(...a),
  getRecentWikiProjects: () => mockGetRecent(),
  recordRecentWikiProject: (...a: unknown[]) => mockRecordRecent(...a),
  createWikiProject: (...a: unknown[]) => mockCreate(...a),
  openWikiProject: (...a: unknown[]) => mockOpen(...a),
  wikiListDirectory: (...a: unknown[]) => mockListDir(...a),
}));

beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { window: { electronAPI: unknown } }).window.electronAPI = {
    selectDirectory: mockSelectDirectory,
  };
});

// Helper: enter create mode (the existing component starts at 'menu' state).
async function enterCreateMode() {
  const createMenuBtn = await screen.findByRole('button', { name: /创建新项目/ });
  fireEvent.click(createMenuBtn);
}

describe('WikiProjectPicker — recent projects default', () => {
  it('fetches recent projects on mount', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await waitFor(() => expect(mockGetRecent).toHaveBeenCalled());
  });

  it('uses parent of most recent project as defaultPath', async () => {
    mockGetRecent.mockResolvedValue([
      { path: '/tmp/projects/foo/wiki', name: 'foo', opened_at: 1, intent: 'open' },
    ]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    mockSelectDirectory.mockResolvedValue('/tmp/projects/foo/wiki');
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      expect(mockSelectDirectory).toHaveBeenCalledWith(
        expect.objectContaining({ defaultPath: expect.stringContaining('projects') }),
      );
    });
  });

  it('passes undefined defaultPath when no recent projects', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });
    fireEvent.click(browseBtn);
    await waitFor(() => {
      const call = mockSelectDirectory.mock.calls[0]?.[0];
      expect(call?.defaultPath).toBeUndefined();
    });
  });
});

describe('WikiProjectPicker — debounced check', () => {
  it('debounces check calls to 300ms', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    // The path input is the second text input in create mode (after the name input).
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    // The storage-path input is the one whose placeholder contains "wiki-projects" (the brief's hint).
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    expect(pathInput).toBeTruthy();
    fireEvent.change(pathInput, { target: { value: '/tmp/a' } });
    fireEvent.change(pathInput, { target: { value: '/tmp/ab' } });
    fireEvent.change(pathInput, { target: { value: '/tmp/abc' } });
    expect(mockCheckWikiProject).not.toHaveBeenCalled();
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalledTimes(1), { timeout: 1500 });
    expect(mockCheckWikiProject).toHaveBeenCalledWith('/tmp/abc', expect.any(String));
  });
});

describe('WikiProjectPicker — submit guard', () => {
  it('disables create button when checkStatus is error', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: false,
      warning: null,
      error: '父目录不可写',
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/x' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    // The submit button is the primary one in the form; the existing component
    // uses "创建项目" / "打开项目" as labels. Match by the wider regex the brief
    // specified.
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    await waitFor(() => expect(createBtn).toBeDisabled());
  });

  it('enables create button when checkStatus is ok and path is non-empty', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/new' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    await waitFor(() => expect(createBtn).not.toBeDisabled());
  });
});

describe('WikiProjectPicker — Browse button', () => {
  it('calls selectDirectory and fills input on non-null result; preserves on null', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const browseBtn = await screen.findByRole('button', { name: /浏览|browse/i });

    mockSelectDirectory.mockResolvedValueOnce(null);
    fireEvent.click(browseBtn);
    await waitFor(() => expect(mockSelectDirectory).toHaveBeenCalled());
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    expect(pathInput.value).toBe('');

    mockSelectDirectory.mockResolvedValueOnce('/tmp/picked');
    fireEvent.click(browseBtn);
    await waitFor(() => expect(pathInput.value).toBe('/tmp/picked'));
  });
});

describe('WikiProjectPicker — record on success', () => {
  it('records recent project after successful create', async () => {
    mockGetRecent.mockResolvedValue([]);
    mockCheckWikiProject.mockResolvedValue({
      exists: false,
      writable: false,
      is_project: false,
      parent_writable: true,
      warning: null,
      error: null,
    });
    mockCreate.mockResolvedValue({
      id: 'p1',
      name: 'demo',
      path: '/tmp/demo',
      created_at: 1,
      has_content: false,
    });
    mockListDir.mockResolvedValue({ entries: [] });
    mockRecordRecent.mockResolvedValue(undefined);

    render(<WikiProjectPicker />);
    await enterCreateMode();
    // Fill the name input first (existing component requires it).
    const nameInput = (await screen.findByPlaceholderText(/我的|名称|name/i)) as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'demo' } });
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;
    fireEvent.change(pathInput, { target: { value: '/tmp/demo' } });
    await waitFor(() => expect(mockCheckWikiProject).toHaveBeenCalled());
    const createBtn = await screen.findByRole('button', { name: /创建项目|创建|create/i });
    fireEvent.click(createBtn);
    await waitFor(() =>
      expect(mockRecordRecent).toHaveBeenCalledWith(
        expect.objectContaining({ path: '/tmp/demo', intent: 'create' }),
      ),
    );
  });
});

describe('WikiProjectPicker — status badge states', () => {
  it('renders green check for ok status and red X for error', async () => {
    mockGetRecent.mockResolvedValue([]);
    render(<WikiProjectPicker />);
    await enterCreateMode();
    const inputs = await screen.findAllByPlaceholderText(/wiki-projects|project|路径/i);
    const pathInput = inputs.find((el) =>
      /wiki-projects|存储路径|项目路径/i.test(el.getAttribute('placeholder') ?? ''),
    ) as HTMLInputElement;

    // Use mockImplementation so the response can be controlled per-path
    // (mockResolvedValueOnce is fragile here because the first call may not
    // happen if the debounce timer is canceled by a quick re-input).
    mockCheckWikiProject.mockImplementation(async (p: string) => {
      if (p === '/tmp/ok') {
        return {
          exists: false,
          writable: false,
          is_project: false,
          parent_writable: true,
          warning: null,
          error: null,
        };
      }
      return {
        exists: false,
        writable: false,
        is_project: false,
        parent_writable: false,
        warning: null,
        error: '父目录不可写',
      };
    });

    fireEvent.change(pathInput, { target: { value: '/tmp/ok' } });
    await waitFor(() => expect(screen.queryByText(/可创建|有效的|valid/i)).toBeTruthy());

    fireEvent.change(pathInput, { target: { value: '/tmp/bad' } });
    await waitFor(() => expect(screen.queryByText(/父目录不可写/i)).toBeTruthy());
  });
});
