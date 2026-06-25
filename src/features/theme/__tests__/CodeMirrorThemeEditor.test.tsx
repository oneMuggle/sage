/**
 * CodeMirrorThemeEditor 单元测试
 *
 * 验证组件渲染 + props 契约。CodeMirror 6 在 jsdom 中
 * 不真正渲染编辑器 DOM（缺少 getBoundingClientRect 等），
 * 所以测试聚焦于：
 * 1. 组件不崩溃
 * 2. 容器有 data-testid
 * 3. readOnly 属性透传
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CodeMirrorThemeEditor } from '../CodeMirrorThemeEditor';

describe('CodeMirrorThemeEditor', () => {
  it('renders with initial value', () => {
    render(
      <CodeMirrorThemeEditor value=":root { --bg-base: #fff; }" onChange={() => {}} />
    );
    expect(screen.getByTestId('cm-editor')).toBeInTheDocument();
  });

  it('does not crash with error prop', () => {
    render(
      <CodeMirrorThemeEditor
        value=""
        onChange={() => {}}
        error='Variable "--evil" is not allowed'
      />
    );
    expect(screen.getByTestId('cm-editor')).toBeInTheDocument();
  });

  it('does not crash with readOnly=true', () => {
    render(
      <CodeMirrorThemeEditor value=":root {}" onChange={() => {}} readOnly />
    );
    expect(screen.getByTestId('cm-editor')).toBeInTheDocument();
  });

  it('renders empty value without crashing', () => {
    render(<CodeMirrorThemeEditor value="" onChange={() => {}} />);
    expect(screen.getByTestId('cm-editor')).toBeInTheDocument();
  });

  it('accepts onChange prop without crashing', () => {
    const onChange = vi.fn();
    render(<CodeMirrorThemeEditor value=":root {}" onChange={onChange} />);
    // CodeMirror 6 在 jsdom 中无法真实触发输入事件，
    // 此处只验证 onChange prop 被接受且不报错。
    expect(onChange).not.toHaveBeenCalled();
  });
});
