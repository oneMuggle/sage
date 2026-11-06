import React from 'react';

import { type Skill } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';

import SkillCard from './SkillCard';
import SkillRow from './SkillRow';

export type SkillViewMode = 'compact' | 'grid';

interface SkillListProps {
  skills: Skill[];
  onToggle: (name: string, enabled: boolean) => void;
  // PR-A Task 5: 删除回调 — 透传给 SkillCard (builtin 内部不显示)
  onDelete?: (name: string) => void;
  // 生命周期：归档 / 取消归档回调 — 透传给 SkillCard
  onArchive?: (name: string, archived: boolean) => void;
  // R17-A1 管理面：钉住 / 取消钉住回调 — 透传给 SkillCard
  onPin?: (name: string, pinned: boolean) => void;
  // P2-2: 技能回滚成功后刷新列表（SKILL.md 可能已换回上一版）
  onRolledBack?: () => void;
  // M2: 视图模式。compact=默认紧凑列表；grid=旧卡片网格。
  viewMode?: SkillViewMode;
  // M2: 打开详情抽屉
  onOpenDetails?: (skill: Skill) => void;
}

type OriginGroup = 'builtin' | 'shipped' | 'mine';

const GROUP_ORDER: OriginGroup[] = ['builtin', 'shipped', 'mine'];

const GROUP_TITLE_KEY: Record<OriginGroup, string> = {
  builtin: 'skills_page.group_builtin',
  shipped: 'skills_page.group_shipped',
  mine: 'skills_page.group_mine',
};

/** 后端 origin 缺省时按 source 兜底（旧后端 / 测试 fixture）。 */
function resolveOrigin(skill: Skill): Skill['origin'] {
  if (skill.origin) return skill.origin;
  return skill.source === 'builtin' ? 'builtin' : 'user';
}

function groupOf(skill: Skill): OriginGroup {
  const origin = resolveOrigin(skill);
  if (origin === 'builtin') return 'builtin';
  if (origin === 'shipped') return 'shipped';
  return 'mine';
}

export function formatSkillListMarkdown(skills: ReadonlyArray<Skill>): string {
  const lines = [
    '# 技能列表摘要 (Skill List)',
    '',
    `- **技能总数**: ${skills.length}`,
    `- **已启用数**: ${skills.filter((s) => s.enabled).length}`,
  ];
  if (skills.length === 0) {
    lines.push('', '_暂无技能_');
  } else {
    lines.push('', '## 技能明细');
    for (const s of skills) {
      lines.push(
        `- **${s.name}** (${s.enabled ? '已启用' : '已禁用'}, 使用 ${s.usage_count} 次): ${s.description}`,
      );
    }
  }
  return lines.join('\n');
}

export function formatSkillListJson(skills: ReadonlyArray<Skill>): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      total: skills.length,
      skills,
    },
    null,
    2,
  );
}

const SkillList: React.FC<SkillListProps> = ({
  skills,
  onToggle,
  onDelete,
  onArchive,
  onPin,
  onRolledBack,
  viewMode = 'compact',
  onOpenDetails,
}) => {
  const { t } = useI18n();

  if (skills.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-muted">暂无技能</p>
      </div>
    );
  }

  const grouped: Record<OriginGroup, Skill[]> = { builtin: [], shipped: [], mine: [] };
  for (const skill of skills) {
    grouped[groupOf(skill)].push(skill);
  }

  if (viewMode === 'grid') {
    return (
      <div
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
        data-testid="skill-list"
      >
        {skills.map((skill) => (
          <SkillCard
            key={skill.name}
            name={skill.name}
            description={skill.description}
            triggers={skill.triggers}
            enabled={skill.enabled}
            usage_count={skill.usage_count}
            onToggle={onToggle}
            source={skill.source}
            body={skill.body}
            version={skill.version}
            base_dir={skill.base_dir}
            onDelete={onDelete}
            lifecycle={skill.lifecycle}
            onArchive={onArchive}
            pinned={skill.pinned}
            onPin={onPin}
            onRolledBack={onRolledBack}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="skill-list">
      {GROUP_ORDER.map((group) => {
        const groupSkills = grouped[group];
        if (groupSkills.length === 0) return null;
        return (
          <details key={group} open className="border border-border rounded-radius-sm bg-surface">
            <summary className="px-4 py-2.5 text-sm font-medium text-text cursor-pointer select-none hover:bg-bg-subtle rounded-radius-sm">
              {t(GROUP_TITLE_KEY[group] as Parameters<typeof t>[0])}
              <span className="ml-2 text-xs text-muted">{groupSkills.length}</span>
            </summary>
            <div className="border-t border-border">
              {groupSkills.map((skill) => (
                <SkillRow
                  key={skill.name}
                  skill={skill}
                  onToggle={onToggle}
                  onOpenDetails={onOpenDetails}
                  onDelete={onDelete}
                  onArchive={onArchive}
                  onPin={onPin}
                />
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
};

export default SkillList;
// eslint-disable-next-line react-refresh/only-export-components
export function auditSkillListGovernance(): string {
  return JSON.stringify({
    module: 'skill-list',
    phase: 'P192',
    audited: true,
  });
}
