// ModelRename.js 离线回归（node + jsdom）。
// ref: reference/Arena模型助手-源码-fyb-0.1.0/tests/rename-bridge.test.cjs —— 桌面端全部用例逐条移植到
//      安卓桥 API（window.__ARENA_RENAME_BRIDGE__.act(action, value, target)），再补 pointer 序列 / 菜单 / 对话框用例。
// 运行：node rename-bridge.test.cjs（或 npm test）。
'use strict';
const assert = require('node:assert/strict');
const { page, counter, runner } = require('./fixture.cjs');

const A = 'https://arena.ai/agent/11111111-1111-4111-8111-111111111111';
const B = 'https://arena.ai/agent/22222222-2222-4222-8222-222222222222';
const title = 'super_nova_ext · 09-16 03:51';
const fixture = (html, url = A) => page(html, { url, scripts: ['ModelRename.js'] });
const act = (w, action, value = '', target = A) => w.__ARENA_RENAME_BRIDGE__.act(action, value, target);
const { check, done } = runner('Rename bridge');

// 手机（<768px）侧栏 = Radix Sheet：role=dialog + data-sidebar/data-mobile，是侧栏本身而不是外来弹窗。
const mobileSidebar = inner => `<div role="dialog" data-sidebar="sidebar" data-mobile="true"><div class="sr-only"><h2>Sidebar</h2><p>Displays the mobile sidebar.</p></div>${inner}</div>`;
const row = `<div><a href="${A}">${title}</a><button aria-label="More options">…</button></div>`;
const renameDialogHtml = `<div role="dialog" aria-labelledby="t1"><h2 id="t1">Rename chat</h2> <input type="text" value="${title}"> <button>Rename</button> <button>Cancel</button></div>`;

// ---- 桌面端原有用例 ------------------------------------------------------------
check('full DOM title survives CSS ellipsis', () => {
  const w = fixture(`<a href="${A}" style="text-overflow:ellipsis"><span>${title}</span></a>`);
  assert.equal(act(w, 'state').title, title); w.close();
});
check('accessibility label and SVG title are not conversation name', () => {
  const w = fixture(`<a href="${A}" aria-label="Open conversation"><svg><title>Icon</title></svg><span>${title}</span><span role="tooltip">Tooltip</span></a>`);
  assert.equal(act(w, 'state').title, title); w.close();
});
check('original ID is confirmed after navigation to new chat', () => {
  const w = fixture(`<a href="/agent">New Chat</a><a href="${A}">${title}</a>`, 'https://arena.ai/agent');
  const s = act(w, 'state');
  assert.equal(s.title, title); assert.equal(s.linkCount, 1); assert.equal(s.routeMatches, false); w.close();
});
check('writes refuse navigation to another page', () => {
  const w = fixture(`<a href="${A}">${title}</a>`, B);
  assert.ok(act(w, 'openMenu').error); w.close();
});
check('same named different conversation cannot confirm', () => {
  const w = fixture(`<a href="${B}">${title}</a>`);
  const s = act(w, 'state'); assert.equal(s.linkCount, 0); assert.equal(s.title, ''); w.close();
});
check('duplicate target links remain ambiguous', () => {
  const w = fixture(`<a href="${A}">${title}</a><a href="${A}">${title}</a>`);
  const s = act(w, 'state'); assert.equal(s.linkCount, 2); assert.equal(s.title, '');
  assert.ok(act(w, 'openMenu').error); w.close();
});
check('trailing slash query and fragment preserve identity', () => {
  const w = fixture(`<a href="${A}/?x=1#h">${title}</a>`);
  assert.equal(act(w, 'state').title, title); w.close();
});
check('upper-case UUID in the link still matches the lower-case target', () => {
  const w = fixture(`<a href="${A.toUpperCase().replace('HTTPS://ARENA.AI', 'https://arena.ai')}">${title}</a>`);
  assert.equal(act(w, 'state').linkCount, 1); w.close();
});
check('external same-path link cannot confirm', () => {
  const w = fixture(`<a href="${A.replace('arena.ai', 'example.invalid')}">${title}</a>`);
  assert.equal(act(w, 'state').linkCount, 0); w.close();
});
check('whitespace normalization preserves full exact name', () => {
  const w = fixture(`<a href="${A}"> super_nova_ext&nbsp;·\n09-16 03:51 </a>`);
  assert.equal(act(w, 'state').title, title); w.close();
});
check('mobile sidebar sheet is not a foreign dialog for openMenu', () => {
  const w = fixture(mobileSidebar(row));
  const c = counter(w.document.querySelector('button'), ['pointerdown', 'click']);
  const r = act(w, 'openMenu');
  assert.equal(r.error, undefined, r.error); assert.equal(r.ok, true);
  assert.equal(c.pointerdown, 1); assert.equal(c.click, 1); w.close();
});
check('mobile sidebar sheet does not block cleanup', () => {
  const w = fixture(mobileSidebar(row));
  const r = act(w, 'cleanup', '', null); assert.equal(r.error, undefined, r.error); assert.equal(r.ok, true); w.close();
});
check('mobile sidebar state reports link and no rename dialog', () => {
  const w = fixture(mobileSidebar(row));
  const s = act(w, 'state'); assert.equal(s.linkCount, 1); assert.equal(s.title, title); assert.equal(s.renameDialog, false); assert.equal(s.renameMenu, false); w.close();
});
check('foreign dialog still blocks openMenu (fail-closed kept)', () => {
  const w = fixture(`<div role="dialog"><h2>Something else</h2></div>${row}`);
  assert.ok(act(w, 'openMenu').error); w.close();
});
check('foreign dialog still blocks cleanup (fail-closed kept)', () => {
  const w = fixture(`<div role="dialog"><h2>Something else</h2></div>${row}`);
  assert.ok(act(w, 'cleanup', '', null).error); w.close();
});
check('dialog with only data-mobile but wrong data-sidebar is foreign', () => {
  const w = fixture(`<div role="dialog" data-mobile="true" data-sidebar="menu">x</div>${row}`);
  assert.ok(act(w, 'openMenu').error); w.close();
});
check('rename dialog inside mobile sidebar page is still detected and cleanup presses Cancel once', () => {
  const w = fixture(mobileSidebar(row) + `<div role="dialog"><h2>Rename chat</h2> <input type="text"> <button>Rename</button> <button>Cancel</button></div>`);
  const s = act(w, 'state'); assert.equal(s.renameDialog, true);
  let cancels = 0;
  w.document.querySelectorAll('button').forEach(b => { if (b.textContent === 'Cancel') b.onclick = () => cancels++; });
  const r = act(w, 'cleanup', '', null); assert.equal(r.ok, true); assert.equal(cancels, 1); w.close();
});

