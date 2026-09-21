// PageBridge.js 离线回归（node + jsdom）。
// fixture 结构取自 2026-09-21 抓取的 arena.ai 前端，见 docs/mcp-android-prompt-confirm-timeout-20260921.md §3：
//   main > div[role=log] > div[data-agent-transcript-message][data-chat-message-id]
//     > (div[data-user-message-layout] > div[data-user-message-body-row] | 助手气泡 + button[aria-label=Copy])
// 运行：node page-bridge.test.cjs（或 npm test）。
'use strict';
const assert = require('node:assert/strict');
const { page, counter, runner } = require('./fixture.cjs');

const UUID = '11111111-1111-4111-8111-111111111111';
const CONV = `https://arena.ai/agent/${UUID}`;

const userMsg = (id, body) =>
  `<div data-agent-transcript-message data-chat-message-id="${id}">` +
  `<div data-user-message-layout><div data-user-message-body-row>` +
  // 动作条在 DOM 里排在气泡前面，且带 sr-only 文本：整行文本不会以提示词开头，气泡本身才会。
  `<div data-user-message-action><button aria-label="Edit message"><span class="sr-only">Edit</span></button>` +
  `<button aria-label="Copy"><span class="sr-only">Copy</span></button></div>` +
  `<div class="bg-surface-raised rounded-lg w-fit max-w-[min(70%,768px)] ml-auto">${body}</div>` +
  `</div></div></div>`;

const assistantMsg = (id, body, o = {}) =>
  `<div data-agent-transcript-message data-chat-message-id="${id}">` +
  `<div class="bg-surface-primary rounded-xl border w-full">` +
  `<div class="header"><span>Assistant</span></div>` +
  `<div class="parts">${body}${o.busy ? '<div class="animate-spin"></div>' : ''}</div>` +
  (o.done === false ? '' :
    '<div class="actions"><button aria-label="Copy"></button><button aria-label="Good response"></button><button aria-label="Bad response"></button></div>') +
  `</div>` +
  (o.error ? `<div role="alert">${o.error}<button>Retry</button></div>` : '') +
  `</div>`;

const log = (...msgs) => `<div role="log" aria-live="polite">\n${msgs.join('\n')}\n</div>`;

const shell = (inner, o = {}) =>
  `<div id="sidebar"><a href="/agent">New Chat</a><a href="/leaderboard/agent">Leaderboard</a>${o.sidebarExtra || ''}</div>` +
  `<main>\n${inner}\n<div id="composer">` +
  `<div contenteditable="true">${o.draft || ''}</div>` +
  `<button aria-label="Send message"${o.sendDisabled === false ? '' : ' disabled'}${o.sendAriaDisabled ? ' aria-disabled="true"' : ''}></button>` +
  (o.stop ? '<button aria-label="Stop generating"></button>' : '') +
  `</div>${o.mainExtra || ''}</main>${o.extra || ''}`;

const snap = (w, prompt = '1+1=') => w.__ARENA_PAGE_BRIDGE__.snapshot(prompt);
const { check, done } = runner('PageBridge regression');

check('bridge exposes version 3 with snapshot/act', () => {
  const w = page(shell(''));
  assert.equal(w.__ARENA_PAGE_BRIDGE__.version, 3);
  assert.equal(typeof w.__ARENA_PAGE_BRIDGE__.snapshot, 'function');
  assert.equal(typeof w.__ARENA_PAGE_BRIDGE__.act, 'function');
  w.close();
});

check('blank new chat: main ready, no conversation, editor present, send disabled', () => {
  const w = page(shell(''));
  const s = snap(w);
  assert.equal(s.main, true);
  assert.equal(s.conversation, false);
  assert.equal(s.promptConfirmed, false);
  assert.equal(s.editor, true);
  assert.equal(s.draft, '');
  assert.equal(s.sendReady, false);
  assert.equal(s.generating, false);
  assert.equal(s.activity, false);
  assert.equal(s.response, false);
  assert.equal(s.failed, false);
  assert.equal(s.completionConfirmed, false);
  assert.equal(s.messageIdentity, '');
  assert.equal(s.responseSignature, '');
  assert.equal(s.blocker, '');
  assert.equal(s.termsPending, false);
  assert.equal(s.newLinks, 1);
  assert.equal(s.canExpand, false);
  assert.equal(s.snapshotConsistent, true);
  assert.equal(s.url, 'https://arena.ai/agent');
  assert.match(s.generationStamp, /^[^:]+:0:0:::$/);
  w.close();
});

