import { describe, expect, it } from 'vitest';

import {
  formatMediaAttachmentJson,
  formatMediaAttachmentSummary,
} from '../MediaAttachment';

describe('MediaAttachment audit helpers', () => {
  it('formats media attachment summary', () => {
    expect(formatMediaAttachmentSummary('image/png', true)).toBe(
      'mimeType=image/png · category=image · caption=true',
    );
    expect(formatMediaAttachmentSummary('audio/mpeg', false)).toBe(
      'mimeType=audio/mpeg · category=audio · caption=false',
    );
    expect(formatMediaAttachmentSummary('application/pdf', false)).toBe(
      'mimeType=application/pdf · category=file · caption=false',
    );
  });

  it('exports media attachment JSON snapshot', () => {
    expect(JSON.parse(formatMediaAttachmentJson('image/webp', true))).toEqual({
      mimeType: 'image/webp',
      category: 'image',
      hasCaption: true,
    });
  });
});

