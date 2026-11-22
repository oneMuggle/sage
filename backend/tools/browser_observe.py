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
from typing import Any, Dict, List, Optional, Tuple

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

#: 每个子 iframe 最多采集的候选元素数（防止 iframe 数量爆炸时拖慢快照）。
#: 老版知网支持 50 条/页，每行多个链接时 60 会截断翻页/条目。
IFRAME_MAX_COLLECT_PER_FRAME = 150

#: 最多处理的子 iframe 数（超出部分标注 truncated_iframes）
IFRAME_MAX_FRAMES = 10

#: 页面候选元素选择器（去重前的原始集合）
CANDIDATE_SELECTOR = (
    "a[href], area[href], button, input, textarea, select, summary, label[for], "
    "[role=button], [role=link], [role=checkbox], [role=radio], [role=combobox], "
    "[role=tab], [role=menuitem], [role=option], [role=switch], "
    '[contenteditable=""], [contenteditable="true"]'
)

#: interactive / full 模式的注入 JS。占位符由 ``build_snapshot_expression``
#: 替换（不用 % / format，避免与 JS 花括号冲突）。
#: iframe 遍历：对 same-origin iframe 通过 contentDocument 递归采集，
#: cross-origin iframe 仅记录 src URL 占位（供 AI 感知有 iframe 存在）。
_INTERACTIVE_JS = r"""
(function(){
  var SELECTOR = __SELECTOR__;
  var MAX_COLLECT = __MAX_COLLECT__;
  var INCLUDE_OFFSCREEN = __INCLUDE_OFFSCREEN__;
  var TEXT_CAP = __TEXT_CAP__;
  var MODE = __MODE__;
  var IFRAME_MAX_PER_FRAME = __IFRAME_MAX_PER_FRAME__;
  var IFRAME_MAX_FRAMES = __IFRAME_MAX_FRAMES__;
  // 跨 frame 巡检：START_REF 让每个 frame 的 ref 全局唯一；FRAME_URL 标注
  // 元素来源；INCLUDE_IFRAMES=false 时只采集当前文档（CDP 逐帧扫描各自采集）。
  var START_REF = __START_REF__;
  var FRAME_URL = __FRAME_URL__;
  var INCLUDE_IFRAMES = __INCLUDE_IFRAMES__;

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
        var labelled = el.ownerDocument.getElementById(ids[i]);
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

  function inViewportOf(doc, el){
    var rect = el.getBoundingClientRect();
    var win = doc.defaultView || window;
    var width = win.innerWidth || doc.documentElement.clientWidth || 0;
    var height = win.innerHeight || doc.documentElement.clientHeight || 0;
    return rect.bottom > 0 && rect.right > 0 && rect.top < height && rect.left < width;
  }

  function fieldOf(el, candidate, frameUrl){
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
    if (frameUrl) item.frame_url = frameUrl;
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

  // collect(doc, refOffset, frameUrl) → {items:[], nextOffset, text}
  // doc: 目标 document（主框架或 iframe.contentDocument）
  // refOffset: 起始 ref 序号（主框架从 1 开始，iframe 接着排）
  // frameUrl: null 表示主框架，非 null 表示子 frame（写入元素的 frame_url 字段）
  function collect(doc, refOffset, frameUrl){
    var raw = doc.querySelectorAll(SELECTOR);
    var unique = [];
    for (var i = 0; i < raw.length; i++) {
      if (unique.indexOf(raw[i]) === -1) unique.push(raw[i]);
    }

    var candidates = [];
    for (var j = 0; j < unique.length; j++) {
      var el = unique[j];
      if (!el.getClientRects || el.getClientRects().length === 0) continue;
      if (el.closest && el.closest('[hidden],[aria-hidden="true"]')) continue;
      candidates.push({el: el, in_viewport: inViewportOf(doc, el)});
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

    var perFrameCap = frameUrl ? IFRAME_MAX_PER_FRAME : MAX_COLLECT;
    if (candidates.length > perFrameCap) candidates = candidates.slice(0, perFrameCap);

    var items = [];
    var nextOffset = refOffset;
    for (var n = 0; n < candidates.length; n++) {
      var candidate = candidates[n];
      candidate.ref = 'e' + nextOffset;
      nextOffset++;
      var accessibleName = nameOf(candidate.el);
      try {
        candidate.el.setAttribute('data-sage-ref', candidate.ref);
        candidate.el.setAttribute('data-sage-ref-name', accessibleName);
      } catch (err) {}
      // 注册到 window（主框架的 window），iframe 元素也存主框架注册表
      // 注：跨 frame ref 在下次 snapshot 后会失效（已知限制），AI 应在交互前重拍快照
      window.__SAGE_REFS__[candidate.ref] = candidate.el;
      window.__SAGE_REF_NAMES__[candidate.ref] = accessibleName;
      items.push(fieldOf(candidate.el, candidate, frameUrl));
    }
    var bodyText = (doc.body && doc.body.innerText || '').slice(0, TEXT_CAP);
    return {items: items, nextOffset: nextOffset, text: bodyText};
  }

  // 重置注册表
  window.__SAGE_REFS__ = {};
  window.__SAGE_REF_NAMES__ = {};

  var allElements = [];
  var allText = '';

  // 主框架采集（refOffset 由调用方指定：CDP 逐帧巡检时全局递增）
  var mainResult = collect(document, START_REF, FRAME_URL ? FRAME_URL : null);
  allElements = allElements.concat(mainResult.items);
  allText = mainResult.text;
  var nextRef = mainResult.nextOffset;

  // iframe 遍历（fallback；CDP 全帧巡检时关闭，避免与逐帧采集重复）
  var iframeCount = 0;
  var truncatedIframes = false;
  if (INCLUDE_IFRAMES) {
    var iframes = document.querySelectorAll('iframe');
    for (var f = 0; f < iframes.length; f++) {
      if (iframeCount >= IFRAME_MAX_FRAMES) {
        truncatedIframes = true;
        break;
      }
      var iframeEl = iframes[f];
      var iframeSrc = '';
      try { iframeSrc = iframeEl.src || iframeEl.getAttribute('src') || ''; } catch(e){}
      var iframeDoc = null;
      try { iframeDoc = iframeEl.contentDocument || null; } catch(e){}
      if (iframeDoc && iframeDoc.body) {
        // same-origin iframe：递归采集
        var sub = collect(iframeDoc, nextRef, iframeSrc);
        allElements = allElements.concat(sub.items);
        nextRef = sub.nextOffset;
        allText = (allText + '\n' + sub.text).slice(0, TEXT_CAP);
        iframeCount++;
      } else if (iframeSrc) {
        // cross-origin 或加载中的 iframe：记录占位
        allElements.push({
          ref: 'e' + nextRef,
          role: 'iframe',
          name: clean(iframeSrc, 200),
          disabled: false,
          in_viewport: inViewportOf(document, iframeEl),
          frame_url: iframeSrc,
          _cross_origin: true
        });
        nextRef++;
        iframeCount++;
      }
    }
  }

  if (allElements.length > MAX_COLLECT) allElements = allElements.slice(0, MAX_COLLECT);

  return JSON.stringify({
    url: location.href,
    title: document.title,
    viewport: {
      width: window.innerWidth || 0,
      height: window.innerHeight || 0,
      scroll_y: window.scrollY || 0
    },
    elements: allElements,
    elements_total: allElements.length,
    next_ref: nextRef,
    mode: MODE,
    text: allText,
    iframes_scanned: iframeCount,
    iframes_truncated: truncatedIframes,
    frameset_count: document.querySelectorAll('frame').length
  });
})()
"""

