/* Sage Browser Bridge — offscreen document.
 *
 * MV3 service workers are evicted when idle, so the long-poll loop lives
 * here.  Commands are relayed to background.js via chrome.runtime messages;
 * background.js owns chrome.debugger and tab access.
 */

'use strict';

const POLL_TIMEOUT_MS = 25000;
const IDLE_MS = 3000;
const RETRY_MS = 2000;
const AUTH_BACKOFF_MS = 5000;

const state = {
  config: null,
  shared: null,
  running: false,
  controller: null,
};

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function baseUrl() {
  return String((state.config && state.config.baseUrl) || '').replace(/\/+$/, '');
}

function deviceToken() {
  return (state.config && state.config.deviceToken) || '';
}

async function notify(message) {
  try {
    return await chrome.runtime.sendMessage(message);
  } catch (error) {
    return null;
  }
}

function wake() {
  if (state.controller) {
    try {
      state.controller.abort();
    } catch (error) {
      // ignore
    }
  }
  void runLoop();
}

function applyState(message) {
  const previous = JSON.stringify({ config: state.config, shared: state.shared });
  state.config = message.config || null;
  state.shared = message.shared || null;
  const current = JSON.stringify({ config: state.config, shared: state.shared });
  if (previous !== current) wake();
}

async function postResult(payload) {
  const response = await fetch(`${baseUrl()}/api/v1/web-access/extension/result`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Sage-Extension-Token': deviceToken(),
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    // Command already timed out or sharing ended; nothing actionable.
    return false;
  }
  return true;
}

async function pollOnce(controller) {
  const tab = state.shared
    ? { id: state.shared.tabId, url: state.shared.url, title: state.shared.title }
    : null;
  const response = await fetch(`${baseUrl()}/api/v1/web-access/extension/poll`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Sage-Extension-Token': deviceToken(),
    },
    body: JSON.stringify({ tab }),
    signal: controller.signal,
  });

  if (response.status === 401) {
    await notify({ type: 'bridge:auth-failed' });
    return 'auth';
  }
  if (response.status === 409) {
    await notify({ type: 'bridge:server-conflict' });
    return 'conflict';
  }
  if (!response.ok) {
    await sleep(IDLE_MS);
    return 'retry';
  }

  const data = await response.json().catch(() => ({}));
  const command = data.command;
  if (!command) return 'ok';

  const outcome = await notify({ type: 'bridge:command', command });
  const payload =
    outcome && outcome.ok
      ? { command_id: command.id, ok: true, result: outcome.result }
      : {
          command_id: command.id,
          ok: false,
          error: (outcome && outcome.error) || { message: 'Sage 扩展后台未响应' },
        };
  try {
    await postResult(payload);
  } catch (error) {
    // Network hiccup; backend command will time out and the agent can retry.
  }
  return 'ok';
}

async function runLoop() {
  if (state.running) return;
  state.running = true;
  try {
    for (;;) {
      if (!state.config || !deviceToken()) {
        await sleep(RETRY_MS);
        continue;
      }
      const controller = new AbortController();
      state.controller = controller;
      const timer = setTimeout(() => controller.abort(), POLL_TIMEOUT_MS);
      try {
        const status = await pollOnce(controller);
        if (status === 'auth') {
          state.config = { ...state.config, deviceToken: '', deviceId: '' };
          await sleep(AUTH_BACKOFF_MS);
        } else if (status === 'conflict') {
          state.shared = null;
          await sleep(RETRY_MS);
        }
      } catch (error) {
        if (!error || error.name !== 'AbortError') {
          await sleep(RETRY_MS);
        }
      } finally {
        clearTimeout(timer);
        if (state.controller === controller) state.controller = null;
      }
    }
  } finally {
    state.running = false;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message && message.type === 'bridge:state') {
    applyState(message);
    sendResponse({ ok: true });
    return false;
  }
  return false;
});

(async () => {
  const hello = await notify({ type: 'bridge:hello' });
  if (hello && hello.ok) {
    state.config = hello.config || null;
    state.shared = hello.shared || null;
  }
  void runLoop();
})();
