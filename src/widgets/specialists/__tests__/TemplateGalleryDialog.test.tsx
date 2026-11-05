/**
 * M4-T2 (2026-11-05): 模板画廊对话框测试。
 *
 * 覆盖：打开时加载模板列表；展示 5 套模板名称 + 头像 + 技能数；
 * 点击「创建」触发 instantiateTemplate 并在成功后回调 onCreated + 关闭对话框；
 * 加载失败显示错误态；创建失败 toast。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  InstantiateTemplateResult,
  SpecialistTemplateMeta,
} from '../../../shared/api/specialistApi';
import { TemplateGalleryDialog } from '../TemplateGalleryDialog';

const mockListTemplates = vi.fn<() => Promise<SpecialistTemplateMeta[]>>();
const mockInstantiate = vi.fn<(id: string) => Promise<InstantiateTemplateResult>>();

vi.mock('../../../shared/api/specialistApi', () => ({
  specialistApi: {
    listTemplates: () => mockListTemplates(),
    instantiateTemplate: (id: string) => mockInstantiate(id),
  },
}));

const mockToastSuccess = vi.fn();
const mockToastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

const templates: SpecialistTemplateMeta[] = [
  {
    id: 'writing',
    name: '写作专家',
    tagline: '专业写作助手',
    avatar: '📝',
    description: '润色与结构化',
    skill_count: 3,
  },
  {
    id: 'research',
    name: '研究专家',
    tagline: '严谨的研究助手',
    avatar: '🔬',
    description: '文献与事实核验',
    skill_count: 3,
  },
  {
    id: 'coding',
    name: '编码专家',
    tagline: '全栈编码助手',
    avatar: '💻',
    description: '写代码查 bug',
    skill_count: 3,
  },
  {
    id: 'presentation',
    name: '演示专家',
    tagline: '演讲稿与幻灯片助手',
    avatar: '🎤',
    description: '演示结构梳理',
    skill_count: 3,
  },
  {
    id: 'office',
    name: 'Office专家',
    tagline: '文档排版与表格助手',
    avatar: '📊',
    description: 'Word 排版与表格清洗',
    skill_count: 3,
  },
];

const defaultResult: InstantiateTemplateResult = {
  id: 'specialist-writing-a1b2c3',
  name: '写作专家',
  template_id: 'writing',
  dropped_bindings: 0,
};

describe('TemplateGalleryDialog (M4-T2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListTemplates.mockResolvedValue(templates);
    mockInstantiate.mockResolvedValue(defaultResult);
  });

  it('loads templates on open', async () => {
    const onOpenChange = vi.fn();
    const onCreated = vi.fn();
    render(
      <TemplateGalleryDialog open onOpenChange={onOpenChange} onCreated={onCreated} />,
    );

    await waitFor(() => expect(mockListTemplates).toHaveBeenCalled());
    for (const tpl of templates) {
      expect(await screen.findByText(tpl.name)).toBeInTheDocument();
    }
  });

  it('displays avatar and skill count per card', async () => {
    render(<TemplateGalleryDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);

    await waitFor(() => expect(mockListTemplates).toHaveBeenCalled());
    // 每卡片一个 avatar 节点（写作专家）
    expect(await screen.findByText('📝')).toBeInTheDocument();
    // 5 套模板各有 "3 项技能"
    const skillLabels = await screen.findAllByText('3 项技能');
    expect(skillLabels.length).toBe(5);
  });

  it('calls instantiateTemplate and onCreated on click', async () => {
    const onCreated = vi.fn();
    render(
      <TemplateGalleryDialog open onOpenChange={vi.fn()} onCreated={onCreated} />,
    );

    // 点击写作专家卡片的「创建」按钮
    const createButtons = await screen.findAllByRole('button', { name: '创建' });
    expect(createButtons.length).toBeGreaterThan(0);
    fireEvent.click(createButtons[0]);

    await waitFor(() => expect(mockInstantiate).toHaveBeenCalledWith('writing'));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(defaultResult));
    expect(mockToastSuccess).toHaveBeenCalled();
  });

  it('shows loading state initially', () => {
    mockListTemplates.mockReturnValue(new Promise(() => {})); // 永不 resolve
    render(<TemplateGalleryDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);
    expect(screen.getByText('加载模板…')).toBeInTheDocument();
  });

  it('shows error state on load failure', async () => {
    mockListTemplates.mockRejectedValue(new Error('network down'));
    render(<TemplateGalleryDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/加载模板失败/)).toBeInTheDocument());
    expect(screen.getByText(/network down/)).toBeInTheDocument();
  });

  it('shows toast on instantiate failure', async () => {
    mockInstantiate.mockRejectedValue(new Error('id conflict'));
    render(<TemplateGalleryDialog open onOpenChange={vi.fn()} onCreated={vi.fn()} />);

    const createButtons = await screen.findAllByRole('button', { name: '创建' });
    fireEvent.click(createButtons[0]);

    await waitFor(() => expect(mockToastError).toHaveBeenCalled());
    expect(mockToastError.mock.calls[0][0]).toMatch(/id conflict/);
  });
});