// ---- 安卓桥补充用例 --------------------------------------------------------------
check('bridge exposes version 3 and state() shortcut uses the current location', () => {
  const w = fixture(row);
  assert.equal(w.__ARENA_RENAME_BRIDGE__.version, 3);
  const s = w.__ARENA_RENAME_BRIDGE__.state();
  assert.equal(s.linkCount, 1); assert.equal(s.title, title); assert.equal(s.error, null); assert.equal(s.pending, false); w.close();
});
check('state with null target resolves the target from location.href', () => {
  const w = fixture(row);
  const s = act(w, 'state', '', null); assert.equal(s.target, A); assert.equal(s.routeMatches, true); w.close();
});
check('openMenu presses the More options button next to the current link, not the first link', () => {
  const other = `<div><a href="${B}">other</a><button aria-label="More options" id="wrong">…</button></div>`;
  const w = fixture(other + `<div><a href="${A}">${title}</a><button aria-label="More options" id="right">…</button></div>`);
  const wrong = counter(w.document.getElementById('wrong'), ['pointerdown', 'click']);
  const right = counter(w.document.getElementById('right'), ['pointerdown', 'click']);
  const r = act(w, 'openMenu'); assert.equal(r.ok, true, r.error);
  assert.deepEqual([wrong.pointerdown, wrong.click, right.pointerdown, right.click], [0, 0, 1, 1]);
  w.close();
});
check('openMenu finds More options via the shadcn menu-item wrapper', () => {
  const w = fixture(`<ul><li data-sidebar="menu-item"><div><a href="${A}">${title}</a></div><button data-sidebar="menu-action" aria-label="More options">…</button></li></ul>`);
  const c = counter(w.document.querySelector('button'), ['pointerdown']);
  const r = act(w, 'openMenu'); assert.equal(r.ok, true, r.error); assert.equal(c.pointerdown, 1); w.close();
});
check('openMenu ignores buttons that merely contain "menu" in their label', () => {
  const w = fixture(`<div><a href="${A}">${title}</a><button aria-label="Open menu">…</button></div>`);
  assert.match(act(w, 'openMenu').error, /More options/); w.close();
});
check('openMenu with collapsed sidebar presses the unique opener once and reports pending', () => {
  const w = fixture(`<button aria-label="Expand sidebar"></button>`);
  const c = counter(w.document.querySelector('button'), ['pointerdown', 'click']);
  assert.equal(act(w, 'openMenu').pending, true);
  assert.equal(act(w, 'openMenu', 'retry').pending, true);
  assert.deepEqual([c.pointerdown, c.click], [1, 1], 'retry must not press the opener again');
  w.close();
});
check('openMenu refuses ambiguous sidebar openers', () => {
  const w = fixture(`<button aria-label="Expand sidebar"></button><button aria-label="Open sidebar"></button>`);
  assert.match(act(w, 'openMenu').error, /不唯一/); w.close();
});
check('renameMenu is reported and menuRename presses the Rename item once', () => {
  const w = fixture(row + `<div role="menu"><div role="menuitem">Rename</div><div role="menuitem">Archive</div></div>`);
  assert.equal(act(w, 'state').renameMenu, true);
  const item = w.document.querySelector('[role="menuitem"]');
  const c = counter(item, ['pointerdown', 'click']);
  const r = act(w, 'menuRename'); assert.equal(r.ok, true, r.error);
  assert.deepEqual([c.pointerdown, c.click], [1, 1]); w.close();
});
check('menuRename refuses when the Rename item is missing or duplicated', () => {
  const none = fixture(row + `<div role="menu"><div role="menuitem">Archive</div></div>`);
  assert.ok(act(none, 'menuRename').error); none.close();
  const two = fixture(row + `<div role="menu"><div role="menuitem">Rename</div><div role="menuitem">Rename</div></div>`);
  assert.ok(act(two, 'menuRename').error); two.close();
});
check('open menu blocks openMenu and cleanup closes it with Escape', () => {
  const w = fixture(row + `<div role="menu"><div role="menuitem">Rename</div></div>`);
  assert.match(act(w, 'openMenu').error, /未确认窗口或菜单/);
  let escapes = 0;
  w.document.querySelector('[role="menu"]').addEventListener('keydown', e => { if (e.key === 'Escape') escapes++; });
  assert.equal(act(w, 'cleanup', '', null).ok, true); assert.equal(escapes, 1); w.close();
});
check('rename dialog is recognised through aria-labelledby and fill writes via native setter + input', () => {
  const w = fixture(row + renameDialogHtml);
  assert.equal(act(w, 'state').renameDialog, true);
  const input = w.document.querySelector('input');
  let inputs = 0; input.addEventListener('input', () => inputs++);
  const r = act(w, 'fill', 'new title'); assert.equal(r.ok, true, r.error);
  assert.equal(input.value, 'new title'); assert.equal(inputs, 1); w.close();
});
check('fill rejects empty or over-long names and non-unique inputs', () => {
  const w = fixture(row + renameDialogHtml);
  assert.ok(act(w, 'fill', '').error);
  assert.ok(act(w, 'fill', 'x'.repeat(101)).error);
  w.close();
  const two = fixture(row + `<div role="dialog"><h2>Rename chat</h2><input type="text"><input type="text"><button>Rename</button></div>`);
  assert.match(act(two, 'fill', 'x').error, /不唯一/); two.close();
});
check('save presses the enabled Rename button once and refuses a disabled one', () => {
  const w = fixture(row + renameDialogHtml);
  const btn = [...w.document.querySelectorAll('button')].find(b => b.textContent === 'Rename');
  const c = counter(btn, ['pointerdown', 'click']);
  const r = act(w, 'save'); assert.equal(r.ok, true, r.error); assert.deepEqual([c.pointerdown, c.click], [1, 1]); w.close();
  const disabled = fixture(row + `<div role="dialog"><h2>Rename chat</h2><input type="text"><button disabled>Rename</button><button>Cancel</button></div>`);
  assert.match(act(disabled, 'save').error, /不可用/); disabled.close();
});
check('a dialog that is not the rename dialog is not mistaken for it', () => {
  const w = fixture(row + `<div role="dialog"><h2>Delete chat</h2><input type="text"><button>Rename</button></div>`);
  assert.equal(act(w, 'state').renameDialog, false);
  assert.ok(act(w, 'fill', 'x').error); w.close();
});
check('hidden links and buttons are ignored', () => {
  const w = fixture(`<div hidden><a href="${A}">${title}</a><button aria-label="More options">…</button></div>`);
  const s = act(w, 'state'); assert.equal(s.linkCount, 0); assert.equal(act(w, 'openMenu').pending, true); w.close();
});
check('unknown action and missing identity are reported as errors', () => {
  const w = fixture(row);
  assert.match(act(w, 'explode').error, /未知重命名操作/);
  const bad = fixture(row, 'https://arena.ai/agent');
  assert.match(act(bad, 'state', '', null).error, /无法确认/); bad.close(); w.close();
});

done();