check('typed draft makes send ready; aria-disabled keeps it unavailable', () => {
  const w = page(shell('', { draft: '1+1=', sendDisabled: false }));
  const s = snap(w);
  assert.equal(s.draft, '1+1=');
  assert.equal(s.sendReady, true);
  w.close();
  const w2 = page(shell('', { draft: '1+1=', sendDisabled: false, sendAriaDisabled: true }));
  assert.equal(snap(w2).sendReady, false);
  w2.close();
});

check('streaming: prompt confirmed, generating, no completion, empty responseSignature', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>The answer is</p>', { done: false })), { stop: true }), { url: CONV });
  const s = snap(w);
  assert.equal(s.conversation, true);
  assert.equal(s.promptConfirmed, true);
  assert.equal(s.generating, true);
  assert.equal(s.activity, true);
  assert.equal(s.response, true);
  assert.equal(s.completionConfirmed, false);
  assert.equal(s.responseSignature, '');
  assert.notEqual(s.progressSignature, '');
  assert.equal(s.messageIdentity, 'u1');
  assert.equal(s.failed, false);
  assert.equal(s.editor, true);
  w.close();
});

check('streaming with an empty assistant shell never looks complete', () => {
  // 助手气泡刚挂载、只有头部标签时：response 允许因头部文本为 true（与桌面端 answer.innerText 语义一致），
  // 但生成中绝不能给出 responseSignature，也不能算完成。
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '', { done: false })), { stop: true }), { url: CONV });
  const s = snap(w);
  assert.equal(s.promptConfirmed, true);
  assert.equal(s.generating, true);
  assert.equal(s.responseSignature, '');
  assert.equal(s.completionConfirmed, false);
  w.close();
  const bare = `<div data-agent-transcript-message data-chat-message-id="a1"><div class="bg-surface-primary rounded-xl border w-full"></div></div>`;
  const w2 = page(shell(log(userMsg('u1', '<p>1+1=</p>'), bare), { stop: true }), { url: CONV });
  assert.equal(snap(w2).response, false);
  w2.close();
});

check('completed: Copy button confirms completion and signature is stable across reads', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>1 + 1 = <strong>2</strong></p>'))), { url: CONV });
  const s = snap(w);
  assert.equal(s.promptConfirmed, true);
  assert.equal(s.generating, false);
  assert.equal(s.activity, false);
  assert.equal(s.response, true);
  assert.equal(s.completionConfirmed, true);
  assert.equal(s.failed, false);
  assert.notEqual(s.responseSignature, '');
  assert.ok(s.generationStamp.includes(':u1:a1:' + s.responseSignature), s.generationStamp);
  assert.equal(s.messageIdentity, 'u1');
  const again = snap(w);
  assert.equal(again.generationStamp, s.generationStamp);
  assert.equal(again.responseSignature, s.responseSignature);
  assert.equal(again.progressSignature, s.progressSignature);
  w.close();
});

check('progressSignature changes while the answer grows', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p id="p">The</p>', { done: false })), { stop: true }), { url: CONV });
  const first = snap(w).progressSignature;
  w.document.getElementById('p').textContent = 'The answer';
  assert.notEqual(snap(w).progressSignature, first);
  w.close();
});

check('thinking / tool activity without Stop button is activity, not completion', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<div role="status">Thinking…</div>', { done: false, busy: true }))), { url: CONV });
  const s = snap(w);
  assert.equal(s.generating, false);
  assert.equal(s.activity, true);
  assert.equal(s.thinking, true);
  assert.equal(s.completionConfirmed, false);
  w.close();
});

check('spinner inside a code block is not activity', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<pre><code><span class="animate-spin">x</span></code></pre>'))), { url: CONV });
  const s = snap(w);
  assert.equal(s.activity, false);
  assert.equal(s.completionConfirmed, true);
  w.close();
});

check('error alert inside the answer marks the round failed', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '', { done: false, error: 'Something went wrong.' }))), { url: CONV });
  const s = snap(w);
  assert.equal(s.failed, true);
  assert.equal(s.promptConfirmed, true);
  w.close();
});

