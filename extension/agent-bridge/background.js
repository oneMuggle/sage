/* Sage Browser Bridge — background service worker (MV3).
 *
 * Owns:
 *  - pairing with the local Sage backend;
 *  - the user's explicit "share this tab" decision;
 *  - chrome.debugger attachment and raw CDP command forwarding;
 *  - saving the shared tab's cookies/localStorage into Sage's vault.
 *
 * The offscreen document owns the long-poll loop (MV3 service workers are
 * evicted when idle; an offscreen document survives).
 */

'use strict';

const CONFIG_KEY = 'sageBridgeConfig';
const SHARED_KEY = 'sageBridgeShared';
const ERROR_KEY = 'sageBridgeError';
const HEARTBEAT_ALARM = 'sage-bridge-heartbeat';

const state = { config: null, shared: null, lastError: '' };
let stateReady = null;
let offscreenCreated = false;
let attachedTabId = null;

// Defense in depth: the backend bridge has the same allow-list.  Keep these
// two lists in sync; unknown methods are never forwarded to chrome.debugger.
const ALLOWED_METHODS = new Set([
  'Browser.getVersion',
  'DOM.getDocument',
  'DOM.querySelector',
  'Input.dispatchKeyEvent',
  'Input.dispatchMouseEvent',
  'Input.insertText',
  'Network.enable',
  'Network.getCookies',
  'Page.addScriptToEvaluateOnNewDocument',
  'Page.captureScreenshot',
  'Page.enable',
  'Page.getLayoutMetrics',
  'Page.navigate',
  'Runtime.enable',
  'Runtime.evaluate',
  'Target.getTargets',
]);

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function extensionError(message, code) {
  const error = new Error(message || '扩展执行失败');
  error.code = code || 'extension_error';
  return error;
}

function errorPayload(error) {
  return {
    message: error && error.message ? error.message : String(error),
    code: (error && error.code) || 'extension_error',
  };
}

function originOf(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.origin;
    }
  } catch (error) {
    // ignore invalid URLs
  }
  return '';
}

function normalizeBaseUrl(raw) {
  let value = String(raw || '').trim();
  if (!value) return '';
  if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
  let parsed;
  try {
    parsed = new URL(value);
  } catch (error) {
    throw extensionError('后端地址格式不正确', 'invalid_base_url');
  }
  if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(parsed.hostname)) {
    throw extensionError('只允许连接本机 Sage（127.0.0.1 / localhost）', 'invalid_base_url');
  }
  return parsed.origin;
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

async function loadState() {
  const stored = await chrome.storage.local.get([CONFIG_KEY, SHARED_KEY, ERROR_KEY]);
  state.config = stored[CONFIG_KEY] || null;
  state.shared = stored[SHARED_KEY] || null;
  state.lastError = stored[ERROR_KEY] || '';
  await updateBadge();
}

async function persistState() {
  await chrome.storage.local.set({
    [CONFIG_KEY]: state.config,
    [SHARED_KEY]: state.shared,
    [ERROR_KEY]: state.lastError,
  });
  await updateBadge();
  await postStateToOffscreen();
}

async function updateBadge() {
  try {
    await chrome.action.setBadgeBackgroundColor({ color: '#2563eb' });
    await chrome.action.setBadgeText({ text: state.shared ? 'ON' : '' });
  } catch (error) {
    // action API is unavailable in some headless contexts
  }
}

// ---------------------------------------------------------------------------
// Offscreen document (long-poll + network)
// ---------------------------------------------------------------------------

async function ensureOffscreen() {
  if (offscreenCreated) return;
  try {
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['WORKERS'],
      justification: '保持与 Sage 本机后端的命令长轮询',
    });
  } catch (error) {
    // A document may already exist after a service-worker restart.
    if (!/single offscreen|already exists|Only a single/i.test(String(error))) {
      console.warn('[Sage Bridge] offscreen create failed', error);
    }
  }
  offscreenCreated = true;
}

async function postStateToOffscreen() {
  try {
    await chrome.runtime.sendMessage({
      type: 'bridge:state',
      config: state.config,
      shared: state.shared,
    });
  } catch (error) {
    // No offscreen document yet; it will request state via bridge:hello.
  }
}

// ---------------------------------------------------------------------------
// Backend HTTP
// ---------------------------------------------------------------------------

