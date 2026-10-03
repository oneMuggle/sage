/**
 * projectApi: wire contract of the project type / constraint / milestone commands, which were
 * never registered on the bridge before. Shapes mirror backend/api/project_routes.py.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { projectApi } from '../projectApi';

const CONSTRAINT_WIRE = {
  id: 'c1',
  project_id: 'p1',
  category: 'style',
  content: 'no any',
  trigger_pattern: null,
  priority: 5,
  enabled: true,
  created_at: 1,
  updated_at: 2,
};

const MILESTONE_WIRE = {
  id: 'm1',
  project_id: 'p1',
  title: 'Beta',
  description: null,
  stage: 'build',
  due_date: '2026-12-01',
  completed_at: null,
  status: 'pending',
  sort_order: 1,
  created_at: 3,
};

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('projectApi.detectType', () => {
  it('maps project_type and {type, weight} signals to what the UI renders', async () => {
    mockInvoke.mockResolvedValueOnce({
      project_type: 'coding',
      confidence: 0.9,
      signals: [
        { type: 'package.json exists', weight: 0.5 },
        { type: 'tsconfig.json exists', weight: 0.3 },
      ],
    });
    const result = await projectApi.detectType('C:/work/p');
    expect(mockInvoke).toHaveBeenCalledWith('projects_detect_type', { path: 'C:/work/p' });
    expect(result).toEqual({
      detectedType: 'coding',
      confidence: 0.9,
      // The UI joins these into a sentence / renders each as a list item: they must be strings.
      signals: ['package.json exists', 'tsconfig.json exists'],
    });
  });

  it('falls back to a neutral type at zero confidence when nothing was detected', async () => {
    mockInvoke.mockResolvedValueOnce({ project_type: null, confidence: 0, signals: [] });
    expect(await projectApi.detectType('C:/empty')).toEqual({
      detectedType: 'personal',
      confidence: 0,
      signals: [],
    });
  });
});

describe('project-scoped constraint and milestone mutations', () => {
  it('updateConstraint sends projectId and constraintId with the payload', async () => {
    mockInvoke.mockResolvedValueOnce({ ...CONSTRAINT_WIRE, content: 'no any, no ts-ignore' });
    const updated = await projectApi.updateConstraint('p1', 'c1', {
      content: 'no any, no ts-ignore',
    });
    expect(mockInvoke).toHaveBeenCalledWith('projects_update_constraint', {
      projectId: 'p1',
      constraintId: 'c1',
      content: 'no any, no ts-ignore',
    });
    expect(updated).toMatchObject({ id: 'c1', projectId: 'p1', content: 'no any, no ts-ignore' });
  });

  it('deleteConstraint sends projectId and constraintId', async () => {
    mockInvoke.mockResolvedValueOnce({ removed: true });
    expect(await projectApi.deleteConstraint('p1', 'c1')).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith('projects_delete_constraint', {
      projectId: 'p1',
      constraintId: 'c1',
    });
  });

  it('updateMilestone sends projectId and milestoneId with the payload', async () => {
    mockInvoke.mockResolvedValueOnce({ ...MILESTONE_WIRE, status: 'completed' });
    const updated = await projectApi.updateMilestone('p1', 'm1', { status: 'completed' });
    expect(mockInvoke).toHaveBeenCalledWith('projects_update_milestone', {
      projectId: 'p1',
      milestoneId: 'm1',
      status: 'completed',
    });
    expect(updated).toMatchObject({ id: 'm1', projectId: 'p1', status: 'completed', sortOrder: 1 });
  });

  it('deleteMilestone sends projectId and milestoneId', async () => {
    mockInvoke.mockResolvedValueOnce({ removed: true });
    expect(await projectApi.deleteMilestone('p1', 'm1')).toBe(true);
    expect(mockInvoke).toHaveBeenCalledWith('projects_delete_milestone', {
      projectId: 'p1',
      milestoneId: 'm1',
    });
  });
});
