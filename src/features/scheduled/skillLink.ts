/**
 * 批次 C · 技能 × 定时任务联动。
 *
 * 后端调度模型只有 `content`（提示词正文），没有技能字段；这里**不新增后端字段、不改
 * 执行链路**：技能引用就是正文里的 `/<name>`，按 `skillsApi.list()` 返回的真实技能名
 * 校验。引用不会自动执行技能，也不会扩大权限或文件访问范围；技能被删除或停用后，引用
 * 在编辑界面被标为失效，而不是被静默改写。
 */
import type { Skill } from '../../shared/api/types';

/** 引用形式：`/name`，出现在行首或分隔符之后（避免匹配 URL 中的路径片段）。 */
const SKILL_REF_RE = /(^|[\s(（，,。;；:：])(\/([A-Za-z0-9][\w-]*))/g;

export interface SkillRefs {
  /** 已注册且启用的技能名 */
  known: string[];
  /** 已注册但已停用 */
  disabled: string[];
  /** 未注册（技能被删除或改名后的失效引用） */
  unknown: string[];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 解析正文中的技能引用（去重、保持出现顺序）。 */
export function parseSkillRefs(content: string): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  const re = new RegExp(SKILL_REF_RE.source, 'g');
  let match = re.exec(content);
  while (match !== null) {
    const name = match[3];
    if (name && !seen.has(name)) {
      seen.add(name);
      names.push(name);
    }
    match = re.exec(content);
  }
  return names;
}

/** 按真实技能列表校验引用；技能列表为空时全部归入 unknown（不猜测）。 */
export function validateSkillRefs(content: string, skills: Skill[]): SkillRefs {
  const byName = new Map(skills.map((skill) => [skill.name, skill]));
  const refs: SkillRefs = { known: [], disabled: [], unknown: [] };
  for (const name of parseSkillRefs(content)) {
    const skill = byName.get(name);
    if (!skill) refs.unknown.push(name);
    else if (skill.enabled === false) refs.disabled.push(name);
    else refs.known.push(name);
  }
  return refs;
}

/** 需要用户确认的失效引用（未注册 / 已停用），文案用“/name（原因）”。 */
export function invalidRefLabels(
  refs: SkillRefs,
  unknownLabel: string,
  disabledLabel: string,
): string[] {
  return [
    ...refs.unknown.map((name) => `/${name}（${unknownLabel}）`),
    ...refs.disabled.map((name) => `/${name}（${disabledLabel}）`),
  ];
}

/** 追加引用；已存在则不重复追加（幂等）。 */
export function insertSkillRef(content: string, name: string): string {
  if (!name) return content;
  if (parseSkillRefs(content).includes(name)) return content;
  const trimmed = content.trimEnd();
  return trimmed.length === 0 ? `/${name}` : `${trimmed} /${name}`;
}

/** 移除引用；不存在时原样返回。 */
export function removeSkillRef(content: string, name: string): string {
  if (!name) return content;
  const re = new RegExp(`(^|[\\s(（，,。;；:：])\\/${escapeRegExp(name)}(?![\\w-])`, 'g');
  return content
    .replace(re, '$1')
    .replace(/[ \t]{2,}/g, ' ')
    .trimEnd();
}


export interface TaskSkillHealth {
  totalRefs: number;
  known: string[];
  invalidLabels: string[];
  hasInvalid: boolean;
  skillsLoaded: boolean;
}

/**
 * 汇总单条定时任务正文的技能引用健康度（供任务列表页渲染失效引用告警徽标）。
 * 当 `skills` 为 `null`（IPC 尚未返回或不可用）时，`skillsLoaded=false` 且不误报 `hasInvalid`。
 */
export function summarizeTaskSkillHealth(
  content: string,
  skills: Skill[] | null,
  unknownLabel = '未注册',
  disabledLabel = '已停用',
): TaskSkillHealth {
  const refs = parseSkillRefs(content);
  if (skills === null) {
    return {
      totalRefs: refs.length,
      known: [],
      invalidLabels: [],
      hasInvalid: false,
      skillsLoaded: false,
    };
  }
  const validated = validateSkillRefs(content, skills);
  const invalidLabels = invalidRefLabels(validated, unknownLabel, disabledLabel);
  return {
    totalRefs: refs.length,
    known: validated.known,
    invalidLabels,
    hasInvalid: invalidLabels.length > 0,
    skillsLoaded: true,
  };
}
