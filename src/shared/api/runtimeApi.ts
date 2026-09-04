/**
 * Sage API - Runtime environment assistant client.
 *
 * Backend counterpart: ``backend/api/runtime_routes.py`` (mounted at /api/v1/runtime).
 * Frontend routes through the Electron IPC bridge (``invoke``) per project convention
 * — never calls HTTP directly from the renderer.
 *
 * Three endpoints:
 *
 * - ``probe()`` — READ, discover available runtimes (Python / Node.js etc.)
 * - ``diagnose()`` — READ, project-level diagnosis (required vs available)
 * - ``exec()`` — EXEC, execute a code snippet in a runtime; subject to
 *   backend ``PermissionEnforcer`` approval gate (same as BashTool). Denied
 *   requests surface as ``ToolCallEnvelope.success === false`` with a
 *   descriptive ``error`` field.
 */

import { invoke } from './desktopInvoke';
import type {
  DiagnoseRequest,
  ExecRequest,
  ExecutionResult,
  ProbeRequest,
  ProbeResult,
  ProjectDiagnosis,
  ToolCallEnvelope,
} from './runtimeTypes';
import { handleApiError } from './utils';

export const runtimeApi = {
  /**
   * Discover available runtimes on this machine.
   *
   * READ operation — no side effects, no approval required.
   */
  async probe(req: ProbeRequest = {}): Promise<ToolCallEnvelope<ProbeResult>> {
    try {
      return await invoke<ToolCallEnvelope<ProbeResult>>('runtime_probe', {
        languages: req.languages ?? null,
        includeTools: req.include_tools ?? true,
        targetVersion: req.target_version ?? null,
        includePaths: req.include_paths ?? null,
        workspaceRoot: req.workspace_root ?? null,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Diagnose the current project's runtime requirements.
   *
   * READ operation — no side effects, no approval required.
   */
  async diagnose(req: DiagnoseRequest = {}): Promise<ToolCallEnvelope<ProjectDiagnosis>> {
    try {
      return await invoke<ToolCallEnvelope<ProjectDiagnosis>>('runtime_diagnose', {
        languages: req.languages ?? null,
        includeTools: req.include_tools ?? true,
        targetVersion: req.target_version ?? null,
        projectRoot: req.project_root ?? null,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /**
   * Execute a code snippet in a chosen runtime.
   *
   * EXEC operation — the backend routes through PermissionEnforcer, same
   * gate as BashTool. On user denial, returns ``success: false`` with
   * ``error: "权限拒绝: ..."`` rather than throwing.
   */
  async exec(req: ExecRequest): Promise<ToolCallEnvelope<ExecutionResult>> {
    try {
      return await invoke<ToolCallEnvelope<ExecutionResult>>('runtime_exec', {
        language: req.language,
        runtimePath: req.runtime_path,
        code: req.code,
        cwd: req.cwd ?? null,
        timeout: req.timeout ?? null,
        envOverrides: req.env_overrides ?? null,
        workspaceRoot: req.workspace_root ?? null,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
