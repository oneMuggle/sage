# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""观察层 v2：无障碍树快照 + 元素引用（ref）协议。

本模块只负责三件事，全部与 CDP 解耦（方便单测）：

1. ``build_snapshot_expression`` —— 构造注入页面的采集 JS；
2. ``parse_snapshot_payload`` —— 把页面返回值归一成工具 content dict；
3. ``build_ref_expression`` —— 把"按元素执行"的 JS 包装成 ref 解析 +
   失效校验 + 执行。

ref 协议（与 ``browser_tool`` 约定）：

- 每次快照在页面内重建注册表 ``window.__SAGE_REFS__ = {"e1": element, ...}``，
  同时记录 ``window.__SAGE_REF_NAMES__``（用于名称一致性校验）；
- 每个候选元素写属性 ``data-sage-ref`` 与 ``data-sage-ref-name``；
- 交互时 ref 未命中注册表 / 元素已脱离文档 / 名字与注册表不一致 → 视为
  失效，返回 ``{"ok": false, "info": "stale-ref"}``，由 Python 层转成
  可操作的错误文案；
- 序号每次快照从 ``e1`` 重新开始，因此旧 ref 不保证指向同一元素 ——
  ``data-sage-ref-name`` 校验正是兜底。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

#: interactive 模式默认返回的节点数
SNAPSHOT_INTERACTIVE_MAX_DEFAULT = 120

#: JS 侧最多收集的候选元素数（同时也是 max_nodes 的硬上限）
SNAPSHOT_HARD_COLLECT_CAP = 500

#: 页面文本快照上限（字符，超出截断）
SNAPSHOT_TEXT_CAP = 30 * 1024

#: 文本短于此且交互元素少于阈值 → 追加 Canvas 渲染提示
SNAPSHOT_CANVAS_TEXT_HINT = 200

#: 交互元素少于此数视为"疑似 Canvas 渲染"
CANVAS_ELEMENT_THRESHOLD = 3

#: ref 失效的机器可读标记（页面侧返回，Python 侧比对）
STALE_REF_INFO = "stale-ref"

#: ref 失效时给 LLM 的错误文案
STALE_REF_ERROR = "ref 已失效（页面已变化），请先调用 browser_snapshot 重新观察"

#: 非 JSON / 结构异常时的统一错误文案
INVALID_SNAPSHOT_ERROR = "页面快照返回异常（非 JSON）"

#: 页面候选元素选择器（去重前的原始集合）
CANDIDATE_SELECTOR = (
    "a[href], area[href], button, input, textarea, select, summary, label[for], "
    "[role=button], [role=link], [role=checkbox], [role=radio], [role=combobox], "
    "[role=tab], [role=menuitem], [role=option], [role=switch], "
    '[contenteditable=""], [contenteditable="true"]'
)

