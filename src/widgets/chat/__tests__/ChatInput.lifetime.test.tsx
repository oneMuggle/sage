import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { skillsApi } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

vi.mock('../../../shared/api', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api')>('../../../shared/api');
  return {
    ...actual,
    skillsApi: { ...actual.skillsApi, list: vi.fn() },
    promptApi: { list: vi.fn().mockResolvedValue([]) },
  };
});

describe('ChatInput asynchronous skill loading lifetime', () => {
  it('does not process a skill response after unmount', async () => {
    let resolve!: (value: never[]) => void;
    vi.mocked(skillsApi.list).mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const view = render(
      <I18nProvider>
        <ChatInput onSend={vi.fn()} />
      </I18nProvider>,
    );
    view.unmount();
    const filter = vi.fn(() => []);
    const late = Object.defineProperty([], 'filter', { value: filter });
    await act(async () => {
      resolve(late);
    });
    expect(filter).not.toHaveBeenCalled();
  });

  it('consumes rejection after unmount without scheduling state work', async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(skillsApi.list).mockReturnValueOnce(
      new Promise((_, r) => {
        reject = r;
      }),
    );
    const view = render(
      <I18nProvider>
        <ChatInput onSend={vi.fn()} />
      </I18nProvider>,
    );
    view.unmount();
    await act(async () => {
      reject(new Error('late IPC failure'));
    });
    expect(view.container.childElementCount).toBe(0);
  });
});
