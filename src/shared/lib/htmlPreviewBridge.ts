// src/shared/lib/htmlPreviewBridge.ts
//
// HTML 预览的错误桥：把预览页里的运行时错误回传给宿主 UI。
//
// 预览文档跑在 sandbox iframe（opaque origin）里，宿主读不到它的
// console / error 事件。做法是在**渲染用的副本**头部注入一段内联脚本，
// 监听 window error / unhandledrejection / console.error，用 postMessage
// 把诊断信息发给宿主；宿主按 message.channel 过滤后展示错误横幅。
//
// 约束：这段脚本只允许出现在渲染副本里 —— 用户看到的源码、复制与下载的
// 内容必须是原文，不能带桥接代码。

/** postMessage 通道名 —— 宿主据此过滤掉与预览无关的消息。 */
export const PREVIEW_BRIDGE_CHANNEL = 'sage-preview-error';

/**
 * 注入预览文档的内联脚本。约束：
 * - 不含 `</script>` 字面量（会提前闭合 script 标签）。
 * - 只用 ES5 语法 —— 预览页可能来自用户的旧式 HTML。
 * - 任何一步失败都不能让预览页崩掉，故全部包 try/catch。
 */
export const HTML_PREVIEW_BRIDGE_SCRIPT = [
  '(function(){',
  "var CH='" + PREVIEW_BRIDGE_CHANNEL + "';",
  'function send(kind,message,detail){',
  'try{parent.postMessage({channel:CH,kind:kind,',
  "message:String(message==null?'':message),",
  "detail:String(detail==null?'':detail)},'*');}catch(e){}",
  '}',
  "window.addEventListener('error',function(e){",
  "var where=(e.filename||'')+(e.lineno?':'+e.lineno:'');",
  "send('error',e.message||'脚本执行错误',where);});",
  "window.addEventListener('unhandledrejection',function(e){",
  'var r=e.reason;',
  "var msg=(r&&(r.message||r))||'未处理的 Promise 拒绝';",
  "send('error',msg,'unhandledrejection');});",
  'var nativeError=console.error;',
  'console.error=function(){',
  'var parts=[];',
  'for(var i=0;i<arguments.length;i++){',
  'var a=arguments[i];',
  "parts.push(typeof a==='string'?a:((a&&a.message)?a.message:String(a)));}",
  "send('warn',parts.join(' '),'');",
  'nativeError.apply(console,arguments);};',
  '})();',
].join('');

/**
 * 把桥接脚本注入 HTML 头部，返回**渲染用的副本**。
 *
 * 注入位置优先级：`<head>` 内 → `<html>` 后新建 `<head>` → 文档最前。
 * 不改动入参（不可变约定）。
 */
export function injectPreviewBridge(html: string): string {
  if (!html) return html;
  const script = `<script>${HTML_PREVIEW_BRIDGE_SCRIPT}</script>`;
  const head = /<head[^>]*>/i.exec(html);
  if (head) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + script + html.slice(at);
  }
  const htmlTag = /<html[^>]*>/i.exec(html);
  if (htmlTag) {
    const at = htmlTag.index + htmlTag[0].length;
    return `${html.slice(0, at)}<head>${script}</head>${html.slice(at)}`;
  }
  return script + html;
}
