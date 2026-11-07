import { useCallback, useEffect, useState } from 'react';

import { getArchetypeBlueprint } from '../../features/project-type/archetypeBlueprints';
import {
  memoryApi,
  projectApi,
  type ProjectMilestone,
  type ProjectScaffoldResult,
  type ProjectSummary,
  type ProjectType,
} from '../../shared/api';
import type { ProjectProfileEntry } from '../../shared/api/types';

export interface BootstrapProgress {
  steps: Array<{ id: string; label: string; done: boolean }>;
  done: number;
  total: number;
}

export function computeBootstrapProgress(project: ProjectSummary): BootstrapProgress {
  const applied = project.bootstrapState?.applied ?? [];
  const steps = [
    {
      id: 'metadata',
      label: '基本信息',
      done: applied.some((item) => item.startsWith('metadata.')) || Boolean(project.description),
    },
    { id: 'sage_md', label: '项目说明', done: applied.includes('sage_md') },
    { id: 'rule', label: '项目规则', done: applied.includes('rule') },
    { id: 'milestones', label: '里程碑', done: applied.includes('milestones') },
    { id: 'git', label: '版本控制', done: applied.includes('git_init') || project.vcsMode === 'git' },
  ];
  return { steps, done: steps.filter((step) => step.done).length, total: steps.length };
}

export interface GovernanceData {
  project: ProjectSummary | null;
  milestones: ProjectMilestone[];
  profileEntries: ProjectProfileEntry[];
  activeProjectType: ProjectType;
  bootstrapProgress: BootstrapProgress;
  upcomingDeadline: { title: string; dueDate: string; daysLeft: number } | null;
  scaffoldResult: ProjectScaffoldResult | null;
  scaffolding: boolean;
  startingSession: boolean;
  savingPaths: boolean;
  newAllowedPath: string;
  setNewAllowedPath: (value: string) => void;
  savingProfile: boolean;
  profileCategory: string;
  setProfileCategory: (value: string) => void;
  profileDraft: string;
  setProfileDraft: (value: string) => void;
  reload: () => Promise<void>;
  reloadMilestones: () => Promise<void>;
  changeProjectType: (next: ProjectType) => Promise<void>;
  changeProjectStage: (next: string) => Promise<void>;
  changeVcsMode: (next: 'git' | 'builtin') => Promise<void>;
  scaffold: () => Promise<void>;
  startSession: () => Promise<string | null>;
  addProfileEntry: () => Promise<void>;
  deleteProfileEntry: (entryId: string) => Promise<void>;
  addAllowedPath: () => Promise<void>;
  quickAddPresetPath: (pattern: string) => Promise<void>;
  removeAllowedPath: (targetPath: string) => Promise<void>;
}

