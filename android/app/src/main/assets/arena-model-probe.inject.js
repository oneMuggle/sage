// ref: backend/services/model_probe_py/classify.py + arena-model-probe/src/classify.js (algorithm)
// spec: docs/mcp-android-implementation-plan.md \u00a73.9 / \u00a74 (document-start \u63a5\u7ba1 fetch/XHR)
// \u5b89\u5353\u7aef\u63a2\u9488 - document-start \u6ce8\u5165\uff0c\u5fc5\u987b\u5728\u9875\u9762\u811a\u672c\u4e4b\u524d\u6267\u884c\u3002
// \u6838\u5fc3\u8bed\u4e49\uff1a\u62e6\u622a arena.ai \u7684 fetch/XHR\uff0c\u6355\u83b7\u6a21\u578b\u8bc1\u636e\u5e76\u66b4\u9732 __MODEL_PROBE__.runState()
// \u6ce8\uff1a\u672c\u6587\u4ef6\u4e3a\u72ec\u7acb\u8bbe\u8ba1\uff0c\u53ea\u63cf\u8ff0\u884c\u4e3a\u9700\u6c42\u4e0e\u7b97\u6cd5\u903b\u8f91\uff0c\u4e0d\u590d\u5236\u6e90\u7801\u3002
(function () {
  'use strict';
  if (typeof location === 'undefined' || location.hostname !== 'arena.ai') return;
  if (window.__MODEL_PROBE__ && window.__MODEL_PROBE__.installed) return;

  var OPTIONS = window.__MODEL_PROBE_OPTIONS__ || {};
  var showHUD = OPTIONS.showHUD === true;

  var lastRunId = '';
  var lastName = '';
  var lastApi = false;
  var lastError = '';
  var evidence = [];
  var history = [];
  var modelHistoryMap = {};

  function normalizeName(raw) {
    if (!raw) return '';
    return String(raw).trim();
  }

  function pushHistory(runId, name) {
    if (!runId || !name) return;
    history.unshift({ runId: runId, name: name, ts: Date.now() });
    if (history.length > 50) history.pop();
    modelHistoryMap[runId] = name;
    lastRunId = runId;
    lastName = normalizeName(name);
    lastApi = true;
  }

  function classifyFromUrl(url) {
    try {
      var u = String(url || '');
      if (u.indexOf('/nextjs-api/') >= 0 || u.indexOf('/api/') >= 0) lastApi = true;
    } catch (_e) {}
  }

  function extractModelFromJson(text) {
    if (!text) return null;
    var m = text.match(/\"model\"\s*:\s*\"([^\"]+)\"/);
    if (m) return m[1];
    m = text.match(/\"modelName\"\s*:\s*\"([^\"]+)\"/);
    if (m) return m[1];
    m = text.match(/\"name\"\s*:\s*\"([^\"]+)\"/);
    if (m && text.indexOf('model') >= 0) return m[1];
    return null;
  }

  function handleResponse(url, status, headers, bodyText) {
    try {
      classifyFromUrl(url);
      var ctype = '';
      if (headers) {
        if (typeof headers.get === 'function') ctype = headers.get('content-type') || '';
        else if (headers['content-type']) ctype = headers['content-type'];
      }
      var model = extractModelFromJson(bodyText);
      if (model) {
        var runId = '';
        var rm = bodyText.match(/\"runId\"\s*:\s*\"([^\"]+)\"/);
        if (rm) runId = rm[1];
        var um = bodyText.match(/\"id\"\s*:\s*\"([^\"]+)\"/);
        if (!runId && um) runId = um[1];
        if (!runId) runId = 'run-' + Date.now();
        pushHistory(runId, model);
        evidence.push({ url: url, model: model, runId: runId, ctype: ctype, ts: Date.now() });
        if (evidence.length > 100) evidence.shift();
      }
    } catch (e) {
      lastError = e.message || String(e);
    }
  }

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      return origFetch.apply(this, arguments).then(function (resp) {
        try {
          var clone = resp.clone();
          clone.text().then(function (t) { handleResponse(url, resp.status, resp.headers, t); }).catch(function () {});
        } catch (_e) {}
        return resp;
      });
    };
  }

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this._probeUrl = url;
    this._probeMethod = method;
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    var xhr = this;
    var url = xhr._probeUrl || '';
    function onLoad() {
      try {
        var t = xhr.responseText || '';
        handleResponse(url, xhr.status, xhr.getAllResponseHeaders(), t);
      } catch (_e) {}
    }
    xhr.addEventListener('load', onLoad);
    return origSend.apply(this, arguments);
  };

  var OrigEventSource = window.EventSource;
  if (OrigEventSource) {
    window.EventSource = function (url, opts) {
      var es = new OrigEventSource(url, opts);
      es.addEventListener('message', function (ev) {
        var model = extractModelFromJson(ev.data);
        if (model) pushHistory('sse-' + Date.now(), model);
      });
      return es;
    };
    window.EventSource.prototype = OrigEventSource.prototype;
  }

  window.__MODEL_PROBE__ = {
    installed: true,
    placeholder: false,
    evidence: evidence,
    history: history,
    runState: function () {
      if (lastError) return { api: lastApi, runId: lastRunId, name: lastName, lastError: lastError };
      return { api: lastApi, runId: lastRunId, name: lastName, lastError: '' };
    },
    modelHistory: function (runId) {
      if (runId && modelHistoryMap[runId]) return modelHistoryMap[runId];
      return lastName || '';
    },
    clear: function () { evidence = []; history = []; modelHistoryMap = {}; lastRunId=''; lastName=''; lastApi=false; lastError=''; }
  };

  if (!showHUD) {
    var style = document.createElement('style');
    style.textContent = '#model-probe-hud{display:none!important}';
    (document.head || document.documentElement).appendChild(style);
  }
})();
