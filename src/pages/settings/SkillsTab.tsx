/**
 * Settings - Skills Tab (T-3/T-4)
 *
 * 提供技能脚本执行开关（fail-closed，缺省关闭）与技能目录配置。
 * 脚本执行开关是两层闸口的第一道：用户显式授权后才允许 SKILL.md 中的脚本分发。
 *
 * 写入走 ``useConfirmedPreference``（保存确认 + 失败回滚 + 错误可见），
 * 与 MemoryKnowledgeTab / ToolsConnectionsTab 一致：保存失败对用户可见、可重试，
 * 而不是静默丢弃后 UI 仍显示新值。
 *
 * @see backend/skills/skill_md/script_policy.py — 读取口径
 * @see backend/adapters/out/skill/inproc.py — 闸口串联
 */

import { useEffect, useState } from 'react';

import { PreferenceSaveStatus } from '../../features/manage-settings/PreferenceSaveStatus';
import { useConfirmedPreference } from '../../features/manage-settings/useConfirmedPreference';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow, Toggle } from './components';

export interface SkillsTabAuditInput {
  allow_skill_scripts: boolean;
  skills_dir: string;
}

export function formatSkillsTabAuditSnapshot(input: SkillsTabAuditInput): string {
  return [
    '# 技能设置审计快照',
    `- 允许执行技能脚本: ${input.allow_skill_scripts ? '开启' : '关闭'}`,
    `- 技能目录: ${input.skills_dir || '缺省 (~/.sage/skills)'}`,
  ].join('\n');
}

export function formatSkillsTabAuditJson(input: SkillsTabAuditInput): string {
  return JSON.stringify(
    {
      allow_skill_scripts: input.allow_skill_scripts,
      skills_dir: input.skills_dir || '',
    },
    null,
    2,
  );
}

type SaveStatus = 'loading' | 'idle' | 'saving' | 'saved' | 'error';

/**
 * T-3: 技能脚本执行开关（fail-closed，缺省关闭）。
 *
 * 用户必须显式开启此开关，SKILL.md 中的脚本（Bash/PowerShell 等）才可被分发执行。
 * 开关状态持久化到后端 preferences 表（key: allow_skill_scripts）。
 *
 * 两层闸口设计：
 * - 第一道：本开关（用户显式授权，fail-closed）
 * - 第二道：权限执行器（模式矩阵，workspace_write/full_access 等）
 *
 * 任一不过即拒绝。
 */
function SkillScriptExecutionRow({
  enabled,
  loaded,
  status,
  onChange,
}: {
  enabled: boolean;
  loaded: boolean;
  status: SaveStatus;
  onChange: (next: boolean) => void;
}): JSX.Element {
  const { t } = useI18n();

  return (
    <SettingRow
      label={t('settings.skills.allow_script_execution.label')}
      desc={t('settings.skills.allow_script_execution.desc')}
      anchor="allow_skill_scripts"
    >
      <Toggle
        value={enabled}
        onChange={onChange}
        disabled={!loaded || status === 'saving'}
        testId="settings-skill-script-toggle"
      />
    </SettingRow>
  );
}

/**
 * T-4a: 技能目录配置（缺省 = ~/.sage/skills）。
 *
 * 用户可指定自定义目录存放 SKILL.md 文件。输入用本地草稿，失焦 / 回车时才提交一次
 * —— 逐键写会把 "~/my/skill" 这类中间态落到后端。
 */
function SkillsDirectoryRow({
  dir,
  loaded,
  status,
  onCommit,
}: {
  dir: string;
  loaded: boolean;
  status: SaveStatus;
  onCommit: (next: string) => void;
}): JSX.Element {
  const { t } = useI18n();
  const [draft, setDraft] = useState<string | null>(null);

  // 保存确认后丢弃草稿，回落到已确认值；失败时保留草稿 + 错误提示 + 重试。
  useEffect(() => {
    if (draft !== null && draft.trim() === dir) setDraft(null);
  }, [draft, dir]);

  const commit = (): void => {
    if (draft === null) return;
    const next = draft.trim();
    if (next === dir) {
      setDraft(null);
      return;
    }
    onCommit(next);
  };

  return (
    <SettingRow
      label={t('settings.skills.directory.label')}
      desc={t('settings.skills.directory.desc')}
      anchor="skills_dir"
    >
      <input
        type="text"
        value={draft ?? dir}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
        disabled={!loaded || status === 'saving'}
        placeholder="~/.sage/skills"
        className="w-64 px-2 py-1 text-xs border border-border rounded bg-surface text-text"
        data-testid="settings-skills-dir-input"
      />
    </SettingRow>
  );
}

export function SkillsTab(): JSX.Element {
  const [copiedAudit, setCopiedAudit] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  const scriptPreference = useConfirmedPreference({
    key: 'allow_skill_scripts',
    initial: false,
    // 仅 "1" 视为开启，其余一律关闭（fail-closed）
    parse: (value) => value === '1',
    serialize: (value: boolean) => (value ? '1' : '0'),
  });
  const dirPreference = useConfirmedPreference({
    key: 'skills_dir',
    initial: '',
    category: 'general',
    parse: (value) => value ?? '',
    serialize: (value: string) => value,
  });

  /* v8 ignore start */
  const handleCopyAudit = async () => {
    setCopiedAudit(true);
    await navigator.clipboard?.writeText(
      formatSkillsTabAuditSnapshot({
        allow_skill_scripts: scriptPreference.value,
        skills_dir: dirPreference.value,
      }),
    );
  };

  const handleCopyJson = async () => {
    setCopiedJson(true);
    await navigator.clipboard?.writeText(
      formatSkillsTabAuditJson({
        allow_skill_scripts: scriptPreference.value,
        skills_dir: dirPreference.value,
      }),
    );
  };
  /* v8 ignore stop */

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <span
          data-testid="skills-tab-copy-audit"
          onClick={() => void handleCopyAudit()}
          title="复制技能设置审计快照"
          className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text cursor-pointer select-none"
        >
          {copiedAudit ? '已复制快照' : '复制快照'}
        </span>
        <span
          data-testid="skills-tab-copy-json"
          onClick={() => void handleCopyJson()}
          title="复制技能设置审计 JSON"
          className="px-2 py-0.5 text-xs rounded border border-border text-muted hover:text-text cursor-pointer select-none"
        >
          {copiedJson ? '已复制 JSON' : 'JSON'}
        </span>
      </div>
      <SkillScriptExecutionRow
        enabled={scriptPreference.value}
        loaded={scriptPreference.loaded}
        status={scriptPreference.status}
        onChange={(next) => {
          if (scriptPreference.status !== 'saving') scriptPreference.update(next);
        }}
      />
      <PreferenceSaveStatus status={scriptPreference.status} reload={scriptPreference.reload} />
      <SkillsDirectoryRow
        dir={dirPreference.value}
        loaded={dirPreference.loaded}
        status={dirPreference.status}
        onCommit={(next) => {
          if (dirPreference.status !== 'saving') dirPreference.update(next);
        }}
      />
      <PreferenceSaveStatus status={dirPreference.status} reload={dirPreference.reload} />
    </div>
  );
}
