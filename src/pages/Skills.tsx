import React, { useState, useEffect } from 'react';

import SkillList from '../components/skills/SkillList';
import { skillsApi, type Skill } from '../lib/api';

const Skills: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const loadSkills = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await skillsApi.list()
        if (!cancelled) setSkills(data)
      } catch (err) {
        if (!cancelled) {
          setError('加载技能列表失败')
          setSkills([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadSkills()
    return () => { cancelled = true }
  }, [])

  const handleToggle = async (name: string, enabled: boolean) => {
    setSkills((prev) =>
      prev.map((skill) =>
        skill.name === name ? { ...skill, enabled } : skill
      )
    )
    try {
      await skillsApi.toggle(name, enabled)
    } catch {
      setSkills((prev) =>
        prev.map((skill) =>
          skill.name === name ? { ...skill, enabled: !enabled } : skill
        )
      )
      setError('切换失败')
    }
  }

  const filteredSkills = skills.filter((skill) =>
    skill.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    skill.description.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const enabledCount = skills.filter((s) => s.enabled).length
  const totalUsage = skills.reduce((sum, s) => sum + s.usageCount, 0)

  if (loading) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-[18px] font-semibold text-text">技能</h2>
        </div>
        <div className="flex-1 flex items-center justify-center text-muted text-sm">加载中...</div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 页面头部 */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">技能</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {error && (
          <div className="mb-4 p-3 rounded-radius-sm bg-error/10 text-error text-sm">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 text-error hover:underline"
            >
              关闭
            </button>
          </div>
        )}

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
