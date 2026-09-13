/**
 * Prompt 模板库 API（R27-A）—— 用户自定义提示词模板 CRUD。
 */

import { invoke } from './desktopInvoke';
import { handleApiError, withRetry } from './utils';

export interface PromptTemplate {
  id: string;
  name: string;
  description: string;
  content: string;
  created_at: number;
  updated_at: number;
}

export const promptApi = {
  /** 列出全部模板（新→旧）。 */
  async list(): Promise<PromptTemplate[]> {
    return withRetry(async () => {
      try {
        const res = await invoke<{ templates: PromptTemplate[] }>('prompts_list');
        return res.templates ?? [];
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },

  /** 创建模板（name/content 必填）。 */
  async create(name: string, content: string, description = ''): Promise<PromptTemplate> {
    try {
      const res = await invoke<{ template: PromptTemplate }>('prompts_create', {
        name,
        content,
        description,
      });
      return res.template;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 更新模板（部分字段）。 */
  async update(
    id: string,
    patch: { name?: string; content?: string; description?: string },
  ): Promise<PromptTemplate> {
    try {
      const res = await invoke<{ template: PromptTemplate }>('prompts_update', {
        id,
        ...patch,
      });
      return res.template;
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 删除模板。 */
  async remove(id: string): Promise<void> {
    await invoke('prompts_delete', { id });
  },
};
