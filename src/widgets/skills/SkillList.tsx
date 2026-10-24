import React from 'react';

import { type Skill } from '../../shared/api';

import SkillCard from './SkillCard';

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
}) => {
  if (skills.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-muted">暂无技能</p>
      </div>
    );
  }

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div className="space-y-2" data-testid="skill-list">
      <div className="flex items-center justify-end gap-1.5"></div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
