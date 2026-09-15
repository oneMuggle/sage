/**
 * R29: {{变量}} 填充对话框测试
 *
 * 纯函数: extractTemplateVars（抽取/去重/保序/空白裁剪）、
 *         resolveTemplate（替换/留空保留占位）
 * 组件:   变量输入 → 确认回调收到解析后文本；取消回调；无变量提示
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import {
  extractTemplateVars,
  resolveTemplate,
  TemplateFillDialog,
} from '../TemplateFillDialog';


const renderDialog = (content: string, onConfirm = vi.fn(), onCancel = vi.fn()) => {
  render(
    <I18nProvider defaultLocale="zh">
      <TemplateFillDialog content={content} onConfirm={onConfirm} onCancel={onCancel} />
    </I18nProvider>,
  );
  return { onConfirm, onCancel };
};

describe('extractTemplateVars — 纯函数', () => {
  it('按出现顺序抽取并去重', () => {
    expect(extractTemplateVars('{{a}} 和 {{b}} 还有 {{a}}')).toEqual(['a', 'b']);
  });

  it('裁剪占位两侧空白', () => {
    expect(extractTemplateVars('{{ 内容 }}')).toEqual(['内容']);
  });

  it('无占位返回空数组', () => {
    expect(extractTemplateVars('没有任何占位 { 单括号也不算 }')).toEqual([]);
  });
});

describe('resolveTemplate — 纯函数', () => {
  it('替换已填写的变量', () => {
    expect(resolveTemplate('{{a}} 和 {{b}}', { a: '1', b: '2' })).toBe('1 和 2');
  });

  it('留空的变量保留 {{占位}} 原样', () => {
    expect(resolveTemplate('{{a}} 和 {{b}}', { a: '1' })).toBe('1 和 {{b}}');
  });

  it('匹配时裁剪占位空白', () => {
    expect(resolveTemplate('{{ 内容 }}', { 内容: '值' })).toBe('值');
  });
});

describe('TemplateFillDialog — 组件', () => {
  it('渲染每个变量的输入框', () => {
    renderDialog('{{a}} {{b}}');
    expect(screen.getByTestId('tplfill-input-a')).toBeInTheDocument();
    expect(screen.getByTestId('tplfill-input-b')).toBeInTheDocument();
  });

  it('确认回调收到解析后的完整文本', () => {
    const onConfirm = vi.fn();
    renderDialog('{{topic}} 大纲', onConfirm);
    fireEvent.change(screen.getByTestId('tplfill-input-topic'), {
      target: { value: '量化交易' },
    });
    fireEvent.click(screen.getByTestId('tplfill-confirm'));
    expect(onConfirm).toHaveBeenCalledWith('量化交易 大纲');
  });

  it('取消回调触发', () => {
    const onCancel = vi.fn();
    renderDialog('{{a}}', vi.fn(), onCancel);
    fireEvent.click(screen.getByTestId('tpl-fill-dialog'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('无变量模板显示提示', () => {
    renderDialog('直接可用的提示词');
    expect(screen.getByText(/无需填写变量/)).toBeInTheDocument();
  });
});
