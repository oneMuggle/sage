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
  /** Can run ``-m pip install ...`` (Python) or ``npm install`` (Node). */
  can_install_packages: boolean;
  /** Has a usable build toolchain (gcc / make / etc.) alongside. */
  has_build_tools: boolean;
}

/** One discovered runtime (interpreter + metadata). */
export interface RuntimeInfo {
  language: 'python' | 'javascript' | string;
  /** Absolute path to the interpreter binary. */
  path: string;
  /** Version string (e.g. "3.11.5", "20.9.0"). */
  version: string | null;
  /** Whether this is the "recommended" runtime for the current project. */
  is_default: boolean;
  /** Whether the runtime meets an optional target_version constraint. */
  is_compatible: boolean | null;
  /** Discovery source — system / conda / venv / project / toolchain / unknown. */
  source: RuntimeSource;
  /** Capability flags. */
  capabilities: RuntimeCapability;
  /** Free-form labels (e.g. "conda-env", "pyenv-shim"). */
  labels: string[];
  /** Optional project manifest that this runtime satisfies. */
  manifest: string | null;
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
export type DiagnosticSeverity = 'info' | 'warn' | 'error';

/** Diagnostic level — how deep into the project the finding reaches. */
export type DiagnosticLevel = 'project' | 'runtime' | 'toolchain' | 'dependency';

/** A single finding from project diagnosis. */
export interface Diagnostic {
  level: DiagnosticLevel;
  severity: DiagnosticSeverity;
  /** Short slug (e.g. "missing-runtime", "version-mismatch"). */
  code: string;
  /** Human-readable message. */
  message: string;
  /** Optional remediation hint (may be empty string). */
  fix_hint: string;
}

/** Result of ``POST /api/v1/runtime/diagnose``. */
export interface ProjectDiagnosis {
  /** Inferred project type (e.g. "python-react", "node-only", "unknown"). */
  project_type: string;
  /** Required runtimes for this project type (inferred). */
  required_languages: string[];
  /** All diagnostics — empty array means "project fully satisfied". */
  diagnostics: Diagnostic[];
  /** Whether the project's runtime needs are fully satisfied. */
  satisfied: boolean;
}

/** Result of ``POST /api/v1/runtime/exec``. */
export interface ExecutionResult {
  /** Process exit code (0 = success). */
  exit_code: number;
  /** Captured stdout (64 KiB cap in backend, may be truncated). */
  stdout: string;
  /** Captured stderr. */
  stderr: string;
  /** Execution wall-clock in seconds. */
  duration_seconds: number;
  /** True iff exit_code === 0 and no fatal signal. */
  success: boolean;
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