#: interactive / full 模式的注入 JS。占位符由 ``build_snapshot_expression``
#: 替换（不用 % / format，避免与 JS 花括号冲突）。
_INTERACTIVE_JS = r"""
(function(){
  var SELECTOR = __SELECTOR__;
  var MAX_COLLECT = __MAX_COLLECT__;
  var INCLUDE_OFFSCREEN = __INCLUDE_OFFSCREEN__;
  var TEXT_CAP = __TEXT_CAP__;
  var MODE = __MODE__;

  function textOf(node){
    if (!node) return '';
    return node.innerText || node.textContent || '';
  }

  function clean(value, cap){
    if (value === null || value === undefined) return '';
    return String(value).replace(/\s+/g, ' ').trim().slice(0, cap);
  }

  function nameOf(el){
    var ariaLabel = clean(el.getAttribute && el.getAttribute('aria-label'), 80);
    if (ariaLabel) return ariaLabel;

    var labelledBy = el.getAttribute && el.getAttribute('aria-labelledby');
    if (labelledBy) {
      var ids = String(labelledBy).split(/\s+/);
      var parts = [];
      for (var i = 0; i < ids.length; i++) {
        if (!ids[i]) continue;
        var labelled = document.getElementById(ids[i]);
        if (labelled) parts.push(textOf(labelled));
      }
      var fromIds = clean(parts.join(' '), 80);
      if (fromIds) return fromIds;
    }

    if (el.labels && el.labels.length) {
      var labelParts = [];
      for (var j = 0; j < el.labels.length; j++) labelParts.push(textOf(el.labels[j]));
      var fromLabels = clean(labelParts.join(' '), 80);
      if (fromLabels) return fromLabels;
    }

    var wrapping = el.closest ? el.closest('label') : null;
    if (wrapping) {
      var fromWrap = clean(textOf(wrapping), 80);
      if (fromWrap) return fromWrap;
    }

    var nameAttrs = ['alt', 'title', 'placeholder'];
    for (var k = 0; k < nameAttrs.length; k++) {
      var attr = clean(el.getAttribute && el.getAttribute(nameAttrs[k]), 80);
      if (attr) return attr;
    }

    var tag = (el.tagName || '').toLowerCase();
    var inputType = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
    if (tag === 'input' && (inputType === 'submit' || inputType === 'button' || inputType === 'reset')) {
      var buttonName = clean(el.value, 80);
      if (buttonName) return buttonName;
    }

    var inner = clean(el.innerText, 80);
    if (inner) return inner;
    return clean(el.value, 80);
  }

  function roleOf(el){
    var explicit = clean(el.getAttribute && el.getAttribute('role'), 40);
    if (explicit) return explicit.split(/\s+/)[0];

    var tag = (el.tagName || '').toLowerCase();
    var inputType = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();

    if (tag === 'a' || tag === 'area') {
      return el.getAttribute('href') !== null ? 'link' : 'generic';
    }
    if (tag === 'button' || tag === 'summary') return 'button';
    if (tag === 'input') {
      if (inputType === 'submit' || inputType === 'button' || inputType === 'reset') return 'button';
      if (inputType === 'checkbox') return 'checkbox';
      if (inputType === 'radio') return 'radio';
      if (inputType === 'text' || inputType === 'search' || inputType === 'email' ||
          inputType === 'tel' || inputType === 'url' || inputType === 'password' ||
          inputType === 'number') {
        return 'textbox';
      }
      return 'generic';
    }
    if (tag === 'textarea') return 'textbox';
    if (el.isContentEditable) return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag.length === 2 && tag.charAt(0) === 'h' && '123456'.indexOf(tag.charAt(1)) >= 0) {
      return 'heading';
    }
    if (tag === 'img' && el.getAttribute('alt') !== null) return 'img';
    return 'generic';
  }

  function inViewport(el){
    var rect = el.getBoundingClientRect();
    var width = window.innerWidth || document.documentElement.clientWidth || 0;
    var height = window.innerHeight || document.documentElement.clientHeight || 0;
    return rect.bottom > 0 && rect.right > 0 && rect.top < height && rect.left < width;
  }

  function fieldOf(el, candidate){
    var role = roleOf(el);
    var tag = (el.tagName || '').toLowerCase();
    var inputType = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
    var item = {
      ref: candidate.ref,
      role: role,
      name: nameOf(el),
      disabled: el.disabled === true,
      in_viewport: candidate.in_viewport
    };
    if (role === 'textbox' || role === 'combobox') {
      var kind = inputType;
      if (!kind) {
        if (tag === 'textarea') kind = 'textarea';
        else if (tag === 'select') kind = 'select';
        else if (el.isContentEditable) kind = 'contenteditable';
        else kind = tag;
      }
      item.type = kind;
      item.value = inputType === 'password' ? '' : clean(el.value, 500);
      item.placeholder = clean(el.getAttribute && el.getAttribute('placeholder'), 120);
    }
    if (role === 'checkbox' || role === 'radio') item.checked = el.checked === true;
    if (role === 'link') {
      item.href = clean(el.getAttribute && el.getAttribute('href'), 200);
    }
    return item;
  }

  var raw = document.querySelectorAll(SELECTOR);
  var unique = [];
  for (var i = 0; i < raw.length; i++) {
    if (unique.indexOf(raw[i]) === -1) unique.push(raw[i]);
  }

  var candidates = [];
  for (var j = 0; j < unique.length; j++) {
    var el = unique[j];
    if (!el.getClientRects || el.getClientRects().length === 0) continue;
    if (el.closest && el.closest('[hidden],[aria-hidden="true"]')) continue;
    candidates.push({el: el, in_viewport: inViewport(el)});
  }

  if (!INCLUDE_OFFSCREEN) {
    var visible = [];
    var offscreen = [];
    for (var m = 0; m < candidates.length; m++) {
      if (candidates[m].in_viewport) visible.push(candidates[m]);
      else offscreen.push(candidates[m]);
    }
    candidates = visible.concat(offscreen);
  }
  if (candidates.length > MAX_COLLECT) candidates = candidates.slice(0, MAX_COLLECT);

  var registry = {};
  var names = {};
  var elements = [];
  for (var n = 0; n < candidates.length; n++) {
    var candidate = candidates[n];
    candidate.ref = 'e' + (n + 1);
    var accessibleName = nameOf(candidate.el);
    try {
      candidate.el.setAttribute('data-sage-ref', candidate.ref);
      candidate.el.setAttribute('data-sage-ref-name', accessibleName);
    } catch (err) {}
    registry[candidate.ref] = candidate.el;
    names[candidate.ref] = accessibleName;
    elements.push(fieldOf(candidate.el, candidate));
  }
  window.__SAGE_REFS__ = registry;
  window.__SAGE_REF_NAMES__ = names;

  return JSON.stringify({
    url: location.href,
    title: document.title,
    viewport: {
      width: window.innerWidth || 0,
      height: window.innerHeight || 0,
      scroll_y: window.scrollY || 0
    },
    elements: elements,
    elements_total: elements.length,
    mode: MODE,
    text: (document.body && document.body.innerText || '').slice(0, TEXT_CAP)
  });
})()
"""

