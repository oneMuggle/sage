/**
 * projectDetector — P2 (2026-10-19).
 *
 * Walks up from a start directory (max 5 levels) looking for project root
 * markers: `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`.
 *
 * Used at Electron startup to detect whether the app was launched from inside
 * a project directory, so new sessions can auto-bind to it.
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
