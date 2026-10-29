// src/widgets/chat/__tests__/ArtifactViewer.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../../features/artifacts/useArtifactContent', () => ({ useArtifactContent: vi.fn() }));
vi.mock('../../../features/artifacts/artifactApi', () => ({
  revealArtifact: vi.fn(),
  updateArtifactContent: vi.fn(),
}));
// R2 批次 A: Shiki 异步高亮在 jsdom 下不确定，mock 成同步 pre 保持断言确定
vi.mock('../ShikiCodeBlock', () => ({
  ShikiCodeBlock: ({ children }: { children: string }) => (
    <pre data-testid="shiki-block">{children}</pre>
  ),
}));
// 2026-10-29: docx-preview 动态 import 在 jsdom 下不执行真实解析——用桩
// 组件断言"默认 Word 版式 + 可切换文本视图"的接线。
vi.mock('../../../features/office/DocxBlobPreview', () => ({
  DocxBlobPreview: ({ dataUrl }: { dataUrl: string }) => (
    <div data-testid="docx-blob-preview" data-src={dataUrl} />
  ),
}));

import type { Artifact, ArtifactKind } from '../../../features/artifacts/artifactApi';
import { useArtifactContent } from '../../../features/artifacts/useArtifactContent';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ArtifactViewer } from '../artifacts/ArtifactViewer';

const sample: Artifact = {
  id: 'a1',
  session_id: 'sess_001',
  tool_call_id: null,
  path: '/tmp/test.md',
  name: 'test.md',
  kind: 'markdown',
  size: 1024,
  created_at: 1,
};

const baseReturn = { refresh: vi.fn() };

describe('ArtifactViewer', () => {
  it('renders breadcrumb', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Hello' },
      loading: false,
      ...baseReturn,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/产物/)).toBeInTheDocument();
    expect(screen.getByText('test.md')).toBeInTheDocument();
  });

  it('calls onBack', () => {
    vi.mocked(useArtifactContent).mockReturnValue({ content: null, loading: false, ...baseReturn });
    const onBack = vi.fn();
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={onBack} />);
    fireEvent.click(screen.getByRole('button', { name: /返回/ }));
    expect(onBack).toHaveBeenCalled();
  });

  it('renders markdown content', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Title' },
      loading: false,
      ...baseReturn,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/Title/)).toBeInTheDocument();
  });

  it('renders image', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'image', data_url: 'data:image/png;base64,xxx' },
      loading: false,
      ...baseReturn,
    });
    render(
      <ArtifactViewer
        artifact={{ ...sample, kind: 'image' }}
        sessionId="sess_001"
        onBack={() => {}}
      />,
    );
    expect(screen.getByRole('img')).toHaveAttribute('src', 'data:image/png;base64,xxx');
  });

  it('shows error state', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: false, error: 'File not found' },
      loading: false,
      ...baseReturn,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    expect(screen.getByText(/File not found/)).toBeInTheDocument();
  });

  it('renders csv cells without trailing carriage return from CRLF input', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'csv', content: 'a,b\r\n1,2\r\n' },
      loading: false,
      ...baseReturn,
    });
    const { container } = render(
      <ArtifactViewer
        artifact={{ ...sample, kind: 'csv' }}
        sessionId="sess_001"
        onBack={() => {}}
      />,
    );
    expect(screen.getByText('2')).toBeInTheDocument();
    const cells = container.querySelectorAll('th, td');
    expect(cells.length).toBeGreaterThan(0);
    cells.forEach((c) => expect(c.textContent).not.toContain('\r'));
  });
});

