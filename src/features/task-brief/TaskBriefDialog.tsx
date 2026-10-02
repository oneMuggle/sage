import { Dialog } from '@headlessui/react';
import { useCallback, useEffect, useState } from 'react';

import type { AssistantRecommendation, TaskScenario } from '../../entities/welcome/recommendations';
import { projectApi, type ProjectSummary } from '../../shared/api/projectApi';
import { useI18n } from '../../shared/lib/i18n';

import { TaskModelAdvisor } from './TaskModelAdvisor';
import { taskBriefPrompt, type TaskBrief } from './taskBrief';
import { saveTaskRecipe } from './taskRecipes';

interface Props {
  recommendation: AssistantRecommendation;
  initialBrief?: TaskBrief;
  disabled?: boolean;
  onClose: () => void;
  onSubmit: (prompt: string, projectId: string | null, modelId?: string) => Promise<boolean>;
}

export function TaskBriefDialog({
  recommendation,
  initialBrief,
  disabled,
  onClose,
  onSubmit,
}: Props) {
  const { locale } = useI18n();
  const en = locale === 'en';
  const [brief, setBrief] = useState<TaskBrief>(
    initialBrief ?? {
      scenario: recommendation.id as TaskScenario,
      goal:
        locale === 'en'
          ? (recommendation.labels?.en.title ?? recommendation.prompt)
          : recommendation.prompt,
      audience: '',
      sources: '',
      format:
        recommendation.id === 'slides' ? 'pptx' : recommendation.id === 'data' ? 'xlsx' : 'docx',
      requirements: '',
      projectId: null,
    },
  );
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectError, setProjectError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(false);
  const [recipeStatus, setRecipeStatus] = useState<'saved' | 'error' | null>(null);
  const [modelId, setModelId] = useState('');
  const chooseModel = useCallback((id: string) => setModelId(id), []);
  useEffect(() => {
    let active = true;
    projectApi
      .list()
      .then((list) => {
        if (active) setProjects(list);
      })
      .catch(() => {
        if (active) setProjectError(true);
      });
    return () => {
      active = false;
    };
  }, []);
  const set = (key: keyof TaskBrief, value: string | null) =>
    setBrief((current) => ({ ...current, [key]: value }));
  const submit = async () => {
    if (submitting || disabled || !brief.goal.trim()) return;
    setSubmitting(true);
    setError(false);
    try {
      if (await onSubmit(taskBriefPrompt(brief, locale), brief.projectId, modelId || undefined))
        onClose();
      else setError(true);
    } catch {
      setError(true);
    } finally {
      setSubmitting(false);
    }
  };
  const inputClass =
    'w-full mt-1 px-3 py-2 text-ui-base rounded border border-ui-border bg-ui-surface text-ui-foreground';
  return (
    <Dialog
      open
      onClose={() => {
        if (!submitting) onClose();
      }}
      className="relative z-50"
    >
      <div className="fixed inset-0 bg-black/40" aria-hidden="true" />
      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-ui-border bg-ui-bg p-4 shadow-lg">
          <Dialog.Title className="text-ui-xl font-semibold">
            {en ? 'Describe the deliverable' : '明确这次交付'}
          </Dialog.Title>
          <Dialog.Description className="text-ui-sm text-text-secondary mt-1">
            {en
              ? 'This brief starts a task in the existing chat. Permissions and review steps remain unchanged.'
              : '简报将进入现有对话执行流程，不绕过文件权限、审批和验收。'}
          </Dialog.Description>
          <fieldset disabled={submitting} className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="sm:col-span-2 text-ui-sm">
              {en ? 'Goal' : '任务目标'}
              <textarea
                data-testid="task-brief-goal"
                maxLength={16000}
                rows={2}
                value={brief.goal}
                onChange={(event) => set('goal', event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="text-ui-sm">
              {en ? 'Project and file scope' : '项目与文件范围'}
              <select
                data-testid="task-brief-project"
                value={brief.projectId ?? ''}
                className={inputClass}
                onChange={(event) => set('projectId', event.target.value || null)}
              >
                <option value="">
                  {en ? 'No project binding' : '不绑定项目（文件操作需另行确认）'}
                </option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-ui-sm">
              {en ? 'Audience' : '受众'}
              <input
                value={brief.audience}
                maxLength={16000}
                onChange={(event) => set('audience', event.target.value)}
                className={inputClass}
              />
            </label>
            <label className="sm:col-span-2 text-ui-sm">
              {en ? 'Sources and notes' : '资料与要点'}
              <textarea
                rows={3}
                maxLength={16000}
                value={brief.sources}
                onChange={(event) => set('sources', event.target.value)}
                className={inputClass}
              />
              <span className="block text-ui-sm text-text-secondary mt-1">
                {en
                  ? 'Paste notes or name project sources. Files are not automatically uploaded or read; attach them in the chat when required.'
                  : '可粘贴要点或列出项目资料；这里不会自动上传或读取文件，需要时在对话中添加附件。'}
              </span>
            </label>
            <label className="text-ui-sm">
              {en ? 'Output format' : '交付格式'}
              <select
                value={brief.format}
                onChange={(event) => set('format', event.target.value)}
                className={inputClass}
              >
                {['docx', 'xlsx', 'pptx', 'pdf', 'markdown'].map((format) => (
                  <option key={format} value={format}>
                    {format.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-ui-sm">
              {en ? 'Length, style and checks' : '长度、格式与检查要求'}
              <textarea
                rows={2}
                maxLength={16000}
                value={brief.requirements}
                onChange={(event) => set('requirements', event.target.value)}
                className={inputClass}
              />
            </label>
          </fieldset>
          <TaskModelAdvisor needsTools={brief.format !== 'markdown'} onChoose={chooseModel} />
          {recipeStatus && (
            <p
              role="status"
              className={`text-ui-sm mt-2 ${recipeStatus === 'error' ? 'text-error' : 'text-text-secondary'}`}
            >
              {recipeStatus === 'saved'
                ? en
                  ? 'Saved as a draft; no task was executed or verified.'
                  : '已保存为草稿，未执行任务，也未声称通过验收。'
                : en
                  ? 'Recipe save failed; existing data was not overwritten.'
                  : '配方保存失败，未覆盖已有数据。'}
            </p>
          )}
          {projectError && (
            <p role="alert" className="text-ui-sm text-error mt-2">
              {en
                ? 'Project list unavailable. Retry later; no scope has been expanded.'
                : '项目列表读取失败，请稍后重试；没有扩大文件访问范围。'}
            </p>
          )}
          {disabled && (
            <p role="status" className="text-ui-sm text-warning mt-2">
              {en
                ? 'Configure a usable chat model before submitting. Your brief can still be edited.'
                : '请先配置可用的对话模型；可以先填写需求，接入后再提交。'}
            </p>
          )}
          {error && (
            <p role="alert" className="text-ui-sm text-error mt-2">
              {en
                ? 'Task was not started. Check the configuration and retry.'
                : '任务未启动，请检查配置后重试。'}
            </p>
          )}
          <div className="flex flex-wrap justify-end gap-2 mt-4">
            <button
              type="button"
              onClick={() => {
                try {
                  saveTaskRecipe(brief);
                  setRecipeStatus('saved');
                } catch {
                  setRecipeStatus('error');
                }
              }}
              disabled={submitting || !brief.goal.trim()}
              className="px-3 py-2 rounded border border-ui-border text-ui-base"
            >
              {en ? 'Save draft recipe' : '保存配方草稿'}
            </button>
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-3 py-2 rounded border border-ui-border text-ui-base"
            >
              {en ? 'Cancel' : '取消'}
            </button>
            <button
              type="button"
              data-testid="task-brief-submit"
              onClick={() => void submit()}
              disabled={disabled || submitting || !brief.goal.trim()}
              className="px-3 py-2 rounded bg-primary text-text-inverse text-ui-base disabled:opacity-50"
            >
              {submitting
                ? en
                  ? 'Starting…'
                  : '正在启动…'
                : en
                  ? 'Start in chat'
                  : '进入对话执行'}
            </button>
          </div>
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
