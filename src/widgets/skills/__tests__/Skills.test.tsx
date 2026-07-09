/**
 * Skills page — Rescan + Import icon buttons (PR-C / Task 6).
 *
 * Verifies the two new header buttons call the right APIs and surface
 * success / skipped / error toasts.
 *
 * The Electron bridge is exposed under the **nested** namespace
 * `window.electronAPI.skills.*` (not flat `window.electronAPI.*`).
 * See `electron/preload.ts:90-96` and Task 4 IPC bridge.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Toaster } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Skills from '../../../pages/Skills';
import { skillsApi } from '../../../shared/api';

// ---- Mock the skillsApi module ------------------------------------------
vi.mock('../../../shared/api', () => ({
  skillsApi: {
    list: vi.fn(),
    rescan: vi.fn(),
    importFiles: vi.fn(),
  },
}));

// ---- Mock the Electron IPC bridge (nested under `skills`) ---------------
// Preserve jsdom's real `window` (which React DOM uses for
// getActiveElementDeep) and just attach electronAPI onto it.
const mockElectronAPI = {
  skills: {
    pickSkillFiles: vi.fn(),
    rescanSkills: vi.fn(),
    importSkills: vi.fn(),
  },
};
Object.defineProperty(globalThis.window, 'electronAPI', {
  value: mockElectronAPI,
  writable: true,
  configurable: true,
});

/** Match sonner toast text — sonner wraps text in nested spans, so we
 *  query the [data-sonner-toast] root directly and substring-match
 *  its textContent. Returns the matching root element. */
const findToastByText = (regex: RegExp): HTMLElement => {
  const roots = Array.from(document.querySelectorAll<HTMLElement>('[data-sonner-toast]'));
  const match = roots.find((el) => regex.test(el.textContent ?? ''));
  if (!match) throw new Error(`No toast matching ${regex}`);
  return match;
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(skillsApi.list).mockResolvedValue([]);
  // default pickSkillFiles → no selection (cancel path)
  mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(null);
});

const renderWithToast = () =>
  render(
    <>
      <Skills />
      <Toaster />
    </>,
  );

describe('Skills page — Rescan + Import buttons', () => {
  it('renders rescan and import buttons in the header', async () => {
    renderWithToast();
    await waitFor(() => {
      expect(screen.getByLabelText('刷新技能列表')).toBeInTheDocument();
      expect(screen.getByLabelText('重扫磁盘')).toBeInTheDocument();
      expect(screen.getByLabelText('导入 SKILL.md')).toBeInTheDocument();
    });
  });

  it('rescan button click calls skillsApi.rescan', async () => {
    vi.mocked(skillsApi.rescan).mockResolvedValue({
      loaded: [{ name: 'new', source: 'skillmd', path: '/p/new/SKILL.md' }],
      skipped: [],
      total_loaded: 1,
    });
    renderWithToast();
    await waitFor(() => screen.getByLabelText('重扫磁盘'));
    fireEvent.click(screen.getByLabelText('重扫磁盘'));
    await waitFor(() => {
      expect(skillsApi.rescan).toHaveBeenCalledTimes(1);
    });
  });

  it('import button opens dialog via electronAPI.skills.pickSkillFiles', async () => {
    mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(['/path/a.md']);
    vi.mocked(skillsApi.importFiles).mockResolvedValue({
      imported: [{ name: 'a', path: '/p/a/SKILL.md' }],
      skipped: [],
    });
    renderWithToast();
    await waitFor(() => screen.getByLabelText('导入 SKILL.md'));
    fireEvent.click(screen.getByLabelText('导入 SKILL.md'));
    await waitFor(() => {
      expect(mockElectronAPI.skills.pickSkillFiles).toHaveBeenCalledTimes(1);
      expect(skillsApi.importFiles).toHaveBeenCalledWith(['/path/a.md']);
    });
  });

  it('import success shows success toast', async () => {
    mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(['/path/a.md']);
    vi.mocked(skillsApi.importFiles).mockResolvedValue({
      imported: [{ name: 'a', path: '/p/a/SKILL.md' }],
      skipped: [],
    });
    renderWithToast();
    await waitFor(() => screen.getByLabelText('导入 SKILL.md'));
    fireEvent.click(screen.getByLabelText('导入 SKILL.md'));
    await waitFor(() => {
      expect(findToastByText(/已导入 1 个技能/)).toBeInTheDocument();
    });
  });

  it('import with skipped shows warn toast', async () => {
    mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(['/path/a.md', '/path/b.md']);
    vi.mocked(skillsApi.importFiles).mockResolvedValue({
      imported: [{ name: 'a', path: '/p/a/SKILL.md' }],
      skipped: [{ name: 'coder', reason: 'builtin_conflict' }],
    });
    renderWithToast();
    await waitFor(() => screen.getByLabelText('导入 SKILL.md'));
    fireEvent.click(screen.getByLabelText('导入 SKILL.md'));
    await waitFor(() => {
      expect(findToastByText(/跳过 1 个/)).toBeInTheDocument();
    });
  });

  it('import error shows error toast', async () => {
    mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(['/path/a.md']);
    vi.mocked(skillsApi.importFiles).mockRejectedValue(new Error('no_skills_dir: cannot create'));
    renderWithToast();
    await waitFor(() => screen.getByLabelText('导入 SKILL.md'));
    fireEvent.click(screen.getByLabelText('导入 SKILL.md'));
    await waitFor(() => {
      expect(findToastByText(/导入失败/)).toBeInTheDocument();
    });
  });

  it('rescan loading state disables the rescan button', async () => {
    let resolveRescan!: (v: Awaited<ReturnType<typeof skillsApi.rescan>>) => void;
    vi.mocked(skillsApi.rescan).mockReturnValue(
      new Promise((resolve) => {
        resolveRescan = resolve;
      }) as ReturnType<typeof skillsApi.rescan>,
    );
    renderWithToast();
    await waitFor(() => screen.getByLabelText('重扫磁盘'));
    fireEvent.click(screen.getByLabelText('重扫磁盘'));
    await waitFor(() => {
      const btn = screen.getByLabelText('重扫磁盘') as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
    });
    resolveRescan({ loaded: [], skipped: [], total_loaded: 0 });
  });

  it('import loading state disables the import button', async () => {
    let resolveImport!: (v: Awaited<ReturnType<typeof skillsApi.importFiles>>) => void;
    mockElectronAPI.skills.pickSkillFiles.mockResolvedValue(['/path/a.md']);
    vi.mocked(skillsApi.importFiles).mockReturnValue(
      new Promise((resolve) => {
        resolveImport = resolve;
      }) as ReturnType<typeof skillsApi.importFiles>,
    );
    renderWithToast();
    await waitFor(() => screen.getByLabelText('导入 SKILL.md'));
    fireEvent.click(screen.getByLabelText('导入 SKILL.md'));
    await waitFor(() => {
      const btn = screen.getByLabelText('导入 SKILL.md') as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
    });
    resolveImport({ imported: [], skipped: [] });
  });
});
