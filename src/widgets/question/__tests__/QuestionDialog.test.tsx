/**
 * QuestionDialog — M2 part B: AskUserQuestion 提问模态框渲染 + 应答行为测试。
 *
 * 策略（与 ApprovalDialog.test.tsx 同约定）:
 *   - mock desktopInvoke.invoke，验证 questions_answer 的调用参数与 store 清理。
 *   - mock sonner.toast，验证 ok=false / 抛错时的错误暴露。
 *   - 用 useQuestionState.setState 直接灌入提问。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useQuestionState } from '../../../entities/question/questionState';
import type { UserQuestion } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import { QuestionDialog } from '../QuestionDialog';

const invokeMock = vi.fn();
vi.mock('../../../shared/api/desktopInvoke', () => ({
  invoke: (...args: unknown[]) => invokeMock(...args),
}));

const toastErrorMock = vi.fn();
vi.mock('sonner', () => ({
  toast: { error: (...args: unknown[]) => toastErrorMock(...args) },
}));

function makeQuestion(overrides: Partial<UserQuestion> = {}): UserQuestion {
  return {
    request_id: 'q-42',
    question: '选择输出格式?',
    header: '输出格式',
    options: [
      { label: 'Markdown', description: '纯文本报告' },
      { label: 'PDF', description: '排版文档' },
    ],
    multi_select: false,
    created_at: 1753718400.123,
    ...overrides,
  };
}

function renderDialog(): void {
  render(
    <I18nProvider>
      <QuestionDialog />
    </I18nProvider>,
  );
}

function seedQuestion(overrides: Partial<UserQuestion> = {}): UserQuestion {
  const q = makeQuestion(overrides);
  useQuestionState.getState().setFromEvent(q);
  return q;
}

function optionInput(index: number): HTMLInputElement {
  const label = screen.getByTestId(`question-option-${index}`);
  return label.querySelector('input') as HTMLInputElement;
}

beforeEach(() => {
  invokeMock.mockReset();
  toastErrorMock.mockReset();
  invokeMock.mockResolvedValue({ ok: true });
  useQuestionState.setState({ currentQuestion: null });
});

describe('QuestionDialog', () => {
  it('renders nothing when no question is pending', () => {
    renderDialog();
    expect(screen.queryByTestId('question-dialog')).toBeNull();
  });

  it('renders question text, header chip and option cards with descriptions', () => {
    seedQuestion();
    renderDialog();

    expect(screen.getByTestId('question-dialog')).toBeInTheDocument();
    expect(screen.getByTestId('question-header')).toHaveTextContent('输出格式');
    expect(screen.getByTestId('question-text')).toHaveTextContent('选择输出格式?');
    expect(screen.getByTestId('question-option-0')).toHaveTextContent('Markdown');
    expect(screen.getByTestId('question-option-0')).toHaveTextContent('纯文本报告');
    expect(screen.getByTestId('question-option-1')).toHaveTextContent('PDF');
    // 单选 → radio 语义
    expect(optionInput(0).type).toBe('radio');
  });

  it('uses checkbox semantics and shows multi hint for multi_select', () => {
    seedQuestion({ multi_select: true });
    renderDialog();

    expect(optionInput(0).type).toBe('checkbox');
    expect(optionInput(1).type).toBe('checkbox');
    expect(screen.getByTestId('question-text')).toHaveTextContent('可多选');
  });

  it('submit is disabled until a selection or custom text exists', () => {
    seedQuestion();
    renderDialog();

    const submit = screen.getByTestId('question-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);

    fireEvent.click(optionInput(1));
    expect((screen.getByTestId('question-submit') as HTMLButtonElement).disabled).toBe(false);
  });

  it('single-select submit invokes questions_answer with the selected label', async () => {
    seedQuestion({ request_id: 'q-single' });
    renderDialog();

    fireEvent.click(optionInput(1)); // PDF
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-single',
        answers: ['PDF'],
        custom: null,
      });
    });
    await waitFor(() => {
      expect(useQuestionState.getState().currentQuestion).toBeNull();
    });
    expect(screen.queryByTestId('question-dialog')).toBeNull();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it('single-select switches selection (last click wins)', async () => {
    seedQuestion({ request_id: 'q-switch' });
    renderDialog();

    fireEvent.click(optionInput(0));
    fireEvent.click(optionInput(1));
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-switch',
        answers: ['PDF'],
        custom: null,
      });
    });
  });

  it('multi-select submits all selections in option order', async () => {
    seedQuestion({ request_id: 'q-multi', multi_select: true });
    renderDialog();

    // 逆序点击 → 输出仍按选项原始顺序
    fireEvent.click(optionInput(1));
    fireEvent.click(optionInput(0));
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-multi',
        answers: ['Markdown', 'PDF'],
        custom: null,
      });
    });
  });

  it('custom text alone enables submit and is forwarded', async () => {
    seedQuestion({ request_id: 'q-custom' });
    renderDialog();

    fireEvent.change(screen.getByTestId('question-custom'), {
      target: { value: '用 HTML' },
    });
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-custom',
        answers: [],
        custom: '用 HTML',
      });
    });
    await waitFor(() => {
      expect(useQuestionState.getState().currentQuestion).toBeNull();
    });
  });

  it('selection + custom text are submitted together', async () => {
    seedQuestion({ request_id: 'q-both' });
    renderDialog();

    fireEvent.click(optionInput(0));
    fireEvent.change(screen.getByTestId('question-custom'), {
      target: { value: '附带说明' },
    });
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-both',
        answers: ['Markdown'],
        custom: '附带说明',
      });
    });
  });

  it('Escape submits an empty answer (timeout semantics) and closes', async () => {
    seedQuestion({ request_id: 'q-escape' });
    renderDialog();

    fireEvent.keyDown(screen.getByTestId('question-dialog').parentElement!, {
      key: 'Escape',
    });

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalledWith('questions_answer', {
        requestId: 'q-escape',
        answers: [],
        custom: null,
      });
    });
    await waitFor(() => {
      expect(useQuestionState.getState().currentQuestion).toBeNull();
    });
  });

  it('surfaces toast but still closes when backend answers ok=false', async () => {
    invokeMock.mockResolvedValueOnce({ ok: false, error: 'unknown_or_expired' });
    seedQuestion({ request_id: 'q-expired' });
    renderDialog();

    fireEvent.click(optionInput(0));
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    expect(String(toastErrorMock.mock.calls[0][0])).toContain('unknown_or_expired');
    await waitFor(() => {
      expect(useQuestionState.getState().currentQuestion).toBeNull();
    });
  });

  it('surfaces toast but still closes when invoke throws (IPC failure)', async () => {
    invokeMock.mockRejectedValueOnce(new Error('bridge down'));
    seedQuestion({ request_id: 'q-ipc-fail' });
    renderDialog();

    fireEvent.click(optionInput(0));
    fireEvent.click(screen.getByTestId('question-submit'));

    await waitFor(() => {
      expect(toastErrorMock).toHaveBeenCalled();
    });
    expect(String(toastErrorMock.mock.calls[0][0])).toContain('bridge down');
    await waitFor(() => {
      expect(useQuestionState.getState().currentQuestion).toBeNull();
    });
  });

  it('resets selection and custom text when a new question arrives', async () => {
    seedQuestion({ request_id: 'q-a' });
    const { rerender } = render(
      <I18nProvider>
        <QuestionDialog />
      </I18nProvider>,
    );

    fireEvent.click(optionInput(0));
    fireEvent.change(screen.getByTestId('question-custom'), { target: { value: 'abc' } });
    expect(optionInput(0).checked).toBe(true);

    // 新提问替换 — 组件不卸载，局部 state 必须重置
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-b' }));
    rerender(
      <I18nProvider>
        <QuestionDialog />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(optionInput(0).checked).toBe(false);
    });
    expect((screen.getByTestId('question-custom') as HTMLInputElement).value).toBe('');
    expect((screen.getByTestId('question-submit') as HTMLButtonElement).disabled).toBe(true);
  });

  it('does not close a newer question when an older submit is still in flight', async () => {
    // 审查加固回归: Q1 提交在途时 Q2 到达 → Q1 的 finally 不得清掉 Q2
    seedQuestion({ request_id: 'q-1' });
    renderDialog();

    let resolveInvoke: (value: unknown) => void = () => {};
    invokeMock.mockReturnValue(
      new Promise((resolve) => {
        resolveInvoke = resolve;
      }),
    );

    fireEvent.click(optionInput(0));
    fireEvent.click(screen.getByTestId('question-submit'));

    // invoke 在途期间 Q2 替换 store
    useQuestionState.getState().setFromEvent(makeQuestion({ request_id: 'q-2' }));

    // Q1 的 invoke 解析 → finally 必须跳过 resolve（store 里已是 q-2）
    resolveInvoke({ ok: true });

    await waitFor(() => {
      expect(invokeMock).toHaveBeenCalled();
    });
    expect(useQuestionState.getState().currentQuestion?.request_id).toBe('q-2');
  });
});
