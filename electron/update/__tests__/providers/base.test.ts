// electron/update/__tests__/providers/base.test.ts
import { describe, it, expect } from 'vitest';
import { ProviderType } from '../../../electron/update/providers/base';

describe('UpdateProvider base types', () => {
  it('ProviderType accepts four known values', () => {
    const types: ProviderType[] = ['github', 'gitee', 'gitlab', 'generic-http'];
    expect(types).toHaveLength(4);
  });
});