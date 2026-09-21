// ModelArchive.js 离线回归（node + jsdom）。
// ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/ModelArchive.js（状态机 open → menu → sent → confirmSent）
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.ModelArchive.cs（调用协议：confirmed / pending / error）
// 夹具：主区取 page-bridge.test.cjs 的真实 DOM 结构（快照要给出 promptConfirmed + generationStamp），
//       侧栏行 = a[href="/agent/<uuid>"] + 同级 button[aria-label="More options"]，
//       Radix 行为用脚本模拟：触发器只在 pointerdown 时切换菜单并写 aria-controls / aria-expanded，菜单项只认 click。
// 运行：node archive-bridge.test.cjs（或 npm test）。
'use strict';
const assert = require('node:assert/strict');
const { page, counter, runner } = require('./fixture.cjs');

const A = 'https://arena.ai/agent/11111111-1111-4111-8111-111111111111';
const B = 'https://arena.ai/agent/22222222-2222-4222-8222-222222222222';
const PROMPT = '1+1=';
const TOAST = 'Your previous chat history was archived';
const { check, done } = runner('Archive bridge');

const userMsg = (id, body) =>
  `<div data-agent-transcript-message data-chat-message-id="${id}"><div data-user-message-layout><div data-user-message-body-row>` +
  `<div data-user-message-action><button aria-label="Copy"><span class="sr-only">Copy</span></button></div>` +
  `<div class="bubble">${body}</div></div></div></div>`;
const assistantMsg = (id, body) =>
  `<div data-agent-transcript-message data-chat-message-id="${id}"><div class="answer"><div class="parts">${body}</div>` +
  `<div class="actions"><button aria-label="Copy"></button></div></div></div>`;
const row = (href = A) => `<div class="row"><a href="${href}">gpt-5 · 09-21 20:00</a><button aria-label="More options">…</button></div>`;
const sidebar = (inner, o = {}) =>
  o.mobile
    ? `<div role="dialog" data-sidebar="sidebar" data-mobile="true"><div class="sr-only"><h2>Sidebar</h2></div><a href="/agent">New Chat</a>${inner}</div>`
    : `<div id="sidebar"><a href="/agent">New Chat</a>${inner}</div>`;
const mainHtml = (o = {}) =>
  `<main><div role="log" aria-live="polite">${userMsg('u1', PROMPT)}${assistantMsg('a1', o.answer || '2')}</div>` +
  `<div id="composer"><div contenteditable="true"></div><button aria-label="Send message" disabled></button>` +
  (o.stop ? '<button aria-label="Stop generating"></button>' : '') + `</div></main>`;

/** 建页并模拟 Radix：pointerdown 切换菜单；Archive 菜单项 click 后按 o 决定弹确认框 / 移除行 / 弹 toast。 */
function fixture(o = {}) {
  const html = (o.sidebar !== undefined ? o.sidebar : sidebar(row(), o)) + mainHtml(o) + (o.extra || '');
  const w = page(html, { url: o.url || A, scripts: ['PageBridge.js', 'ModelArchive.js'] });
  const d = w.document;
  const trigger = d.querySelector('button[aria-label="More options"]');
  const items = o.items || ['Rename', 'Archive'];
  const events = { menuOpen: 0, archiveClick: 0, confirmClick: 0, undoClick: 0 };
  const showToast = (message) => {
    const t = d.createElement('div');
    t.setAttribute('data-sonner-toast', '');
    // 真机 innerText 在 flex 子项之间给出换行；jsdom 的 innerText 只是 textContent，这里用空白模拟那个分隔。
    t.innerHTML = `<span>${message}</span> <button>Undo</button>`;
    t.querySelector('button').addEventListener('click', () => { events.undoClick++; });
    d.body.appendChild(t);
  };
  const finish = () => {
    if (o.keepRow !== true) trigger.closest('.row').remove();
    if (o.toast !== false) showToast(o.toastText || TOAST);
  };
  const openConfirm = () => {
    const dlg = d.createElement('div');
    dlg.setAttribute('role', 'dialog');
    dlg.innerHTML = `<h2>${o.dialogTitle || 'Archive chat?'}</h2><p>This chat will be moved to your archive.</p><button>Cancel</button><button>Archive</button>`;
    dlg.querySelectorAll('button')[1].addEventListener('click', () => { events.confirmClick++; dlg.remove(); finish(); });
    d.body.appendChild(dlg);
  };
  let menu = null;
  if (trigger) {
    trigger.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.ctrlKey) return;
      if (menu) { menu.remove(); menu = null; trigger.removeAttribute('aria-controls'); trigger.setAttribute('aria-expanded', 'false'); return; }
      events.menuOpen++;
      menu = d.createElement('div');
      menu.setAttribute('role', 'menu');
      menu.id = 'radix-menu-1';
      menu.innerHTML = items.map((t) => `<div role="menuitem">${t}</div>`).join('');
      d.body.appendChild(menu);
      if (o.ariaExpanded !== false) {
        trigger.setAttribute('aria-controls', menu.id);
        trigger.setAttribute('aria-expanded', 'true');
      }
      const archive = [...menu.querySelectorAll('[role="menuitem"]')].find((e) => e.textContent === 'Archive');
      if (archive) archive.addEventListener('click', () => {
        events.archiveClick++;
        menu.remove(); menu = null;
        trigger.removeAttribute('aria-controls'); trigger.setAttribute('aria-expanded', 'false');
        if (o.confirm) openConfirm(); else finish();
      });
    });
  }
  const stamp = w.__ARENA_PAGE_BRIDGE__.snapshot(PROMPT).generationStamp;
  const step = (target = A, token = 'tok-1', prompt = PROMPT, gs = stamp) => w.__ARENA_ARCHIVE_BRIDGE__.step(target, token, prompt, gs);
  return { w, d, trigger, events, stamp, step, showToast };
}

