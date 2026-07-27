import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

interface PackageLockRoot {
  version: string;
  packages: Record<string, { version?: string }>;
}

describe('package metadata version contract', () => {
  it('keeps package.json and both package-lock root versions equal', () => {
    const root = process.cwd();
    const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')) as {
      version: string;
    };
    const lock = JSON.parse(
      readFileSync(resolve(root, 'package-lock.json'), 'utf8'),
    ) as PackageLockRoot;

    expect(lock.version).toBe(pkg.version);
    expect(lock.packages['']?.version).toBe(pkg.version);
  });
});
