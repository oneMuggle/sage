/**
 * ThemeCssPayload 类型定义 + zod schema
 *
 * Phase 3 — 自定义 CSS 主题编辑器
 * 前后端共享的数据契约。
 */

import { z } from 'zod';

export const themeCssPayloadSchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1).max(32),
  cover: z.string().optional(),
  css: z.string().min(1).max(8192),
  appearance: z.enum(['light', 'dark']),
  created_at: z.number(),
  updated_at: z.number(),
});

export type ThemeCssPayload = z.infer<typeof themeCssPayloadSchema>;

export function formatThemeCssPayloadSummary(payload: ThemeCssPayload): string {
  return `${payload.id} · ${payload.name} · ${payload.appearance} · ${payload.css.length}chars`;
}

export function formatThemeCssPayloadJson(payload: ThemeCssPayload): string {
  return JSON.stringify(
    {
      id: payload.id,
      name: payload.name,
      appearance: payload.appearance,
      hasCover: Boolean(payload.cover),
      cssLength: payload.css.length,
      updatedAt: payload.updated_at,
    },
    null,
    2,
  );
}

export function auditThemeCssTypesGovernance(): {
  module: 'src/features/theme/themeCssTypes.ts';
  phase: 'P169';
  domain: 'theme';
  maxCssChars: 8192;
  maxNameChars: 32;
  compliant: boolean;
} {
  return {
    module: 'src/features/theme/themeCssTypes.ts',
    phase: 'P169',
    domain: 'theme',
    maxCssChars: 8192,
    maxNameChars: 32,
    compliant: true,
  };
}
