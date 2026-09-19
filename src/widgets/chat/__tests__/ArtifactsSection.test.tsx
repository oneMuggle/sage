// src/widgets/chat/__tests__/ArtifactsSection.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { ArtifactsSection } from '../artifacts/ArtifactsSection';

const arts: Artifact[] = [
  { id: 'a1', session_id: 's', tool_call_id: null, path: '/a.md', name: 'a.md', kind: 'markdown', size: 100, created_at: 1 },
  { id: 'a2', session_id: 's', tool_call_id: null, path: '/b.py', name: 'b.py', kind: 'code', size: 200, created_at: 2 },
];
const base = { loading: false, sessionId: 'sess_001', onRefresh: () => {}, onSelect: () => {}, onReveal: () => {} };

describe('ArtifactsSection', () => {
  it('shows empty state', () => {
    render(<ArtifactsSection artifacts={[]} {...base} />);
    expect(screen.getByText(/暂无产物/)).toBeInTheDocument();
  });

  it('renders artifact list', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.getByText('b.py')).toBeInTheDocument();
  });

  it('calls onRefresh', () => {
    const onRefresh = vi.fn();
    render(<ArtifactsSection artifacts={[]} {...base} onRefresh={onRefresh} />);
    fireEvent.click(screen.getByRole('button', { name: /刷新/ }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('asks to select session when sessionId null', () => {
    render(<ArtifactsSection artifacts={[]} {...base} sessionId={null} />);
    expect(screen.getByText(/请先选择会话/)).toBeInTheDocument();
  });
});

describe('ArtifactsSection — right-panel R4 批次 C: 类型过滤', () => {
  it('默认全部显示，过滤 chips 渲染', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    expect(screen.getByTestId('artifact-filter-all')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-filter-code')).toBeInTheDocument();
    expect(screen.getByTestId('artifact-filter-doc')).toBeInTheDocument();
  });

  it('点击代码 chip 后只显示代码类产物', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    fireEvent.click(screen.getByTestId('artifact-filter-code'));
    expect(screen.getByText('b.py')).toBeInTheDocument();
    expect(screen.queryByText('a.md')).not.toBeInTheDocument();
  });

  it('切回全部恢复完整列表', () => {
    render(<ArtifactsSection artifacts={arts} {...base} />);
    fireEvent.click(screen.getByTestId('artifact-filter-code'));
    fireEvent.click(screen.getByTestId('artifact-filter-all'));
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.getByText('b.py')).toBeInTheDocument();
  });

  it('过滤后无匹配显示空提示', () => {
    const imgOnly: Artifact[] = [
      { id: 'i1', session_id: 's', tool_call_id: null, path: '/c.png', name: 'c.png', kind: 'image', size: 10, created_at: 3 },
    ];
    render(<ArtifactsSection artifacts={imgOnly} {...base} />);
    fireEvent.click(screen.getByTestId('artifact-filter-code'));
    expect(screen.getByTestId('artifacts-filter-empty')).toBeInTheDocument();
  });
});
