/* Sage 会话导出渲染器 (U18)
 *
 * 从 <script id="session-data"> 读取 Base64 JSON 载荷,客户端渲染:
 * - 消息历史 (user/assistant/system,Markdown via marked)
 * - 工具调用 (按工具名定制布局:bash/read/write/edit/默认)
 * - edit 工具 old_string/new_string 行级 LCS diff
 * - 思考过程 (reasoning_content,折叠块)
 * - 代码高亮 (highlight.js)
 * - 深色/浅色/跟随系统三态主题切换 (localStorage 持久化)
 *
 * 约束:CSP script-src 仅允许 sha256 白名单脚本 —— 全文件禁止
 * 内联事件属性 (onclick 等),一律 addEventListener;正则中的闭合
 * script 标签一律写成转义形式 (<\/script>)。ES5 语法,兼容旧内核。
 */
(function () {
  'use strict';

  // ---------- 载荷解码 ----------

  function loadSessionData() {
    var el = document.getElementById('session-data');
    var b64 = ((el && el.textContent) || '').replace(/\s/g, '');
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) {
      bytes[i] = bin.charCodeAt(i);
    }
    return JSON.parse(new TextDecoder('utf-8').decode(bytes));
  }

  var data = loadSessionData();
  var entries = Array.isArray(data.entries) ? data.entries : [];

  // ---------- 工具函数 ----------

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtDateTime(ms) {
    if (!ms) {
      return '';
    }
    try {
      return new Date(ms).toLocaleString();
    } catch (e) {
      return '';
    }
  }

  function fmtClock(ms) {
    if (!ms) {
      return '';
    }
    try {
      return new Date(ms).toLocaleTimeString();
    } catch (e) {
      return '';
    }
  }

  function formatTokens(n) {
    if (!n) {
      return '0';
    }
    if (n >= 1000000) {
      return (n / 1000000).toFixed(1).replace(/\.0$/, '') + 'M';
    }
    if (n >= 1000) {
      return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k';
    }
    return String(n);
  }

  // ---------- Markdown ----------

  // hljs 高亮的代码块渲染;兼容 marked v4 (code(code, lang)) 与
  // v5+ (code({text, lang})) 两种 renderer 签名。
  var HIGHLIGHT_LIMIT = 50000; // 超长代码块跳过高亮,避免导出卡顿

  function highlightCode(text, lang) {
    if (!text) {
      return '';
    }
    if (text.length > HIGHLIGHT_LIMIT) {
      return esc(text);
    }
    try {
      if (lang && window.hljs && hljs.getLanguage(lang)) {
        return hljs.highlight(text, { language: lang }).value;
      }
      if (window.hljs) {
        return hljs.highlightAuto(text).value;
      }
    } catch (e) {
      // 高亮失败降级为纯文本
    }
    return esc(text);
  }

  function codeRenderer(token) {
    var text;
    var lang;
    if (typeof token === 'string') {
      text = token;
      lang = arguments[1] || '';
    } else {
      text = (token && token.text) || '';
      lang = (token && token.lang) || '';
    }
    lang = String(lang || '').split(/\s+/)[0];
    return '<pre><code class="hljs">' + highlightCode(text, lang) + '</code></pre>';
  }

  if (window.marked) {
    try {
      marked.use({ gfm: true, breaks: true, renderer: { code: codeRenderer } });
    } catch (e) {
      // marked 配置失败时用默认配置
    }
  }

  // 深度防御:CSP script-src 哈希白名单已阻断脚本执行,这里再剥一层
  // 危险结构,防止 markdown 原文里的原始 HTML 产生视觉欺骗/旧内核绕过。
  // 标签集含 meta/link/base(阻断 <meta http-equiv=refresh> 自动跳转钓鱼)、
  // style(阻断 CSS 注入)及媒体标签;on* 前缀放宽到 [\s/] 以捕获 <svg/onload=>。
  function sanitizeHtml(htmlText) {
    return String(htmlText || '')
      .replace(/<script\b[\s\S]*?<\/script\s*>/gi, '')
      .replace(
        /<\s*\/?\s*(script|iframe|object|embed|form|meta|link|base|style|audio|video|source)\b/gi,
        '&lt;$1'
      )
      .replace(/[\s/]+on\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, ' ')
      .replace(/javascript\s*:/gi, '');
  }

  function renderMarkdown(text) {
    if (!text) {
      return '';
    }
    if (!window.marked) {
      return '<pre>' + esc(text) + '</pre>';
    }
    var htmlText;
    try {
      htmlText = marked.parse(text, { async: false });
    } catch (e) {
      return '<pre>' + esc(text) + '</pre>';
    }
    return sanitizeHtml(htmlText);
  }

  // ---------- 工具调用 ----------

  // role=tool 的消息按 tool_call_id 索引,渲染时挂回对应调用下方。
  // 用 null 原型避免攻击者可控的 tool_call_id (__proto__/constructor) 命中原型链。
  var toolResultByCallId = Object.create(null);
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i];
    if (entry.role === 'tool' && entry.tool_call_id) {
      toolResultByCallId[entry.tool_call_id] = entry;
    }
  }

  function toolArgs(tc) {
    if (tc && tc.args && typeof tc.args === 'object') {
      return tc.args;
    }
    if (tc && tc.arguments && typeof tc.arguments === 'object') {
      return tc.arguments;
    }
    return {};
  }

  function pickArg(args, names) {
    for (var i = 0; i < names.length; i++) {
      var value = args[names[i]];
      if (typeof value === 'string' && value.length) {
        return value;
      }
    }
    return '';
  }

  function renderOutput(text) {
    if (!text) {
      return '';
    }
    var lineCount = String(text).split('\n').length;
    return (
      '<span class="tool-output-label">输出 (' +
      lineCount +
      ' 行)</span><pre class="tool-output">' +
      esc(text) +
      '</pre>'
    );
  }

  function renderCodeFile(text) {
    if (!text) {
      return '';
    }
    return '<pre class="tool-output"><code class="hljs">' + highlightCode(text, '') + '</code></pre>';
  }

  // 行级 LCS diff:edit 类工具的 old_string → new_string 可视化
  function diffLines(oldText, newText) {
    var a = String(oldText == null ? '' : oldText).split('\n');
    var b = String(newText == null ? '' : newText).split('\n');
    var n = a.length;
    var m = b.length;

    // 超大 diff 降级:整体 -/+ 展示,避免 O(n*m) DP 卡死
    if (n * m > 250000) {
      var coarse = [];
      for (var ci = 0; ci < n; ci++) {
        coarse.push({ type: 'remove', text: a[ci] });
      }
      for (var cj = 0; cj < m; cj++) {
        coarse.push({ type: 'add', text: b[cj] });
      }
      return coarse;
    }

    var dp = [];
    var r;
    var c;
    for (r = 0; r <= n; r++) {
      dp.push(new Uint32Array(m + 1));
    }
    for (r = n - 1; r >= 0; r--) {
      for (c = m - 1; c >= 0; c--) {
        dp[r][c] = a[r] === b[c] ? dp[r + 1][c + 1] + 1 : Math.max(dp[r + 1][c], dp[r][c + 1]);
      }
    }

    var ops = [];
    r = 0;
    c = 0;
    while (r < n && c < m) {
      if (a[r] === b[c]) {
        ops.push({ type: 'context', text: a[r] });
        r++;
        c++;
      } else if (dp[r + 1][c] >= dp[r][c + 1]) {
        ops.push({ type: 'remove', text: a[r] });
        r++;
      } else {
        ops.push({ type: 'add', text: b[c] });
        c++;
      }
    }
    while (r < n) {
      ops.push({ type: 'remove', text: a[r++] });
    }
    while (c < m) {
      ops.push({ type: 'add', text: b[c++] });
    }
    return ops;
  }

  function renderDiff(oldText, newText) {
    var ops = diffLines(oldText, newText);
    var lines = [];
    for (var i = 0; i < ops.length; i++) {
      var op = ops[i];
      var sign = op.type === 'add' ? '+' : op.type === 'remove' ? '-' : ' ';
      lines.push(
        '<div class="diff-line diff-' +
          op.type +
          '"><span class="diff-sign">' +
          sign +
          '</span>' +
          esc(op.text) +
          '</div>'
      );
    }
    return '<div class="tool-diff">' + lines.join('') + '</div>';
  }

  var BASH_NAMES = ['bash', 'shell', 'run_command', 'execute_command', 'execute', 'terminal'];
  var READ_NAMES = ['read', 'read_file', 'view'];
  var WRITE_NAMES = ['write', 'write_file', 'create_file'];
  var EDIT_NAMES = ['edit', 'edit_file', 'str_replace', 'str_replace_editor', 'patch', 'apply_patch'];

  function nameIn(name, list) {
    var lower = String(name || '').toLowerCase();
    for (var i = 0; i < list.length; i++) {
      if (lower === list[i]) {
        return true;
      }
    }
    return false;
  }

  function pathLabel(args) {
    var path = pickArg(args, ['path', 'file_path', 'filename', 'file', 'filepath']);
    return path ? ' <span class="tool-path">' + esc(path) + '</span>' : '';
  }

  function renderToolCall(tc) {
    var name = (tc && tc.name) || 'tool';
    var args = toolArgs(tc);
    var result = tc && tc.id ? toolResultByCallId[tc.id] : null;
    var resultText = result ? result.content || '' : '';
    var body = '';

    if (nameIn(name, BASH_NAMES)) {
      var cmd = pickArg(args, ['command', 'cmd', 'script']);
      body =
        '<div class="tool-command"><span class="prompt">$</span>' +
        esc(cmd || JSON.stringify(args)) +
        '</div>' +
        renderOutput(resultText);
    } else if (nameIn(name, READ_NAMES)) {
      body = renderCodeFile(resultText) || renderOutput(resultText);
    } else if (nameIn(name, WRITE_NAMES)) {
      var content = pickArg(args, ['content', 'new_content', 'file_text', 'text']);
      body = renderCodeFile(content) || renderOutput(resultText);
    } else if (nameIn(name, EDIT_NAMES)) {
      var oldStr = pickArg(args, ['old_string', 'old_str', 'old_text', 'search', 'oldText']);
      var newStr = pickArg(args, ['new_string', 'new_str', 'new_text', 'replace', 'newText']);
      if (oldStr || newStr) {
        body = renderDiff(oldStr, newStr) + renderOutput(resultText);
      } else {
        body =
          '<pre class="tool-args">' + esc(JSON.stringify(args, null, 2)) + '</pre>' +
          renderOutput(resultText);
      }
    } else {
      body =
        '<pre class="tool-args">' + esc(JSON.stringify(args, null, 2)) + '</pre>' +
        renderOutput(resultText);
    }

    return (
      '<details class="tool-execution"><summary><span class="tool-name">' +
      esc(name) +
      '</span>' +
      pathLabel(args) +
      '</summary><div class="tool-body">' +
      body +
      '</div></details>'
    );
  }

  // ---------- 消息渲染 ----------

  function renderEntry(entry) {
    if (!entry || entry.role === 'tool') {
      return ''; // tool 结果已内联到对应调用下方
    }
    var time = '<span class="message-time">' + esc(fmtClock(entry.created_at)) + '</span>';
    var anchor = entry.id ? ' id="msg-' + esc(entry.id) + '"' : '';

    if (entry.role === 'user') {
      return (
        '<div class="message user-message"' + anchor + '>' +
        '<div class="message-meta"><span class="role-badge user-badge">用户</span>' + time + '</div>' +
        '<div class="markdown-content">' + renderMarkdown(entry.content) + '</div>' +
        '</div>'
      );
    }

    if (entry.role === 'assistant') {
      var parts = [];
      parts.push('<div class="message assistant-message"' + anchor + '>');
      parts.push(
        '<div class="message-meta"><span class="role-badge assistant-badge">助手</span>' +
          (entry.model ? '<span class="model-name">' + esc(entry.model) + '</span>' : '') +
          time +
          '</div>'
      );
      if (entry.reasoning_content) {
        parts.push(
          '<details class="thinking-block"><summary>💭 思考过程</summary>' +
            '<div class="thinking-text">' + renderMarkdown(entry.reasoning_content) + '</div></details>'
        );
      }
      if (entry.content) {
        parts.push('<div class="markdown-content">' + renderMarkdown(entry.content) + '</div>');
      }
      var calls = Array.isArray(entry.tool_calls) ? entry.tool_calls : [];
      for (var i = 0; i < calls.length; i++) {
        parts.push(renderToolCall(calls[i]));
      }
      parts.push('</div>');
      return parts.join('');
    }

    if (entry.role === 'system') {
      return (
        '<details class="system-message"><summary>' +
        '<span class="role-badge system-badge">系统</span> 系统提示</summary>' +
        '<div class="markdown-content">' + renderMarkdown(entry.content) + '</div></details>'
      );
    }

    return (
      '<div class="message"' + anchor + '>' +
      '<div class="message-meta"><span class="role-badge">' + esc(entry.role || '?') + '</span>' + time + '</div>' +
      '<div class="markdown-content">' + renderMarkdown(entry.content) + '</div>' +
      '</div>'
    );
  }

  function renderMessages() {
    var container = document.getElementById('messages');
    if (!entries.length) {
      container.innerHTML = '<div class="empty-note">此会话暂无消息</div>';
      return;
    }
    var chunks = [];
    for (var i = 0; i < entries.length; i++) {
      var html = renderEntry(entries[i]);
      if (html) {
        chunks.push(html);
      }
    }
    container.innerHTML = chunks.join('');
  }

  // ---------- 头部 ----------

  function infoItem(label, value) {
    if (!value) {
      return '';
    }
    return '<span class="info-item">' + esc(label) + ' <strong>' + esc(value) + '</strong></span>';
  }

  function renderHeader() {
    var header = data.header || {};
    var stats = data.stats || {};
    document.getElementById('session-title').textContent = header.title || '(未命名会话)';

    var items = [];
    items.push(infoItem('创建时间', fmtDateTime(header.created_at)));
    items.push(infoItem('消息数', String(entries.length)));
    if (stats.user_messages != null) {
      items.push(infoItem('用户', String(stats.user_messages)));
    }
    if (stats.assistant_messages != null) {
      items.push(infoItem('助手', String(stats.assistant_messages)));
    }
    if (stats.tool_calls) {
      items.push(infoItem('工具调用', String(stats.tool_calls)));
    }
    if (stats.thinking_blocks) {
      items.push(infoItem('思考', String(stats.thinking_blocks)));
    }
    if (Array.isArray(stats.models) && stats.models.length) {
      items.push(infoItem('模型', stats.models.join(' / ')));
    }
    if (header.total_tokens) {
      items.push(infoItem('Tokens', formatTokens(header.total_tokens)));
    }
    items.push(infoItem('导出于', fmtDateTime(data.exported_at)));
    document.getElementById('session-info').innerHTML = items.join('');
  }

  // ---------- 主题切换 ----------

  var THEME_LABELS = { auto: '主题:跟随系统', dark: '主题:深色', light: '主题:浅色' };
  var THEME_CYCLE = { auto: 'light', light: 'dark', dark: 'auto' };
  var THEME_KEY = 'sage-export-theme';

  function currentTheme() {
    var attr = document.documentElement.getAttribute('data-theme');
    return attr === 'dark' || attr === 'light' ? attr : 'auto';
  }

  function applyThemeButton() {
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.textContent = THEME_LABELS[currentTheme()];
    }
  }

  function initTheme() {
    var stored = null;
    try {
      stored = localStorage.getItem(THEME_KEY);
    } catch (e) {
      // file:// 下 localStorage 可能不可用,忽略
    }
    if (stored === 'dark' || stored === 'light' || stored === 'auto') {
      document.documentElement.setAttribute('data-theme', stored);
    }
    var btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', function () {
        var next = THEME_CYCLE[currentTheme()] || 'auto';
        document.documentElement.setAttribute('data-theme', next);
        try {
          localStorage.setItem(THEME_KEY, next);
        } catch (e) {
          // 忽略持久化失败
        }
        applyThemeButton();
      });
    }
    applyThemeButton();
  }

  // ---------- 启动 ----------

  renderHeader();
  renderMessages();
  initTheme();
})();
