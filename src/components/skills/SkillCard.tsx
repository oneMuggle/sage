import React from 'react';

interface SkillCardProps {
  name: string;
  description: string;
  triggers: string[];
  enabled: boolean;
  usageCount: number;
  onToggle: (name: string, enabled: boolean) => void;
}

const SkillCard: React.FC<SkillCardProps> = ({
  name,
  description,
  triggers,
  enabled,
  usageCount,
  onToggle,
}) => {
  return (
    <div className={`bg-white rounded-lg shadow-md p-4 border-2 transition-all ${
      enabled ? 'border-blue-500' : 'border-gray-200 opacity-75'
    }`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-800">{name}</h3>
          <p className="text-sm text-gray-600 mt-1">{description}</p>
          
          {/* 触发词 */}
          <div className="flex flex-wrap gap-1 mt-2">
            {triggers.map((trigger, index) => (
              <span
                key={index}
                className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full"
              >
                {trigger}
              </span>
            ))}
          </div>
          
          {/* 使用统计 */}
          <p className="text-xs text-gray-400 mt-2">
            已使用 {usageCount} 次
          </p>
        </div>
        
        {/* 开关 */}
        <label className="relative inline-flex items-center cursor-pointer ml-4">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={enabled}
            onChange={(e) => onToggle(name, e.target.checked)}
          />
          <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 
                       peer-focus:ring-blue-300 rounded-full peer 
                       peer-checked:after:translate-x-full peer-checked:after:border-white 
                       after:content-[''] after:absolute after:top-[2px] after:left-[2px] 
                       after:bg-white after:border-gray-300 after:border after:rounded-full 
                       after:h-5 after:w-5 after:transition-all 
                       peer-checked:bg-blue-500"></div>
        </label>
      </div>
    </div>
  );
};

export default SkillCard;
