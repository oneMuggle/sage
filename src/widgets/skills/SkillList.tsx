import React from 'react';

import { type Skill } from '../../lib/api';

import SkillCard from './SkillCard';

interface SkillListProps {
  skills: Skill[];
  onToggle: (name: string, enabled: boolean) => void;
}

const SkillList: React.FC<SkillListProps> = ({ skills, onToggle }) => {
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
        />
      ))}
    </div>
  );
};

export default SkillList;
