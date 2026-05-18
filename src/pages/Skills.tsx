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
    <div className="container mx-auto px-4 py-8">
      {/* 页面标题 */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-800">技能商店</h1>
        <p className="text-gray-600 mt-2">
          管理和启用你的 AI 技能
        </p>
      </div>

      {/* 统计信息 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">已启用技能</p>
          <p className="text-2xl font-bold text-blue-600">
            {enabledCount} / {skills.length}
          </p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">总使用次数</p>
          <p className="text-2xl font-bold text-green-600">{totalUsage}</p>
        </div>
        <div className="bg-white rounded-lg shadow p-4">
          <p className="text-sm text-gray-500">技能类型</p>
          <p className="text-2xl font-bold text-purple-600">4 种</p>
        </div>
      </div>

      {/* 搜索框 */}
      <div className="mb-6">
        <input
          type="text"
          placeholder="搜索技能..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full max-w-md px-4 py-2 border border-gray-300 rounded-lg 
                   focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* 技能列表 */}
      <SkillList skills={filteredSkills} onToggle={handleToggle} />

      {/* 技能使用提示 */}
      <div className="mt-8 bg-blue-50 rounded-lg p-4">
        <h3 className="font-semibold text-blue-800 mb-2">💡 如何使用技能？</h3>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>• 在聊天框中输入触发词即可自动调用对应技能</li>
          <li>• 例如：输入"帮我搜索 Python 教程"会触发搜索技能</li>
          <li>• 可以在下方开关来启用/禁用特定技能</li>
        </ul>
      </div>
    </div>
  );
};

export default Skills;
