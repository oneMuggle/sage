// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PlaybookSharePage } from '../PlaybookSharePage';

const resolveShareTokenMock = vi.fn();
const bindMock = vi.fn();
const saveLibraryMock = vi.fn();
const projectListMock = vi.fn();

vi.mock('../../shared/api/playbookApi', () => ({
  playbookApi: {
    resolveShareToken: (...args: unknown[]) => resolveShareTokenMock(...args),
    bind: (...args: unknown[]) => bindMock(...args),
    saveLibrary: (...args: unknown[]) => saveLibraryMock(...args),
  },
}));

vi.mock('../../shared/api/projectApi', () => ({
  projectApi: {
    list: (...args: unknown[]) => projectListMock(...args),
  },
}));

const SPEC = {
  schema_version: '1',
  id: 'pb-1',
  name: '科研课题规程',
  description: '开题—实施—结题',
  applies_to: { project_types: ['research'], sub_types: [] },
  directory_layout: [],
  stages: [
    {
      id: 's1',
      label: '开题',
      order: 1,
      objective: '',
      artifacts: [{ id: 'a1' }],
      exit_criteria: [],
      rules: [],
      recommended_milestones: [],
    },
    {
      id: 's2',
      label: '实施',
      order: 2,
      objective: '',
      artifacts: [],
      exit_criteria: [],
      rules: [],
      recommended_milestones: [],
    },
  ],
  global_rules: [{ id: 'r1', content: '评审材料须双人复核' }],
  todos: [],
  ai_guidance: {},
  meta: {},
};

const PAYLOAD = {
  playbook_id: 'pb-1',
  playbook_name: '科研课题规程',
  spec: SPEC,
  shared_at: 1793500000000,
  expires_at: 1794100000000,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/share/playbook/tok_abc123']}>
      <Routes>
        <Route path="/share/playbook/:token" element={<PlaybookSharePage />} />
        <Route path="/chat" element={<div data-testid="chat-page" />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  projectListMock.mockResolvedValue([{ id: 'p-1', name: 'SageCore', path: '/w/sage' }]);
});

/** jsdom 缺 PointerEvent 捕获 API，Radix Select 依赖它来打开下拉。 */
function installPointerStubs(): void {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    releasePointerCapture: () => undefined,
    setPointerCapture: () => undefined,
    scrollIntoView: () => undefined,
  });
  if (!window.PointerEvent) {
    window.PointerEvent = MouseEvent as unknown as typeof PointerEvent;
  }
}

async function selectProject(name: string): Promise<void> {
  const trigger = screen.getByTestId('playbook-share-project-select');
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false, pointerType: 'mouse' });
  const option = await screen.findByRole('option', { name });
  fireEvent.click(option);
}

describe('PlaybookSharePage', () => {
  it('预览阶段、产物与规则', async () => {
    resolveShareTokenMock.mockResolvedValue(PAYLOAD);
    renderPage();

    expect(await screen.findByText('科研课题规程')).toBeInTheDocument();
    expect(await screen.findByText('1. 开题')).toBeInTheDocument();
    expect(screen.getByText('评审材料须双人复核')).toBeInTheDocument();
    expect(resolveShareTokenMock).toHaveBeenCalledWith('tok_abc123');
  });

  it('分享链接无效时展示提示', async () => {
    resolveShareTokenMock.mockRejectedValue(new Error('分享链接无效或已被删除'));
    renderPage();

    expect(
      await screen.findByText('分享链接无效或已过期，请向分享者索取新链接。'),
    ).toBeInTheDocument();
  });

  it('导入到选中项目并绑定规程', async () => {
    installPointerStubs();
    resolveShareTokenMock.mockResolvedValue(PAYLOAD);
    bindMock.mockResolvedValue({});
    renderPage();

    await screen.findByText('科研课题规程');
    await selectProject('SageCore');
    fireEvent.click(screen.getByTestId('playbook-share-import'));
    await waitFor(() => expect(bindMock).toHaveBeenCalled());
    expect(bindMock.mock.calls[0][0]).toBe('p-1');
    expect(bindMock.mock.calls[0][1].source).toBe('shared-link');
  });

  it('仅保存到规程库时提交 sage.playbook 信封', async () => {
    resolveShareTokenMock.mockResolvedValue(PAYLOAD);
    saveLibraryMock.mockResolvedValue({ id: 'lib-9', name: '科研课题规程' });
    renderPage();

    await screen.findByText('科研课题规程');
    fireEvent.click(screen.getByTestId('playbook-share-save-library'));
    await waitFor(() => expect(saveLibraryMock).toHaveBeenCalled());
    const [envelope, source] = saveLibraryMock.mock.calls[0];
    expect(envelope.format).toBe('sage.playbook');
    expect(envelope.playbook.id).toBe('pb-1');
    expect(source).toBe('shared');
  });
});
