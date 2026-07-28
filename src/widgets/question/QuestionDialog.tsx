/**
 * QuestionDialog — M2 part B: AskUserQuestion 全局提问模态框。
 *
 * 当 `useQuestionState.currentQuestion` 非空时渲染（由 useChat 消费
 * `state: 'ask_user_question'` 流事件写入 store）。用户选择选项 / 填写
 * "其他"文本后点「提交」→ `invoke('questions_answer', {requestId,
 * answers, custom})` → 无论成败都 resolve() 关闭对话框：
 *
 *   - ok=false（unknown_or_expired / question_gate_not_initialized）
 *     说明后端 gate 已自行超时，agent 已带着"用户未回答"软结果继续跑。
 *   - invoke 抛错（IPC/HTTP 故障）同理：后端 300s 后按空应答处理，
 *     对话框一直挂着只会误导用户。
 *
 * Escape = 空提交（answers=[], custom=null），等价于超时语义 —— agent
 * 收到"用户未回答，请自行决定合理默认值"后继续，不卡住。
 *
 * 错误通过 sonner toast 暴露（与 ApprovalDialog 一致）。
 */
import { HelpCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useQuestionState } from '../../entities/question/questionState';
import { invoke } from '../../shared/api/desktopInvoke';
import { useI18n } from '../../shared/lib/i18n';

/** questions_answer 应答体（HTTP 恒 200，ok 字段区分成败） */
interface AnswerResponse {
  ok: boolean;
  error?: string;
}

export function QuestionDialog() {
  const { t } = useI18n();
  const currentQuestion = useQuestionState((s) => s.currentQuestion);
  const resolve = useQuestionState((s) => s.resolve);
  // 已选选项 label（不可变数组；single-select 时替换，multi-select 时切换）
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [custom, setCustom] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // 新提问到达时重置上一个提问遗留的局部 state（store 直接替换
  // currentQuestion，组件不卸载，必须显式重置）
  const requestId = currentQuestion?.request_id ?? null;
  useEffect(() => {
    setSelected([]);
    setCustom('');
    setSubmitting(false);
  }, [requestId]);

  if (!currentQuestion) return null;

  const multi = currentQuestion.multi_select;
  const customText = custom.trim();
  const canSubmit = selected.length > 0 || customText.length > 0;

  const toggleOption = (label: string): void => {
    setSelected((prev) => {
      if (!multi) return [label]; // 单选：直接替换
      return prev.includes(label) ? prev.filter((l) => l !== label) : [...prev, label];
    });
  };

  const submit = async (answers: readonly string[], customValue: string | null): Promise<void> => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const resp = await invoke<AnswerResponse>('questions_answer', {
        requestId: currentQuestion.request_id,
        answers,
        custom: customValue,
      });
      if (!resp || resp.ok !== true) {
        toast.error(`${t('question.toast.failed')}: ${resp?.error ?? 'unknown'}`);
      }
    } catch (err) {
      toast.error(
        `${t('question.toast.failed')}: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      // 无论 ok/error 都关闭 — 理由见文件头注
      resolve();
    }
  };

  const onSubmitClick = (): void => {
    // 按选项原始顺序输出选中项（而非点击顺序），结果稳定可测
    const ordered = currentQuestion.options
      .map((o) => o.label)
      .filter((label) => selected.includes(label));
    void submit(ordered, customText.length > 0 ? customText : null);
  };

  const onKeyDown = (e: React.KeyboardEvent): void => {
    // Escape = 空提交（= 超时语义；不做静默关闭，后端软结果一致）
    if (e.key === 'Escape') void submit([], null);
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      role="presentation"
      onKeyDown={onKeyDown}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('question.title')}
        data-testid="question-dialog"
        className="bg-surface border border-border rounded-lg w-full max-w-md mx-4 p-5 shadow-xl"
      >
        <div className="flex items-center gap-2 mb-3">
          <HelpCircle className="w-4 h-4 text-primary shrink-0" aria-hidden="true" />
          <h3 className="text-sm font-semibold text-text">{t('question.title')}</h3>
          {currentQuestion.header ? (
            <span
              data-testid="question-header"
              className="ml-auto px-2 py-0.5 text-xs rounded border border-primary/40 bg-primary/10 text-primary"
            >
              {currentQuestion.header}
            </span>
          ) : null}
        </div>

        <div className="space-y-3">
          <p data-testid="question-text" className="text-sm text-text leading-relaxed">
            {currentQuestion.question}
            {multi ? (
              <span className="ml-1 text-xs text-text-secondary">{t('question.multi_hint')}</span>
            ) : null}
          </p>

          <div role={multi ? 'group' : 'radiogroup'} className="space-y-2">
            {currentQuestion.options.map((opt, index) => {
              const checked = selected.includes(opt.label);
              return (
                <label
                  key={`${opt.label}-${index}`}
                  data-testid={`question-option-${index}`}
                  className={`flex items-start gap-2 p-2.5 rounded border cursor-pointer select-none transition-colors ${
                    checked
                      ? 'border-primary bg-primary/10'
                      : 'border-border hover:bg-bg-hover'
                  }`}
                >
                  <input
                    type={multi ? 'checkbox' : 'radio'}
                    name={`question-options-${currentQuestion.request_id}`}
                    checked={checked}
                    onChange={() => toggleOption(opt.label)}
                    className="mt-0.5 w-3.5 h-3.5 accent-primary"
                  />
                  <span className="min-w-0">
                    <span className="block text-sm text-text">{opt.label}</span>
                    {opt.description ? (
                      <span className="block text-xs text-text-secondary mt-0.5">
                        {opt.description}
                      </span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </div>

          <div>
            <label
              htmlFor={`question-custom-${currentQuestion.request_id}`}
              className="block text-xs text-text-secondary mb-1"
            >
              {t('question.custom.label')}
            </label>
            <input
              id={`question-custom-${currentQuestion.request_id}`}
              type="text"
              data-testid="question-custom"
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              placeholder={t('question.custom.placeholder')}
              className="w-full px-2.5 py-1.5 text-sm rounded border border-border bg-bg text-text placeholder:text-text-secondary focus:outline-none focus:border-primary"
            />
          </div>

          <div className="flex justify-end pt-1">
            <button
              type="button"
              data-testid="question-submit"
              disabled={!canSubmit || submitting}
              onClick={onSubmitClick}
              className="px-3 py-1.5 text-xs bg-primary text-text-inverse rounded hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {t('question.submit')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
