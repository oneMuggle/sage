import { render, screen, renderHook, act } from '@testing-library/react';
import { type ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { I18nProvider, useI18n } from '../index';
import { useLocaleStore } from '../useLocaleStore';

// 测试辅助：在每个 test 间重置 store + localStorage
function Wrapper({ children }: { children: ReactNode }) {
  return <I18nProvider>{children}</I18nProvider>;
}

describe('I18nProvider + useI18n', () => {
  beforeEach(() => {
    localStorage.clear();
    useLocaleStore.setState({ locale: 'zh' });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders children', () => {
    render(
      <I18nProvider>
        <div data-testid="child">child content</div>
      </I18nProvider>,
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('exposes default locale zh via useI18n', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.locale).toBe('zh');
  });

  it('t() returns zh translation for chat.title', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.t('chat.title')).toBe('对话');
  });

  it('t() returns en translation when locale=en', () => {
    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    expect(result.current.locale).toBe('en');
    expect(result.current.t('chat.title')).toBe('Chat');
  });

  it('t() accepts params and returns string', () => {
    const { result } = renderHook(() => useI18n(), { wrapper: Wrapper });
    // M1 zh 字典中暂不带占位符的 key；这里只验证 t() 接受 params 参数且不报错
    const out = result.current.t('chat.title', { unused: 'x' });
    expect(typeof out).toBe('string');
    expect(out).toBe('对话');
  });

  it('useI18n throws when used outside Provider', () => {
    expect(() => {
      renderHook(() => useI18n());
    }).toThrow(/must be used within an <I18nProvider>/);
  });

  it('setLocale triggers context re-render', () => {
    function DisplayLocale() {
      const { locale, t } = useI18n();
      return <div data-testid="locale">{`${locale}:${t('chat.send')}`}</div>;
    }
    render(
      <I18nProvider>
        <DisplayLocale />
      </I18nProvider>,
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('zh:发送');

    act(() => {
      useLocaleStore.getState().setLocale('en');
    });
    expect(screen.getByTestId('locale')).toHaveTextContent('en:Send');
  });
});