export function useGovernanceProject(projectId: string | undefined): GovernanceData {
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);
  const [profileEntries, setProfileEntries] = useState<ProjectProfileEntry[]>([]);
  const [scaffoldResult, setScaffoldResult] = useState<ProjectScaffoldResult | null>(null);
  const [scaffolding, setScaffolding] = useState(false);
  const [startingSession, setStartingSession] = useState(false);
  const [savingPaths, setSavingPaths] = useState(false);
  const [newAllowedPath, setNewAllowedPath] = useState('');
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileCategory, setProfileCategory] = useState('convention');
  const [profileDraft, setProfileDraft] = useState('');

  const reload = useCallback(async () => {
    try {
      const list = await projectApi.list();
      setProject(Array.isArray(list) ? (list.find((p) => p.id === projectId) ?? null) : null);
    } catch {
      setProject(null);
    }
  }, [projectId]);

  const reloadMilestones = useCallback(async () => {
    if (!project?.id) return;
    try {
      const items = await projectApi.listMilestones(project.id);
      setMilestones(Array.isArray(items) ? items : []);
    } catch {
      setMilestones([]);
    }
  }, [project?.id]);

  const loadProfile = useCallback(async (projectPath?: string) => {
    if (!projectPath) return;
    try {
      const res = await memoryApi.getProjectProfile({ projectKey: projectPath });
      setProfileEntries(res?.items ?? []);
    } catch {
      setProfileEntries([]);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void reloadMilestones();
  }, [reloadMilestones]);

  useEffect(() => {
    if (project?.path) void loadProfile(project.path);
  }, [project?.path, loadProfile]);

  const activeProjectType: ProjectType = (project?.projectType ??
    project?.detectedType ??
    'business') as ProjectType;

  const upcomingDeadline = (() => {
    const withDue = milestones
      .filter((m) => m.status !== 'completed' && m.dueDate)
      .sort((a, b) => String(a.dueDate).localeCompare(String(b.dueDate)));
    const next = withDue[0];
    if (!next?.dueDate) return null;
    const dueMs = Date.parse(`${next.dueDate}T23:59:59`);
    if (Number.isNaN(dueMs)) return null;
    return {
      title: next.title,
      dueDate: next.dueDate,
      daysLeft: Math.ceil((dueMs - Date.now()) / (1000 * 60 * 60 * 24)),
    };
  })();

  const changeProjectType = async (nextType: ProjectType) => {
    if (!project) return;
    try {
      const nextStage = getArchetypeBlueprint(nextType).stages[0]?.id ?? null;
      setProject(await projectApi.update(project.id, { project_type: nextType, project_stage: nextStage }));
    } catch {
      /* 保持旧值 */
    }
  };

  const changeProjectStage = async (nextStage: string) => {
    if (!project) return;
    try {
      setProject(await projectApi.update(project.id, { project_stage: nextStage }));
    } catch {
      /* 保持旧值 */
    }
  };

  const changeVcsMode = async (nextVcs: 'git' | 'builtin') => {
    if (!project) return;
    try {
      setProject(await projectApi.update(project.id, { vcs_mode: nextVcs }));
    } catch {
      /* 保持旧值 */
    }
  };

  const scaffold = async () => {
    if (!project || scaffolding) return;
    setScaffolding(true);
    setScaffoldResult(null);
    try {
      const res = await projectApi.scaffold(project.id, {
        projectType: activeProjectType,
        createDirectories: true,
        createSageMd: true,
        importDefaultConstraints: true,
        seedDefaultMilestones: true,
      });
      setScaffoldResult(res);
      setProject(res.project);
      await reloadMilestones();
    } catch {
      /* 初始化失败时保留原状态 */
    } finally {
      setScaffolding(false);
    }
  };

  const startSession = async (): Promise<string | null> => {
    if (!project || startingSession) return null;
    setStartingSession(true);
    try {
      const opened = await projectApi.open(project.id);
      return opened.session?.id ?? null;
    } catch {
      return null;
    } finally {
      setStartingSession(false);
    }
  };

  const addProfileEntry = async () => {
    const content = profileDraft.trim();
    if (!project?.path || !content || savingProfile) return;
    setSavingProfile(true);
    try {
      await memoryApi.createProjectProfile(content, {
        projectKey: project.path,
        category: profileCategory,
        importance: 5,
      });
      setProfileDraft('');
      await loadProfile(project.path);
    } catch {
      /* 保留草稿供重试 */
    } finally {
      setSavingProfile(false);
    }
  };

  const deleteProfileEntry = async (entryId: string) => {
    if (!project?.path) return;
    try {
      await memoryApi.deleteProjectProfile(entryId);
      await loadProfile(project.path);
    } catch {
      /* 保留列表 */
    }
  };

  const persistAllowedPaths = async (next: string[]) => {
    if (!project) return;
    setSavingPaths(true);
    try {
      const saved = await projectApi.updateAllowedPaths(project.id, next);
      setProject({ ...project, allowedPaths: saved });
    } catch {
      /* 保持旧值 */
    } finally {
      setSavingPaths(false);
    }
  };

  const addAllowedPath = async () => {
    const trimmed = newAllowedPath.trim();
    if (!project || !trimmed) return;
    const current = project.allowedPaths ?? [];
    if (current.includes(trimmed)) {
      setNewAllowedPath('');
      return;
    }
    await persistAllowedPaths([...current, trimmed]);
    setNewAllowedPath('');
  };

  const quickAddPresetPath = async (pattern: string) => {
    const trimmed = pattern.trim();
    if (!project || !trimmed) return;
    const current = project.allowedPaths ?? [];
    if (current.includes(trimmed)) return;
    await persistAllowedPaths([...current, trimmed]);
  };

  const removeAllowedPath = async (targetPath: string) => {
    if (!project) return;
    const current = project.allowedPaths ?? [];
    await persistAllowedPaths(current.filter((item) => item !== targetPath));
  };

  return {
    project,
    milestones,
    profileEntries,
    activeProjectType,
    bootstrapProgress: project ? computeBootstrapProgress(project) : { steps: [], done: 0, total: 0 },
    upcomingDeadline,
    scaffoldResult,
    scaffolding,
    startingSession,
    savingPaths,
    newAllowedPath,
    setNewAllowedPath,
    savingProfile,
    profileCategory,
    setProfileCategory,
    profileDraft,
    setProfileDraft,
    reload,
    reloadMilestones,
    changeProjectType,
    changeProjectStage,
    changeVcsMode,
    scaffold,
    startSession,
    addProfileEntry,
    deleteProfileEntry,
    addAllowedPath,
    quickAddPresetPath,
    removeAllowedPath,
  };
}
