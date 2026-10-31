/* Sage Browser Bridge — popup UI. */

'use strict';

const els = {
  badge: document.getElementById('state-badge'),
  error: document.getElementById('error'),
  pairView: document.getElementById('pair-view'),
  deviceView: document.getElementById('device-view'),
  statusView: document.getElementById('status-view'),
  baseUrl: document.getElementById('base-url'),
  pairCode: document.getElementById('pair-code'),
  pairLabel: document.getElementById('pair-label'),
  pairBtn: document.getElementById('pair-btn'),
  deviceLabel: document.getElementById('device-label'),
  forgetBtn: document.getElementById('forget-btn'),
  tabTitle: document.getElementById('tab-title'),
  tabOrigin: document.getElementById('tab-origin'),
  shareHint: document.getElementById('share-hint'),
  shareBtn: document.getElementById('share-btn'),
  stopBtn: document.getElementById('stop-btn'),
  syncBtn: document.getElementById('sync-btn'),
};

let currentState = null;
let notice = '';
let busy = false;

function setError(message) {
  if (!message) {
    els.error.hidden = true;
    els.error.textContent = '';
    return;
  }
  els.error.hidden = false;
  els.error.textContent = message;
}

function setBusy(value) {
  busy = value;
  els.pairBtn.disabled = value;
  els.shareBtn.disabled = value;
  els.stopBtn.disabled = value;
  els.syncBtn.disabled = value || !(currentState && currentState.shared);
  els.forgetBtn.disabled = value;
}

async function send(message) {
  let response;
  try {
    response = await chrome.runtime.sendMessage(message);
  } catch (error) {
    throw new Error(`Sage 扩展后台未响应：${error.message || error}`);
  }
  if (!response) throw new Error('Sage 扩展后台未响应');
  if (!response.ok) {
    const error = new Error((response.error && response.error.message) || '操作失败');
    error.code = response.error && response.error.code;
    throw error;
  }
  return response;
}

function friendlyError(code, message) {
  switch (code) {
    case 'origin_changed':
      return '共享的标签页已跳转到其他网站，共享已自动停止。请回到目标网站重新共享。';
    case 'tab_closed':
      return '共享的标签页已关闭，共享已停止。';
    case 'another_tab_shared':
      return '另一个浏览器窗口正在共享标签页，请先在那边停止共享。';
    case 'extension_unauthorized':
      return '设备凭据已失效，请在 Sage 设置页重新生成配对码。';
    case 'debugger_attach_failed':
      return message || '无法附加到该标签页，请关闭 DevTools 后重试。';
    default:
      return message || '操作失败';
  }
}

function badge(text, kind) {
  els.badge.textContent = text;
  els.badge.className = 'badge';
  if (kind) els.badge.classList.add(kind);
}

function render() {
  const state = currentState || {};
  const config = state.config || null;
  const paired = !!(config && config.deviceToken);
  const shared = state.shared || null;
  const activeTab = state.activeTab || null;

  els.pairView.hidden = paired;
  els.deviceView.hidden = !paired;
  els.statusView.hidden = true;

  if (!config) {
    badge('未配对');
  } else if (shared) {
    badge('共享中', 'on');
  } else if (paired) {
    badge('已连接');
  } else {
    badge('需重新配对', 'warn');
  }

  if (!paired) {
    els.baseUrl.value = (config && config.baseUrl) || els.baseUrl.value;
    els.pairLabel.value = (config && config.label) || els.pairLabel.value;
    setError(
      state.lastError
        ? friendlyError(state.lastError, state.lastError)
        : '',
    );
    return;
  }

  els.deviceLabel.textContent = config.label || '浏览器扩展';

  const info = shared || activeTab;
  if (info) {
    els.tabTitle.textContent = info.title || '当前标签页';
    els.tabOrigin.textContent = info.origin || info.url || '';
  } else {
    els.tabTitle.textContent = '未找到可共享标签页';
    els.tabOrigin.textContent = '';
  }

  const shareable = !!(activeTab && activeTab.shareable);
  els.shareBtn.hidden = !!shared;
  els.stopBtn.hidden = !shared;
  els.shareBtn.disabled = busy || !shareable;
  els.syncBtn.disabled = busy || !shared;

  if (shared) {
    els.shareHint.textContent =
      notice || 'Sage 正在使用这个标签页；你可以随时点「停止共享」。';
  } else if (!shareable) {
    els.shareHint.textContent = '请切换到 http/https 网页后再共享。';
  } else if (currentState.lastError) {
    els.shareHint.textContent = friendlyError(
      currentState.lastError,
      currentState.lastError,
    );
  } else {
    els.shareHint.textContent =
      notice || 'Sage 只能操作你手动共享的这一个标签页。';
  }
  setError('');
}

