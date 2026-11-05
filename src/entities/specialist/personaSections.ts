/**
 * 专家人设六段解析/序列化（M1-E）。
 *
 * 专家人设以 Markdown 标题块存于 `agents.system_prompt`：
 *
 * ```markdown
 * # 身份
 *
 * 你是一位专业写作助手…
 *
 * # 行为边界
 *
 * - 保持原文核心意思
 * ```
 *
 * 六段固定顺序：身份 → 职责 → 工作方式 → 风格 → 行为边界 → 输出模板。
 * 解析容忍别名（如「工作流程」「护栏」）与前置正文（归入身份）；
 * 序列化只输出非空段，未知标题行按正文保留在当前段，不丢数据。
 */

export type PersonaSectionKey =
  | 'identity'
  | 'responsibilities'
  | 'workflow'
  | 'style'
  | 'guardrails'
  | 'output';

export interface PersonaSectionMeta {
  key: PersonaSectionKey;
  /** 序列化时写出的规范标题（不含 `# `）。 */
  heading: string;
  label: string;
  placeholder: string;
}

export const PERSONA_SECTIONS: readonly PersonaSectionMeta[] = [
  {
    key: 'identity',
    heading: '身份',
    label: '身份',
    placeholder: '你是一位专业的写作助手，擅长润色、改写与翻译。',
  },
  {
    key: 'responsibilities',
    heading: '职责',
    label: '职责',
    placeholder: '列出专家负责的任务，例如：\n- 润色文章\n- 校对措辞',
  },
  {
    key: 'workflow',
    heading: '工作方式',
    label: '工作方式',
    placeholder: '描述工作流程，例如：先通读全文，再逐段修改，最后统一文风。',
  },
  {
    key: 'style',
    heading: '风格',
    label: '风格',
    placeholder: '描述语气与表达习惯，例如：简洁、主动语态、避免生僻词。',
  },
  {
    key: 'guardrails',
    heading: '行为边界',
    label: '行为边界',
    placeholder: '列出不可逾越的边界，例如：\n- 永远保持原文核心意思\n- 不虚构引用',
  },
  {
    key: 'output',
    heading: '输出模板',
    label: '输出模板',
    placeholder: '给出固定输出格式，例如：\n## 润色结果\n\n[文本]\n\n## 修改说明',
  },
] as const;

export type PersonaSections = Record<PersonaSectionKey, string>;

/** 标题 → 段 key 的别名表（小写去空白后匹配）。 */
const HEADING_ALIASES: Readonly<Record<string, PersonaSectionKey>> = {
  身份: 'identity',
  角色: 'identity',
  定位: 'identity',
  职责: 'responsibilities',
  任务: 'responsibilities',
  工作方式: 'workflow',
  工作流程: 'workflow',
  流程: 'workflow',
  技能: 'workflow',
  风格: 'style',
  语气: 'style',
  沟通风格: 'style',
  行为边界: 'guardrails',
  边界: 'guardrails',
  护栏: 'guardrails',
  限制: 'guardrails',
  输出模板: 'output',
  输出格式: 'output',
  输出: 'output',
};

export function emptyPersonaSections(): PersonaSections {
  return {
    identity: '',
    responsibilities: '',
    workflow: '',
    style: '',
    guardrails: '',
    output: '',
  };
}

function sectionKeyForHeading(raw: string): PersonaSectionKey | null {
  const normalized = raw.replace(/\s+/gu, '').toLowerCase();
  return HEADING_ALIASES[normalized] ?? null;
}

/**
 * 解析人设 Markdown → 六段。一级标题（`# xxx`）划分段落；
 * 首个标题前的正文归入「身份」；未识别标题行作为正文保留在当前段。
 */
export function parsePersonaSections(markdown: string): PersonaSections {
  const sections = emptyPersonaSections();
  const source = typeof markdown === 'string' ? markdown : '';
  if (!source.trim()) return sections;

  const lines = source.split(/\r?\n/u);
  let current: PersonaSectionKey = 'identity';
  const buffers: Record<PersonaSectionKey, string[]> = {
    identity: [],
    responsibilities: [],
    workflow: [],
    style: [],
    guardrails: [],
    output: [],
  };

  for (const line of lines) {
    const match = /^#(?!#)\s+(.+?)\s*#*\s*$/u.exec(line);
    const key = match ? sectionKeyForHeading(match[1]) : null;
    if (key) {
      current = key;
      continue;
    }
    buffers[current].push(line);
  }

  for (const meta of PERSONA_SECTIONS) {
    sections[meta.key] = buffers[meta.key].join('\n').trim();
  }
  return sections;
}

/**
 * 六段 → 人设 Markdown。按固定顺序输出非空段；全空返回空串。
 */
export function serializePersonaSections(sections: PersonaSections): string {
  const parts: string[] = [];
  for (const meta of PERSONA_SECTIONS) {
    const body = (sections[meta.key] ?? '').trim();
    if (!body) continue;
    parts.push(`# ${meta.heading}\n\n${body}`);
  }
  return parts.join('\n\n');
}

/** 所有段均为空 → true（向导据此禁用「预览/创建」）。 */
export function isPersonaEmpty(sections: PersonaSections): boolean {
  return PERSONA_SECTIONS.every((meta) => !(sections[meta.key] ?? '').trim());
}