check('error alert under the user message (no assistant message yet) marks failed', () => {
  const html = `<div data-agent-transcript-message data-chat-message-id="u1"><div data-user-message-layout><div data-user-message-body-row><p>1+1=</p></div></div><div role="alert">Error: the request failed<button>Retry</button></div></div>`;
  const w = page(shell(log(html)), { url: CONV });
  const s = snap(w);
  assert.equal(s.promptConfirmed, true);
  assert.equal(s.failed, true);
  w.close();
});

check('alerts outside the conversation scope do not fail the round', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>2</p>')), {
    mainExtra: '<div role="alert">File not saved: error while syncing</div>',
    extra: '<div role="alert">Plan unavailable. Something went wrong loading the plan.</div>',
  }), { url: CONV });
  const s = snap(w);
  assert.equal(s.failed, false);
  assert.equal(s.completionConfirmed, true);
  w.close();
});

check('multi-turn: the last user/assistant pair is the current round', () => {
  const html = log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>2</p>'), userMsg('u2', '<p>and 2+2=</p>'), assistantMsg('a2', '<p>4</p>'));
  const w = page(shell(html), { url: CONV });
  const s = snap(w, 'and 2+2=');
  assert.equal(s.promptConfirmed, true);
  assert.equal(s.messageIdentity, 'u2');
  assert.ok(s.generationStamp.includes(':2:u2:a2:'), s.generationStamp);
  assert.equal(s.completionConfirmed, true);
  const stale = snap(w, '1+1=');
  assert.equal(stale.promptConfirmed, false, 'an earlier turn must not confirm the current prompt');
  w.close();
});

check('prompt with newline, full-width space and NBSP is normalized before comparison', () => {
  const w = page(shell(log(userMsg('u1', '<p>第一行</p>\n<p>第二行&nbsp;end</p>'), assistantMsg('a1', '<p>ok</p>'))), { url: CONV });
  const s = snap(w, '  第一行\n第二行\u3000end \n');
  assert.equal(s.promptConfirmed, true);
  w.close();
});

check('prompt appearing only as a substring does not confirm', () => {
  const w = page(shell(log(userMsg('u1', '<p>What is 1+1=? explain</p>'), assistantMsg('a1', '<p>1+1= equals 2</p>'))), { url: CONV });
  const s = snap(w);
  assert.equal(s.promptConfirmed, false);
  assert.equal(s.completionConfirmed, false);
  w.close();
});

check('user bubble followed by attachment name still confirms (prefix + space)', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p><span>photo.png</span>'), assistantMsg('a1', '<p>2</p>'))), { url: CONV });
  assert.equal(snap(w).promptConfirmed, true);
  w.close();
});

check('legacy log without message markers falls back to full-prompt prefix', () => {
  const w = page(shell('<div role="log"><p>1+1=</p>\n<article>2</article></div>'), { url: CONV });
  assert.equal(snap(w, '1+1=').promptConfirmed, true);
  assert.equal(snap(w, '1+1').promptConfirmed, false);
  assert.equal(snap(w, '1+1=').conversation, true);
  w.close();
});

check('nested transcript wrappers are not counted as separate messages', () => {
  const nested = `<div data-agent-transcript-message data-chat-message-id="a1"><div class="quote"><div data-agent-transcript-message data-chat-message-id="q1"><p>quoted</p></div></div><p>2</p><button aria-label="Copy"></button></div>`;
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), nested)), { url: CONV });
  const s = snap(w);
  assert.ok(s.generationStamp.includes(':1:u1:a1:'), s.generationStamp);
  w.close();
});

check('rate-limit notice near the composer sets the blocker', () => {
  const w = page(shell('', { draft: '1+1=', sendDisabled: false, mainExtra: '<div>Too many requests. Please try again later.<br>Visit ID: 01a0bf92</div>' }));
  assert.equal(snap(w).blocker, '网站限流，请稍后继续');
  w.close();
  const toast = page(shell('', { extra: '<ol data-sonner-toaster><li data-sonner-toast role="status">Too many requests</li></ol>' }));
  assert.equal(snap(toast).blocker, '网站限流，请稍后继续');
  toast.close();
});

check('rate-limit wording inside the answer or the draft is not a blocker', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>A rate limit means too many requests… 请稍后再试。</p>')), { draft: 'explain rate limit' }), { url: CONV });
  const s = snap(w);
  assert.equal(s.blocker, '');
  assert.equal(s.completionConfirmed, true);
  w.close();
});

