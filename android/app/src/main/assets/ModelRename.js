// ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/ModelRename.js（逐句移植，动作协议不变）
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/RenamePage.cs（state / openMenu / menuRename / fill / save / cleanup）
// spec: docs/mcp-android-implementation-plan.md §3.1 rename 阶段 / §5
// DOM 证据与修复依据: docs/mcp-android-prompt-confirm-timeout-20260921.md §3 / §5 B32
//
// 只做一件事：把当前对话在 arena 侧栏里重命名。由 ConversationRenamer.kt 按
//   state → openMenu → (等 renameMenu) → menuRename → (等 renameDialog) → fill → save → state…
// 驱动；每次 act 都是一次 evaluateJavascript，返回值只需要 linkCount / title / renameMenu /
// renameDialog / pending / error 这几个字段（WebViewRenameExecutor.kt）。
//
// 真实 DOM（2026-09-21 抓取）：侧栏条目 = 会话链接 a[href="/agent/<uuid>"] + 同级 button[aria-label="More options"]；
// 菜单项 [role="menuitem"] 文案 Rename / Archive / Unarchive；重命名对话框标题 "Rename chat"，按钮 Rename / Cancel。
// 旧版用 aria-label*="menu" 找菜单按钮、用 links[0] 而不是当前会话链接、用 el.click()，真机上打不开菜单，
// 多会话时还可能改错会话——都已按桌面端语义改掉。
//
// 三个必须保留的坑：
//   1. Radix 菜单要用 pointerdown 打开；第三十批又证明移动页 HTMLElement.click() 不触发，
//      所以所有点击统一派发 pointerdown → mousedown → pointerup → mouseup → click；
//   2. 名称输入框是 React 受控输入，必须用原生 setter 写值再派发 input；
//   3. <768px 时侧栏是 Radix Sheet（role=dialog + data-sidebar="sidebar" data-mobile="true"），
//      它是侧栏本身而不是外来弹窗，openMenu / cleanup 不能因它拒绝操作；别的弹窗照旧 fail-closed。
// 离线回归：android/app/src/test/js/rename-bridge.test.cjs。
(function () {
  'use strict';
  if (window.__ARENA_RENAME_BRIDGE__) return;

  var SELECTORS = {
    link: 'a[href]',
    menuItem: '[role="menuitem"]',
    menu: '[role="menu"]',
    dialog: '[role="dialog"]',
    anyDialog: '[role="dialog"],[role="alertdialog"]',
    menuItemRow: 'li,[data-sidebar="menu-item"]',
  };
  var MORE_OPTIONS = /^(More options|更多选项)$/;
  var RENAME = /^(Rename|重命名)$/;
  var CANCEL = /^(Cancel|取消)$/;
  var RENAME_DIALOG = /^(Rename chat|重命名对话)\b/;
  var OPENER = /^(Expand sidebar|Open sidebar|Show sidebar|展开侧边栏|打开侧边栏|展开侧栏|打开侧栏)$/i;
  var TOGGLE = /^(Toggle sidebar|切换侧边栏|切换侧栏)$/i;
  var UUID_PATH = /^\/agent\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  // 与桌面端一致：不看 opacity——侧栏的 More options 常用 opacity-0 + hover/触摸显示。
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

  // 与 ConversationIdentity.created() 同构：只认 https://arena.ai/agent/<uuid>，小写化，忽略尾斜杠 / query / hash。
  function key(value) {
    try {
      var u = new URL(value, location.href);
      var path = u.pathname.replace(/\/+$/, '');
      return u.origin === 'https://arena.ai' && UUID_PATH.test(path) ? u.origin + path.toLowerCase() : null;
    } catch (e) { return null; }
  }

  // 读完整 DOM 文本，而不是链接的无障碍标签或被 CSS 省略号截断的显示文本。
  function conversationTitle(e) {
    var copy = e.cloneNode(true);
    Array.prototype.slice.call(copy.querySelectorAll('svg,button,[role="tooltip"],[aria-hidden="true"]')).forEach(function (n) { n.remove(); });
    return normalize(copy.textContent);
  }

  function isMobileSidebar(e) {
    return e.getAttribute('data-sidebar') === 'sidebar' && e.getAttribute('data-mobile') === 'true';
  }
  function foreign(q) { return all(q).filter(function (e) { return !isMobileSidebar(e); }); }

  // 对话框标题：优先 aria-labelledby 指向的元素（Radix Dialog 的做法），其次首个标题元素，最后整段文本。
  function dialogTitle(d) {
    var id = d.getAttribute('aria-labelledby');
    var byId = id ? document.getElementById(id) : null;
    if (byId) return normalize(text(byId));
    var heading = d.querySelector('h1,h2,h3,h4');
    if (heading) return normalize(text(heading));
    return normalize(text(d));
  }
  function isRenameDialog(d) { return RENAME_DIALOG.test(dialogTitle(d)) || RENAME_DIALOG.test(normalize(text(d))); }
  function renameDialog() {
    var ds = all(SELECTORS.dialog).filter(isRenameDialog);
    return ds.length === 1 ? ds[0] : null;
  }

  function menuItems() {
    var items = all(SELECTORS.menuItem);
    all(SELECTORS.menu).forEach(function (m) {
      all('button', m).forEach(function (b) { if (items.indexOf(b) < 0) items.push(b); });
    });
    return items;
  }
  function renameItems() { return menuItems().filter(function (e) { return RENAME.test(label(e)); }); }

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
    // shadcn 侧栏：<li data-sidebar="menu-item"><a …/><button data-sidebar="menu-action" aria-label="More options"/></li>
    var item = link.closest(SELECTORS.menuItemRow);
    if (item && item !== row) b = all('button', item).filter(function (e) { return MORE_OPTIONS.test(label(e)); });
    return b;
  }

  function act(action, value, target) {
    try {
      var expected = key(target || location.href);
      var links = expected ? all(SELECTORS.link).filter(function (e) { return key(e.href) === expected; }) : [];
      if (action !== 'cleanup' && (!expected || location.origin !== 'https://arena.ai')) throw new Error('无法确认待重命名会话身份');

      if (action === 'state') {
        return {
          title: links.length === 1 ? conversationTitle(links[0]) : '',
          target: expected,
          linkCount: links.length,
          routeMatches: key(location.href) === expected,
          renameDialog: !!renameDialog(),
          renameMenu: renameItems().length > 0,
          pending: false,
          error: null,
        };
      }

      if (action === 'cleanup') {
        var ds = foreign(SELECTORS.anyDialog), menus = all(SELECTORS.menu);
        if (!ds.length && !menus.length) return { ok: true };
        if (ds.length === 1 && isRenameDialog(ds[0]) && !menus.length) {
          var cancels = all('button', ds[0]).filter(function (e) { return CANCEL.test(label(e)) && !e.disabled; });
          if (cancels.length !== 1) throw new Error('无法安全关闭重命名窗口');
          press(cancels[0]);
          return { ok: true };
        }
        if (!ds.length && menus.length === 1 && all(SELECTORS.menuItem, menus[0]).some(function (e) { return RENAME.test(label(e)); })) {
          menus[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
          return { ok: true };
        }
        throw new Error('存在未确认窗口，未继续自动操作');
      }

      if (action === 'openMenu') {
        if (key(location.href) !== expected) throw new Error('当前页面已切换，未操作其他对话');
        var prior = window.__arenaRenameSidebarAttempt;
        if (value !== 'retry' || !prior || prior.target !== expected) {
          window.__arenaRenameSidebarAttempt = { target: expected, expanded: false };
        }
        var attempt = window.__arenaRenameSidebarAttempt;
        if (foreign(SELECTORS.anyDialog + ',' + SELECTORS.menu).length) throw new Error('存在未确认窗口或菜单，未展开侧栏或点击其他对话');
        if (links.length === 0) {
          var opener = all('button').filter(function (e) {
            return !e.disabled && (OPENER.test(label(e)) || (TOGGLE.test(label(e)) && e.getAttribute('aria-expanded') === 'false'));
          });
          if (opener.length > 1) throw new Error('展开侧栏按钮不唯一，未点击');
          if (opener.length === 1 && !attempt.expanded) { attempt.expanded = true; press(opener[0]); }
          return { pending: true };
        }
        if (links.length > 1) throw new Error('当前对话在侧栏中不唯一，无法定位菜单');
        try { links[0].scrollIntoView({ block: 'nearest' }); } catch (e) {}
        var more = moreOptionsButton(links[0]);
        if (more.length !== 1) throw new Error('未找到当前对话的 More options 菜单');
        press(more[0]);
        return { ok: true };
      }

      if (action === 'menuRename') {
        var items = renameItems();
        if (items.length !== 1) throw new Error('重命名菜单项不唯一或尚未出现');
        press(items[0]);
        return { ok: true };
      }

      if (action === 'fill') {
        var d = renameDialog();
        if (!d) throw new Error('当前没有唯一的重命名对话框');
        if (!value || value.length > 100) throw new Error('名称长度错误');
        var inputs = all('input', d).filter(function (e) { return e.type === 'text'; });
        if (inputs.length !== 1) throw new Error('名称输入框不唯一');
        var input = inputs[0];
        var last = input.value;
        Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, value);
        var tracker = input._valueTracker;
        if (tracker) tracker.setValue(last);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return { ok: true };
      }

      if (action === 'save') {
        var dialog = renameDialog();
        if (!dialog) throw new Error('当前没有唯一的重命名对话框');
        var saves = all('button', dialog).filter(function (e) { return RENAME.test(label(e)); });
        if (saves.length !== 1 || saves[0].disabled) throw new Error('重命名按钮不可用');
        press(saves[0]);
        return { ok: true };
      }

      throw new Error('未知重命名操作: ' + action);
    } catch (e) {
      return { error: e.message || String(e) };
    }
  }

  window.__ARENA_RENAME_BRIDGE__ = {
    version: 3,
    act: act,
    state: function () { return act('state', '', null); },
    selectors: SELECTORS,
  };
})();
