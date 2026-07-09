/**
 * backgroundInjector 测试 — jsdom 环境
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
  clearPreviewCss,
  injectPersistedStyle,
  injectPreviewCss,
  removePersistedStyle,
  setCoverImage,
} from '../backgroundInjector';

describe('backgroundInjector', () => {
  beforeEach(() => {
    document.head.innerHTML = '';
  });

  afterEach(() => {
    document.head.innerHTML = '';
  });

  describe('injectPreviewCss', () => {
    it('creates a style element with id theme-preview', () => {
      injectPreviewCss(':root { --bg-base: #fff; }');
      const el = document.getElementById('theme-preview');
      expect(el).not.toBeNull();
      expect(el?.tagName).toBe('STYLE');
    });

    it('replaces existing preview on second call', () => {
      injectPreviewCss(':root { --bg-base: #fff; }');
      injectPreviewCss(':root { --bg-base: #000; }');
      const els = document.querySelectorAll('#theme-preview');
      expect(els.length).toBe(1);
      expect(els[0].textContent).toContain('#000');
    });
  });

  describe('clearPreviewCss', () => {
    it('removes preview element', () => {
      injectPreviewCss(':root {}');
      clearPreviewCss();
      expect(document.getElementById('theme-preview')).toBeNull();
    });
  });

  describe('injectPersistedStyle', () => {
    it('creates style with id theme-{id}', () => {
      injectPersistedStyle('my-id', ':root {}');
      const el = document.getElementById('theme-my-id');
      expect(el).not.toBeNull();
    });

    it('replaces existing on second call', () => {
      injectPersistedStyle('my-id', ':root { --bg-base: #fff; }');
      injectPersistedStyle('my-id', ':root { --bg-base: #000; }');
      const els = document.querySelectorAll('#theme-my-id');
      expect(els.length).toBe(1);
    });
  });

  describe('removePersistedStyle', () => {
    it('removes style by id', () => {
      injectPersistedStyle('my-id', ':root {}');
      removePersistedStyle('my-id');
      expect(document.getElementById('theme-my-id')).toBeNull();
    });
  });

  describe('setCoverImage', () => {
    it('sets --cover-image CSS variable on :root', () => {
      setCoverImage('data:image/png;base64,abc');
      const value = document.documentElement.style.getPropertyValue('--cover-image');
      expect(value).toBe('url("data:image/png;base64,abc")');
    });

    it('clears variable when called with empty string', () => {
      setCoverImage('data:image/png;base64,abc');
      setCoverImage('');
      const value = document.documentElement.style.getPropertyValue('--cover-image');
      expect(value).toBe('');
    });
  });
});