check('bridge exposes version 1 with step/reset and the desktop alias', () => {
  const { w } = fixture();
  assert.equal(w.__ARENA_ARCHIVE_BRIDGE__.version, 1);
  assert.equal(typeof w.__ARENA_ARCHIVE_BRIDGE__.step, 'function');
  assert.equal(typeof w.__ARENA_ARCHIVE_BRIDGE__.reset, 'function');
  assert.equal(w.__arenaModelArchive, w.__ARENA_ARCHIVE_BRIDGE__.step);
  w.close();
});

check('fixture snapshot is a completed answer to the prompt', () => {
  const { w, stamp } = fixture();
  const s = w.__ARENA_PAGE_BRIDGE__.snapshot(PROMPT);
  assert.equal(s.promptConfirmed, true); assert.equal(s.completionConfirmed, true);
  assert.equal(s.generating, false); assert.ok(stamp);
  w.close();
});

check('invalid target is refused', () => {
  const { w, step } = fixture();
  assert.equal(step('https://arena.ai/agent').error, '归档目标不是有效对话');
  assert.equal(step('https://example.invalid/agent/11111111-1111-4111-8111-111111111111').error, '归档目标不是有效对话');
  assert.equal(step(A, '').error, '归档目标不是有效对话');
  w.close();
});

check('starting on another route is refused', () => {
  const { w, step } = fixture({ url: B });
  assert.equal(step().error, '当前页面不是待归档对话');
  w.close();
});

check('foreign dialog or menu blocks the start', () => {
  const { w, step } = fixture({ extra: '<div role="dialog"><h2>Something else</h2></div>' });
  assert.equal(step().error, '请先关闭已有菜单或对话框，再继续归档');
  w.close();
});

check('mobile sidebar sheet is not a foreign dialog', () => {
  const { w, step, events } = fixture({ mobile: true });
  const r = step();
  assert.equal(r.error, undefined, r.error); assert.equal(r.pending, true); assert.equal(r.stage, 'menu');
  assert.equal(events.menuOpen, 1);
  w.close();
});

check('changed or unconfirmed answer never clicks', () => {
  const { w, step, trigger } = fixture();
  const c = counter(trigger, ['pointerdown']);
  assert.equal(step(A, 'tok-1', PROMPT, 'other-stamp').error, '当前回答已改变或不可确认，未点击网站归档');
  assert.equal(step(A, 'tok-1', PROMPT, '').error, '当前回答已改变或不可确认，未点击网站归档');
  assert.equal(step(A, 'tok-1', 'a different prompt').error, '当前回答已改变或不可确认，未点击网站归档');
  assert.equal(c.pointerdown, 0);
  w.close();
});

check('generation still running never clicks', () => {
  const { w, step, trigger } = fixture({ stop: true });
  const c = counter(trigger, ['pointerdown']);
  assert.ok(step().error);
  assert.equal(c.pointerdown, 0);
  w.close();
});