#: text 模式：纯文本快照，不含任何 ref 注册逻辑（保持旧形状）。
#: 遍历 same-origin iframe 的正文一并归入 text。
_TEXT_JS = r"""
(function(){
  var TEXT_CAP = __TEXT_CAP__;
  var parts = [(document.body && document.body.innerText || '').slice(0, TEXT_CAP)];
  var iframes = document.querySelectorAll('iframe');
  for (var f = 0; f < iframes.length && f < __IFRAME_MAX_FRAMES__; f++) {
    var iframeDoc = null;
    try { iframeDoc = iframes[f].contentDocument || null; } catch(e){}
    if (iframeDoc && iframeDoc.body) {
      var subText = (iframeDoc.body.innerText || '').slice(0, TEXT_CAP);
      if (subText) parts.push(subText);
    }
  }
  return JSON.stringify({
    url: location.href,
    title: document.title,
    text: parts.join('\n').slice(0, TEXT_CAP),
    frameset_count: document.querySelectorAll('frame').length
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
    include_iframes: bool = True,
    ref_offset: int = 1,
    frame_url: str = "",
) -> str:
    """构造快照注入 JS。

    ``mode=text`` 只取正文，不注入 ref 注册表；``interactive`` / ``full``
    共享同一套采集逻辑（``full`` 的差异在 ``parse_snapshot_payload``）。

    ``include_iframes=False`` 关闭页面内同源 iframe 遍历（CDP 逐帧巡检时
    由 Python 侧对每个 frame 分别执行本表达式，避免重复采集）；
    ``ref_offset`` 让各 frame 的 ref 序号连续（全局唯一）；
    ``frame_url`` 写入每个元素的 ``frame_url``，标注元素来源 frame。
    """
    normalized = _normalize_mode(mode)
    if normalized == "text":
        return (
            _TEXT_JS.replace("__TEXT_CAP__", str(int(SNAPSHOT_TEXT_CAP)))
            .replace("__IFRAME_MAX_FRAMES__", str(int(IFRAME_MAX_FRAMES)))
        )

    try:
        collect_cap = max(0, int(max_collect))
    except (TypeError, ValueError):
        collect_cap = SNAPSHOT_HARD_COLLECT_CAP
    try:
        start_ref = max(1, int(ref_offset))
    except (TypeError, ValueError):
        start_ref = 1
    return (
        _INTERACTIVE_JS.replace("__SELECTOR__", json.dumps(CANDIDATE_SELECTOR))
        .replace("__MAX_COLLECT__", str(collect_cap))
        .replace("__INCLUDE_OFFSCREEN__", "true" if include_offscreen else "false")
        .replace("__TEXT_CAP__", str(int(SNAPSHOT_TEXT_CAP)))
        .replace("__MODE__", json.dumps(normalized))
        .replace("__IFRAME_MAX_PER_FRAME__", str(int(IFRAME_MAX_COLLECT_PER_FRAME)))
        .replace("__IFRAME_MAX_FRAMES__", str(int(IFRAME_MAX_FRAMES)))
        .replace("__START_REF__", str(start_ref))
        .replace("__FRAME_URL__", json.dumps(str(frame_url or "")))
        .replace("__INCLUDE_IFRAMES__", "true" if include_iframes else "false")
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
            or (item.get("_cross_origin") is True
                and needle in _as_text(item.get("frame_url")).lower())
        ]
        # 清理内部标记字段（不暴露给 AI）
        for item in elements:
            item.pop("_cross_origin", None)

    # 清理非 query 模式下的内部标记字段
    for item in elements:
        item.pop("_cross_origin", None)

    total = len(elements)
    limit = _clamp_max_nodes(max_nodes)
    truncated = total > limit
    viewport = data.get("viewport")
    iframes_scanned = int(data.get("iframes_scanned") or 0)
    iframes_truncated = bool(data.get("iframes_truncated"))
    frameset_count = int(data.get("frameset_count") or 0)
    result: Dict[str, Any] = {
        "url": url,
        "title": title,
        "viewport": viewport if isinstance(viewport, dict) else {},
        "elements": elements[:limit],
        "elements_total": total,
        "truncated": truncated,
        "mode": normalized,
        "iframes_scanned": iframes_scanned,
        "iframes_truncated": iframes_truncated,
    }
    frames_meta = data.get("frames")
    if isinstance(frames_meta, list):
        result["frames"] = [item for item in frames_meta if isinstance(item, dict)]
    if frameset_count > 0:
        result["frameset_count"] = frameset_count

    hints = []
    if truncated:
        hints.append(
            f"共 {total} 个交互元素，已返回前 {limit} 个；可用 query 过滤或滚动后重新快照"
        )
    if iframes_truncated:
        hints.append(
            f"iframe 数量超过上限 {IFRAME_MAX_FRAMES}，部分子 frame 内容未采集；"
            "可用 query 过滤目标 frame 内的元素"
        )
    if frameset_count > 0 and iframes_scanned == 0:
        hints.append(
            "页面含 frameset/<frame> 子框架，但未采集到子 frame 内容；"
            "请升级浏览器组件或直接 navigate 到 frame_url"
        )
    if total < CANVAS_ELEMENT_THRESHOLD and len(text) < SNAPSHOT_CANVAS_TEXT_HINT:
        hints.append("页面可能由 Canvas 渲染，建议 browser_screenshot(return_image=true)")
    if hints:
        result["hint"] = "；".join(hints)

    if normalized == "full":
        result["text"] = text
        result["truncated_text"] = len(text) >= SNAPSHOT_TEXT_CAP
    return result


#: 交互目标可访问名提取片段（调用方已把目标元素绑定为 ``el``）。
#: 宽泛容器只取直接文本节点，避免整页/整块 innerText 进入审计与确认描述。
TARGET_NAME_SOURCE_JS = (
    "var name='';"
    "var isBody=(el===document.body||el===document.documentElement);"
    "var role=(el.getAttribute&&el.getAttribute('role'))||'';"
    "var tag=(el.tagName||'').toUpperCase();"
    "var broadRoles={generic:1,presentation:1,none:1,main:1,region:1,"
    "document:1,group:1,list:1};"
    "var broadTags={DIV:1,MAIN:1,SECTION:1,ARTICLE:1,NAV:1,FORM:1,"
    "ASIDE:1,HEADER:1,FOOTER:1,UL:1,OL:1,TABLE:1,TBODY:1,TR:1,"
    "BODY:1,HTML:1};"
    "var isBroad=!!broadTags[tag]&&(!role||broadRoles[role]===1);"
    "if(!isBody){"
    "name=(el.getAttribute&&(el.getAttribute('aria-label')||''))||'';"
    "if(!name){name=(el.getAttribute&&(el.getAttribute('title')||''))||'';}"
    "if(!name&&el.labels&&el.labels.length){name=el.labels[0].textContent||'';}"
    "if(!name){"
    "if(!isBroad){name=el.innerText||el.textContent||'';}"
    "else{var tn='';var kids=el.childNodes||[];"
    "for(var i=0;i<kids.length&&tn.length<120;i++){"
    "if(kids[i].nodeType===3){tn+=kids[i].nodeValue;}}"
    "name=tn;}"
    "}"
    "}"
)


def merge_snapshot_payloads(
    main: Dict[str, Any],
    frames: List[Dict[str, Any]],
    frames_meta: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """把主框架与子 frame 的快照 payload 合并成一份。

    ``frames`` 与 ``frames_meta`` 一一对应（被策略拦截的 frame 由调用方传
    空 payload + ``state=blocked`` 的元数据）。子 frame 元素补 ``frame_url``；
    正文按 ``SNAPSHOT_TEXT_CAP`` 截断；``iframes_scanned`` 只统计真正读取的
    frame；``next_ref`` 取各 payload 的最大值，供后续 frame 继续编号。
    """
    result: Dict[str, Any] = dict(main) if isinstance(main, dict) else {}
    elements: List[Dict[str, Any]] = [
        item for item in (result.get("elements") or []) if isinstance(item, dict)
    ]
    text_parts = [str(result.get("text") or "")]
    try:
        next_ref = int(result.get("next_ref") or 0)
    except (TypeError, ValueError):
        next_ref = 0

    for raw_payload, meta in zip(frames or [], frames_meta or []):  # noqa: B905 — py3.8 无 strict
        payload = raw_payload if isinstance(raw_payload, dict) else {}
        frame_url = str((meta or {}).get("url") or "") if isinstance(meta, dict) else ""
        for item in payload.get("elements") or []:
            if not isinstance(item, dict):
                continue
            current = item
            if frame_url and not item.get("frame_url"):
                current = dict(item)
                current["frame_url"] = frame_url
            elements.append(current)
        sub_text = str(payload.get("text") or "")
        if sub_text:
            text_parts.append(sub_text)
        try:
            next_ref = max(next_ref, int(payload.get("next_ref") or 0))
        except (TypeError, ValueError):
            continue

    merged_text = "\n".join(part for part in text_parts if part)
    if len(merged_text) > SNAPSHOT_TEXT_CAP:
        merged_text = merged_text[:SNAPSHOT_TEXT_CAP]
    scanned = sum(
        1
        for meta in (frames_meta or [])
        if isinstance(meta, dict) and meta.get("state") == "scanned"
    )
    truncated = bool(result.get("iframes_truncated")) or any(
        bool(payload.get("iframes_truncated"))
        for payload in (frames or [])
        if isinstance(payload, dict)
    )
    result.update(
        {
            "elements": elements,
            "elements_total": len(elements),
            "text": merged_text,
            "iframes_scanned": scanned,
            "iframes_truncated": truncated,
            "frames": list(frames_meta or []),
        }
    )
    if next_ref:
        result["next_ref"] = next_ref
    return result


def build_frame_ref_expression(action_js: str, ref: str, expected_name: str = "") -> str:
    """按 ``data-sage-ref`` 属性在子 frame 内定位并执行动作。

    隔离世界与页面重新建世界后 ``window.__SAGE_REFS__`` 不保证存在，
    但 ``data-sage-ref`` / ``data-sage-ref-name`` 属性随 DOM 保留，因此
    frame 内交互统一走属性定位；失效与改名同样返回 ``stale-ref``。
    """
    return (
        "(function(){"
        "var __sageRef=" + json.dumps(str(ref)) + ";"
        "var __sageName=" + json.dumps(str(expected_name), ensure_ascii=False) + ";"
        "var el=document.querySelector('[data-sage-ref=\"'+__sageRef+'\"]');"
        "if(!el||el.isConnected!==true){return{ok:false,info:'stale-ref'};}"
        "if(el.getAttribute('data-sage-ref-name')!==__sageName)"
        "{return{ok:false,info:'stale-ref'};}"
        f"return {action_js};"
        "})()"
    )


def build_frame_target_expression(ref: str) -> str:
    """按 ``data-sage-ref`` 属性读取子 frame 目标元数据（敏感动作分类用）。"""
    return (
        "(function(){var __sageRef=" + json.dumps(str(ref)) + ";"
        "var el=document.querySelector('[data-sage-ref=\"'+__sageRef+'\"]');"
        "if(!el)return null;"
        + TARGET_NAME_SOURCE_JS
        + "return{"
        "tag:(el.tagName||'').toLowerCase(),"
        "role:(el.getAttribute&&el.getAttribute('role'))||'',"
        "name:String(name).trim().slice(0,120),"
        "type:String((el.getAttribute&&el.getAttribute('type'))||'').toLowerCase(),"
        "placeholder:String((el.getAttribute&&el.getAttribute('placeholder'))||'').slice(0,120)};"
        "})()"
    )


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