async function backendRequest(baseUrl, path, body, token) {
  const base = normalizeBaseUrl(baseUrl || (state.config && state.config.baseUrl));
  if (!base) throw extensionError('尚未配置 Sage 后端地址', 'missing_base_url');
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-Sage-Extension-Token'] = token;
  const response = await fetch(`${base}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      data.message || data.error || `Sage 后端返回 HTTP ${response.status}`;
    throw extensionError(message, data.error || 'backend_error');
  }
  return data;
}

// ---------------------------------------------------------------------------
// Pairing / sharing lifecycle
// ---------------------------------------------------------------------------

async function pair(message) {
  const baseUrl = normalizeBaseUrl(message.baseUrl);
  const data = await backendRequest(baseUrl, '/api/v1/web-access/extension/pair', {
    code: String(message.code || '').trim(),
    label: String(message.label || '').trim(),
  });
  state.config = {
    baseUrl: data.base_url || baseUrl,
    deviceId: data.device_id,
    deviceToken: data.device_token,
    label: data.label || message.label || '浏览器扩展',
  };
  state.lastError = '';
  await persistState();
  await ensureOffscreen();
  await postStateToOffscreen();
  return { ok: true, config: state.config };
}

async function shareTab(tabId) {
  if (!state.config || !state.config.deviceToken) {
    throw extensionError('请先在扩展弹窗中完成配对', 'not_paired');
  }
  const tab = await chrome.tabs.get(tabId);
  const origin = originOf(tab.url || '');
  if (!origin) throw extensionError('只能共享 http/https 标签页', 'invalid_tab');
  state.shared = {
    tabId,
    url: tab.url,
    title: tab.title || '',
    origin,
    sharedAt: Date.now(),
  };
  state.lastError = '';
  await persistState();
  await ensureOffscreen();
  await postStateToOffscreen();
  return { ok: true, shared: state.shared };
}

async function detachDebugger(tabId) {
  if (tabId === null || tabId === undefined) return;
  try {
    await chrome.debugger.detach({ tabId });
  } catch (error) {
    // not attached / tab gone
  }
  if (attachedTabId === tabId) attachedTabId = null;
}

async function stopSharing(reason, notifyBackend) {
  const shared = state.shared;
  if (shared) await detachDebugger(shared.tabId);
  state.shared = null;
  if (reason && reason !== 'user') state.lastError = String(reason);
  await persistState();
  if (notifyBackend !== false && shared && state.config && state.config.deviceToken) {
    try {
      await backendRequest(
        state.config.baseUrl,
        '/api/v1/web-access/extension/detach',
        { reason: reason || 'user' },
        state.config.deviceToken,
      );
    } catch (error) {
      // backend will also notice on the next poll
    }
  }
}

async function forgetDevice() {
  await stopSharing('user', false);
  state.config = null;
  state.lastError = '';
  await persistState();
  await postStateToOffscreen();
}

async function handleAuthFailed() {
  state.lastError = '设备凭据已失效，请在 Sage 设置页重新生成配对码并重新配对';
  if (state.shared) await detachDebugger(state.shared.tabId);
  state.shared = null;
  if (state.config) {
    state.config = { ...state.config, deviceToken: '', deviceId: '' };
  }
  await persistState();
}

// ---------------------------------------------------------------------------
// Command execution (chrome.debugger -> raw CDP)
// ---------------------------------------------------------------------------

async function assertSharedTab() {
  if (!state.shared) {
    throw extensionError('尚未共享标签页，请在扩展弹窗中点击「共享此标签页」', 'no_shared_tab');
  }
  const tab = await chrome.tabs.get(state.shared.tabId);
  const origin = originOf(tab.url || '');
  if (!origin || origin !== state.shared.origin) {
    await stopSharing('origin_changed');
    throw extensionError('共享标签页已跳转到其他网站，已自动停止共享', 'origin_changed');
  }
  return tab;
}

async function sendCdp(tabId, method, params) {
  const target = { tabId };
  try {
    return (await chrome.debugger.sendCommand(target, method, params || {})) || {};
  } catch (error) {
    if (!/not attached|No debugger|debugger is not attached/i.test(String(error.message))) {
      throw error;
    }
    try {
      await chrome.debugger.attach(target, '1.3');
      attachedTabId = tabId;
    } catch (attachError) {
      throw extensionError(
        `无法附加到该标签页：${attachError.message || attachError}。请关闭该标签页的 DevTools 后重试。`,
        'debugger_attach_failed',
      );
    }
    return (await chrome.debugger.sendCommand(target, method, params || {})) || {};
  }
}

async function runCommand(command) {
  if (!command || !command.method) {
    throw extensionError('命令缺少 method', 'invalid_command');
  }
  if (!ALLOWED_METHODS.has(command.method)) {
    return {
      ok: false,
      error: { message: `扩展不允许的 CDP 方法: ${command.method}`, code: 'unsupported_method' },
    };
  }
  if (command.deadline && Date.now() / 1000 > Number(command.deadline) + 2) {
    return { ok: false, error: { message: '命令已过期', code: 'expired' } };
  }
  const tab = await assertSharedTab();

  if (command.method === 'Target.getTargets') {
    return {
      ok: true,
      result: {
        targetInfos: [
          {
            targetId: String(tab.id),
            type: 'page',
            title: tab.title || '',
            url: tab.url || '',
          },
        ],
      },
    };
  }

  try {
    const result = await sendCdp(tab.id, command.method, command.params || {});
    return { ok: true, result };
  } catch (error) {
    return { ok: false, error: errorPayload(error) };
  }
}

// ---------------------------------------------------------------------------
// Save login state (cookies + localStorage)
// ---------------------------------------------------------------------------

function normalizeCookie(cookie) {
  return {
    name: cookie.name,
    value: cookie.value,
    domain: cookie.domain,
    path: cookie.path || '/',
    secure: !!cookie.secure,
    httpOnly: !!cookie.httpOnly,
    sameSite: cookie.sameSite || 'Lax',
    expires:
      typeof cookie.expirationDate === 'number' && cookie.expirationDate > 0
        ? Math.floor(cookie.expirationDate)
        : -1,
    session: !!cookie.session,
  };
}

async function collectLocalStorage(tabId) {
  const expression =
    "(() => { try { const data = {}; for (let i = 0; i < localStorage.length; i++) { const key = localStorage.key(i); if (key) data[key] = localStorage.getItem(key); } return JSON.stringify({ origin: location.origin, localStorage: data }); } catch (error) { return JSON.stringify({ origin: location.origin, localStorage: {} }); } })()";
  const evaluated = await sendCdp(tabId, 'Runtime.evaluate', {
    expression,
    returnByValue: true,
  });
  const raw = evaluated && evaluated.result ? evaluated.result.value : '';
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed.origin === 'string' &&
      parsed.localStorage &&
      Object.keys(parsed.localStorage).length > 0
    ) {
      return [{ origin: parsed.origin, localStorage: parsed.localStorage }];
    }
  } catch (error) {
    // ignore malformed page data
  }
  return [];
}

async function syncSession() {
  if (!state.config || !state.config.deviceToken) {
    throw extensionError('请先完成配对', 'not_paired');
  }
  const tab = await assertSharedTab();
  let cookies = [];
  try {
    cookies = (await chrome.cookies.getAll({ url: tab.url })).map(normalizeCookie);
  } catch (error) {
    throw extensionError(`读取 cookie 失败：${error.message || error}`, 'cookie_read_failed');
  }
  const origins = await collectLocalStorage(tab.id);
  const data = await backendRequest(
    state.config.baseUrl,
    '/api/v1/web-access/extension/sync-session',
    { url: tab.url, cookies, origins },
    state.config.deviceToken,
  );
  return { ok: true, summary: data };
}

async function activeTabInfo() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs && tabs[0];
  if (!tab) return null;
  const origin = originOf(tab.url || '');
  return {
    id: tab.id,
    url: tab.url || '',
    title: tab.title || '',
    origin,
    shareable: !!origin,
  };
}

// ---------------------------------------------------------------------------
// Messaging
// ---------------------------------------------------------------------------

async function handleMessage(message) {
  await stateReady;
  switch (message && message.type) {
    case 'bridge:hello':
      await ensureOffscreen();
      return { ok: true, config: state.config, shared: state.shared };
    case 'bridge:get-state':
      return {
        ok: true,
        config: state.config,
        shared: state.shared,
        lastError: state.lastError,
        activeTab: await activeTabInfo(),
      };
    case 'bridge:pair':
      return pair(message);
    case 'bridge:share':
      return shareTab(message.tabId);
    case 'bridge:stop-sharing':
      await stopSharing(message.reason || 'user');
      return { ok: true };
    case 'bridge:forget-device':
      await forgetDevice();
      return { ok: true };
    case 'bridge:sync-session':
      return syncSession();
    case 'bridge:command':
      return runCommand(message.command);
    case 'bridge:auth-failed':
      await handleAuthFailed();
      return { ok: true };
    case 'bridge:server-conflict':
      await stopSharing('another_tab_shared', false);
      return { ok: true };
    case 'bridge:state':
      // Sent from background to offscreen; ignore if echoed back.
      return { ok: true };
    default:
      return { ok: false, error: { message: '未知消息', code: 'unknown_message' } };
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  handleMessage(message)
    .then((response) => sendResponse(response))
    .catch((error) => sendResponse({ ok: false, error: errorPayload(error) }));
  return true;
});

// ---------------------------------------------------------------------------
// Lifecycle / tab safety
// ---------------------------------------------------------------------------

chrome.tabs.onRemoved.addListener((tabId) => {
  if (state.shared && state.shared.tabId === tabId) {
    void stopSharing('tab_closed');
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!state.shared || state.shared.tabId !== tabId || !changeInfo.url) return;
  if (originOf(changeInfo.url) !== state.shared.origin) {
    void stopSharing('origin_changed');
  }
});

chrome.debugger.onDetach.addListener((source) => {
  if (source && source.tabId === attachedTabId) attachedTabId = null;
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === HEARTBEAT_ALARM) {
    void ensureOffscreen().then(() => postStateToOffscreen());
  }
});

function createHeartbeatAlarm() {
  try {
    chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 1 });
  } catch (error) {
    // alarms are best-effort
  }
}

chrome.runtime.onInstalled.addListener(() => {
  createHeartbeatAlarm();
  void ensureOffscreen();
});

chrome.runtime.onStartup.addListener(() => {
  createHeartbeatAlarm();
  void ensureOffscreen();
});

stateReady = (async () => {
  await loadState();
  await ensureOffscreen();
  createHeartbeatAlarm();
  await updateBadge();
})();

// Export for syntax tests / debugging (no effect in the worker).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { originOf, normalizeBaseUrl, normalizeCookie };
}
