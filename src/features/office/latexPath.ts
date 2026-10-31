export function joinWorkspacePath(root: string, relative: string): string {
  const rel = relative.trim().replace(/^[\\/]+/, '');
  if (!rel) return '';
  if (/^([a-zA-Z]:[\\/]|[\\/])/.test(rel)) return rel;
  const separator = root.includes('\\') ? '\\' : '/';
  return `${root.replace(/[\\/]+$/, '')}${separator}${rel}`;
}
