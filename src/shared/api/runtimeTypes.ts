/**
 * Runtime environment assistant — frontend types.
 *
 * Mirrors the backend domain models in ``backend/domain/runtime.py``.
 * These types describe the response payload of the 3 REST endpoints
 * mounted under ``/api/v1/runtime/`` (probe / diagnose / exec).
 *
 * Field names are snake_case to match the Python models verbatim — the
 * Electron ``invokeBackend`` bridge would otherwise translate camelCase
 * keys back to snake_case, so round-tripping is a no-op.
 */

/** Where the runtime was discovered from. */
export type RuntimeSource = 'system' | 'conda' | 'venv' | 'project' | 'toolchain' | 'unknown';

/** Capability flags — what the runtime can do. */
export interface RuntimeCapability {
  /** Can execute arbitrary code (Python / Node). */
  can_execute: boolean;
  /** Can inspect installed packages for compatibility checks. */
  can_package_check: boolean;
  /** Can receive source code through stdin. */
  supports_stdin_source: boolean;
  /** Can receive source code through a temporary file. */
  supports_tempfile_source: boolean;
  /** Adapter-specific capability notes. */
  notes: string;
}

/** One discovered runtime (interpreter + metadata). */
export interface RuntimeInfo {
  language: 'python' | 'javascript' | string;
  /** Adapter name for the discovered runtime. */
  name: string;
  /** Absolute path to the interpreter binary. */
  path: string;
  /** Version string (e.g. "3.11.5", "20.9.0"). */
  version: string;
  /** Discovery source — system / conda / venv / project / toolchain / unknown. */
  source: RuntimeSource;
  /** Whether the runtime is the "recommended" runtime for the current project. */
  is_default: boolean;
  /** Whether the runtime meets an optional target_version constraint. */
  is_compatible: boolean | null;
  /** Human-readable compatibility notes. */
  compatibility_notes: string[];
  /** Capability flags. */
  capabilities: RuntimeCapability;
  /** Adapter-specific diagnostics. */
  diagnostics: string[];
}

/** Result of ``POST /api/v1/runtime/probe``. */
export interface ProbeResult {
  runtimes: RuntimeInfo[];
  /** Recommended runtime path for the current workspace (if any). */
  recommended: string | null;
  /** Per-language or per-adapter error messages (empty array on success). */
  errors: string[];
}

/** Diagnostic severity for project-level findings. */
export type DiagnosticSeverity = 'info' | 'warning' | 'error';

/** Diagnostic level — how deep into the project the finding reaches. */
export type DiagnosticLevel = 'satisfied' | 'partial' | 'unsatisfied';

/** A single finding from project diagnosis. */
export interface Diagnostic {
  code: string;
  severity: DiagnosticSeverity;
  /** Human-readable message. */
  message: string;
  /** Optional remediation hint. */
  remediation: string | null;
  /** Optional manifest or project path related to the finding. */
  related_path: string | null;
}

export interface ProjectManifest {
  language: string;
  path: string;
  kind: string;
  requires: string[];
  extras: Record<string, unknown>;
}

/** Result of ``POST /api/v1/runtime/diagnose``. */
export interface ProjectDiagnosis {
  level: DiagnosticLevel;
  diagnostics: Diagnostic[];
  manifests: ProjectManifest[];
  recommended_runtime: string | null;
  probe_errors: string[];
}

/** Result of ``POST /api/v1/runtime/exec`` (``ExecutionResult.to_dict()``). */
export interface ExecutionResult {
  /** Process exit code; ``null`` when the process was killed or never started. */
  exit_code: number | null;
  /** Captured stdout (64 KiB cap in backend, may be truncated). */
  stdout: string;
  /** Captured stderr. */
  stderr: string;
  /** Execution wall-clock in seconds. */
  duration_seconds: number;
  /** True when the process was killed after exceeding the timeout. */
  timed_out: boolean;
  /** True when stdout/stderr hit the per-stream byte cap. */
  output_truncated: boolean;
  /** Fatal spawn/exec error, if any (``null`` on a normal run). */
  error: string | null;
  /** The argv actually executed. */
  command: string[] | null;
}

/** Shared "tool call" envelope — what the REST endpoints return. */
export interface ToolCallEnvelope<T> {
  success: boolean;
  output?: T;
  error?: string;
  metadata?: Record<string, unknown>;
}

/** Request body for ``POST /api/v1/runtime/probe``. */
export interface ProbeRequest {
  languages?: string[] | null;
  include_tools?: boolean;
  target_version?: string | null;
  include_paths?: string[] | null;
  workspace_root?: string | null;
}

/** Request body for ``POST /api/v1/runtime/diagnose``. */
export interface DiagnoseRequest {
  languages?: string[] | null;
  include_tools?: boolean;
  target_version?: string | null;
  project_root?: string | null;
}

/** Request body for ``POST /api/v1/runtime/exec``. */
export interface ExecRequest {
  language: string;
  runtime_path: string;
  code: string;
  cwd?: string | null;
  timeout?: number | null;
  env_overrides?: Record<string, string> | null;
  workspace_root?: string | null;
}
