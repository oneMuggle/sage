import React from 'react';

import SkillCard from './SkillCard';

interface Skill {
  name: string;
  description: string;
  triggers: string[];
  enabled: boolean;
  usageCount: number;
}

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
          usageCount={skill.usageCount}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
};

export default SkillList;
