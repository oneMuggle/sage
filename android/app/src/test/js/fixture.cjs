// 离线 jsdom 夹具：给 android/app/src/main/assets 下的页面桥脚本一个最小可用的浏览器环境。
// ref: reference/Arena模型助手-源码-fyb-0.1.0/tests/rename-bridge.test.cjs（fixture() 的写法）
// jsdom 没有布局引擎：getBoundingClientRect / getClientRects / innerText / scrollIntoView /
// PointerEvent 都要补齐，规则是「自身或祖先 hidden / display:none 即不可见」。
'use strict';
const fs = require('node:fs');
const path = require('node:path');

function loadJsdom() {
  try { return require('jsdom'); } catch (e) { /* fall through */ }
  // 未在本目录 npm install 时，复用桌面端离线测试已安装的 jsdom 26.1.0。
  const fallback = path.join(__dirname, '..', '..', '..', '..', '..',
    'reference', 'Arena模型助手-源码-fyb-0.1.0', 'tests', 'node_modules', 'jsdom');
  try { return require(fallback); } catch (e) { /* fall through */ }
  throw new Error('jsdom 不可用：请在 android/app/src/test/js 执行 npm install（devDependencies: jsdom 26.1.0）');
}

const { JSDOM } = loadJsdom();
const ASSETS = path.join(__dirname, '..', '..', 'main', 'assets');

function source(name) {
  return fs.readFileSync(path.join(ASSETS, name), 'utf8');
}

function hiddenBy(el) {
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    if (n.hidden) return true;
    if (/display\s*:\s*none/i.test(n.getAttribute('style') || '')) return true;
  }
  return false;
}

/**
 * @param {string} html  body 内容
 * @param {{url?: string, scripts?: string[], width?: number, height?: number}} [options]
 */
function page(html, options = {}) {
  const url = options.url || 'https://arena.ai/agent';
  const scripts = options.scripts || ['PageBridge.js'];
  const dom = new JSDOM(html, { url, runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  // 手机竖屏视口（Magic5 Pro 逻辑像素），navVisible() 要用到 innerWidth / innerHeight。
  Object.defineProperty(w, 'innerWidth', { value: options.width || 412, configurable: true });
  Object.defineProperty(w, 'innerHeight', { value: options.height || 915, configurable: true });
  w.Element.prototype.getClientRects = function () { return hiddenBy(this) ? [] : [{}]; };
  w.Element.prototype.getBoundingClientRect = function () {
    if (hiddenBy(this)) return { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
    return { x: 10, y: 10, top: 10, left: 10, right: 110, bottom: 30, width: 100, height: 20 };
  };
  w.Element.prototype.scrollIntoView = function () {};
  if (!w.PointerEvent) {
    w.PointerEvent = class PointerEvent extends w.MouseEvent {
      constructor(type, init = {}) {
        super(type, init);
        this.pointerId = init.pointerId;
        this.pointerType = init.pointerType;
        this.isPrimary = init.isPrimary;
      }
    };
  }
  if (!('innerText' in w.HTMLElement.prototype)) {
    Object.defineProperty(w.HTMLElement.prototype, 'innerText', {
      get() { return this.textContent; },
      set(v) { this.textContent = v; },
      configurable: true,
    });
  }
  if (typeof w.document.execCommand !== 'function') {
    w.document.execCommand = () => false;
  }
  for (const s of scripts) w.eval(source(s));
  return w;
}

/** 统计某元素收到的事件次数，用来断言点击序列真的派发到了目标。 */
function counter(el, types) {
  const counts = {};
  for (const t of types) {
    counts[t] = 0;
    el.addEventListener(t, () => { counts[t]++; });
  }
  return counts;
}

function runner(suiteName) {
  let passed = 0;
  const failures = [];
  function check(name, fn) {
    try {
      fn();
      passed++;
      console.log('PASS ' + name);
    } catch (e) {
      failures.push(name);
      console.log('FAIL ' + name + '\n  ' + String(e && e.stack || e).split('\n').slice(0, 6).join('\n  '));
    }
  }
  function done() {
    if (failures.length) {
      console.log(`${suiteName}: ${failures.length} failed, ${passed} passed`);
      process.exitCode = 1;
    } else {
      console.log(`${suiteName} passed: ${passed} checks`);
    }
  }
  return { check, done };
}

module.exports = { JSDOM, page, counter, runner, source };
