<<<<<<< HEAD
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

=======
import {
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../src/shared/lib/i18n';

>>>>>>> origin/main
vi.mock('node-fetch', async () => {
  const actual = await vi.importActual<typeof import('node-fetch')>('node-fetch');
  const { wireFetch } = await import('./fetchStub');
  return { ...actual, default: wireFetch };
});

import { PromptTemplatesTab } from '../../../src/pages/settings/PromptTemplatesTab';
<<<<<<< HEAD
import { I18nProvider } from '../../../src/shared/lib/i18n';

import { received, releaseBackend, strictBody, useBackend } from './harness';

function renderTab() {
  return render(
    <I18nProvider defaultLocale="zh">
      <PromptTemplatesTab />
    </I18nProvider>,
  );
}

=======

import { received, releaseBackend, strictBody, useBackend } from './harness';

function I18nWrapper({ children }: { children: React.ReactNode }) {
  return <I18nProvider defaultLocale="zh">{children}</I18nProvider>;
}

const render = (ui: React.ReactElement, options?: Parameters<typeof rtlRender>[1]) =>
  rtlRender(ui, { wrapper: I18nWrapper, ...options });

function renderTab() {
  return render(<PromptTemplatesTab />);
}
>>>>>>> origin/main
const tpl = (id: string, name: string) => ({
  id,
  name,
  description: '',
  content: `${name} body`,
  created_at: 1,
  updated_at: 1,
});
const STORED = [tpl('a', 'Alpha'), tpl('b', 'Beta'), tpl('c', 'Gamma')];

const REORDER = '/api/v1/prompts/templates/reorder';
// each row starts with the template name, followed by its preview text
const order = () =>
  screen
    .getAllByTestId('prompts-item')
    .map((el) => STORED.find((s) => (el.textContent ?? '').startsWith(s.name))?.name);

/** Drag the first row onto the last one, the way the browser fires it. */
function dragFirstOntoLast() {
  const items = screen.getAllByTestId('prompts-item');
  fireEvent.dragStart(items[0]);
  fireEvent.dragOver(items[2]);
  fireEvent.drop(items[2]);
}

describe('Settings > Prompt templates: drag-to-sort over the real bridge (#857 dropped prompts_reorder)', () => {
  beforeEach(() => vi.spyOn(console, 'warn').mockImplementation(() => {}));
  afterEach(() => {
    cleanup();
    releaseBackend();
    vi.restoreAllMocks();
  });

  it('sends the new order to PUT /prompts/templates/reorder as ordered_ids', async () => {
    let stored = [...STORED];
    useBackend([
      {
        method: 'GET',
        path: '/api/v1/prompts/templates',
        reply: () => ({ json: { templates: stored } }),
      },
      {
        method: 'PUT',
        path: REORDER,
        reply: strictBody(['ordered_ids'], (body) => {
          const ids = body.ordered_ids as string[];
          stored = ids.map((id) => stored.find((t) => t.id === id)!);
          return { json: { templates: stored } };
        }),
      },
    ]);

    renderTab();
    await screen.findAllByTestId('prompts-item');
    expect(order()).toEqual(['Alpha', 'Beta', 'Gamma']);

    dragFirstOntoLast();

    await waitFor(() => expect(received('PUT', REORDER)).toHaveLength(1));
    expect(received('PUT', REORDER)[0].body).toEqual({ ordered_ids: ['b', 'c', 'a'] });
    expect(order()).toEqual(['Beta', 'Gamma', 'Alpha']);
  });

  it('rolls the list back when the backend rejects the new order', async () => {
    useBackend([
      {
        method: 'GET',
        path: '/api/v1/prompts/templates',
        reply: () => ({ json: { templates: STORED } }),
      },
      { method: 'PUT', path: REORDER, reply: () => ({ status: 500, json: { detail: 'boom' } }) },
    ]);

    renderTab();
    await screen.findAllByTestId('prompts-item');

    dragFirstOntoLast();

    // the optimistic order is reverted by reloading from the backend
    await waitFor(() =>
      expect(received('GET', '/api/v1/prompts/templates').length).toBeGreaterThanOrEqual(2),
    );
    await waitFor(() => expect(order()).toEqual(['Alpha', 'Beta', 'Gamma']));
    expect(within(screen.getByTestId('prompts-list')).getAllByTestId('prompts-item')).toHaveLength(
      3,
    );
  });
});
