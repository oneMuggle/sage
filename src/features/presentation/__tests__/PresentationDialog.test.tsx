import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { presentationApi } from '../../../shared/api/presentationApi';
import type {
  PresentationEnvironment,
  PresentationRenderResult,
  PresentationTemplate,
} from '../../../shared/api/presentationApi';
import { useTaskCenterStore } from '../../task-center/taskCenterStore';
import { PresentationDialog } from '../PresentationDialog';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../../../shared/api/presentationApi', () => ({
  presentationApi: {
    getEnvironment: vi.fn(),
    getTemplates: vi.fn(),
    refreshTemplates: vi.fn(),
    renderFromSvgs: vi.fn(),
  },
}));

const mockedEnv = vi.mocked(presentationApi.getEnvironment);
const mockedTemplates = vi.mocked(presentationApi.getTemplates);
const mockedRefresh = vi.mocked(presentationApi.refreshTemplates);
const mockedRender = vi.mocked(presentationApi.renderFromSvgs);
const mockedToastSuccess = vi.mocked(toast.success);

const SVG_A = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>';
const SVG_B = '<svg xmlns="http://www.w3.org/2000/svg"><circle r="5"/></svg>';
const SVG_STRUCTURED =
  '<svg xmlns="http://www.w3.org/2000/svg" data-pptx-layout="cover"><rect/></svg>';

const READY_ENV: PresentationEnvironment = { ready: true, skill_root: '/skills/ppt-master' };
const NO_TEMPLATES = { available: true, error: null, templates: [] };

function template(kind: string, id: string): PresentationTemplate {
  return {
    kind,
    template_id: id,
    name: id,
    summary: `${id} 摘要`,
    primary_color: null,
    canvas_format: kind === 'layout' ? '16:9' : null,
    page_count: null,
    page_types: ['cover'],
    root_path: `/fake/templates/${kind}s/${id}`,
  };
}

const SUCCESS_RESULT: PresentationRenderResult = {
  success: true,
  output_path: '/ws/presentation.pptx',
  quality_passed: true,
  blocking_errors: [],
  warnings: [],
  summary: { total: 1, passed: 1, warnings: 0, errors: 0 },
  message: '转换完成',
  templates_applied: [],
};

const BLOCKED_RESULT: PresentationRenderResult = {
  success: false,
  output_path: null,
  quality_passed: false,
  blocking_errors: [{ code: 'E100', message: '文本框超出画布边界' }],
  warnings: [],
  summary: { total: 1, passed: 0, warnings: 0, errors: 1 },
  message: '质量门禁未通过',
  templates_applied: [],
};

function renderDialog(workspacePath = '/ws') {
  const onClose = vi.fn();
  render(<PresentationDialog isOpen onClose={onClose} workspacePath={workspacePath} />);
  return { onClose };
}

function addPastedSlide(text: string) {
  const textarea = screen.getByTestId('presentation-paste');
  fireEvent.change(textarea, { target: { value: text } });
  fireEvent.click(screen.getByText('添加为幻灯片'));
}

beforeEach(() => {
  mockedEnv.mockReset();
  mockedRender.mockReset();
  mockedTemplates.mockReset();
  mockedRefresh.mockReset();
  mockedToastSuccess.mockReset();
  mockedTemplates.mockResolvedValue(NO_TEMPLATES);
  useTaskCenterStore.setState({ tasks: {} });
});