check('happy path: pointerdown opens menu, click on Archive, toast confirms; Undo untouched', () => {
  const { w, step, trigger, events } = fixture();
  const c = counter(trigger, ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']);
  const r1 = step();
  assert.equal(r1.error, undefined, r1.error); assert.equal(r1.pending, true); assert.equal(r1.stage, 'menu');
  assert.deepEqual(c, { pointerdown: 1, mousedown: 1, pointerup: 1, mouseup: 1, click: 1 });
  assert.equal(events.menuOpen, 1);
  const r2 = step();
  assert.equal(r2.error, undefined, r2.error); assert.equal(r2.pending, true); assert.equal(r2.stage, 'sent');
  assert.equal(events.archiveClick, 1);
  const r3 = step();
  assert.equal(r3.error, undefined, r3.error); assert.equal(r3.confirmed, true); assert.equal(r3.evidence, 'toast'); assert.equal(r3.stage, 'sent');
  assert.equal(events.undoClick, 0);
  // 同一 token 再问仍是 confirmed，且不再点击。
  assert.equal(step().confirmed, true);
  assert.equal(c.pointerdown, 1); assert.equal(events.archiveClick, 1);
  w.close();
});

check('menu stage waits until the menu is mounted', () => {
  const { w, step, trigger, d } = fixture();
  step();
  // 模拟菜单尚未挂载：先把菜单摘掉但保留 aria 状态。
  const menu = d.getElementById('radix-menu-1');
  const parent = menu.parentNode; menu.remove();
  const r = step();
  assert.equal(r.error, undefined, r.error); assert.equal(r.pending, true); assert.equal(r.stage, 'menu');
  parent.appendChild(menu);
  assert.equal(step().stage, 'sent');
  assert.equal(trigger.getAttribute('aria-expanded'), 'false');
  w.close();
});

check('menu not owned by the trigger is refused', () => {
  const { w, step } = fixture({ ariaExpanded: false });
  step();
  assert.equal(step().error, '无法确认菜单属于当前对话');
  w.close();
});

check('menu without a unique Archive entry never falls back to Delete', () => {
  const { w, step, d } = fixture({ items: ['Rename', 'Delete'] });
  step();
  const del = [...d.querySelectorAll('[role="menuitem"]')].find((e) => e.textContent === 'Delete');
  const c = counter(del, ['click']);
  assert.equal(step().error, '当前菜单没有唯一可用的归档入口；不会改用删除');
  assert.equal(c.click, 0);
  w.close();
});

check('disabled Archive entry is refused', () => {
  const { w, step, d } = fixture();
  step();
  [...d.querySelectorAll('[role="menuitem"]')].find((e) => e.textContent === 'Archive').setAttribute('aria-disabled', 'true');
  assert.equal(step().error, '当前菜单没有唯一可用的归档入口；不会改用删除');
  w.close();
});

check('confirm dialog: title checked, Archive button pressed once, then toast confirms', () => {
  const { w, step, events } = fixture({ confirm: true });
  step(); step();
  assert.equal(events.archiveClick, 1);
  const r3 = step();
  assert.equal(r3.error, undefined, r3.error); assert.equal(r3.pending, true); assert.equal(r3.stage, 'confirmSent');
  assert.equal(events.confirmClick, 1);
  const r4 = step();
  assert.equal(r4.error, undefined, r4.error); assert.equal(r4.confirmed, true); assert.equal(r4.evidence, 'toast'); assert.equal(r4.stage, 'confirmSent');
  assert.equal(events.undoClick, 0);
  w.close();
});

check('unrecognised confirm dialog is never confirmed', () => {
  const { w, step, events } = fixture({ confirm: true, dialogTitle: 'Delete chat?' });
  step(); step();
  assert.equal(step().error, '不是可识别的归档确认窗口，未继续点击');
  assert.equal(events.confirmClick, 0);
  w.close();
});

check('answer changing while the confirm dialog is open stops before the click', () => {
  const { w, step, events, d } = fixture({ confirm: true });
  step(); step();
  d.querySelector('.parts').textContent = 'a completely different answer';
  assert.equal(step().error, '确认归档前回答发生变化，未继续点击');
  assert.equal(events.confirmClick, 0);
  w.close();
});

check('failure toast is reported, not retried', () => {
  const { w, step } = fixture({ toastText: 'Failed to archive chat' });
  step(); step();
  assert.equal(step().error, '网页报告归档失败，请人工检查');
  w.close();
});

check('pre-existing notices are not mistaken for success', () => {
  const { w, step, showToast } = fixture({ toast: false, keepRow: true });
  showToast(TOAST);
  step(); step();
  const r = step();
  assert.equal(r.error, undefined, r.error); assert.equal(r.pending, true);
  w.close();
});

check('row removal without toast confirms only after a stable 1.5s window', () => {
  const { w, step } = fixture({ toast: false });
  let now = 1_000_000;
  w.Date.now = () => now;
  step(); step();
  const r1 = step();
  assert.equal(r1.error, undefined, r1.error); assert.equal(r1.pending, true);
  now += 1000;
  assert.equal(step().pending, true);
  now += 600;
  const r2 = step();
  assert.equal(r2.confirmed, true); assert.equal(r2.evidence, 'current-row-removed'); assert.equal(r2.stage, 'sent');
  w.close();
});

check('row removal is not evidence while a loading state or hidden replacement exists', () => {
  const { w, step, d } = fixture({ toast: false });
  let now = 1_000_000;
  w.Date.now = () => now;
  step(); step();
  const ghost = d.createElement('a'); ghost.href = A; ghost.hidden = true; d.body.appendChild(ghost);
  now += 2000;
  assert.equal(step().pending, true);
  ghost.remove();
  const bar = d.createElement('div'); bar.setAttribute('role', 'progressbar'); d.body.appendChild(bar);
  now += 2000;
  assert.equal(step().pending, true);
  bar.remove();
  // 干扰消失后观察窗从头计时。
  now += 1000;
  assert.equal(step().pending, true);
  now += 1000;
  assert.equal(step().pending, true);
  now += 600;
  assert.equal(step().confirmed, true);
  w.close();
});

check('navigation to another conversation after sending stops the confirmation', () => {
  const { w, step } = fixture({ toast: false, keepRow: true });
  step(); step();
  w.history.pushState({}, '', B);
  assert.equal(step().error, '已切换到其他对话，归档确认已停止');
  w.close();
});

check('navigation to the empty composer only waits for the toast', () => {
  const { w, step, showToast } = fixture({ toast: false, keepRow: true });
  step(); step();
  w.history.pushState({}, '', 'https://arena.ai/agent');
  const r = step();
  assert.equal(r.error, undefined, r.error); assert.equal(r.pending, true); assert.equal(r.stage, 'sent');
  showToast(TOAST);
  assert.equal(step().confirmed, true);
  w.close();
});

check('navigation to the empty composer before sending is refused', () => {
  const { w, step } = fixture();
  step();
  w.history.pushState({}, '', 'https://arena.ai/agent');
  assert.equal(step().error, '页面已切换且未获取归档成功提示，请人工确认');
  w.close();
});

check('duplicate target rows are ambiguous', () => {
  const { w, step } = fixture({ sidebar: sidebar(row() + row()) });
  assert.equal(step().error, '侧栏中没有唯一的当前对话，未点击任何其他对话');
  w.close();
});

check('missing More options button is refused', () => {
  const { w, step } = fixture({ sidebar: sidebar(`<div class="row"><a href="${A}">gpt-5 · 09-21 20:00</a></div>`) });
  assert.equal(step().error, '未找到当前对话的唯一三个点菜单');
  w.close();
});

check('collapsed sidebar: opener pressed once, then the row is used', () => {
  const { w, step, d } = fixture({ sidebar: '<button aria-label="Open sidebar">☰</button><div id="sidebar" hidden><a href="/agent">New Chat</a>' + row() + '</div>' });
  const opener = d.querySelector('button[aria-label="Open sidebar"]');
  const c = counter(opener, ['pointerdown', 'click']);
  opener.addEventListener('click', () => { d.getElementById('sidebar').hidden = false; opener.hidden = true; });
  const r1 = step();
  assert.equal(r1.error, undefined, r1.error); assert.equal(r1.pending, true); assert.equal(r1.stage, 'open');
  assert.equal(c.pointerdown, 1); assert.equal(c.click, 1);
  const r2 = step();
  assert.equal(r2.error, undefined, r2.error); assert.equal(r2.stage, 'menu');
  w.close();
});

check('collapsed sidebar that stays collapsed is refused after one attempt', () => {
  const { w, step } = fixture({ sidebar: '<button aria-label="Open sidebar">☰</button>' });
  assert.equal(step().pending, true);
  assert.equal(step().error, '侧栏中没有唯一的当前对话，未点击任何其他对话');
  w.close();
});

check('different target with a live state is refused; new token starts over', () => {
  const { w, step, events } = fixture({ toast: false, keepRow: true });
  step();
  assert.equal(step(B).error, '归档目标改变，已停止');
  const r = step(A, 'tok-2');
  // 新 token：菜单已经打开（上一轮 pointerdown 之后），fail-closed 要求先关掉。
  assert.equal(r.error, '请先关闭已有菜单或对话框，再继续归档');
  assert.equal(events.menuOpen, 1);
  w.close();
});

check('reset clears the persisted state', () => {
  const { w, step } = fixture();
  step(); step(); assert.equal(step().confirmed, true);
  assert.equal(w.__ARENA_ARCHIVE_BRIDGE__.reset(), true);
  assert.equal(w.__arenaModelArchiveState, null);
  w.close();
});

done();
