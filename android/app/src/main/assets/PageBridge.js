// ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/PageBridge.js (view / action)
// ref: reference/Arena模型助手-源码-fyb-0.1.0/src/WebPage.cs (Read/Act)
// spec: docs/mcp-android-implementation-plan.md §4 「必须保持单次快照语义」
// 根因与映射依据: docs/mcp-android-prompt-confirm-timeout-20260921.md §3 / §4
//
// 单次调用返回整个 PageState 快照。绝不能拆成多次 evaluate——
// 那会撕裂 snapshotConsistent 的语义，让阶段机基于半新半旧的页面做判断。
//
// 对话区按 2026-09-21 抓取的 arena.ai 前端（部署 dpl_8JFP6KSwW7PUGUCzKeAYEMTvMtDN）重映射：
//   对话区      main [role="log"]（ChatMessageList）
//   每条消息    [data-agent-transcript-message][data-chat-message-id]
//   用户消息    消息内含 [data-user-message-layout]（站点里唯一稳定的角色标记）
//   正在生成    main 内 button[aria-label="Stop generating"]
//   完成证据    最后一条助手消息内出现 button[aria-label="Copy"]（非流式时才渲染动作条）
//   出错        限定在回答范围内的 [role="alert"]（全局另有 Plan unavailable / 文件未保存等提示）
// 站点全站 JS 不存在 data-message-author-role / data-message-id / "Copy response"（ChatGPT 风格），
// 不要再把它们当作选择器引入。
// 输入框 / 发送 / New Chat / 侧栏展开 / 条款弹窗 / pointer 点击序列已在真机校准（第二十八至三十批），保持不变。
// 离线回归：android/app/src/test/js/page-bridge.test.cjs（node + jsdom，fixture 取自真实结构）。
(function () {
  'use strict';
  if (window.__ARENA_PAGE_BRIDGE__) return;

  var SELECTORS = {
    main: 'main',
    log: '[role="log"]',
    message: '[data-agent-transcript-message]',
    userLayout: '[data-user-message-layout]',
    userBody: '[data-user-message-body-row]',
    editor: 'textarea[name="message"], textarea[data-testid="prompt-textarea"], [contenteditable="true"], textarea',
    sendButton: 'button[data-testid="send-button"], button[aria-label*="Send" i], button[aria-label*="发送"]',
    // ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/PageBridge.js
    //      只按精确 href 取入口，再按标签过滤。后缀写法 a[href$="/agent"] 会连侧栏的
    //      /leaderboard/agent（Leaderboard）一起算进来，newLinks 变成 2 → 阶段机以
    //      「检测到多个 New Chat 入口」保护性暂停（真机已复现：1 个 New Chat + 1 个 Leaderboard）。
    newChat: 'a[href="/agent"]',
    stopButton: 'button[aria-label="Stop generating"], button[data-testid="stop-button"]',
    copyButton: 'button[aria-label="Copy"]',
    alert: '[role="alert"]',
    busy: '[aria-busy="true"],[role="progressbar"],.animate-spin',
    // 限流 / 验证提示只在这些容器 + main 中对话区以外的部分查找，绝不扫整个 body：
    // 回答正文里出现 "rate limit" / "请稍后" 不能被当成站点限流。
    notice: '[role="alert"],[role="status"],[role="alertdialog"],[role="dialog"],[data-sonner-toast]',
    errorState: '[role="alert"],[role="status"],[data-state="error"],[data-status="error"],[data-state="stopped"],[data-status="stopped"]',
  };

  var STOP_LABEL = /^(Stop generating|Stop generation|停止生成|停止回答)$/i;
  var SEND_LABEL = /^(Send message|发送消息)$/i;
  var COPY_LABEL = /^(Copy|Copy response|Copy message|Copy answer|复制|复制回答|复制回复)$/i;
  var THINKING_LABEL = /^(Thinking\b|Thought\b|思考|已思考)/i;
  var FAILED_ALERT = /stopped|error|something went wrong|failed|rejected|出错|失败|已停止/i;
  var FAILED_STATUS = /^(Stopped|Generation stopped|Error|Something went wrong|已停止|生成已停止|生成失败)[.!。！]?$/i;
  var RATE_LIMIT = /rate limit|too many requests|429 too many|try again later|quota exceeded|limit reached|请稍后/i;
  var CHALLENGE = /security verification|verify you are human|需要人机验证|人机身份验证|complete this quick security check/i;
  // 附件入口按钮的标签（只在 label[for] / 包裹 label / 同容器唯一按钮都找不到时才用，且要求唯一命中）。
  var ATTACH_LABEL = /attach|upload|add file|add files|choose file|添加附件|上传|附件/i;

  function all(sel, root) {
    if (root === null) return [];
    try { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); } catch (e) { return []; }
  }
  function one(sel, root) {
    if (root === null) return null;
    try { return (root || document).querySelector(sel); } catch (e) { return null; }
  }
  // 可交互目标（输入框 / 发送 / 入口）的可见性：真机校准过的严格版，含 opacity。
  function visible(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  }
  // 对话区节点 / 完成证据按钮的可见性：与桌面端 visible() 一致，不看 opacity——
  // 动作条常用 opacity-0 + hover 显示，opacity 为 0 不代表它不存在。
  function shown(el) {
    if (!el) return false;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    var s = window.getComputedStyle(el);
    return s.visibility !== 'hidden' && s.display !== 'none';
  }
  function text(el) { return el ? (el.innerText || el.textContent || '').trim() : ''; }
  // NFC + 空白折叠：提示词与页面文本比较前都要过一遍，全角空格 / 换行 / NBSP 一视同仁。
  function norm(s) {
    s = s == null ? '' : String(s);
    try { s = s.normalize('NFC'); } catch (e) {}
    return s.replace(/\s+/g, ' ').trim();
  }
  function notInCode(el) { return !el.closest('pre,code'); }
  function buttons(scope) { return all('button', scope).filter(shown); }

  // ref: reference/Arena模型助手-源码-fyb-0.1.0/assets/PageBridge.js —— label/navVisible/
  //      newChatLinks/sidebarOpener 与桌面端逐句对齐：
  //      侧栏被 transform 移出视口后仍会有 clientRect，所以「可见」还必须落在视口内、
  //      不能被 aria-hidden/inert 包住；标签必须严格等于 New Chat，别的 /agent 链接不算入口。
  function label(el) {
    return (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ');
  }

  function navVisible(el) {
    if (!el || !visible(el) || el.closest('[aria-hidden="true"],[inert]')) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
      r.left < window.innerWidth && r.top < window.innerHeight;
  }

  function newChatLinks() {
    return all(SELECTORS.newChat).filter(function (e) {
      return navVisible(e) && label(e) === 'New Chat';
    });
  }

  // 与桌面端一致：只有「没有可见 New Chat 入口 + 没有已展开的侧栏控件 + 恰好一个
  // Expand/Open sidebar 按钮」才认为侧栏可以展开，别的按钮一概不碰。
  function sidebarOpener() {
    if (newChatLinks().length) return null;
    var opened = all('button').filter(navVisible).some(function (e) {
      return /^(Collapse sidebar|Close sidebar)$/.test(label(e));
    });
    if (opened) return null;
    var matches = all('button').filter(function (e) {
      return navVisible(e) && !e.disabled &&
        /^(Expand sidebar|Open sidebar)$/.test(label(e)) &&
        e.getAttribute('aria-expanded') !== 'true';
    });
    return matches.length === 1 ? matches[0] : null;
  }

  // 内容指纹（FNV-1a + djb2，与桌面端 digest 同构）。用于 responseSignature /
  // progressSignature 比较，不需要密码学强度，只需要"内容变了就一定变"。空文本返回空串。
  function digest(s) {
    if (!s) return '';
    var a = 2166136261, b = 5381;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      a = Math.imul(a ^ c, 16777619);
      b = Math.imul(b, 33) ^ c;
    }
    return s.length + ':' + (a >>> 0).toString(16) + ':' + (b >>> 0).toString(16);
  }

  function mainElement() { return all(SELECTORS.main).filter(visible)[0] || null; }

  function editorOf(mainEl) {
    return all(SELECTORS.editor, mainEl).filter(visible)[0] || one(SELECTORS.editor);
  }

  function draft(mainEl) {
    var e = editorOf(mainEl);
    if (!e) return null;
    return (e.value !== undefined ? e.value : e.innerText || '').trim();
  }

  function sendButton(mainEl) {
    var candidates = all(SELECTORS.sendButton, mainEl || undefined).filter(visible);
    for (var i = 0; i < candidates.length; i++) if (SEND_LABEL.test(label(candidates[i]))) return candidates[i];
    return candidates[0] || null;
  }

  function stopButton(mainEl) {
    var root = mainEl || undefined;
    var byLabel = all('button', root).filter(shown).filter(function (b) { return !b.disabled && STOP_LABEL.test(label(b)); });
    if (byLabel.length) return byLabel[0];
    return all(SELECTORS.stopButton, root).filter(shown).filter(function (b) { return !b.disabled; })[0] || null;
  }

  function isUser(m) { return !!one(SELECTORS.userLayout, m); }
  function idOf(m) { return m ? (m.getAttribute('data-chat-message-id') || '') : ''; }

  // 去掉按钮 / 状态条 / 时间戳后的正文，用于回答文本与进度指纹（不要求保留换行）。
  function bodyText(el) {
    if (!el) return '';
    var copy = el.cloneNode(true);
    all('button,[role="status"],[role="progressbar"],time,svg', copy).forEach(function (n) { n.remove(); });
    return norm(text(copy));
  }

  // 「我的问题已出现在页面上」：用户消息内必须有某个节点的完整文本等于提示词，
  // 或以「提示词 + 空格」开头（动作条 / 附件名可能跟在后面）。禁止 indexOf 子串匹配——
  // 那会把「1+1=」匹配进任何包含它的回答。读活节点的 innerText 才能保留段落间换行。
  function promptShown(user, expected) {
    if (!user || !expected) return false;
    var root = one(SELECTORS.userBody, user) || user;
    var candidates = [root].concat(all('div,p,span', root).filter(function (n) { return !n.closest('button'); }));
    for (var i = 0; i < candidates.length; i++) {
      var t = norm(text(candidates[i]));
      if (t === expected || t.indexOf(expected + ' ') === 0) return true;
    }
    return false;
  }

  function isFailed(scope) {
    if (!scope) return false;
    var nodes = [scope].concat(all(SELECTORS.errorState, scope));
    return nodes.filter(shown).filter(notInCode).some(function (e) {
      var state = e.getAttribute('data-state') || e.getAttribute('data-status') || '';
      if (/^(error|stopped|failed)$/.test(state)) return true;
      var role = e.getAttribute('role');
      if (role === 'alert') return FAILED_ALERT.test(norm(text(e)));
      if (role === 'status') return FAILED_STATUS.test(norm(text(e)));
      return false;
    });
  }

  // 站点提示文本：alert / status / dialog / toast + main 中对话区、输入框、代码块以外的部分。
  function noticeText(mainEl) {
    var parts = all(SELECTORS.notice).filter(shown).map(text);
    if (mainEl) {
      var copy = mainEl.cloneNode(true);
      all(SELECTORS.log + ',textarea,[contenteditable="true"],pre,code', copy).forEach(function (n) { n.remove(); });
      parts.push(text(copy));
    } else {
      parts.push(text(document.body));
    }
    return parts.join('\n');
  }

  function blockerOf(mainEl) {
    var notices = noticeText(mainEl);
    if (CHALLENGE.test(notices)) return '需要人机验证';
    var cleaned = notices.replace(/This site is protected by reCAPTCHA[^\.]*\./gi, '');
    if (/captcha/i.test(cleaned)) return '需要人机验证';
    if (RATE_LIMIT.test(notices)) return '网站限流，请稍后继续';
    return '';
  }

  function termsDialogs() {
    return all('[role="dialog"]').filter(visible).filter(function (d) {
      var t = text(d);
      return /terms of (service|use)|服务条款|使用条款/i.test(t) && !/sidebar|导航/i.test(t);
    });
  }

  function termsButton() {
    var dialogs = termsDialogs();
    if (!dialogs.length) return null;
    var btns = Array.prototype.slice.call(dialogs[0].querySelectorAll('button')).filter(visible);
    for (var i = 0; i < btns.length; i++) {
      var t = text(btns[i]);
      if (/agree|同意|accept|confirm/i.test(t)) return btns[i];
    }
    return btns.length ? btns[0] : null;
  }

  // 附件（B35 接线用）：桌面端 stagedNames —— 输入区 "Remove <name>" 按钮即已暂存附件。
  function stagedNames(mainEl) {
    if (!mainEl) return [];
    return buttons(mainEl).filter(function (b) { return !b.closest('[role="log"]'); })
      .map(label).filter(function (t) { return t.indexOf('Remove ') === 0; })
      .map(function (t) { return t.slice(7); });
  }

  // ref: 桌面端 __arenaCompanion.attachmentsReady —— 绑定附件必须一个不少地出现在 "Remove <name>"
  //      列表里、数量恰好相等、且 main 内没有上传中的进度指示；空清单恒为就绪。
  function attachmentsReady(names) {
    names = Array.isArray(names) ? names : [];
    if (!names.length) return true;
    var mainEl = mainElement();
    if (!mainEl) return false;
    var attached = stagedNames(mainEl);
    var busy = all('[role="progressbar"],.animate-spin', mainEl).some(shown);
    if (busy || attached.length !== names.length) return false;
    for (var i = 0; i < names.length; i++) if (attached.indexOf(names[i]) < 0) return false;
    return true;
  }

  function cssEscape(s) {
    try { if (window.CSS && CSS.escape) return CSS.escape(s); } catch (e) {}
    return String(s).replace(/["\\]/g, '\\$&');
  }

  // 能被真实触摸的附件入口：input 自身可见就点 input；否则依次找 label[for=id]、包裹它的 label、
  // 与 input 同一父容器里唯一的可用按钮、最后是 main 内标签匹配 ATTACH_LABEL 的唯一按钮。都没有则放弃。
  function attachmentTrigger(input, mainEl) {
    if (visible(input)) return input;
    if (input.id) {
      var labels = all('label[for="' + cssEscape(input.id) + '"]').filter(visible);
      if (labels.length === 1) return labels[0];
    }
    var wrap = input.closest('label');
    if (wrap && visible(wrap)) return wrap;
    var parent = input.parentElement;
    if (parent) {
      var siblings = buttons(parent).filter(visible).filter(function (b) { return !b.disabled; });
      if (siblings.length === 1) return siblings[0];
    }
    var named = buttons(mainEl).filter(visible).filter(function (b) {
      return !b.disabled && !b.closest('[role="log"]') && ATTACH_LABEL.test(label(b));
    });
    return named.length === 1 ? named[0] : null;
  }

  // ref: 桌面端 AttachmentUpload.Stage 的定位脚本 —— main 可见、对话区没有文字（只在空白新对话里暂存）、
  //      父级可见的 input[type=file] 恰好一个，才标记 data-arena-bound-upload 并返回 count=1。
  //      安卓没有 CDP DOM.setFileInputFiles，文件只能经 WebChromeClient.onShowFileChooser 交付，而 Blink 要求
  //      文件选择必须由用户激活触发，所以这里额外给出可触摸入口的视口坐标（CSS px），由原生侧派发真实触摸。
  function attachmentEntry() {
    var mainEl = mainElement();
    if (!mainEl) return { count: 0, reason: 'no main' };
    var logs = all(SELECTORS.log, mainEl).filter(shown);
    if (logs.some(function (l) { return norm(text(l)).length > 0; })) return { count: 0, reason: 'conversation' };
    var inputs = all('input[type="file"]', mainEl).filter(function (e) {
      return e.parentElement && e.parentElement.getClientRects().length > 0;
    });
    if (inputs.length !== 1) return { count: inputs.length, reason: inputs.length ? 'ambiguous' : 'no input' };
    var input = inputs[0];
    all('[data-arena-bound-upload]').forEach(function (e) { e.removeAttribute('data-arena-bound-upload'); });
    input.setAttribute('data-arena-bound-upload', 'true');
    var out = { count: 1, accept: input.accept || '', multiple: !!input.multiple, trigger: false };
    var trigger = attachmentTrigger(input, mainEl);
    if (!trigger) return out;
    trigger.scrollIntoView({ block: 'center', inline: 'center' });
    var r = trigger.getBoundingClientRect();
    var vv = window.visualViewport;
    out.trigger = true;
    out.label = label(trigger).slice(0, 80);
    out.x = r.left + r.width / 2;
    out.y = r.top + r.height / 2;
    out.width = r.width;
    out.height = r.height;
    out.offsetX = vv ? vv.offsetLeft : 0;
    out.offsetY = vv ? vv.offsetTop : 0;
    out.scale = vv && vv.scale ? vv.scale : 1;
    out.dpr = window.devicePixelRatio || 1;
    out.innerWidth = window.innerWidth;
    out.innerHeight = window.innerHeight;
    return out;
  }

  // ref: 桌面端 __arenaGenerationTracker —— 每次提交（点发送 / 回车 / 重新生成）与每次
  //      「开始生成」上升沿都让 revision 自增，同一提示词重发或 Regenerate 才能得到不同的 generationStamp。
  if (!window.__arenaGenerationTracker) {
    var nonce;
    try { nonce = crypto.randomUUID(); } catch (e) { nonce = Math.random().toString(36).slice(2) + Date.now().toString(36); }
    var tracker = window.__arenaGenerationTracker = { nonce: nonce, revision: 0, lastGenerating: false };
    document.addEventListener('click', function (e) {
      var b = e.target && e.target.closest ? e.target.closest('button') : null;
      if (b && /^(Send message|发送消息|Regenerate|Regenerate response|Retry response|Retry|重新生成|重试)$/i.test(label(b))) tracker.revision++;
    }, true);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.target && e.target.closest &&
        e.target.closest('main [contenteditable="true"], main textarea')) tracker.revision++;
    }, true);
  }

  function snapshot(prompt) {
    // 读取前后各取一次原生地址：不一致说明导航正在进行中，本次快照不可信。
    var before = location.href;

    var mainEl = mainElement();
    var log = all(SELECTORS.log, mainEl).filter(shown)[0] || null;
    var logText = norm(text(log));
    // 只取最外层消息包装；嵌套引用不算独立消息。
    var messages = all(SELECTORS.message, log).filter(shown).filter(function (m) {
      return !(m.parentElement && m.parentElement.closest(SELECTORS.message));
    });
    var users = messages.filter(isUser);
    var user = users.length ? users[users.length - 1] : null;
    var afterUser = user ? messages.slice(messages.indexOf(user) + 1) : [];
    var answer = null;
    for (var i = afterUser.length - 1; i >= 0; i--) {
      if (!isUser(afterUser[i])) { answer = afterUser[i]; break; }
    }

    var expected = norm(prompt);
    // 优先按角色标记判定；标记缺失时回退到「对话区文本以完整提示词开头」（桌面端旧 DOM 回退），
    // 两条路都不允许子串匹配。
    var promptConfirmed = !!expected && (user
      ? promptShown(user, expected)
      : (logText === expected || logText.indexOf(expected + ' ') === 0));

    var response = bodyText(answer);
    var scope = answer || log;
    var progressText = user
      ? afterUser.map(bodyText).join('\n')
      : bodyText(log);

    var generating = !!stopButton(mainEl);
    var activity = generating || (!!scope && all(SELECTORS.busy, scope).filter(shown).some(notInCode));
    var answerButtons = answer ? buttons(answer).filter(notInCode) : [];
    var completionConfirmed = !!answer && promptConfirmed && !activity && (
      /^(complete|completed|finished|done)$/.test(answer.getAttribute('data-state') || '') ||
      answerButtons.some(function (b) { return COPY_LABEL.test(label(b)); }));
    var failed = isFailed(scope);
    var thinking = !!scope && (
      buttons(scope).filter(notInCode).some(function (b) { return THINKING_LABEL.test(label(b)); }) ||
      all('[role="status"]', scope).filter(shown).some(function (s) { return THINKING_LABEL.test(norm(text(s))); }));

    // 生成中不给出 responseSignature：阶段机只在拿到非空签名且连续 10 秒不变时才算完成。
    var responseSignature = generating ? '' : digest(response);
    var t = window.__arenaGenerationTracker;
    if (generating && !t.lastGenerating) t.revision++;
    t.lastGenerating = generating;
    var generationStamp = t.nonce + ':' + t.revision + ':' + users.length + ':' + idOf(user) + ':' + idOf(answer) + ':' + responseSignature;

    var editorEl = editorOf(mainEl);
    var sendEl = sendButton(mainEl);
    var newLinks = newChatLinks().length;

    var after = location.href;

    return {
      url: after,
      browserSourceBefore: before,
      browserSourceAfter: after,
      snapshotConsistent: before === after,
      main: !!mainEl,
      conversation: logText.length > 0,
      promptConfirmed: promptConfirmed,
      thinking: thinking,
      generating: generating,
      activity: activity,
      failed: failed,
      response: response.length > 0 && !/^(finding|waiting|initializ|starting)/i.test(response),
      generationStamp: generationStamp,
      progressSignature: digest(progressText),
      responseSignature: responseSignature,
      completionConfirmed: completionConfirmed,
      messageIdentity: idOf(user),
      draft: draft(mainEl),
      editor: visible(editorEl),
      blocker: blockerOf(mainEl),
      termsPending: termsDialogs().length > 0,
      sendReady: !!sendEl && !sendEl.disabled && sendEl.getAttribute('aria-disabled') !== 'true',
      newLinks: newLinks,
      canExpand: !!sidebarOpener(),
      attachmentNames: stagedNames(mainEl),
      conversationAttachments: log ? all('img', log).filter(shown).map(function (e) { return e.alt; }).filter(Boolean) : [],
    };
  }

  // 第三十批真机结论：Arena 当前移动页上 HTMLElement.click() 不会真正提交，必须派发
  // pointer/mouse down → up → click 的完整事件序列。
  function click(el) {
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    var r = el.getBoundingClientRect();
    var x = r.left + r.width / 2;
    var y = r.top + r.height / 2;
    var base = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      button: 0,
    };
    function fire(Ctor, type, extra) {
      try { el.dispatchEvent(new Ctor(type, Object.assign({}, base, extra || {}))); } catch (e) {}
    }
    if (window.PointerEvent) {
      fire(PointerEvent, 'pointerover', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 1 });
      fire(PointerEvent, 'pointerenter', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 1 });
      fire(PointerEvent, 'pointerdown', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 1 });
    }
    fire(MouseEvent, 'mouseover', { buttons: 1 });
    fire(MouseEvent, 'mouseenter', { buttons: 1 });
    fire(MouseEvent, 'mousedown', { buttons: 1 });
    if (typeof el.focus === 'function') el.focus();
    if (window.PointerEvent) {
      fire(PointerEvent, 'pointerup', { pointerId: 1, pointerType: 'touch', isPrimary: true, buttons: 0 });
    }
    fire(MouseEvent, 'mouseup', { buttons: 0 });
    fire(MouseEvent, 'click', { buttons: 0 });
    return true;
  }

  function fill(value) {
    var e = editorOf(mainElement());
    if (!e) return false;
    e.focus();
    if (e.value === undefined) {
      // contenteditable：与桌面端 writeDraft 一样用 execCommand('insertText') 走编辑器的
      // 受控输入路径。直接改 textContent + 派发 input 事件，站点编辑器收不到，
      // 草稿读不回来 —— 发送按钮会一直不可用。
      var range = document.createRange();
      range.selectNodeContents(e);
      var selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      return document.execCommand('insertText', false, value);
    }
    var last = e.value;
    var proto = e instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    var desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) {
      desc.set.call(e, value);
    } else {
      e.value = value;
    }
    var tracker = e._valueTracker;
    if (tracker) tracker.setValue(last);
    e.dispatchEvent(new Event('input', { bubbles: true }));
    e.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  }

  function act(name, prompt) {
    switch (name) {
      case 'new': {
        // 参考实现要求入口唯一确认；不唯一就不点，交给阶段机按 newLinks 暂停并说明原因。
        var links = newChatLinks();
        if (links.length !== 1) return false;
        return click(links[0]);
      }
      case 'expand': return click(sidebarOpener());
      case 'fill':
      case 'retryFill': return fill(prompt);
      case 'send':
      case 'retrySend': return click(sendButton(mainElement()));
      case 'stop': return click(stopButton(mainElement()));
      case 'terms': return click(termsButton());
      default: return false;
    }
  }

  window.__ARENA_PAGE_BRIDGE__ = {
    version: 4,
    snapshot: snapshot,
    act: act,
    attachmentsReady: attachmentsReady,
    attachmentEntry: attachmentEntry,
    selectors: SELECTORS,
  };
})();
