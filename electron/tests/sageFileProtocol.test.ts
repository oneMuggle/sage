/**
 * P17: sage-file 工作区注册表生命周期 —— register / unregister / 幂等。
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { registerWorkspaceRoot, unregisterWorkspaceRoot } from '../sageFileProtocol';

describe('sageFileProtocol registry', () => {
  it('register / unregister 生命周期', () => {
    const tmp = mkdtempSync(join(tmpdir(), 'sage-reg-test-'));
    try {
      expect(registerWorkspaceRoot(tmp)).toBe(true);
      // 幂等：重复登记仍 true
      expect(registerWorkspaceRoot(tmp)).toBe(true);
      // 注销
      expect(unregisterWorkspaceRoot(tmp)).toBe(true);
      // 再次注销返回 false（已不存在）
      expect(unregisterWorkspaceRoot(tmp)).toBe(false);
    } finally {
      rmSync(tmp, { recursive: true, force: true });
    }
  });

  it('register 不存在的路径返回 false', () => {
    expect(registerWorkspaceRoot('/nonexistent/path/xyz/abc')).toBe(false);
  });
});
