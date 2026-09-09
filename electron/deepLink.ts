// electron/deepLink.ts
//
// E-1 (round5 批次 E): sage:// 深链协议解析。
//
// 协议形态: sage://chat?session=<sessionId>
// - Windows/Linux: 第二实例以 `sage://...` 为 argv 启动 → second-instance
//   事件里从 argv 提取（parseSageDeepLink 纯函数，可单测）;
// - macOS: 系统 open-url 事件直接给 URL。
//
// 命中后由 main.ts 复用既有 `sage:event:session-notify-click` 通道
// （App.sessionDeeplink 桥已消费并 navigate('/chat?session=...')）。

/** 深链协议名（setAsDefaultProtocolClient 注册用） */
export const SAGE_PROTOCOL = 'sage';

export interface SageDeepLink {
  sessionId: string;
}

/**
 * 从 second-instance argv 中提取 sage:// 深链。
 *
 * Windows/Linux 把协议 URL 作为启动参数追加到 argv（位置不定，可能与
 * 已有参数混排），因此逐个扫描而非取固定下标。非 sage:// 参数忽略。
 */
export function extractSageUrlFromArgv(argv: string[]): string | null {
  for (const arg of argv) {
    if (typeof arg === 'string' && arg.startsWith(`${SAGE_PROTOCOL}://`)) {
      return arg;
    }
  }
  return null;
}

/**
 * 解析 sage:// 深链 URL。当前仅支持 sage://chat?session=<id> 形态；
 * 其余 host / 缺参返回 null（调用方静默忽略）。
 */
export function parseSageDeepLink(url: string): SageDeepLink | null {
  if (typeof url !== 'string' || !url.startsWith(`${SAGE_PROTOCOL}://`)) {
    return null;
  }
  // WHATWG URL 需要 host 存在——sage://chat?x=1 中 "chat" 即 host。
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.host.toLowerCase() !== 'chat') {
    return null;
  }
  const sessionId = parsed.searchParams.get('session');
  if (!sessionId || !/^[0-9a-f-]{6,64}$/i.test(sessionId)) {
    return null;
  }
  return { sessionId };
}
