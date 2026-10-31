import { describe, expect, it } from 'vitest';

import type { PetPackManifestBridge } from '../../shared/types/electron-api';
import { DAFEIYU_PACK, packFromManifest, packSource } from '../engine/packs';

const MANIFEST: PetPackManifestBridge = {
  id: 'my-pet',
  name: '小叶灵',
  version: '1.0.0',
  license: 'CC-BY-4.0',
  canvas: { width: 256, height: 256 },
  anchor: { x: 128, y: 236 },
  actions: {
    idle: ['frames/idle-0.webp', 'frames/待机.webm'],
    thinking: ['frames/think.webm'],
  },
};

describe('packFromManifest', () => {
  it('converts a user manifest into a renderer pack', () => {
    const pack = packFromManifest(MANIFEST);
    expect(pack).not.toBeNull();
    expect(pack?.id).toBe('my-pet');
    expect(pack?.builtin).toBe(false);
    expect(pack?.actions.idle).toEqual(['frames/idle-0.webp', 'frames/待机.webm']);
  });

  it('rejects manifests without a usable idle action', () => {
    expect(packFromManifest({ ...MANIFEST, actions: {} })).toBeNull();
    expect(packFromManifest({ ...MANIFEST, actions: { idle: [] } })).toBeNull();
    expect(
      packFromManifest({ ...MANIFEST, actions: { idle: [123 as unknown as string] } }),
    ).toBeNull();
  });

  it('rejects malformed input', () => {
    expect(packFromManifest(null as unknown as PetPackManifestBridge)).toBeNull();
    expect(packFromManifest({ ...MANIFEST, id: '' })).toBeNull();
    expect(packFromManifest({ ...MANIFEST, actions: null as never })).toBeNull();
  });
});

describe('packSource', () => {
  it('keeps built-in packs on relative public paths', () => {
    expect(packSource(DAFEIYU_PACK, '写代码.webm')).toBe(
      './pet/dafeiyu/%E5%86%99%E4%BB%A3%E7%A0%81.webm',
    );
  });

  it('serves user packs through sage-pet://', () => {
    const pack = packFromManifest(MANIFEST)!;
    expect(packSource(pack, 'frames/待机.webm')).toBe(
      'sage-pet://my-pet/frames/%E5%BE%85%E6%9C%BA.webm',
    );
  });
});
