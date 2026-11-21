/**
 * Design Studio Store — Zustand state management
 *
 * Manages: systems, templates, projects list, current project,
 * current artifact, loading/error states.
 */
import { create } from 'zustand';

import * as api from './designApi';
import type {
  ChartSpec,
  CreateProjectInput,
  DesignArtifact,
  DesignArtifactSummary,
  DesignProject,
  DesignSourceBinding,
  DesignSystem,
  DesignTemplate,
  EmbedChartResult,
  GenerationProgress,
  IterationMessage,
  ProjectTweaks,
  ReviewResult,
} from './types';

interface DesignState {
  // -- 元数据（系统 & 模板） --
  systems: DesignSystem[];
  templates: DesignTemplate[];
  loadingMeta: boolean;
  errorMeta: string | null;

  // -- 项目列表 --
  projects: DesignProject[];
  loadingProjects: boolean;
  errorProjects: string | null;

  // -- 当前项目 & 产物 --
  currentProject: DesignProject | null;
  currentArtifact: DesignArtifact | null;
  /** 正在只读预览的历史版本（null = 跟随最新版本） */
  previewArtifact: DesignArtifact | null;
  /** 版本对比对（左=更早版本，右=当前选择版本） */
  comparePair: { left: DesignArtifact; right: DesignArtifact } | null;
  messages: IterationMessage[];
  artifacts: DesignArtifactSummary[];
  tweaks: ProjectTweaks;
  /** 数据源绑定（未绑定时 null） */
  sourceBinding: DesignSourceBinding | null;
  /** 最近一次质量评审结果 */
  review: ReviewResult | null;
  /** 生成阶段进度（loading 期间由轮询更新，结束后清空） */
  generationProgress: GenerationProgress | null;
  loadingProject: boolean;
  errorProject: string | null;

