import { describe, expect, it } from 'vitest';

import {
  resolveDefaultFidelity,
  shouldAutoLoadFidelity,
  shouldDefaultFidelityOn,
} from '../officeFidelity';

describe('officeFidelity', () => {
  describe('shouldDefaultFidelityOn', () => {
    it('word always defaults to fidelity on (no converter needed)', () => {
      expect(shouldDefaultFidelityOn('word', true)).toBe(true);
      expect(shouldDefaultFidelityOn('word', false)).toBe(true);
    });
    it('excel defaults on only when converter available', () => {
      expect(shouldDefaultFidelityOn('excel', true)).toBe(true);
      expect(shouldDefaultFidelityOn('excel', false)).toBe(false);
    });
    it('ppt defaults on only when converter available', () => {
      expect(shouldDefaultFidelityOn('ppt', true)).toBe(true);
      expect(shouldDefaultFidelityOn('ppt', false)).toBe(false);
    });
    it('pdf returns false (pdf uses its own path, not this switch)', () => {
      expect(shouldDefaultFidelityOn('pdf', true)).toBe(false);
    });
    it('undefined docType returns false', () => {
      expect(shouldDefaultFidelityOn(undefined, true)).toBe(false);
    });
  });

  describe('shouldAutoLoadFidelity', () => {
    it('excel/ppt with converter triggers auto-load', () => {
      expect(shouldAutoLoadFidelity('excel', true)).toBe(true);
      expect(shouldAutoLoadFidelity('ppt', true)).toBe(true);
    });
    it('word does not auto-load (docx-preview is synchronous, no need)', () => {
      expect(shouldAutoLoadFidelity('word', true)).toBe(false);
    });
    it('excel/ppt without converter does not auto-load', () => {
      expect(shouldAutoLoadFidelity('excel', false)).toBe(false);
      expect(shouldAutoLoadFidelity('ppt', false)).toBe(false);
    });
  });

  describe('resolveDefaultFidelity', () => {
    it('override=true forces on regardless of defaults', () => {
      expect(resolveDefaultFidelity('excel', false, true)).toBe(true);
    });
    it('override=false forces off even if default is on', () => {
      expect(resolveDefaultFidelity('word', true, false)).toBe(false);
    });
    it('no override falls back to shouldDefaultFidelityOn', () => {
      expect(resolveDefaultFidelity('word', false)).toBe(true);
      expect(resolveDefaultFidelity('excel', false)).toBe(false);
    });
  });
});