describe('PresentationDialog', () => {
  it('环境不可用时展示提示且禁止提交', async () => {
    mockedEnv.mockResolvedValue({ ready: false, error: '缺少 svg_to_pptx.py' });
    renderDialog();

    await waitFor(() =>
      expect(screen.getByTestId('presentation-env-not-ready')).toHaveTextContent(
        '缺少 svg_to_pptx.py',
      ),
    );

    addPastedSlide(SVG_A);
    const submit = screen.getByText('生成 PPTX').closest('button') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(mockedRender).not.toHaveBeenCalled();
  });

  it('未绑定工作区时提示且禁止提交', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    renderDialog('');

    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());
    expect(screen.getByTestId('presentation-no-workspace')).toBeTruthy();

    addPastedSlide(SVG_A);
    const submit = screen.getByText('生成 PPTX').closest('button') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it('提交时打包 svg_slides 并补全 .pptx 后缀', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedRender.mockResolvedValue(SUCCESS_RESULT);
    renderDialog();

    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());

    addPastedSlide(SVG_A);
    addPastedSlide(SVG_B);

    const filenameInput = screen.getByTestId('presentation-filename');
    fireEvent.change(filenameInput, { target: { value: '季度汇报' } });

    fireEvent.click(screen.getByText('生成 PPTX'));

    await waitFor(() => expect(mockedRender).toHaveBeenCalledTimes(1));
    expect(mockedRender).toHaveBeenCalledWith({
      workspace_path: '/ws',
      filename: '季度汇报.pptx',
      svg_slides: [SVG_A, SVG_B],
    });
  });

  it('质量门禁阻塞时展示阻塞问题且不显示输出文件', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedRender.mockResolvedValue(BLOCKED_RESULT);
    renderDialog();

    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());
    addPastedSlide(SVG_A);
    fireEvent.click(screen.getByText('生成 PPTX'));

    await waitFor(() =>
      expect(screen.getByTestId('presentation-quality-status')).toHaveTextContent('质量门禁未通过'),
    );
    expect(screen.getByTestId('presentation-quality-blocking')).toHaveTextContent(
      '文本框超出画布边界',
    );
    expect(screen.queryByTestId('presentation-quality-output')).toBeNull();
  });

  it('成功时展示输出文件路径', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedRender.mockResolvedValue(SUCCESS_RESULT);
    renderDialog();

    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());
    addPastedSlide(SVG_A);
    fireEvent.click(screen.getByText('生成 PPTX'));

    await waitFor(() =>
      expect(screen.getByTestId('presentation-quality-output')).toHaveTextContent(
        '/ws/presentation.pptx',
      ),
    );
    expect(mockedToastSuccess).toHaveBeenCalled();
  });

  it('接口异常时展示错误并允许重试', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedRender.mockRejectedValue(new Error('后端不可达'));
    renderDialog();

    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());
    addPastedSlide(SVG_A);
    fireEvent.click(screen.getByText('生成 PPTX'));

    await waitFor(() =>
      expect(screen.getByTestId('presentation-error')).toHaveTextContent('后端不可达'),
    );
    const submit = screen.getByText('生成 PPTX').closest('button') as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });

  it('可以通过上移/下移调整幻灯片顺序', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    renderDialog();
    await waitFor(() => expect(mockedEnv).toHaveBeenCalled());

    addPastedSlide(SVG_A);
    addPastedSlide(SVG_B);

    const items = () => screen.getAllByTestId('presentation-slide-item');
    const firstName = () => items()[0].querySelector('span[title]')?.textContent;

    expect(firstName()).toBe('粘贴的幻灯片 1');
    fireEvent.click(items()[1].querySelector('button[aria-label="上移"]') as HTMLElement);
    expect(firstName()).toBe('粘贴的幻灯片 2');
  });

  it('模板库为空时不显示选择器', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    renderDialog();
    await waitFor(() => expect(mockedTemplates).toHaveBeenCalled());

    expect(screen.queryByTestId('presentation-templates')).toBeNull();
    expect(mockedRefresh).not.toHaveBeenCalled();
  });

  it('按种类分组渲染模板选择器', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedTemplates.mockResolvedValue({
      available: true,
      error: null,
      templates: [template('brand', 'acme'), template('layout', 'brief')],
    });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId('presentation-template-brand')).toBeTruthy());
    expect(screen.getByTestId('presentation-template-layout')).toBeTruthy();
    expect(screen.queryByTestId('presentation-template-style')).toBeNull();
    expect(screen.queryByTestId('presentation-template-deck')).toBeNull();
  });

  it('选中模板后提交 template_ids', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedTemplates.mockResolvedValue({
      available: true,
      error: null,
      templates: [template('brand', 'acme'), template('layout', 'brief')],
    });
    mockedRender.mockResolvedValue({ ...SUCCESS_RESULT, templates_applied: ['acme', 'brief'] });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId('presentation-template-brand')).toBeTruthy());
    addPastedSlide(SVG_STRUCTURED);
    fireEvent.change(screen.getByTestId('presentation-template-brand'), {
      target: { value: 'brand:acme' },
    });
    fireEvent.change(screen.getByTestId('presentation-template-layout'), {
      target: { value: 'layout:brief' },
    });
    fireEvent.click(screen.getByText('生成 PPTX'));

    await waitFor(() => expect(mockedRender).toHaveBeenCalledTimes(1));
    expect(mockedRender).toHaveBeenCalledWith({
      workspace_path: '/ws',
      filename: 'presentation.pptx',
      svg_slides: [SVG_STRUCTURED],
      template_ids: ['brand:acme', 'layout:brief'],
    });
    await waitFor(() =>
      expect(screen.getByTestId('presentation-quality-templates')).toHaveTextContent('acme、brief'),
    );
  });

  it('选版式但 SVG 缺少结构元数据时给出提示', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedTemplates.mockResolvedValue({
      available: true,
      error: null,
      templates: [template('layout', 'brief')],
    });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId('presentation-template-layout')).toBeTruthy());
    addPastedSlide(SVG_A);
    fireEvent.change(screen.getByTestId('presentation-template-layout'), {
      target: { value: 'layout:brief' },
    });

    expect(screen.getByTestId('presentation-template-hint')).toHaveTextContent('data-pptx-layout');
  });

  it('SVG 含结构元数据时不做提示', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedTemplates.mockResolvedValue({
      available: true,
      error: null,
      templates: [template('layout', 'brief')],
    });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId('presentation-template-layout')).toBeTruthy());
    addPastedSlide(SVG_STRUCTURED);
    fireEvent.change(screen.getByTestId('presentation-template-layout'), {
      target: { value: 'layout:brief' },
    });

    expect(screen.queryByTestId('presentation-template-hint')).toBeNull();
  });

  it('刷新模板库后重新加载列表', async () => {
    mockedEnv.mockResolvedValue(READY_ENV);
    mockedTemplates.mockResolvedValueOnce({
      available: true,
      error: null,
      templates: [template('brand', 'acme')],
    });
    mockedRefresh.mockResolvedValue({ available: true, count: 2, error: null });
    mockedTemplates.mockResolvedValueOnce({
      available: true,
      error: null,
      templates: [template('brand', 'acme'), template('brand', 'beta')],
    });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId('presentation-templates-refresh')).toBeTruthy());
    fireEvent.click(screen.getByTestId('presentation-templates-refresh'));

    await waitFor(() => expect(mockedRefresh).toHaveBeenCalledTimes(1));
    await waitFor(() => {
      const options = screen.getByTestId('presentation-template-brand').querySelectorAll('option');
      expect(options).toHaveLength(3); // 不使用 + acme + beta
    });
  });
});
