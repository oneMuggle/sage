/**
 * 对话（chat）设置项搜索条目。
 *
 * 从 `settingsSearchEntries.ts` 拆出，避免主索引越过 800 行质量门禁。
 */

import type { SettingsSearchEntry } from './settingsSearchEntries';

export const CHAT_SETTINGS_SEARCH_ENTRIES: SettingsSearchEntry[] = [
  {
    key: 'streaming',
    tab: 'basic',
    label: '流式输出',
    labelEn: 'Streaming',
    keywords: 'streaming 流式 逐字 输出',
  },
  {
    key: 'inputHistorySize',
    tab: 'basic',
    label: '输入历史条数',
    labelEn: 'Input history size',
    keywords: 'input history size 输入 历史 条数 上限',
  },
  {
    key: 'attachment_rag',
    tab: 'basic',
    label: '超长文档检索注入',
    labelEn: 'Attachment RAG',
    keywords: 'rag 附件 检索 embedding 长文档 top_k',
  },
  {
    key: 'chat_display_mode',
    tab: 'basic',
    label: '思考展示档位',
    labelEn: 'Reasoning display mode',
    keywords: 'chat_display_mode 思考 展示 档位 display mode reasoning thinking',
  },
];
