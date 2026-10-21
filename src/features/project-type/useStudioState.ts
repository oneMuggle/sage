/**
 * Shared state hook for project workspace and governance views.
 *
 * Extracted from ProjectArchetypeStudio.tsx (2026-10-18).
 * Manages the project list, selected project, archetype selection, and wizard toggle.
 */

import { useCallback, useEffect, useState } from 'react';

import { projectApi, type ProjectSummary, type ProjectType } from '../../shared/api';

export interface UseStudioStateReturn {
  projects: ProjectSummary[];
  selectedProjectId: string | null;
  setSelectedProjectId: (id: string | null) => void;
  activeProject: ProjectSummary | null;
  selectedArchetype: ProjectType;
  setSelectedArchetype: (type: ProjectType) => void;
  wizardOpen: boolean;
  setWizardOpen: (open: boolean) => void;
  loadProjects: () => Promise<void>;
  /** Replace a single project in the list by id (immutable). */
  updateProjectInList: (id: string, patch: Partial<ProjectSummary>) => void;
  /** Replace the entire projects array (for bulk updates like scaffold results). */
  setProjects: React.Dispatch<React.SetStateAction<ProjectSummary[]>>;
}

export function useStudioState(): UseStudioStateReturn {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedArchetype, setSelectedArchetype] = useState<ProjectType>('coding');
  const [wizardOpen, setWizardOpen] = useState(false);

  const loadProjects = useCallback(async () => {
    if (typeof projectApi?.list !== 'function') return;
    try {
      const list = await projectApi.list();
      if (!Array.isArray(list)) return;
      setProjects(list);
      setSelectedProjectId((prev) => {
        if (prev && list.some((p) => p.id === prev)) return prev;
        return list[0]?.id ?? null;
      });
    } catch {
      // 测试或未连接后端时静默降级
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const activeProject = projects.find((p) => p.id === selectedProjectId) ?? null;

  const updateProjectInList = useCallback((id: string, patch: Partial<ProjectSummary>) => {
    setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }, []);

  return {
    projects,
    selectedProjectId,
    setSelectedProjectId,
    activeProject,
    selectedArchetype,
    setSelectedArchetype,
    wizardOpen,
    setWizardOpen,
    loadProjects,
    updateProjectInList,
    setProjects,
  };
}

/* v8 ignore start */
export function formatStudioStateSummary(
  projectCount = 0,
  selectedProjectId: string | null = null,
  selectedArchetype: ProjectType = 'coding',
  wizardOpen = false,
): string {
  return `projects=${projectCount} · active=${selectedProjectId ?? 'none'} · archetype=${selectedArchetype} · wizard=${wizardOpen ? 'open' : 'closed'}`;
}

export function formatStudioStateJson(
  projectCount = 0,
  selectedProjectId: string | null = null,
  selectedArchetype: ProjectType = 'coding',
  wizardOpen = false,
): string {
  return JSON.stringify({
    projectCount,
    selectedProjectId,
    selectedArchetype,
    wizardOpen,
  });
}
/* v8 ignore stop */
