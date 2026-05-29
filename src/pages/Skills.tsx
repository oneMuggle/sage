import React, { useState, useEffect } from 'react';
import SkillList from '../components/skills/SkillList';

interface Skill {
  name: string;
  description: string;
  triggers: string[];
  enabled: boolean;
  usageCount: number;
}

// 模拟技能数据（实际应从后端 API 获取）
const mockSkills: Skill[] = [
  {
    name: 'search',
    description: '搜索网络信息并整理结果',
    triggers: ['搜索', '查一下', '帮我找', 'search'],
    enabled: true,
    usageCount: 42,
  },
  {
    name: 'writer',
    description: '帮助用户撰写文章、文案、报告等文本内容',
    triggers: ['写', '帮我写', '创作', 'write'],
    enabled: true,
    usageCount: 28,
  },
  {
    name: 'coder',
    description: '帮助编写、调试、解释代码',
    triggers: ['写代码', '帮我写程序', 'code'],
    enabled: true,
    usageCount: 35,
  },
  {
    name: 'travel',
    description: '规划旅行行程、推荐景点餐厅',
    triggers: ['旅行', '旅游', '行程', 'travel'],
    enabled: false,
    usageCount: 10,
  },
];

const Skills: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>(mockSkills);
  const [searchTerm, setSearchTerm] = useState('');

  // 模拟从后端加载技能数据
  useEffect(() => {
    // TODO: 从后端 API 加载真实数据
    // const loadSkills = async () => {
    //   const response = await fetch('/api/skills');
    //   const data = await response.json();
    //   setSkills(data);
    // };
    // loadSkills();
  }, []);

  const handleToggle = (name: string, enabled: boolean) => {
    setSkills((prev) =>
      prev.map((skill) =>
        skill.name === name ? { ...skill, enabled } : skill
      )
    );
    // TODO: 同步到后端
    console.log(`技能 ${name} 已${enabled ? '启用' : '禁用'}`);
  };

  const filteredSkills = skills.filter((skill) =>
    skill.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    skill.description.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const enabledCount = skills.filter((s) => s.enabled).length;
  const totalUsage = skills.reduce((sum, s) => sum + s.usageCount, 0);

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 页面头部 */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">技能</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {/* 统计信息 */}
        <div className="flex gap-3 mb-5">
          <div className="flex-1 p-3.5 border border-border rounded-radius-sm bg-surface">
            <p className="text-xs text-muted">已启用技能</p>
            <p className="text-xl font-bold font-mono text-primary mt-1">
              {enabledCount} / {skills.length}
            </p>
          </div>
          <div className="flex-1 p-3.5 border border-border rounded-radius-sm bg-surface">
            <p className="text-xs text-muted">总使用次数</p>
            <p className="text-xl font-bold font-mono text-success mt-1">{totalUsage}</p>
          </div>
        </div>

        {/* 搜索框 */}
        <div className="mb-4">
          <input
            type="text"
            placeholder="搜索技能..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full max-w-[320px] px-3 py-1.5 border border-border rounded-radius-sm text-sm bg-surface text-text"
          />
        </div>

        {/* 技能列表 */}
        <SkillList skills={filteredSkills} onToggle={handleToggle} />
      </div>
    </div>
  );
};

export default Skills;