async function refresh() {
  currentState = await send({ type: 'bridge:get-state' });
  render();
}

async function onPair() {
  if (busy) return;
  setBusy(true);
  notice = '';
  try {
    await send({
      type: 'bridge:pair',
      baseUrl: els.baseUrl.value,
      code: els.pairCode.value,
      label: els.pairLabel.value,
    });
    els.pairCode.value = '';
    await refresh();
  } catch (error) {
    setError(friendlyError(error.code, error.message));
  } finally {
    setBusy(false);
    render();
  }
}

async function onShare() {
  if (busy || !currentState || !currentState.activeTab) return;
  const tab = currentState.activeTab;
  if (!tab.shareable) {
    setError('只能共享 http/https 网页。');
    return;
  }
  setBusy(true);
  notice = '';
  try {
    const origin = new URL(tab.url).origin;
    const granted = await chrome.permissions.request({ origins: [`${origin}/*`] });
    if (!granted) {
      setError('需要允许扩展访问该网站，才能共享这个标签页。');
      return;
    }
    await send({ type: 'bridge:share', tabId: tab.id });
    await refresh();
  } catch (error) {
    setError(friendlyError(error.code, error.message));
  } finally {
    setBusy(false);
    render();
  }
}

async function onStop() {
  if (busy) return;
  setBusy(true);
  notice = '';
  try {
    await send({ type: 'bridge:stop-sharing', reason: 'user' });
    await refresh();
  } catch (error) {
    setError(friendlyError(error.code, error.message));
  } finally {
    setBusy(false);
    render();
  }
}

async function onSync() {
  if (busy) return;
  setBusy(true);
  notice = '';
  try {
    const result = await send({ type: 'bridge:sync-session' });
    const summary = result.summary || {};
    const saved = Array.isArray(summary.saved) ? summary.saved : [];
    const domains = saved.map((item) => item.domain).filter(Boolean);
    notice = domains.length
      ? `已保存 ${domains.join('、')} 的登录状态（${summary.total_cookies || 0} 个 Cookie）。`
      : '已保存登录状态。';
  } catch (error) {
    setError(friendlyError(error.code, error.message));
  } finally {
    setBusy(false);
    render();
  }
}

async function onForget() {
  if (busy) return;
  if (!window.confirm('解除配对后需要重新在 Sage 设置页生成配对码。确定吗？')) return;
  setBusy(true);
  notice = '';
  try {
    await send({ type: 'bridge:forget-device' });
    await refresh();
  } catch (error) {
    setError(friendlyError(error.code, error.message));
  } finally {
    setBusy(false);
    render();
  }
}

els.pairBtn.addEventListener('click', () => void onPair());
els.shareBtn.addEventListener('click', () => void onShare());
els.stopBtn.addEventListener('click', () => void onStop());
els.syncBtn.addEventListener('click', () => void onSync());
els.forgetBtn.addEventListener('click', () => void onForget());
els.pairCode.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') void onPair();
});

void refresh().catch((error) => {
  els.statusView.hidden = false;
  els.statusView.innerHTML = '';
  const hint = document.createElement('p');
  hint.className = 'hint';
  hint.textContent = `读取扩展状态失败：${error.message || error}`;
  els.statusView.appendChild(hint);
});
