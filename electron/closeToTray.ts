// electron/closeToTray.ts
//
// E-2 (round5 批次 E): 「关闭即隐藏到托盘」偏好持久化。
//
// 主进程无 SQLite 依赖——沿用 demo mode 的 JSON 文件先例：
// <userData>/sage-close-to-tray.json（dev = <cwd>/data/）。
// main.ts 在 win.on('close') 拦截时读取本模块维护的内存态。

import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export function getCloseToTrayPath(isPackaged: boolean, userDataPath: string, cwd: string): string {
  if (isPackaged) return join(userDataPath, 'sage-close-to-tray.json');
  return join(cwd, 'data', 'sage-close-to-tray.json');
}

export function readCloseToTray(path: string): boolean {
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as { enabled?: unknown };
    return parsed.enabled === true;
  } catch {
    // 文件不存在/JSON 损坏 → 默认关（关闭即退出，保持既有用户预期）
    return false;
  }
}

export function writeCloseToTray(path: string, enabled: boolean): void {
  writeFileSync(path, JSON.stringify({ enabled }), 'utf-8');
}
