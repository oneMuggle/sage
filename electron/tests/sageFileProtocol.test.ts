/**
 * P17: sage-file 工作区注册表生命周期 —— register / unregister / 幂等。
 * P22 (2026-09-17): 项目级 allowed_paths 注册表 (registerAllowedPaths /
 *   unregisterAllowedPaths) 与 getAllowedPathsByProject 快照。
 */
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { beforeEach, describe, expect, it } from 'vitest';

import {
  registerWorkspaceRoot,
  unregisterWorkspaceRoot,
  registerAllowedPaths,
  unregisterAllowedPaths,
  getAllowedPathsByProject,
} from '../sageFileProtocol';

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

describe('P22: allowed_paths 注册表', () => {
  beforeEach(() => {
    // 测试隔离：每个用例开始时清空 — 但 P22 注册表是模块级单例，
    // 我们仅清理本组用例产生的项目 id（避免污染后续测试文件）。
    for (const id of ['proj-a', 'proj-b', 'proj-c']) {
      unregisterAllowedPaths(id);
    }
  });

  it('registerAllowedPaths 写入、getAllowedPathsByProject 读取', () => {
    registerAllowedPaths('proj-a', ['~/Documents/**', '/tmp/scratch/*']);
    const snap = getAllowedPathsByProject();
    expect(snap.get('proj-a')).toEqual(['~/Documents/**', '/tmp/scratch/*']);
  });

  it('registerAllowedPaths 幂等：同 id 多次写入以最后一次为准', () => {
    registerAllowedPaths('proj-b', ['/a/**']);
    registerAllowedPaths('proj-b', ['/b/**', '/c/**']);
    expect(getAllowedPathsByProject().get('proj-b')).toEqual(['/b/**', '/c/**']);
  });

  it('registerAllowedPaths 传入空数组 → 保留 key 但规则为空', () => {
    registerAllowedPaths('proj-c', ['/a/**']);
    registerAllowedPaths('proj-c', []);
    expect(getAllowedPathsByProject().get('proj-c')).toEqual([]);
    expect(getAllowedPathsByProject().has('proj-c')).toBe(true);
  });

  it('unregisterAllowedPaths 返回 true/false 表示是否移除', () => {
    registerAllowedPaths('proj-a', ['/x/**']);
    expect(unregisterAllowedPaths('proj-a')).toBe(true);
    expect(unregisterAllowedPaths('proj-a')).toBe(false); // 已删
    expect(getAllowedPathsByProject().has('proj-a')).toBe(false);
  });

  it('registerAllowedPaths 拷贝入参：外部修改不影响注册表', () => {
    const input: string[] = ['/a/**'];
    registerAllowedPaths('proj-a', input);
    input.push('/b/**');
    expect(getAllowedPathsByProject().get('proj-a')).toEqual(['/a/**']);
  });
});
