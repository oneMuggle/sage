import { describe, expect, it } from 'vitest';

import type { ProjectSummary } from '../../../shared/api/projectApiTypes';
import { filterAndSortProjects, projectStatus } from '../../../features/project-type/projectFilters';

function p(over: Partial<ProjectSummary>): ProjectSummary {
  return {
    id: over.id ?? 'p-1',
    path: over.path ?? '/w/a',
    name: over.name ?? 'Alpha',
    createdAt: 1,
    lastOpenedAt: over.lastOpenedAt ?? 10,
    sessionCount: 0,
    lastSessionId: null,
    allowedPaths: [],
    ...over,
  };
}

const base = { q: '', type: 'all', status: 'all', sort: 'recent' } as const;

describe('projectStatus', () => {
  it('treats missing status as active', () => {
    expect(projectStatus(p({}))).toBe('active');
  });
  it('returns archived when backend says so', () => {
    expect(projectStatus(p({ status: 'archived' }))).toBe('archived');
  });
});

describe('filterAndSortProjects', () => {
  it('matches query against name, path and description', () => {
    const list = [
      p({ id: '1', name: 'Sage', path: '/w/sage' }),
      p({ id: '2', name: 'Paper', path: '/w/latex', description: '论文投稿' }),
    ];
    expect(filterAndSortProjects(list, { ...base, q: 'sage' }).map((x) => x.id)).toEqual(['1']);
    expect(filterAndSortProjects(list, { ...base, q: '论文' }).map((x) => x.id)).toEqual(['2']);
  });

  it('filters by explicit type and falls back to detectedType', () => {
    const list = [p({ id: '1', projectType: 'coding' }), p({ id: '2', detectedType: 'research' })];
    expect(filterAndSortProjects(list, { ...base, type: 'research' }).map((x) => x.id)).toEqual([
      '2',
    ]);
  });

  it('filters archived and active separately', () => {
    const list = [p({ id: '1' }), p({ id: '2', status: 'archived' as const })];
    expect(filterAndSortProjects(list, { ...base, status: 'archived' }).map((x) => x.id)).toEqual([
      '2',
    ]);
    expect(filterAndSortProjects(list, { ...base, status: 'active' }).map((x) => x.id)).toEqual([
      '1',
    ]);
  });

  it('sorts by recent, name and stage with empty stage last', () => {
    const list = [
      p({ id: '1', name: 'Beta', lastOpenedAt: 5, projectStage: 'dev' }),
      p({ id: '2', name: 'Alpha', lastOpenedAt: 30, projectStage: null }),
      p({ id: '3', name: 'Gamma', lastOpenedAt: 12, projectStage: 'design' }),
    ];
    expect(filterAndSortProjects(list, base).map((x) => x.id)).toEqual(['2', '3', '1']);
    expect(filterAndSortProjects(list, { ...base, sort: 'name' }).map((x) => x.id)).toEqual([
      '2',
      '1',
      '3',
    ]);
    expect(filterAndSortProjects(list, { ...base, sort: 'stage' }).map((x) => x.id)).toEqual([
      '3',
      '1',
      '2',
    ]);
  });

  it('does not mutate the input array', () => {
    const list = [p({ id: '1', lastOpenedAt: 1 }), p({ id: '2', lastOpenedAt: 2 })];
    filterAndSortProjects(list, base);
    expect(list.map((x) => x.id)).toEqual(['1', '2']);
  });
});
