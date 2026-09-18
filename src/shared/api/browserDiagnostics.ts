/**
 * 浏览器环境诊断 API 客户端
 *
 * 调用后端 `/api/v1/diagnostic/browser-check` 端点，
 * 返回浏览器环境健康检查结果。
 *
 * API 契约见 docs/plans/2026-09-17_multi-browser-support.md §4。
 */

export interface BrowserCheckItem {
  id: string;
  status: 'pass' | 'warn' | 'fail' | 'na';
  detail: string;
  fix_hint: string | null;
}

export interface BrowserCheckResponse {
  platform: string;
  checks: BrowserCheckItem[];
  recommended_browser: string;
  errors: string[];
}

/**
 * 执行浏览器环境检查
 *
 * 通过 Electron IPC 调用后端诊断 API。
 *
 * @returns 诊断结果；若后端不可用则抛出错误
 */
export async function fetchBrowserCheck(): Promise<BrowserCheckResponse> {
  const api = window.electronAPI;
  if (!api?.diagnostic?.browserCheck) {
    throw new Error('浏览器诊断 API 不可用（需 Electron 桌面端）');
  }
  return api.diagnostic.browserCheck() as Promise<BrowserCheckResponse>;
}
