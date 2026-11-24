/**
 * 网页回退模式的本地凭据读取（轻量模块）。
 *
 * 为什么从 webTransport.ts 里拆出来：
 * webTransport.ts 静态引入 `electron/commands.ts` → `electron/commandRoutes/**`
 * （约 130KB 源码的 IPC 路由表），而这张表只有浏览器模式用得上 —— 桌面端
 * 渲染层始终有 `window.electronAPI`，走 IPC 桥，根本不会进同源 HTTP 回退。
 *
 * 若把两者放在一个模块里，桌面端产物就会把整张路由表打进主 chunk：
 * 既白白增大 Electron 安装包，又会撞上渲染产物体积门禁
 * （`scripts/check-bundle-size.mjs`，主 chunk 预算 2.25MB）。
 *
 * 因此这里只放「读 token / 拼 header / 判断运行时」这几件小事，它们与
 * 路由表无关，桌面端可以安全地静态引入。
 */

/** 网页模式下后端下发的 token 在 localStorage 里的键（index.html 引导写入）。 */
export const WEB_AUTH_TOKEN_STORAGE_KEY = 'sage_auth_token';

/** 是否运行在没有 Electron preload 桥的纯浏览器里。 */
export function isBrowserRuntime(): boolean {
  return typeof window !== 'undefined' && !window.electronAPI;
}

/** 读取本地能力凭据（无 token 时返回空串）。 */
export function getWebAuthToken(): string {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(WEB_AUTH_TOKEN_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

/** 本地能力 header —— 用于后端自身接口（`Authorization` 无其它占用时）。 */
export function getWebAuthHeaders(): Record<string, string> {
  const token = getWebAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * 本地能力 header（不占用 `Authorization`）。
 *
 * 复刻 Electron 主进程 `sage:backend-request` 中继语义：能力放入
 * `X-Sage-Local-Authorization`，**不**写入 `Authorization`。这样调用方自带的
 * `Authorization`（例如 LLM 代理转发的上游 API Key）不会被本地 token 覆盖。
 * `is_local_auth_valid` 在 `authorization` 为空时回退到
 * `x-sage-local-authorization`，LLM 代理路径则直接以 compatibility 为准。
 */
export function getWebCapabilityHeaders(): Record<string, string> {
  const token = getWebAuthToken();
  return token ? { 'X-Sage-Local-Authorization': `Bearer ${token}` } : {};
}
