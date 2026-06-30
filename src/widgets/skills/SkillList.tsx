import React from 'react';

import { type Skill } from '../../shared/api';

import SkillCard from './SkillCard';

interface SkillListProps {
  skills: Skill[];
  onToggle: (name: string, enabled: boolean) => void;
  // PR-A Task 5: 删除回调 — 透传给 SkillCard (builtin 内部不显示)
  onDelete?: (name: string) => void;
}

const SkillList: React.FC<SkillListProps> = ({ skills, onToggle, onDelete }) => {
  if (skills.length === 0) {
    return (
      <div className="text-center py-8">
        <p className="text-muted">暂无技能</p>
      </div>
    );
  }

  return (
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
        />
      ))}
    </div>
  );
};

export default SkillList;
