/**
 * r93: journalApi 单元测试——office journal 模板链路的通道与 snake_case 载荷。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';

const mockInvoke = vi.fn();

vi.mock('../desktopInvoke', () => ({
  invoke: (...args: unknown[]) => mockInvoke(...args),
}));

import { journalApi } from '../journalApi';

beforeEach(() => {
  mockInvoke.mockReset();
});

describe('journalApi', () => {
  it('parseTemplate() 传 file_path', async () => {
    const resp = { ok: true, title: '周报' };
    mockInvoke.mockResolvedValueOnce(resp);
    const r = await journalApi.parseTemplate('C:/tpl.docx');
    expect(mockInvoke).toHaveBeenCalledWith('office_journal_parse_template', {
      file_path: 'C:/tpl.docx',
    });
    expect(r).toEqual(resp);
  });

  it('listSpecs() 空载荷', async () => {
    const resp = { specs: [{ id: 'j1' }] };
    mockInvoke.mockResolvedValueOnce(resp);
    const r = await journalApi.listSpecs();
    expect(mockInvoke).toHaveBeenCalledWith('office_journal_list_specs', {});
    expect(r).toEqual(resp);
  });

  it('getSpec() 传 spec_id', async () => {
    const resp = { spec: { id: 'j1' } };
    mockInvoke.mockResolvedValueOnce(resp);
    await journalApi.getSpec('j1');
    expect(mockInvoke).toHaveBeenCalledWith('office_journal_get_spec', { spec_id: 'j1' });
  });

  it('validate() 透传参数对象', async () => {
    const args = { spec_id: 'j1', file_path: 'C:/a.docx' };
    const resp = { ok: true, issues: [] };
    mockInvoke.mockResolvedValueOnce(resp);
    const r = await journalApi.validate(args);
    expect(mockInvoke).toHaveBeenCalledWith('office_journal_validate', args);
    expect(r).toEqual(resp);
  });

  it('fillFromContent() 字段映射为 snake_case', async () => {
    const resp = { ok: true, output_path: 'C:/out.docx' };
    mockInvoke.mockResolvedValueOnce(resp);
    const r = await journalApi.fillFromContent({
      spec_id: 'j1',
      workspace_path: 'C:/ws',
      content: '正文',
      output_filename: 'out.docx',
    });
    expect(mockInvoke).toHaveBeenCalledWith('office_journal_fill_from_content', {
      spec_id: 'j1',
      workspace_path: 'C:/ws',
      content: '正文',
      output_filename: 'out.docx',
    });
    expect(r).toEqual(resp);
  });

  it('invoke 拒绝经 handleApiError 包装', async () => {
    mockInvoke.mockRejectedValueOnce({ error: 'NOT_FOUND', message: 'missing' });
    await expect(journalApi.getSpec('nope')).rejects.toMatchObject({ code: 'NOT_FOUND' });
  });
});
