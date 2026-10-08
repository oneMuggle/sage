import { describe, expect, it } from 'vitest';

import { taskBriefPrompt, type TaskBrief } from '../taskBrief';
const brief: TaskBrief = {
  scenario: 'report',
  goal: 'A report',
  audience: 'Leads',
  sources: 'provided notes',
  format: 'docx',
  requirements: 'APA and 3 pages',
  projectId: null,
};
describe('deliverable task brief', () => {
  it('keeps requirements and source-access limitations explicit', () => {
    const result = taskBriefPrompt(brief, 'en');
    expect(result).toContain('Deliverable: docx');
    expect(result).toContain('APA and 3 pages');
    expect(result).toContain('Naming a file is not an upload');
    expect(result).toContain('existing approvals');
    expect(result).toContain('Never invent completed checks');
  });
  it('rejects empty, overlong and unsupported requests', () => {
    expect(() => taskBriefPrompt({ ...brief, goal: ' ' })).toThrow();
    expect(() => taskBriefPrompt({ ...brief, sources: 'x'.repeat(16001) })).toThrow();
    expect(() => taskBriefPrompt({ ...brief, format: 'exe' as TaskBrief['format'] })).toThrow();
  });
});
