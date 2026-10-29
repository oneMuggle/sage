/**
 * projectDetector — P2 (2026-10-19).
 *
 * Walks up from a start directory (max 5 levels) looking for project root
 * markers: `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`.
 *
 * 2026-10-29 (feat/workspace-optimization): 降级为决策链的**最低优先级**输入。
 * 嗅探结果只作为 `detected_root` 参考值传给后端 `DefaultWorkspaceResolver`，
 * 优先级低于「用户显式偏好」和「已打开项目」，也不会被记住为用户偏好。
 * 后端是工作区决策的单一来源 —— 本模块不再触发任何 auto-bind。
 */

import { existsSync } from 'fs';
import { dirname, join } from 'path';

const PROJECT_MARKERS = ['.git', 'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod'];
const MAX_DEPTH = 5;

/**
 * Walk up from `startDir` looking for a project root (directory containing
 * any of `PROJECT_MARKERS`). Returns the first match found, or `null` if
 * no marker is found within `MAX_DEPTH` levels or at the filesystem root.
 */
export function detectProjectRoot(startDir: string): string | null {
  let current = startDir;
  for (let depth = 0; depth <= MAX_DEPTH; depth++) {
    for (const marker of PROJECT_MARKERS) {
      if (existsSync(join(current, marker))) {
        return current;
      }
    }
    const parent = dirname(current);
    if (parent === current) break; // reached filesystem root
    current = parent;
  }
  return null;
}
