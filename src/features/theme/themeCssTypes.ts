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
