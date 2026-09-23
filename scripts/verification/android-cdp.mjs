#!/usr/bin/env node
// Android WebView CDP helper for on-device verification of Arena Companion.
// Usage:
//   node cdp.mjs pages                       # list DevTools pages (needs adb forward tcp:9222 -> webview socket)
//   node cdp.mjs eval '<js expression>'      # evaluate in the first arena.ai page (awaits promises)
//   node cdp.mjs eval-in <pageIndex> '<js>'  # evaluate in a specific page
// Env: CDP_PORT (default 9222)
const port = process.env.CDP_PORT || "9222";
const [cmd, ...rest] = process.argv.slice(2);

async function pages() {
  const r = await fetch(`http://127.0.0.1:${port}/json/list`);
  return r.json();
}
async function evalIn(page, expression) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  const result = await new Promise((res, rej) => {
    const id = 1;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === id) res(msg);
    };
    ws.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, awaitPromise: true, returnByValue: true, timeout: 30000 } }));
    setTimeout(() => rej(new Error("CDP timeout")), 35000);
  });
  ws.close();
  if (result.error) throw new Error(JSON.stringify(result.error));
  const r = result.result;
  if (r.exceptionDetails) return { exception: r.exceptionDetails.exception?.description || r.exceptionDetails.text };
  return r.result.value;
}
(async () => {
  const list = await pages();
  if (cmd === "pages") {
    for (const [i, p] of list.entries()) console.log(i, p.type, p.url, "|", (p.title || "").slice(0, 60));
    return;
  }
  if (cmd === "watch") {
    // watch <seconds> <urlRegex>: enable Network on the arena page, dump matching request/response summaries + bodies.
    const seconds = Number(rest[0] || 60), re = new RegExp(rest[1] || "create-chat");
    const page = list.find(p => /arena\.ai/.test(p.url)) || list[0];
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let nextId = 1; const pending = new Map(); const reqs = new Map(); const out = [];
    const send = (method, params) => new Promise((res) => { const id = nextId++; pending.set(id, res); ws.send(JSON.stringify({ id, method, params })); });
    ws.onmessage = async (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); return; }
      const p = msg.params || {};
      if (msg.method === "Network.requestWillBeSent" && re.test(p.request.url)) {
        let bodyKeys = null; try { bodyKeys = Object.keys(JSON.parse(p.request.postData || "{}")); } catch { bodyKeys = p.request.postData ? ["<non-json " + p.request.postData.length + "B>"] : null; }
        reqs.set(p.requestId, { url: p.request.url.replace("https://arena.ai", ""), method: p.request.method, reqHeaderKeys: Object.keys(p.request.headers || {}), bodyKeys, t: new Date().toISOString().slice(11, 19) });
      } else if (msg.method === "Network.responseReceived" && reqs.has(p.requestId)) {
        const r = reqs.get(p.requestId); r.status = p.response.status; r.mime = p.response.mimeType;
        const h = p.response.headers || {}; r.respHeaders = Object.fromEntries(Object.entries(h).filter(([k]) => /^(cf-|x-|retry-after|content-type|server|date)/i.test(k)).map(([k, v]) => [k, String(v).slice(0, 80)]));
      } else if ((msg.method === "Network.loadingFinished" || msg.method === "Network.loadingFailed") && reqs.has(p.requestId)) {
        const r = reqs.get(p.requestId);
        if (msg.method === "Network.loadingFailed") r.error = p.errorText;
        else { const b = await send("Network.getResponseBody", { requestId: p.requestId }); r.body = b.result ? (b.result.base64Encoded ? "<base64 " + b.result.body.length + ">" : b.result.body.slice(0, 1500)) : JSON.stringify(b.error); }
        out.push(r); reqs.delete(p.requestId);
      }
    };
    await send("Network.enable", {});
    await new Promise(res => setTimeout(res, seconds * 1000));
    for (const r of reqs.values()) out.push({ ...r, note: "still pending at deadline" });
    console.log(JSON.stringify(out, null, 1));
    ws.close(); process.exit(0);
  }
  let page, expr;
  if (cmd === "eval") { page = list.find(p => /arena\.ai/.test(p.url)) || list[0]; expr = rest.join(" "); }
  else if (cmd === "eval-in") { page = list[Number(rest[0])]; expr = rest.slice(1).join(" "); }
  else { console.error("unknown command"); process.exit(2); }
  if (!page) { console.error("no page"); process.exit(3); }
  const v = await evalIn(page, expr);
  console.log(typeof v === "string" ? v : JSON.stringify(v, null, 2));
  process.exit(0);
})().catch(e => { console.error("ERR", e.message); process.exit(1); });