#: text 模式：纯文本快照，不含任何 ref 注册逻辑（保持旧形状）。
_TEXT_JS = r"""
(function(){
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text: (document.body && document.body.innerText || '').slice(0, __TEXT_CAP__)
  });
})()
"""


def _normalize_mode(mode: str) -> str:
    return mode if mode in ("interactive", "text", "full") else "interactive"


def _clamp_max_nodes(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return SNAPSHOT_INTERACTIVE_MAX_DEFAULT
    return max(1, min(number, SNAPSHOT_HARD_COLLECT_CAP))


def build_snapshot_expression(
    mode: str = "interactive",
    max_collect: int = SNAPSHOT_HARD_COLLECT_CAP,
    include_offscreen: bool = False,
) -> str:
    """构造快照注入 JS。

    ``mode=text`` 只取正文，不注入 ref 注册表；``interactive`` / ``full``
    共享同一套采集逻辑（``full`` 的差异在 ``parse_snapshot_payload``）。
    """
    normalized = _normalize_mode(mode)
    if normalized == "text":
        return _TEXT_JS.replace("__TEXT_CAP__", str(int(SNAPSHOT_TEXT_CAP)))

    try:
        collect_cap = max(0, int(max_collect))
    except (TypeError, ValueError):
        collect_cap = SNAPSHOT_HARD_COLLECT_CAP
    return (
        _INTERACTIVE_JS.replace("__SELECTOR__", json.dumps(CANDIDATE_SELECTOR))
        .replace("__MAX_COLLECT__", str(collect_cap))
        .replace("__INCLUDE_OFFSCREEN__", "true" if include_offscreen else "false")
        .replace("__TEXT_CAP__", str(int(SNAPSHOT_TEXT_CAP)))
        .replace("__MODE__", json.dumps(normalized))
    )


def _coerce_payload(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_snapshot_payload(
    payload: Any,
    mode: str = "interactive",
    max_nodes: int = SNAPSHOT_INTERACTIVE_MAX_DEFAULT,
    query: str = "",
    include_offscreen: bool = False,
) -> Dict[str, Any]:
    """把页面返回值归一成工具 content；结构异常返回 ``{"error": ...}``。

    ``include_offscreen`` 由 JS 采集阶段生效（是否把视口外元素纳入候选），
    解析阶段无需再次决策，保留参数是为了接口自洽。
    """
    normalized = _normalize_mode(mode)
    data = _coerce_payload(payload)
    if data is None:
        return {"error": INVALID_SNAPSHOT_ERROR}

    url = _as_text(data.get("url"))
    title = _as_text(data.get("title"))
    text = _as_text(data.get("text"))

    if normalized == "text":
        return {
            "url": url,
            "title": title,
            "text": text,
            "truncated": len(text) >= SNAPSHOT_TEXT_CAP,
        }

    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list):
        return {"error": INVALID_SNAPSHOT_ERROR}
    elements = [
        item
        for item in raw_elements
        if isinstance(item, dict) and isinstance(item.get("ref"), str)
    ]

    needle = (query or "").strip().lower()
    if needle:
        elements = [
            item
            for item in elements
            if needle in _as_text(item.get("role")).lower()
            or needle in _as_text(item.get("name")).lower()
        ]

    total = len(elements)
    limit = _clamp_max_nodes(max_nodes)
    truncated = total > limit
    viewport = data.get("viewport")
    result: Dict[str, Any] = {
        "url": url,
        "title": title,
        "viewport": viewport if isinstance(viewport, dict) else {},
        "elements": elements[:limit],
        "elements_total": total,
        "truncated": truncated,
        "mode": normalized,
    }

    hints = []
    if truncated:
        hints.append(
            f"共 {total} 个交互元素，已返回前 {limit} 个；可用 query 过滤或滚动后重新快照"
        )
    if total < CANVAS_ELEMENT_THRESHOLD and len(text) < SNAPSHOT_CANVAS_TEXT_HINT:
        hints.append("页面可能由 Canvas 渲染，建议 browser_screenshot(return_image=true)")
    if hints:
        result["hint"] = "；".join(hints)

    if normalized == "full":
        result["text"] = text
        result["truncated_text"] = len(text) >= SNAPSHOT_TEXT_CAP
    return result


def build_ref_expression(action_js: str, ref: str) -> str:
    """把按元素执行的 JS 包装成 ref 解析 + 失效校验 + 执行。

    ``action_js`` 必须是一个以 ``el`` 为元素变量的 IIFE 表达式，且返回
    ``{"ok": bool, "info": str}``。
    """
    return (
        "(function(){"
        f"var __sageRef={json.dumps(str(ref))};"
        "var __sageRegs=window.__SAGE_REFS__||{};"
        "var __sageNames=window.__SAGE_REF_NAMES__||{};"
        "var el=__sageRegs[__sageRef];"
        "if(!el){return{ok:false,info:'stale-ref'};}"
        "if(el.isConnected!==true){return{ok:false,info:'stale-ref'};}"
        "var __sageName=__sageNames[__sageRef];"
        "if(el.getAttribute('data-sage-ref-name')!==__sageName)"
        "{return{ok:false,info:'stale-ref'};}"
        f"return {action_js};"
        "})()"
    )


def parse_key_combo(key: str) -> Tuple[Dict[str, bool], str]:
    """把 ``"Control+Shift+A"`` 拆成 (modifier 标志, 主键)。"""
    modifiers = {"ctrlKey": False, "shiftKey": False, "altKey": False, "metaKey": False}
    aliases = {
        "control": "ctrlKey",
        "ctrl": "ctrlKey",
        "shift": "shiftKey",
        "alt": "altKey",
        "option": "altKey",
        "meta": "metaKey",
        "cmd": "metaKey",
        "command": "metaKey",
        "win": "metaKey",
        "super": "metaKey",
    }
    main = ""
    for part in str(key or "").split("+"):
        token = part.strip()
        if not token:
            continue
        flag = aliases.get(token.lower())
        if flag:
            modifiers[flag] = True
        else:
            main = token
    return modifiers, main
