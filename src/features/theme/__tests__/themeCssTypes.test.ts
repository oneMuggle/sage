import { describe, expect, it } from 'vitest';

import { themeCssPayloadSchema, type ThemeCssPayload } from '../themeCssTypes';

describe('themeCssPayloadSchema', () => {
  const validPayload: ThemeCssPayload = {
    id: '550e8400-e29b-41d4-a716-446655440000',
    name: 'My Theme',
    css: ':root { --bg-base: #fff; }',
    appearance: 'light',
    created_at: 1700000000000,
    updated_at: 1700000000000,
  };

  describe('valid payloads', () => {
    it('accepts valid payload with all required fields', () => {
      const result = themeCssPayloadSchema.safeParse(validPayload);
      expect(result.success).toBe(true);
    });

    it('accepts payload with optional cover field', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        cover: 'data:image/png;base64,iVBOR',
      });
      expect(result.success).toBe(true);
    });

    it('accepts dark appearance', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        appearance: 'dark' as const,
      });
      expect(result.success).toBe(true);
    });

    it('accepts CSS at max length (8192 chars)', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        css: 'a'.repeat(8192),
      });
      expect(result.success).toBe(true);
    });

    it('accepts name at max length (32 chars)', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        name: 'a'.repeat(32),
      });
      expect(result.success).toBe(true);
    });
  });

  describe('invalid payloads', () => {
    it('rejects non-UUID id', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        id: 'not-a-uuid',
      });
      expect(result.success).toBe(false);
    });

    it('rejects empty name', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        name: '',
      });
      expect(result.success).toBe(false);
    });

    it('rejects name over 32 chars', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        name: 'a'.repeat(33),
      });
      expect(result.success).toBe(false);
    });

    it('rejects empty CSS', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        css: '',
      });
      expect(result.success).toBe(false);
    });

    it('rejects CSS over 8192 chars', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        css: 'a'.repeat(8193),
      });
      expect(result.success).toBe(false);
    });

    it('rejects invalid appearance', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        appearance: 'sepia',
      });
      expect(result.success).toBe(false);
    });

    it('rejects non-number created_at', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        created_at: '2024-01-01',
      });
      expect(result.success).toBe(false);
    });

    it('rejects non-number updated_at', () => {
      const result = themeCssPayloadSchema.safeParse({
        ...validPayload,
        updated_at: '2024-01-01',
      });
      expect(result.success).toBe(false);
    });

    it('rejects missing required field', () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { name: _name, ...incomplete } = validPayload;
      const result = themeCssPayloadSchema.safeParse(incomplete);
      expect(result.success).toBe(false);
    });

    it('rejects null', () => {
      const result = themeCssPayloadSchema.safeParse(null);
      expect(result.success).toBe(false);
    });

    it('rejects undefined', () => {
      const result = themeCssPayloadSchema.safeParse(undefined);
      expect(result.success).toBe(false);
    });

    it('rejects non-object', () => {
      const result = themeCssPayloadSchema.safeParse('string');
      expect(result.success).toBe(false);
    });
  });

  describe('type inference', () => {
    it('infers correct type from schema', () => {
      const result = themeCssPayloadSchema.safeParse(validPayload);
      if (result.success) {
        const data: ThemeCssPayload = result.data;
        expect(data.id).toBe(validPayload.id);
        expect(data.name).toBe(validPayload.name);
        expect(data.css).toBe(validPayload.css);
        expect(data.appearance).toBe(validPayload.appearance);
        expect(data.created_at).toBe(validPayload.created_at);
        expect(data.updated_at).toBe(validPayload.updated_at);
      }
    });
  });
});
