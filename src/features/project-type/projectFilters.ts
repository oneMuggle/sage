import type { ProjectStatus, ProjectSummary, ProjectType } from '../../shared/api/projectApiTypes';

export interface OverviewFilters {
  q: string;
  type: ProjectType | 'all';
  status: ProjectStatus | 'all';
  sort: 'recent' | 'name' | 'stage';
}

export function projectStatus(project: ProjectSummary): ProjectStatus {
  return project.status === 'archived' ? 'archived' : 'active';
}

export function projectOverviewType(project: ProjectSummary): ProjectType {
  return project.projectType ?? project.detectedType ?? 'business';
}

export function filterAndSortProjects(
  projects: ProjectSummary[],
  filters: OverviewFilters,
): ProjectSummary[] {
  const q = filters.q.trim().toLowerCase();
  const filtered = projects.filter((project) => {
    if (filters.type !== 'all' && projectOverviewType(project) !== filters.type) return false;
    if (filters.status !== 'all' && projectStatus(project) !== filters.status) return false;
    if (!q) return true;
    const haystack = `${project.name}\n${project.path}\n${project.description ?? ''}`.toLowerCase();
    return haystack.includes(q);
  });
  return [...filtered].sort((a, b) => {
    if (filters.sort === 'name') return a.name.localeCompare(b.name, 'zh-Hans-CN');
    if (filters.sort === 'stage') {
      const aStage = a.projectStage ?? '';
      const bStage = b.projectStage ?? '';
      if (aStage === bStage) return 0;
      if (!aStage) return 1;
      if (!bStage) return -1;
      return aStage.localeCompare(bStage);
    }
    return b.lastOpenedAt - a.lastOpenedAt;
  });
}