check('security verification dialog is a challenge blocker', () => {
  const w = page(shell('', { extra: '<div role="dialog"><h2>Security Verification</h2><p>Complete this quick security check</p></div>' }));
  assert.equal(snap(w).blocker, '需要人机验证');
  w.close();
});

check('terms dialog is pending and act(terms) presses Agree once', () => {
  const w = page(shell('', { extra: '<div role="dialog"><h2>Terms of Use & Privacy Policy</h2><p>Please review.</p><button>Agree</button></div>' }));
  assert.equal(snap(w).termsPending, true);
  const agree = [...w.document.querySelectorAll('button')].find(b => b.textContent === 'Agree');
  const c = counter(agree, ['pointerdown', 'click']);
  assert.equal(w.__ARENA_PAGE_BRIDGE__.act('terms', '1+1='), true);
  assert.equal(c.pointerdown, 1);
  assert.equal(c.click, 1);
  w.close();
});

check('act(send) presses the Send button with a pointer sequence and bumps the generation revision', () => {
  const w = page(shell('', { draft: '1+1=', sendDisabled: false }));
  const before = snap(w).generationStamp.split(':')[1];
  const send = w.document.querySelector('button[aria-label="Send message"]');
  const c = counter(send, ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click']);
  assert.equal(w.__ARENA_PAGE_BRIDGE__.act('send', '1+1='), true);
  assert.deepEqual(c, { pointerdown: 1, pointerup: 1, mousedown: 1, mouseup: 1, click: 1 });
  const after = snap(w).generationStamp.split(':')[1];
  assert.equal(Number(after), Number(before) + 1);
  w.close();
});

check('generation revision also advances on the generating rising edge', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>')), { stop: true }), { url: CONV });
  const first = snap(w).generationStamp.split(':')[1];
  const second = snap(w).generationStamp.split(':')[1];
  assert.equal(Number(first), 1);
  assert.equal(second, first, 'revision must stay stable while generating continues');
  w.close();
});

check('Stop button in the sidebar does not count as generating', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>'), assistantMsg('a1', '<p>2</p>')), { sidebarExtra: '<button aria-label="Stop generating"></button>' }), { url: CONV });
  const s = snap(w);
  assert.equal(s.generating, false);
  assert.equal(s.completionConfirmed, true);
  w.close();
});

check('newLinks counts only exact New Chat entries; duplicates refuse act(new)', () => {
  const w = page(shell(''));
  assert.equal(snap(w).newLinks, 1);
  const link = w.document.querySelector('a[href="/agent"]');
  const c = counter(link, ['click']);
  assert.equal(w.__ARENA_PAGE_BRIDGE__.act('new', '1+1='), true);
  assert.equal(c.click, 1);
  w.close();
  const dup = page(shell('', { sidebarExtra: '<a href="/agent">New Chat</a>' }));
  assert.equal(snap(dup).newLinks, 2);
  assert.equal(dup.__ARENA_PAGE_BRIDGE__.act('new', '1+1='), false);
  dup.close();
});

check('collapsed sidebar: canExpand only with a unique Expand sidebar button', () => {
  const w = page(`<button aria-label="Expand sidebar"></button>` + shell('').replace('<a href="/agent">New Chat</a>', ''));
  const s = snap(w);
  assert.equal(s.newLinks, 0);
  assert.equal(s.canExpand, true);
  w.close();
  const two = page(`<button aria-label="Expand sidebar"></button><button aria-label="Open sidebar"></button>` + shell('').replace('<a href="/agent">New Chat</a>', ''));
  assert.equal(snap(two).canExpand, false);
  two.close();
});

check('staged attachment names come from Remove buttons outside the log', () => {
  const w = page(shell(log(userMsg('u1', '<p>1+1=</p>')), { mainExtra: '<button aria-label="Remove photo.png"></button>' }), { url: CONV });
  assert.equal(JSON.stringify(snap(w).attachmentNames), JSON.stringify(['photo.png']));
  w.close();
});

check('missing main yields main=false and no crash', () => {
  const w = page('<div>loading…</div>');
  const s = snap(w);
  assert.equal(s.main, false);
  assert.equal(s.conversation, false);
  assert.equal(s.editor, false);
  assert.equal(s.blocker, '');
  w.close();
});

done();
