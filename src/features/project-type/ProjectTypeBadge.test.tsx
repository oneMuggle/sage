/**
 * ProjectTypeBadge 组件测试 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.6
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { ProjectTypeBadge } from './ProjectTypeBadge';
import { TypeDetectionPreview } from './TypeDetectionPreview';

describe('ProjectTypeBadge', () => {
  it('renders coding type with correct label and icon', () => {
    render(<ProjectTypeBadge type="coding" />);
    expect(screen.getByText('编码')).toBeInTheDocument();
  });

  it('renders research type with correct label', () => {
    render(<ProjectTypeBadge type="research" />);
    expect(screen.getByText('科研')).toBeInTheDocument();
  });

  it('renders business type with correct label', () => {
    render(<ProjectTypeBadge type="business" />);
    expect(screen.getByText('事务')).toBeInTheDocument();
  });

  it('renders personal type with correct label', () => {
    render(<ProjectTypeBadge type="personal" />);
    expect(screen.getByText('个人')).toBeInTheDocument();
  });

  it('renders "未分类" when type is null', () => {
    render(<ProjectTypeBadge type={null} />);
    expect(screen.getByText('未分类')).toBeInTheDocument();
  });

  it('renders "未分类" when type is undefined', () => {
    render(<ProjectTypeBadge type={undefined} />);
    expect(screen.getByText('未分类')).toBeInTheDocument();
  });

  it('applies detected ring when detected prop is true', () => {
    const { container } = render(<ProjectTypeBadge type="coding" detected />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('ring');
  });

  it('does not apply detected ring when detected is false', () => {
    const { container } = render(<ProjectTypeBadge type="coding" detected={false} />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).not.toContain('ring-1');
  });

  it('accepts custom className', () => {
    const { container } = render(<ProjectTypeBadge type="coding" className="custom-class" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('custom-class');
  });
});

describe('TypeDetectionPreview', () => {
  it('renders detected blueprint preview and allows one-click apply when selectedType differs', () => {
    const onApply = vi.fn();
    render(
      <TypeDetectionPreview
        result={{
          detectedType: 'research',
          confidence: 0.88,
          signals: ['发现 .bib 与 .tex 文件'],
        }}
        selectedType="coding"
        onApplyDetectedType={onApply}
      />,
    );

    expect(screen.getByTestId('detection-blueprint-preview')).toBeInTheDocument();
    const applyBtn = screen.getByTestId('apply-detected-type-btn');
    fireEvent.click(applyBtn);
    expect(onApply).toHaveBeenCalledWith('research');
  });
});