  // -- Actions --
  loadMeta: () => Promise<void>;
  loadProjects: (kind?: 'deck' | 'prototype') => Promise<void>;
  loadProject: (projectId: string) => Promise<void>;
  createProject: (input: CreateProjectInput) => Promise<DesignProject>;
  deleteProject: (projectId: string) => Promise<void>;
  generate: (projectId: string, brief?: string) => Promise<void>;
  iterate: (projectId: string, feedback: string) => Promise<void>;
  previewVersion: (projectId: string, artifactId: string) => Promise<void>;
  compareVersion: (projectId: string, artifactId: string) => Promise<void>;
  clearCompare: () => void;
  restoreVersion: (projectId: string, artifactId: string) => Promise<void>;
  updateTweaksLocal: (patch: Partial<ProjectTweaks>) => void;
  persistTweaks: (projectId: string) => Promise<void>;
  applyTweaksPreset: (projectId: string, tweaks: ProjectTweaks) => Promise<void>;
  bindSource: (projectId: string, filePath: string) => Promise<void>;
  unbindSource: (projectId: string) => Promise<void>;
  refreshWithSource: (projectId: string) => Promise<void>;
  embedChart: (projectId: string, chart: ChartSpec) => Promise<EmbedChartResult | null>;
  runReview: (projectId: string) => Promise<ReviewResult | null>;
  clearPreview: () => void;
  clearCurrent: () => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

/** 生成期间轮询阶段进度；返回停止函数。 */
const PROGRESS_POLL_MS = 800;

function startProgressPolling(
  projectId: string,
  set: (partial: Partial<DesignState>) => void,
): () => void {
  const timer = setInterval(() => {
    void api
      .getProgress(projectId)
      .then((progress) => set({ generationProgress: progress }))
      .catch(() => undefined);
  }, PROGRESS_POLL_MS);
  return () => clearInterval(timer);
}

export const useDesignStore = create<DesignState>((set) => ({
  // -- Initial state --
  systems: [],
  templates: [],
  loadingMeta: false,
  errorMeta: null,

  projects: [],
  loadingProjects: false,
  errorProjects: null,

  currentProject: null,
  currentArtifact: null,
  previewArtifact: null,
  comparePair: null,
  messages: [],
  artifacts: [],
  tweaks: {},
  sourceBinding: null,
  review: null,
  generationProgress: null,
  loadingProject: false,
  errorProject: null,

  // -- Actions --

  async loadMeta() {
    set({ loadingMeta: true, errorMeta: null });
    try {
      const [systems, templates] = await Promise.all([api.listSystems(), api.listTemplates()]);
      set({ systems, templates, loadingMeta: false });
    } catch (error) {
      set({ errorMeta: getErrorMessage(error), loadingMeta: false });
    }
  },

  async loadProjects(kind?: 'deck' | 'prototype') {
    set({ loadingProjects: true, errorProjects: null });
    try {
      const projects = await api.listProjects(kind);
      set({ projects, loadingProjects: false });
    } catch (error) {
      set({ errorProjects: getErrorMessage(error), loadingProjects: false });
    }
  },

  async loadProject(projectId: string) {
    set({ loadingProject: true, errorProject: null });
    try {
      const [detail, messages, artifacts, tweaks] = await Promise.all([
        api.getProject(projectId),
        api.listMessages(projectId),
        api.listArtifacts(projectId),
        api.getTweaks(projectId),
      ]);
      // 未绑定数据源时后端返回 404，这里降级为 null 而不是让整个加载失败
      let sourceBinding: DesignSourceBinding | null = null;
      try {
        sourceBinding = await api.getSource(projectId);
      } catch {
        sourceBinding = null;
      }
      set({
        currentProject: detail,
        currentArtifact: detail.latest_artifact,
        previewArtifact: null,
        comparePair: null,
        messages,
        artifacts,
        tweaks,
        sourceBinding,
        review: null,
        loadingProject: false,
      });
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    }
  },

  async createProject(input) {
    const project = await api.createProject(input);
    set((state) => ({ projects: [project, ...state.projects] }));
    return project;
  },

  async deleteProject(projectId: string) {
    await api.deleteProject(projectId);
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== projectId),
      currentProject: state.currentProject?.id === projectId ? null : state.currentProject,
    }));
  },

  async generate(projectId: string, brief?: string) {
    set({
      loadingProject: true,
      errorProject: null,
      generationProgress: { stage: 'starting', message: '' },
    });
    const stopStreaming = api.subscribeDesignProgress(projectId, (progress) =>
      set({ generationProgress: progress }),
    );
    const stopPolling = stopStreaming
      ? () => undefined
      : startProgressPolling(projectId, set);
    try {
      await api.generateArtifact(projectId, { brief });
      await useDesignStore.getState().loadProject(projectId);
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    } finally {
      stopPolling();
      stopStreaming?.();
      set({ generationProgress: null });
    }
  },

  async iterate(projectId: string, feedback: string) {
    set({
      loadingProject: true,
      errorProject: null,
      generationProgress: { stage: 'starting', message: '' },
    });
    const stopStreaming = api.subscribeDesignProgress(projectId, (progress) =>
      set({ generationProgress: progress }),
    );
    const stopPolling = stopStreaming
      ? () => undefined
      : startProgressPolling(projectId, set);
    try {
      await api.iterateArtifact(projectId, { feedback });
      await useDesignStore.getState().loadProject(projectId);
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    } finally {
      stopPolling();
      stopStreaming?.();
      set({ generationProgress: null });
    }
  },

  async previewVersion(projectId: string, artifactId: string) {
    try {
      const artifact = await api.getArtifact(projectId, artifactId);
      set({ previewArtifact: artifact });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  async compareVersion(projectId: string, artifactId: string) {
    try {
      const right = await api.getArtifact(projectId, artifactId);
      const artifacts = useDesignStore.getState().artifacts;
      const previousSummary = artifacts
        .filter((artifact) => artifact.version < right.version)
        .sort((a, b) => b.version - a.version)[0];
      if (!previousSummary) return;
      const left = await api.getArtifact(projectId, previousSummary.id);
      set({ comparePair: { left, right }, previewArtifact: null });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  clearCompare() {
    set({ comparePair: null });
  },

  async restoreVersion(projectId: string, artifactId: string) {
    set({ loadingProject: true, errorProject: null });
    try {
      await api.restoreArtifact(projectId, artifactId);
      set({ previewArtifact: null });
      await useDesignStore.getState().loadProject(projectId);
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    }
  },

  clearPreview() {
    set({ previewArtifact: null });
  },

  updateTweaksLocal(patch: Partial<ProjectTweaks>) {
    set((state) => ({ tweaks: { ...state.tweaks, ...patch } }));
  },

  async persistTweaks(projectId: string) {
    try {
      const saved = await api.updateTweaks(projectId, useDesignStore.getState().tweaks);
      set({ tweaks: saved });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  async applyTweaksPreset(projectId: string, tweaks: ProjectTweaks) {
    set({ tweaks });
    try {
      const saved = await api.updateTweaks(projectId, tweaks, true);
      set({ tweaks: saved });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  async bindSource(projectId: string, filePath: string) {
    try {
      const binding = await api.bindSource(projectId, filePath);
      set({ sourceBinding: binding });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  async unbindSource(projectId: string) {
    try {
      await api.unbindSource(projectId);
      set({ sourceBinding: null });
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
    }
  },

  async refreshWithSource(projectId: string) {
    set({ loadingProject: true, errorProject: null });
    try {
      await api.refreshArtifact(projectId);
      await useDesignStore.getState().loadProject(projectId);
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    }
  },

  async embedChart(projectId: string, chart: ChartSpec) {
    set({ loadingProject: true, errorProject: null });
    try {
      const result = await api.embedChart(projectId, chart);
      await useDesignStore.getState().loadProject(projectId);
      return result;
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
      return null;
    }
  },

  async runReview(projectId: string) {
    try {
      const result = await api.reviewArtifact(projectId);
      set({ review: result });
      return result;
    } catch (error) {
      set({ errorProject: getErrorMessage(error) });
      return null;
    }
  },

  clearCurrent() {
    set({
      currentProject: null,
      currentArtifact: null,
      previewArtifact: null,
      comparePair: null,
      messages: [],
      artifacts: [],
      tweaks: {},
      sourceBinding: null,
      review: null,
      generationProgress: null,
      loadingProject: false,
      errorProject: null,
    });
  },
}));