describe('ArtifactViewer — right-panel R2 批次 A: 预览升级', () => {
  beforeEach(() => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it('markdown 默认渲染视图，可切源码再切回', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'markdown', content: '# Title\n\n**bold**' },
      loading: false,
      ...baseReturn,
    });
    render(<ArtifactViewer artifact={sample} sessionId="sess_001" onBack={() => {}} />);
    // 默认渲染视图：标题被渲染成 h1
    expect(screen.getByTestId('artifact-md-rendered')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Title' })).toBeInTheDocument();
    // 切源码：渲染视图消失，出现 Shiki 块
    fireEvent.click(screen.getByTestId('artifact-md-toggle'));
    expect(screen.queryByTestId('artifact-md-rendered')).not.toBeInTheDocument();
    expect(screen.getByTestId('shiki-block')).toHaveTextContent('# Title');
    // 切回渲染
    fireEvent.click(screen.getByTestId('artifact-md-toggle'));
    expect(screen.getByTestId('artifact-md-rendered')).toBeInTheDocument();
  });

  it('code 产物走 Shiki 高亮块', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'code', content: 'print("hi")' },
      loading: false,
      ...baseReturn,
    });
    render(
      <ArtifactViewer
        artifact={{ ...sample, kind: 'code', name: 'main.py' }}
        sessionId="sess_001"
        onBack={() => {}}
      />,
    );
    expect(screen.getByTestId('shiki-block')).toHaveTextContent('print("hi")');
  });

  it('html 产物有刷新按钮，点击后 iframe 重挂载', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'html', content: '<b>x</b>' },
      loading: false,
      ...baseReturn,
    });
    render(
      <ArtifactViewer
        // ArtifactKind 类型漏列 'html'（运行时后端会返回），测试按实际形状断言
        artifact={{ ...sample, kind: 'html' as unknown as ArtifactKind, name: 'page.html' }}
        sessionId="sess_001"
        onBack={() => {}}
      />,
    );
    const before = screen.getByTestId('html-artifact-preview');
    fireEvent.click(screen.getByTestId('artifact-html-refresh'));
    const after = screen.getByTestId('html-artifact-preview');
    expect(after).not.toBe(before); // key 重挂载 = 新 DOM 节点
  });

  it('csv 复制按钮写入剪贴板', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: { ok: true, kind: 'csv', content: 'a,b\r\n1,2\r\n' },
      loading: false,
      ...baseReturn,
    });
    render(
      <ArtifactViewer
        artifact={{ ...sample, kind: 'csv' }}
        sessionId="sess_001"
        onBack={() => {}}
      />,
    );
    fireEvent.click(screen.getByTestId('artifact-csv-copy'));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('a,b\r\n1,2\r\n');
  });

  it('docx 默认渲染 Word 版式，可切换为文本视图', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: {
        ok: true,
        kind: 'docx',
        data_url:
          'data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,xxx',
        structured: {
          paragraphs: [{ text: '正文段落', style: 'Normal', level: 0 }],
          tables: [],
          images: 0,
        } as never,
      },
      loading: false,
      ...baseReturn,
    });
    render(
      <I18nProvider>
        <ArtifactViewer
          artifact={{ ...sample, kind: 'docx', name: 'report.docx' }}
          sessionId="sess_001"
          onBack={() => {}}
        />
      </I18nProvider>,
    );
    expect(screen.getByTestId('docx-blob-preview')).toHaveAttribute(
      'data-src',
      expect.stringContaining('application/vnd.openxmlformats-officedocument'),
    );
    fireEvent.click(screen.getByRole('button', { name: /切换为文本视图/ }));
    expect(screen.getByTestId('office-structured-preview')).toBeInTheDocument();
    expect(screen.queryByTestId('docx-blob-preview')).not.toBeInTheDocument();
  });

  it('docx 无 data_url 时直接渲染结构化视图（旧后端降级）', () => {
    vi.mocked(useArtifactContent).mockReturnValue({
      content: {
        ok: true,
        kind: 'docx',
        structured: {
          paragraphs: [{ text: '正文段落', style: 'Normal', level: 0 }],
          tables: [],
          images: 0,
        } as never,
      },
      loading: false,
      ...baseReturn,
    });
    render(
      <I18nProvider>
        <ArtifactViewer
          artifact={{ ...sample, kind: 'docx', name: 'legacy.docx' }}
          sessionId="sess_001"
          onBack={() => {}}
        />
      </I18nProvider>,
    );
    expect(screen.getByTestId('office-structured-preview')).toBeInTheDocument();
    expect(screen.queryByTestId('docx-blob-preview')).not.toBeInTheDocument();
    expect(screen.queryByTestId('artifact-docx-view-toggle')).not.toBeInTheDocument();
  });
});
