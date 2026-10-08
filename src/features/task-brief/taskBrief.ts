import type { TaskScenario } from '../../entities/welcome/recommendations';

export interface TaskBrief {
  scenario: TaskScenario;
  goal: string;
  audience: string;
  sources: string;
  format: 'docx' | 'xlsx' | 'pptx' | 'pdf' | 'markdown';
  requirements: string;
  projectId: string | null;
}

/** User-visible requirements, not a claim that a named file has been uploaded/read. */
export function taskBriefPrompt(brief: TaskBrief, locale = 'zh'): string {
  if (!brief.goal.trim()) throw new Error('A task goal is required');
  if (
    !['report', 'organize', 'data', 'slides', 'coding'].includes(brief.scenario) ||
    !['docx', 'xlsx', 'pptx', 'pdf', 'markdown'].includes(brief.format)
  )
    throw new Error('Unsupported task or output format');
  const fields = [brief.goal, brief.audience, brief.sources, brief.requirements];
  if (fields.some((field) => field.length > 16000)) throw new Error('Brief field is too long');
  const english = locale === 'en';
  const labels = english
    ? ['Goal', 'Audience', 'Sources to use', 'Deliverable', 'Requirements']
    : ['任务目标', '受众', '参考资料', '交付格式', '格式与检查要求'];
  const values = [
    brief.goal.trim(),
    brief.audience.trim(),
    brief.sources.trim(),
    brief.format,
    brief.requirements.trim(),
  ];
  return (
    labels
      .map(
        (label, index) =>
          `${label}: ${values[index] || (english ? 'Please clarify if needed' : '必要时先澄清')}`,
      )
      .join('\n') +
    '\n\n' +
    (english
      ? 'Before executing, confirm missing inputs and source access. Naming a file is not an upload or proof that it was read. For substantial work, propose an outline first. Use existing approvals for file changes. Deliver editable files where supported, and separately report generation, formatting checks, source verification, and review status. Never invent completed checks or sources.'
      : '执行前确认缺失输入及资料访问范围。列出文件名不等于已上传或已读取，不得假装使用未提供的资料。复杂任务先给出可调整的大纲，文件变更遵守既有审批。按能力交付可编辑文件，分别报告生成结果、格式检查、来源核验及待验收事项，不得虚构检查完成或引用来源。')
  );
}
