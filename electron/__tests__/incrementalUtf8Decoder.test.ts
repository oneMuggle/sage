import { describe, expect, it } from 'vitest';
import { createIncrementalUtf8Decoder } from '../incrementalUtf8Decoder';

describe('createIncrementalUtf8Decoder', () => {
  it('decodes a single ASCII chunk', () => {
    const dec = createIncrementalUtf8Decoder();
    expect(dec.push(Buffer.from('hello'))).toBe('hello');
  });

  it('decodes a single multi-byte chunk (BMP Chinese char)', () => {
    const dec = createIncrementalUtf8Decoder();
    // '中' is 0xE4 0xB8 0xAD
    expect(dec.push(Buffer.from([0xe4, 0xb8, 0xad]))).toBe('中');
  });

  it('decodes a single 4-byte chunk (emoji)', () => {
    const dec = createIncrementalUtf8Decoder();
    // 😀 = U+1F600 = F0 9F 98 80
    expect(dec.push(Buffer.from([0xf0, 0x9f, 0x98, 0x80]))).toBe('😀');
  });

  it('reassembles a multi-byte char split across chunks', () => {
    const dec = createIncrementalUtf8Decoder();
    // '中' = E4 B8 AD — split as E4 B8 then AD
    expect(dec.push(Buffer.from([0xe4, 0xb8]))).toBe('');
    expect(dec.push(Buffer.from([0xad]))).toBe('中');
  });

  it('reassembles a 4-byte emoji split across multiple chunks', () => {
    const dec = createIncrementalUtf8Decoder();
    // 😀 = F0 9F 98 80 — split as F0 then 9F 98 then 80
    expect(dec.push(Buffer.from([0xf0]))).toBe('');
    expect(dec.push(Buffer.from([0x9f, 0x98]))).toBe('');
    expect(dec.push(Buffer.from([0x80]))).toBe('😀');
  });

  it('handles a stream of mixed ASCII + multi-byte chars correctly', () => {
    const dec = createIncrementalUtf8Decoder();
    const out: string[] = [];
    out.push(dec.push(Buffer.from('hi ')));
    out.push(dec.push(Buffer.from([0xe4, 0xb8, 0xad]))); // '中'
    out.push(dec.push(Buffer.from(' ok')));
    expect(out.join('')).toBe('hi 中 ok');
  });

  it('close() returns a non-empty fallback for an incomplete trailing sequence', () => {
    const dec = createIncrementalUtf8Decoder();
    // Incomplete 3-byte sequence (E4 B8 missing the third byte)
    dec.push(Buffer.from([0xe4, 0xb8]));
    const flushed = dec.close();
    expect(typeof flushed).toBe('string');
    expect(flushed.length).toBeGreaterThan(0);
  });

  it('close() returns empty string when no buffered bytes remain', () => {
    const dec = createIncrementalUtf8Decoder();
    dec.push(Buffer.from('complete'));
    expect(dec.close()).toBe('');
  });

  it('reset() discards buffered partial bytes from a previous stream', () => {
    const dec = createIncrementalUtf8Decoder();
    // Incomplete sequence
    dec.push(Buffer.from([0xe4, 0xb8]));
    dec.reset();
    // Now push a complete string; the old partial must not contaminate.
    expect(dec.push(Buffer.from('hi'))).toBe('hi');
    expect(dec.close()).toBe('');
  });
});