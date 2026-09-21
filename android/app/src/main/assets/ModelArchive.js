// ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/ModelArchive.js（逐句移植，状态机 / 返回协议不变）
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.ModelArchive.cs（调用方：每 250ms 一次，最多 120 次）
// spec: docs/mcp-android-implementation-plan.md §3.4 保留策略 / docs/mcp-android-prompt-confirm-timeout-20260921.md §6 B34
//
// 只做一件事：把「未勾选保留的模型」所在的当前对话，通过侧栏 More options → Archive（→ 可能的确认框）
// 移入 Arena 网站归档，并等到成功证据（toast 或当前行确实消失）才返回 confirmed。
// 由 core 的 WebsiteArchiver.kt 轮询驱动：每次 step() 都是一次 evaluateJavascript，
// 状态挂在 window.__arenaModelArchiveState 上并用 token 隔离不同轮次。
//
// 与桌面端的差异（都是为对齐安卓桥，不改判定语义）：
//   1. 快照来自 window.__ARENA_PAGE_BRIDGE__.snapshot(prompt)（桌面端是 __arenaCompanion.read）；
//   2. 所有点击统一走 pointerdown → mousedown → pointerup → mouseup → click（第三十批：移动页 HTMLElement.click() 不触发；
//      Radix 菜单触发器只认 pointerdown，菜单项 / 对话框按钮认 click）；
//   3. <768px 时侧栏是 Radix Sheet（role=dialog + data-sidebar="sidebar" data-mobile="true"），不是外来弹窗；
//   4. 不认 arena-demo.local：安卓的离线演示由 DemoArenaPage.kt 完成，阶段机在 demo 下根本不会调网站归档。
// 绝不改用删除、绝不点 Undo、绝不在页面切走后继续点：任何不确定都以 error 结束，由阶段机暂停等人工。
// 离线回归：android/app/src/test/js/archive-bridge.test.cjs。
(function () {
  'use strict';
  if (window.__ARENA_ARCHIVE_BRIDGE__) return;

  var SELECTORS = {
    link: 'a[href]',
    menu: '[role="menu"]',
    menuItem: '[role="menuitem"]',
    anyDialog: '[role="dialog"],[role="alertdialog"]',
    unsettled: '[role="menu"],[role="dialog"],[role="alertdialog"],[role="progressbar"]',
    notice: '[role="status"],[role="alert"],[data-sonner-toast]',
    menuItemRow: 'li,[data-sidebar="menu-item"]',
  };
  var UUID_PATH = /^\/agent\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  var MORE_OPTIONS = /^(More options|更多选项|更多操作)$/;
  var ARCHIVE = /^(Archive|Archive chat|Archive conversation|归档|归档对话|归档聊天)$/i;
  var ARCHIVE_DIALOG = /^(Archive (chat|conversation)|归档(对话|聊天))[?？]?$/i;
  var STOP = /^(Stop generating|Stop generation|停止生成|停止回答)$/;
  var NEW_CHAT = /^(New Chat|新对话|新建对话)$/i;
  var OPENER = /^(Expand sidebar|Open sidebar|Show sidebar|展开侧边栏|打开侧边栏|展开侧栏|打开侧栏)$/i;
  var TOGGLE = /^(Toggle sidebar|切换侧边栏|切换侧栏)$/i;
  var FAILURE = /error|failed|失败|出错/i;

  // 与 ModelRename.js 一致：不看 opacity——More options 常用 opacity-0 + hover/触摸显示。
  function visible(e) { return !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden'; }
  function label(e) { return (e.getAttribute('aria-label') || e.textContent || '').trim().replace(/\s+/g, ' '); }
  function all(q, root) {
    try { return Array.prototype.slice.call((root || document).querySelectorAll(q)).filter(visible); } catch (e) { return []; }
  }
  function normalize(s) {
    s = s == null ? '' : String(s);
    try { s = s.normalize('NFC'); } catch (e) {}
    return s.replace(/\s+/g, ' ').trim();
  }
  function text(e) { return e ? (e.innerText || e.textContent || '') : ''; }
  function isMobileSidebar(e) {
    return e.getAttribute('data-sidebar') === 'sidebar' && e.getAttribute('data-mobile') === 'true';
  }
  function foreign(q, root) { return all(q, root).filter(function (e) { return !isMobileSidebar(e); }); }

  // 与 ConversationIdentity.created() 同构：只认 https://arena.ai/agent/<uuid>，小写化，忽略尾斜杠 / query / hash。
  function key(value) {
    try {
      var u = new URL(value, location.href);
      var path = u.pathname.replace(/\/+$/, '');
      return u.origin === 'https://arena.ai' && UUID_PATH.test(path) ? u.origin + path.toLowerCase() : null;
    } catch (e) { return null; }
  }
  function emptyComposerRoute() {
    return location.origin === 'https://arena.ai' && /^\/agent\/?$/.test(location.pathname);
  }

  function notices() { return all(SELECTORS.notice).map(function (e) { return normalize(text(e)); }); }
  // 成功 toast 里带 Undo 按钮文本：只读，绝不点。
  function success(s) {
    var t = normalize(s);
    return /^Your previous chat history was archived[.!]?(?: Undo)?$/i.test(t)
      || /\b(chat|conversation) (has been |was )?archived(?: successfully)?[.!]?(?: Undo)?$/i.test(t)
      || /^(已归档|归档成功|对话已归档|聊天已归档)[。！]?(?: 撤销)?$/.test(t);
  }

  function snapshot(prompt) {
    try {
      var bridge = window.__ARENA_PAGE_BRIDGE__;
      if (bridge && typeof bridge.snapshot === 'function') return bridge.snapshot(prompt);
      var legacy = window.__arenaCompanion;
      if (legacy && typeof legacy.read === 'function') return legacy.read(prompt);
    } catch (e) {}
    return null;
  }
  // 与 RetryController.archiveExcludedModel 的前置条件同构：回答必须仍是那一条、已完成、无阻塞。
  function answerUnchanged(prompt, generationStamp) {
    var s = snapshot(prompt);
    return !!generationStamp && !!s && !!s.promptConfirmed && s.generationStamp === generationStamp &&
      !s.generating && !s.activity && !s.failed && !s.blocker;
  }

  // pointerdown 让 Radix 菜单打开，click 让菜单项 / 对话框按钮生效；不抢焦点，避免打断菜单的 FocusScope。
  function press(el) {
    if (!el) return false;
    try { el.scrollIntoView({ block: 'nearest' }); } catch (e) {}
    var r = el.getBoundingClientRect();
    var base = {
      bubbles: true, cancelable: true, view: window,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
      button: 0, ctrlKey: false,
    };
    function fire(Ctor, type, extra) {
      try { el.dispatchEvent(new Ctor(type, Object.assign({}, base, extra || {}))); } catch (e) {}
    }
    var P = window.PointerEvent;
    if (P) fire(P, 'pointerdown', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 1 });
    fire(MouseEvent, 'mousedown', { buttons: 1 });
    if (P) fire(P, 'pointerup', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 0 });
    fire(MouseEvent, 'mouseup', { buttons: 0 });
    fire(MouseEvent, 'click', { buttons: 0 });
    return true;
  }

  function moreOptionsButton(link) {
    var row = link.parentElement;
    var b = row ? all('button', row).filter(function (e) { return MORE_OPTIONS.test(label(e)); }) : [];
    if (b.length === 1) return b;
    var item = link.closest(SELECTORS.menuItemRow);
    if (item && item !== row) b = all('button', item).filter(function (e) { return MORE_OPTIONS.test(label(e)); });
    return b;
  }
  function targetLinks(expected) {
    return all(SELECTORS.link).filter(function (e) { return key(e.href) === expected; });
  }
  function sidebarOpeners() {
    return all('button').filter(function (e) {
      return !e.disabled && (OPENER.test(label(e)) || (TOGGLE.test(label(e)) && e.getAttribute('aria-expanded') === 'false'));
    });
  }
  // 菜单归属：Radix 打开后触发器带 aria-controls=<menu id> 与 aria-expanded=true。
  function ownedMenu(trigger) {
    var id = trigger.getAttribute('aria-controls');
    var menu = id ? document.getElementById(id) : null;
    if (!menu) {
      var menus = foreign(SELECTORS.menu);
      menu = menus.length === 1 ? menus[0] : null;
    }
    if (!visible(menu)) return null;
    if (menu.getAttribute('role') !== 'menu' || trigger.getAttribute('aria-expanded') !== 'true')
      throw new Error('无法确认菜单属于当前对话');
    return menu;
  }

  function step(target, token, prompt, generationStamp) {
    try {
      var expected = key(target);
      if (!expected || !token) throw new Error('归档目标不是有效对话');
      var state = window.__arenaModelArchiveState;
      if (!state || state.token !== token) {
        if (key(location.href) !== expected) throw new Error('当前页面不是待归档对话');
        if (foreign(SELECTORS.menu + ',' + SELECTORS.anyDialog).length) throw new Error('请先关闭已有菜单或对话框，再继续归档');
        state = window.__arenaModelArchiveState = { token: token, target: expected, stage: 'open', before: [], confirmed: false, expanded: false, absentSince: 0 };
      }
      if (state.target !== expected) throw new Error('归档目标改变，已停止');
      var onTarget = key(location.href) === expected;
      var emptyRoute = emptyComposerRoute();
      if (!onTarget && !emptyRoute) throw new Error('已切换到其他对话，归档确认已停止');
      if (state.confirmed) return { confirmed: true, stage: state.stage };

      if (state.stage === 'open' || state.stage === 'menu') {
        if (!answerUnchanged(prompt, generationStamp)) throw new Error('当前回答已改变或不可确认，未点击网站归档');
      }

      if (state.stage === 'sent' || state.stage === 'confirmSent') {
        var fresh = notices().filter(function (s) { return state.before.indexOf(s) < 0; });
        if (fresh.some(function (s) { return FAILURE.test(s); })) throw new Error('网页报告归档失败，请人工检查');
        if (fresh.some(success)) { state.confirmed = true; return { confirmed: true, evidence: 'toast', stage: state.stage }; }
        // 有些版本只把当前行从侧栏移除而不弹成功提示：要求原始行确实脱离文档、没有替身（连隐藏的都不能有）、
        // 侧栏可用、没有弹窗 / 加载态，并稳定观察 1.5 秒。
        var stillPresent = Array.prototype.slice.call(document.querySelectorAll(SELECTORS.link)).some(function (e) { return key(e.href) === expected; });
        var newChat = all(SELECTORS.link).filter(function (e) {
          try { return new URL(e.href, location.href).pathname === '/agent' && NEW_CHAT.test(label(e)); } catch (err) { return false; }
        });
        var sidebarClosed = sidebarOpeners().length > 0;
        var unsettled = foreign(SELECTORS.unsettled).length > 0;
        var removed = !!state.originalLink && !state.originalLink.isConnected && !stillPresent &&
          newChat.length === 1 && !sidebarClosed && !unsettled && all('main').length === 1;
        if (removed) {
          if (!state.absentSince) state.absentSince = Date.now();
          if (Date.now() - state.absentSince >= 1500) { state.confirmed = true; return { confirmed: true, evidence: 'current-row-removed', stage: state.stage }; }
        } else {
          state.absentSince = 0;
        }
      }

      if (!onTarget) {
        // 归档可能先跳到空白输入页、再弹成功提示：只等确认，不在新页面上操作。
        if ((state.stage === 'sent' || state.stage === 'confirmSent') && emptyRoute) return { pending: true, stage: state.stage };
        throw new Error('页面已切换且未获取归档成功提示，请人工确认');
      }
      var mains = all('main');
      if (mains.length !== 1) throw new Error('当前对话尚未加载');
      if (all('button', mains[0]).some(function (e) { return STOP.test(label(e)); })) throw new Error('生成尚未停止，不执行归档');

      if (state.stage === 'open') {
        var links = targetLinks(expected);
        if (links.length === 0) {
          var openers = sidebarOpeners();
          if (openers.length > 1) throw new Error('展开侧栏按钮不唯一，未点击');
          if (openers.length === 1 && !state.expanded) { state.expanded = true; press(openers[0]); return { pending: true, stage: state.stage }; }
          throw new Error('侧栏中没有唯一的当前对话，未点击任何其他对话');
        }
        if (links.length !== 1) throw new Error('侧栏中没有唯一的当前对话，未点击任何其他对话');
        try { links[0].scrollIntoView({ block: 'nearest' }); } catch (e) {}
        var controls = moreOptionsButton(links[0]);
        if (controls.length !== 1 || controls[0].disabled) throw new Error('未找到当前对话的唯一三个点菜单');
        state.originalLink = links[0]; state.trigger = controls[0]; state.stage = 'menu';
        press(state.trigger);
        return { pending: true, stage: state.stage };
      }

      if (state.stage === 'menu') {
        var menu = ownedMenu(state.trigger);
        if (!menu) return { pending: true, stage: state.stage };
        var entries = all(SELECTORS.menuItem, menu).filter(function (e) { return ARCHIVE.test(label(e)); });
        if (entries.length !== 1 || entries[0].getAttribute('aria-disabled') === 'true')
          throw new Error('当前菜单没有唯一可用的归档入口；不会改用删除');
        state.before = notices(); state.stage = 'sent';
        press(entries[0]);
        return { pending: true, stage: state.stage };
      }

      if (state.stage === 'sent') {
        var ds = foreign(SELECTORS.anyDialog);
        if (ds.length) {
          if (ds.length !== 1) throw new Error('归档确认窗口不唯一');
          var d = ds[0];
          if (!answerUnchanged(prompt, generationStamp)) throw new Error('确认归档前回答发生变化，未继续点击');
          var title = all('h1,h2,h3,[role="heading"]', d).map(function (e) { return normalize(text(e)); }).join(' ');
          if (!ARCHIVE_DIALOG.test(title)) throw new Error('不是可识别的归档确认窗口，未继续点击');
          var buttons = all('button', d).filter(function (e) { return ARCHIVE.test(label(e)) && !e.disabled; });
          if (buttons.length !== 1) throw new Error('没有唯一的归档确认按钮');
          state.stage = 'confirmSent';
          press(buttons[0]);
        }
      }
      return { pending: true, stage: state.stage };
    } catch (e) {
      return { error: e.message || String(e) };
    }
  }

  window.__ARENA_ARCHIVE_BRIDGE__ = {
    version: 1,
    step: step,
    reset: function () { window.__arenaModelArchiveState = null; return true; },
    selectors: SELECTORS,
  };
  // 与桌面端 WebPage.ModelArchive.cs 的调用名保持兼容。
  if (!window.__arenaModelArchive) window.__arenaModelArchive = step;
})();
