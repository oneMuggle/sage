// @vitest-environment jsdom
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FONT_DEFAULTS, type FontSettings } from '../fontOptions';
import { FontProvider, useFontSettings } from '../useFontSettings';
const storage = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn() }));
vi.mock('../fontStorage', () => ({
  loadFontSettings: storage.load,
  saveFontSettings: storage.save,
}));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
function Consumer({ name }: { name: string }) {
  const { settings, updateSettings, resetSettings, error, loading } = useFontSettings();
  return (
    <div>
      <output data-testid={name}>{JSON.stringify(settings)}</output>
      <output data-testid={`${name}-loading`}>{String(loading)}</output>
      <button onClick={() => updateSettings({ fontSizeUi: 20 })}>{name} UI</button>
      <button onClick={() => updateSettings({ fontSizeCode: 18 })}>{name} code</button>
      <button onClick={resetSettings}>{name} reset</button>
      {error && <span role="alert">{error}</span>}
    </div>
  );
}
function mount() {
  return render(
    <FontProvider>
      <Consumer name="one" />
      <Consumer name="two" />
    </FontProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  storage.load.mockResolvedValue(FONT_DEFAULTS);
  storage.save.mockResolvedValue(undefined);
});
describe('FontProvider', () => {
  it('hydrates CSS and shares independent UI/code state with every consumer', async () => {
    storage.load.mockResolvedValue({ ...FONT_DEFAULTS, fontUi: 'system', fontSizeUi: 16 });
    mount();
    await waitFor(() =>
      expect(document.documentElement.style.getPropertyValue('--font-size-ui')).toBe('16px'),
    );
    expect(document.documentElement.style.getPropertyValue('--font-ui')).toContain('system-ui');
    fireEvent.click(screen.getByText('one UI'));
    expect(screen.getByTestId('two')).toHaveTextContent('"fontSizeUi":20');
    expect(document.documentElement.style.getPropertyValue('--font-size-code')).toBe('13px');
    fireEvent.click(screen.getByText('two code'));
    expect(document.documentElement.style.getPropertyValue('--font-size-ui')).toBe('20px');
    expect(document.documentElement.style.getPropertyValue('--font-size-code')).toBe('18px');
    await waitFor(() => expect(storage.save).toHaveBeenCalledTimes(2));
  });
  it('queues saves behind hydration and ignores the stale loaded snapshot', async () => {
    const load = deferred<FontSettings>();
    storage.load.mockReturnValue(load.promise);
    const save = deferred<void>();
    storage.save.mockReturnValueOnce(save.promise);
    mount();
    fireEvent.click(screen.getByText('one UI'));
    fireEvent.click(screen.getByText('two code'));
    expect(storage.save).not.toHaveBeenCalled();
    await act(async () => load.resolve({ ...FONT_DEFAULTS, fontSizeUi: 11 }));
    expect(screen.getByTestId('one')).toHaveTextContent('"fontSizeUi":20');
    expect(storage.save).toHaveBeenCalledTimes(1);
    await act(async () => save.resolve());
    expect(storage.save).toHaveBeenLastCalledWith({
      ...FONT_DEFAULTS,
      fontSizeUi: 20,
      fontSizeCode: 18,
    });
  });
  it('resets all values and persists the defaults', async () => {
    mount();
    await act(async () => {});
    fireEvent.click(screen.getByText('one UI'));
    fireEvent.click(screen.getByText('one reset'));
    expect(screen.getByTestId('two')).toHaveTextContent(JSON.stringify(FONT_DEFAULTS));
    await waitFor(() => expect(storage.save).toHaveBeenLastCalledWith(FONT_DEFAULTS));
  });
  it('exposes save failures and allows later saves to recover', async () => {
    storage.save.mockRejectedValueOnce(new Error('offline'));
    mount();
    await act(async () => {});
    fireEvent.click(screen.getByText('one UI'));
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
    fireEvent.click(screen.getByText('two code'));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
  it('does not apply a late load after unmount', async () => {
    const load = deferred<FontSettings>();
    storage.load.mockReturnValue(load.promise);
    const view = mount();
    view.unmount();
    const before = document.documentElement.style.cssText;
    await act(async () => load.resolve({ ...FONT_DEFAULTS, fontSizeUi: 24 }));
    expect(document.documentElement.style.cssText).toBe(before);
  });
  it('exposes loading=true until load completes, then loading=false', async () => {
    const load = deferred<FontSettings>();
    storage.load.mockReturnValue(load.promise);
    mount();
    expect(screen.getByTestId('one-loading')).toHaveTextContent('true');
    expect(screen.getByTestId('two-loading')).toHaveTextContent('true');
    await act(async () => load.resolve(FONT_DEFAULTS));
    expect(screen.getByTestId('one-loading')).toHaveTextContent('false');
    expect(screen.getByTestId('two-loading')).toHaveTextContent('false');
  });
  it('sets loading=false even when load rejects', async () => {
    storage.load.mockRejectedValue(new Error('offline'));
    mount();
    await waitFor(() => expect(screen.getByTestId('one-loading')).toHaveTextContent('false'));
    expect(screen.getByTestId('two-loading')).toHaveTextContent('false');
  });
});
