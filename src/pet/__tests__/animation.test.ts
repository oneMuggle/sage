import { describe, expect, it } from 'vitest';

import {
  bubbleText,
  resolveAnimation,
  resolveInteraction,
  type PetPack,
} from '../engine/animation';

const PACK: PetPack = {
  id: 'test',
  name: 'Test',
  version: '1.0.0',
  license: 'MIT',
  source: 'test',
  canvas: { width: 640, height: 360 },
  anchor: { x: 320, y: 330 },
  actions: {
    idle: ['idle.webm'],
    thinking: ['thinking.webm'],
    acting: ['acting.webm'],
    acting_edit: ['edit.webm'],
    done: ['done.webm'],
    click: ['click.webm'],
    sleep_loop: ['sleep.webm'],
  },
};

describe('pet animation selection', () => {
  it('prefers a detail-specific action', () => {
    expect(resolveAnimation({ action: 'acting', detail: 'edit' }, PACK)).toEqual({
      file: 'edit.webm',
      loop: true,
    });
  });

  it('falls back to the generic action and then idle', () => {
    expect(resolveAnimation({ action: 'acting', detail: 'web' }, PACK)).toEqual({
      file: 'acting.webm',
      loop: true,
    });
    expect(resolveAnimation({ action: 'error', detail: null }, PACK)).toEqual({
      file: 'idle.webm',
      loop: false,
    });
  });

  it('marks terminal actions as one-shot', () => {
    expect(resolveAnimation({ action: 'done', detail: null }, PACK)).toEqual({
      file: 'done.webm',
      loop: false,
    });
  });

  it('uses the sleep loop for sleeping', () => {
    expect(resolveAnimation({ action: 'sleeping', detail: null }, PACK)).toEqual({
      file: 'sleep.webm',
      loop: true,
    });
  });

  it('resolves click interactions and bubble text', () => {
    expect(resolveInteraction(PACK, 'click')).toEqual({ file: 'click.webm', loop: false });
    expect(resolveInteraction(PACK, 'missing')).toBeNull();
    expect(bubbleText('waiting')).toBeTruthy();
    expect(bubbleText(null)).toBeNull();
    expect(bubbleText('unknown')).toBeNull();
  });

  it('rotates idle variants and plays each one once', () => {
    const pack = {
      ...PACK,
      actions: { ...PACK.actions, idle: ['idle-a.webm', 'idle-b.webm'] },
    };
    expect(resolveAnimation({ action: 'idle', detail: null }, pack, 0)).toEqual({
      file: 'idle-a.webm',
      loop: false,
    });
    expect(resolveAnimation({ action: 'idle', detail: null }, pack, 3)).toEqual({
      file: 'idle-b.webm',
      loop: false,
    });
  });

  it('picks a random click response', () => {
    const pack = {
      ...PACK,
      actions: { ...PACK.actions, click: ['click-a.webm', 'click-b.webm'] },
    };
    expect(resolveInteraction(pack, 'click', () => 0)).toEqual({
      file: 'click-a.webm',
      loop: false,
    });
    expect(resolveInteraction(pack, 'click', () => 0.9)).toEqual({
      file: 'click-b.webm',
      loop: false,
    });
  });
});
