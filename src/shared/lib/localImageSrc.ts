/**
 * 本地路径 → sage-file:// URL 转换 — P9 (UI 优化循环, 2026-09-14)。
 *
 * MarkdownImage 把模型输出的本地图片路径（绝对 Windows/POSIX 路径或
 * 相对工作区的路径）转换为 `sage-file://p/<enc(file)>?ws=<enc(ws)>`，
 * 由主进程 registerFileProtocol 校验（工作区包含 + 图片扩展名白名单 +
 * realpath 防符号链接逃逸）后安全读取。http/https/data/blob/sage-file
 * 原样透传；无工作区绑定的相对路径保持原样（与现状一致，仅无法加载）。
 */

const EXTERNAL_RE = /^(https?|data|blob|sage-file|mailto):/i;
const WIN_ABS_RE = /^[A-Za-z]:[\\/]/;
const POSIX_ABS_RE = /^\/(?!\/)/;
/** 后端媒体路由走 fetchMediaBlobUrl 通道（MarkdownImage 内处理），不转协议 */
const API_MEDIA_RE = /^\/api\//i;

/** 归一为 POSIX 风格分隔符并去掉尾斜杠（sage-file 载荷统一形态） */
function toPosix(p: string): string {
  return p.replace(/\\/g, '/').replace(/\/+$/, '');
}

export function buildLocalImageSrc(src: string, workspacePath?: string): string {
  if (!src || EXTERNAL_RE.test(src) || API_MEDIA_RE.test(src)) return src;

  let abs: string | null = null;
  if (WIN_ABS_RE.test(src) || POSIX_ABS_RE.test(src)) {
    abs = toPosix(src);
  } else if (workspacePath) {
    const rel = src.replace(/\\/g, '/').replace(/^(\.\/)+/, '');
    abs = `${toPosix(workspacePath)}/${rel}`;
  }
  if (!abs) return src;

  const file = encodeURIComponent(abs);
  const ws = workspacePath ? `?ws=${encodeURIComponent(toPosix(workspacePath))}` : '';
  return `sage-file://p/${file}${ws}`;
}
