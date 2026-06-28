/**
 * Unified API response envelope shared across all IPC calls.
 * Mirrors backend ApiResponse in backend/schemas/common.py.
 */
export type ApiResponse<T> =
  | { success: true; data: T }
  | { success: false; error: string; code?: string; details?: unknown };

export function isApiError<T>(
  r: ApiResponse<T>,
): r is { success: false; error: string; code?: string; details?: unknown } {
  return r.success === false;
}