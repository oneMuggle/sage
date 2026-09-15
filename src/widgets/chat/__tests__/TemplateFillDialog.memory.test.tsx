/**
 * R31: 模板变量记忆测试 —— 上次填写值存 localStorage，下次预填。
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  extractTemplateVars,
  loadRememberedValues,
  resolveTemplate,
  saveRememberedValues,
  TemplateFillDialog,
} from '../TemplateFillDialog';



const CONTENT = '写周报：{{内容}} 截止 {{截止日}}';

describe('R31 变量记忆 — 纯函数', () => {
  it('save 后 load 返回相同值', () => {
    saveRememberedValues(CONTENT, { 内容: '本周进展', 截止日: '周五' });
    expect(loadRememberedValues(CONTENT)).toEqual({ 内容: '本周进展', 截止日: '周五' });
  });

  it('不同模板内容互不串扰', () => {
    saveRememberedValues(CONTENT, { 内容: 'A' });
    expect(loadRememberedValues('另一个模板 {{内容}}')).toEqual({});
  });

  it('空值不写入（清空输入=遗忘）', () => {
    saveRememberedValues(CONTENT, { 内容: '   ', 截止日: '' });
    expect(loadRememberedValues(CONTENT)).toEqual({});
  });

  it('损坏的存储返回空对象', () => {
    const key = Object.keys(localStorage).find((k) => k.startsWith('sage:tplfill:'));
    if (key) localStorage.setItem(key, '{broken json');
    // 直接写坏值再读
    saveRememberedValues(CONTENT, { 内容: 'x' });
    const realKey = Object.keys(localStorage).find((k) => k.startsWith('sage:tplfill:'));
    localStorage.setItem(realKey!, '{broken');
    expect(loadRememberedValues(CONTENT)).toEqual({});
  });
});

describe('R31 变量记忆 — 组件预填', () => {
  beforeEach(() => {
    Object.keys(localStorage)
      .filter((k) => k.startsWith('sage:tplfill:'))
      .forEach((k) => localStorage.removeItem(k));
  });

  it('确认后保存的值在下次打开时预填', () => {
    const onConfirm = vi.fn();
    const { unmount } = render(
      <I18nProvider defaultLocale="zh">
        <TemplateFillDialog
          content={CONTENT}
          onConfirm={(resolved) => {
            expect(resolved).toBe('写周报：进展A 截止 周五');
          }}
          onCancel={vi.fn()}
        />
      </I18nProvider>,
    );
    fireEvent.change(screen.getByTestId('tplfill-input-内容'), {
      target: { value: '进展A' },
    });
    fireEvent.change(screen.getByTestId('tplfill-input-截止日'), {
      target: { value: '周五' },
    });
    fireEvent.click(screen.getByTestId('tplfill-confirm'));
    unmount();

    // 重新打开 —— 预填上次值
    render(
      <I18nProvider defaultLocale="zh">
        <TemplateFillDialog content={CONTENT} onConfirm={onConfirm} onCancel={vi.fn()} />
      </I18nProvider>,
    );
    expect((screen.getByTestId('tplfill-input-内容') as HTMLInputElement).value).toBe('进展A');
    expect((screen.getByTestId('tplfill-input-截止日') as HTMLInputElement).value).toBe('周五');
  });
});

// 引用防未使用（既有口径复用断言）
describe('R31 — 既有纯函数回归', () => {
  it('extract/resolve 不受影响', () => {
    expect(extractTemplateVars(CONTENT)).toEqual(['内容', '截止日']);
    expect(resolveTemplate(CONTENT, {})).toBe('写周报：{{内容}} 截止 {{截止日}}');
  });
});
