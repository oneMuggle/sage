/**
 * M6d — officeApi.readPpt 透传 PPT 内嵌图片开关（include_images /
 * max_images_per_slide / embed_image_data → bridge camelCase）。
 * 未传时保持 undefined（JSON 序列化丢弃 → 后端默认关闭）。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { invoke } from '../desktopInvoke';
import { officeApi } from '../officeApi';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

const EMPTY_RESULT = {
  summary: {
    id: 'doc-ppt',
    workspace_path: '/ws',
    doc_type: 'ppt',
    original_filename: 'deck.pptx',
    generated_filename: 'deck.pptx',
    status: 'parsed',
    created_at: 0,
    updated_at: 0,
    metadata: { file_size_bytes: 1024 },
    derived_from: null,
    archived_at: null,
  },
  slides: [],
};

describe('officeApi.readPpt (M6d image options)', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('forwards the M6d image switches as bridge camelCase args', async () => {
    invokeMock.mockResolvedValueOnce(EMPTY_RESULT);

    await officeApi.readPpt({
      workspace_path: '/ws',
      file_path: '/ws/deck.pptx',
      include_images: true,
      max_images_per_slide: 2,
      embed_image_data: true,
    });

    expect(invokeMock).toHaveBeenCalledWith('office_ppt_read', {
      workspacePath: '/ws',
      filePath: '/ws/deck.pptx',
      maxSizeBytes: undefined,
      includeImages: true,
      maxImagesPerSlide: 2,
      embedImageData: true,
    });
  });

  it('leaves the switches undefined when the caller omits them', async () => {
    invokeMock.mockResolvedValueOnce(EMPTY_RESULT);

    await officeApi.readPpt({ workspace_path: '/ws', file_path: '/ws/deck.pptx' });

    expect(invokeMock).toHaveBeenCalledWith('office_ppt_read', {
      workspacePath: '/ws',
      filePath: '/ws/deck.pptx',
      maxSizeBytes: undefined,
      includeImages: undefined,
      maxImagesPerSlide: undefined,
      embedImageData: undefined,
    });
  });
});
