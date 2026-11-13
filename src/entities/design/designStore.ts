/**
 * Design Studio Store — Zustand state management
 *
 * Manages: systems, templates, projects list, current project,
 * current artifact, loading/error states.
 */
import { create } from 'zustand';

import * as api from './designApi';
import type {
  DesignArtifact,
  DesignProject,
  DesignSystem,
  DesignTemplate,
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
  loadingProject: boolean;
  errorProject: string | null;

  // -- Actions --
  loadMeta: () => Promise<void>;
  loadProjects: (kind?: 'deck' | 'prototype') => Promise<void>;
  loadProject: (projectId: string) => Promise<void>;
  createProject: (input: {
    name: string;
    kind: 'deck' | 'prototype';
    system_id: string;
    template_id: string;
    brief: string;
  }) => Promise<DesignProject>;
  deleteProject: (projectId: string) => Promise<void>;
  generate: (projectId: string, brief?: string) => Promise<void>;
  iterate: (projectId: string, feedback: string) => Promise<void>;
  clearCurrent: () => void;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
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
  loadingProject: false,
  errorProject: null,

  // -- Actions --

  async loadMeta() {
    set({ loadingMeta: true, errorMeta: null });
    try {
      const [systems, templates] = await Promise.all([
        api.listSystems(),
        api.listTemplates(),
      ]);
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
      const detail = await api.getProject(projectId);
      set({
        currentProject: detail,
        currentArtifact: detail.latest_artifact,
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
      currentProject:
        state.currentProject?.id === projectId
          ? null
          : state.currentProject,
    }));
  },

  async generate(projectId: string, brief?: string) {
    set({ loadingProject: true, errorProject: null });
    try {
      const artifact = await api.generateArtifact(projectId, { brief });
      set({ currentArtifact: artifact });
      // Reload project to get updated status + canonical artifact
      const detail = await api.getProject(projectId);
      set({
        currentProject: detail,
        currentArtifact: detail.latest_artifact ?? artifact,
        loadingProject: false,
      });
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    }
  },

  async iterate(projectId: string, feedback: string) {
    set({ loadingProject: true, errorProject: null });
    try {
      const artifact = await api.iterateArtifact(projectId, { feedback });
      set({ currentArtifact: artifact });
      // Reload project to get updated status + canonical artifact
      const detail = await api.getProject(projectId);
      set({
        currentProject: detail,
        currentArtifact: detail.latest_artifact ?? artifact,
        loadingProject: false,
      });
    } catch (error) {
      set({ errorProject: getErrorMessage(error), loadingProject: false });
    }
  },

  clearCurrent() {
    set({
      currentProject: null,
      currentArtifact: null,
      loadingProject: false,
      errorProject: null,
    });
  },
}));
