import { RefreshCw, RotateCw, Upload } from 'lucide-react';
import React, { useCallback, useState, useEffect } from 'react';
import { toast } from 'sonner';

import { skillsApi, type Skill } from '../shared/api';
import { ErrorState } from '../shared/ui/ErrorState';
import { LoadingState } from '../shared/ui/LoadingState';
import { RetryButton } from '../shared/ui/RetryButton';
import { SkillList } from '../widgets/skills';

const Skills: React.FC = () => {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [rescanLoading, setRescanLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);

  const loadSkills = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await skillsApi.list();
      setSkills(data);
    } catch {
      setError('加载技能列表失败');
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  // PR-B: 自动刷新 toggle — 默认关闭,用户主动启用
  useEffect(() => {
    if (!autoRefresh) return;
    const id = window.setInterval(() => {
      loadSkills();
    }, 10000);
    return () => window.clearInterval(id);
    // loadSkills 是 useCallback 包装的, deps 应包含它
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh]);

  const handleToggle = async (name: string, enabled: boolean) => {
    setSkills((prev) => prev.map((skill) => (skill.name === name ? { ...skill, enabled } : skill)));
    try {
      await skillsApi.toggle(name, enabled);
    } catch {
      setSkills((prev) =>
        prev.map((skill) => (skill.name === name ? { ...skill, enabled: !enabled } : skill)),
      );
      setError('切换失败');
    }
  };

  // PR-A Task 5: 删除技能 (optimistic + rollback + toast)
  const handleDelete = async (name: string) => {
    if (!window.confirm(`确定删除 '${name}'?此操作不可撤销。`)) return;
    // optimistic: 先从 list 里过滤掉
    const prev = skills;
    setSkills(skills.filter((s) => s.name !== name));
    try {
      await skillsApi.delete(name);
      toast.success(`已删除 ${name}`);
    } catch (error) {
      // 失败: 回滚 + 提示
      setSkills(prev);
      toast.error(`删除失败: ${(error as Error).message}`);
    }
  };

  // PR-C Task 6: 重扫磁盘按钮
  const handleRescan = async () => {
    setRescanLoading(true);
    try {
      const result = await skillsApi.rescan();
      if (result.total_loaded > 0) {
        toast.success(`已加载 ${result.total_loaded} 个技能`);
      }
      // rescan 的 `skipped` 字段当前始终为 `[]` (loader API 只返 count tuple 不返 detail;
      // 见 inproc.py::rescan_skill_mds docstring + spec §10 已知限制)。保留 `if` 是为未来
      // loader API 扩展后立即启用 toast.warning,无需改前端。
      if (result.skipped.length > 0) {
        toast.warning(`跳过 ${result.skipped.length} 个`);
      }
      await loadSkills();
    } catch (err) {
      toast.error(`重扫失败: ${(err as Error).message}`);
    } finally {
      setRescanLoading(false);
    }
  };

  // PR-C Task 6: 导入 SKILL.md 按钮
  const handleImport = async () => {
    const paths = await window.electronAPI?.skills?.pickSkillFiles();
    if (!paths || paths.length === 0) return;
    setImportLoading(true);
    try {
      const result = await skillsApi.importFiles(paths);
      if (result.imported.length > 0) {
        toast.success(`已导入 ${result.imported.length} 个技能`);
      }
      if (result.skipped.length > 0) {
        const reasons = result.skipped.map((s) => `${s.name}(${s.reason})`).join(', ');
        toast.warning(`跳过 ${result.skipped.length} 个: ${reasons}`);
      }
      await loadSkills();
    } catch (err) {
      toast.error(`导入失败: ${(err as Error).message}`);
    } finally {
      setImportLoading(false);
    }
  };

  const filteredSkills = skills.filter(
    (skill) =>
      skill.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      skill.description.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  const enabledCount = skills.filter((s) => s.enabled).length;
  const totalUsage = skills.reduce((sum, s) => sum + s.usage_count, 0);

  // 首次加载且失败：整页错误态 + 重试
  if (loading && skills.length === 0 && error) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-[18px] font-semibold text-text">技能</h2>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <ErrorState
            title="技能加载失败"
            message={error}
            onRetry={loadSkills}
            retryLabel="重新加载"
          />
        </div>
      </div>
    );
  }

  if (loading && skills.length === 0) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-[18px] font-semibold text-text">技能</h2>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <LoadingState label="加载技能中..." />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 页面头部 */}
      <div className="h-12 flex items-center justify-between px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">技能</h2>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted cursor-pointer">
            <input
              type="checkbox"
              role="switch"
              aria-checked={autoRefresh}
              aria-label="自动刷新"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="w-4 h-4 accent-primary"
            />
            自动刷新 (10s)
          </label>
          <button
            type="button"
            onClick={loadSkills}
            disabled={loading}
            aria-label="刷新技能列表"
            title="刷新技能列表"
            className="p-1.5 rounded text-muted hover:text-text hover:bg-bg-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={handleRescan}
            disabled={rescanLoading}
            aria-label="重扫磁盘"
            title="重扫磁盘"
            className="p-1.5 rounded text-muted hover:text-text hover:bg-bg-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <RotateCw className={`w-4 h-4 ${rescanLoading ? 'animate-spin' : ''}`} />
          </button>
          <button
            type="button"
            onClick={handleImport}
            disabled={importLoading}
            aria-label="导入 SKILL.md"
            title="导入 SKILL.md"
            className="p-1.5 rounded text-muted hover:text-text hover:bg-bg-subtle transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <Upload className={`w-4 h-4 ${importLoading ? 'animate-pulse' : ''}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {error && (
          <div className="mb-4 p-3 rounded-radius-sm bg-error/10 text-error text-sm flex items-center justify-between">
            <span>{error}</span>
            <div className="flex items-center gap-2">
              <RetryButton onRetry={loadSkills} label="重试" className="!px-2 !py-1 !text-xs" />
              <button onClick={() => setError(null)} className="text-error hover:underline">
                关闭
              </button>
            </div>
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
        <SkillList skills={filteredSkills} onToggle={handleToggle} onDelete={handleDelete} />
      </div>
    </div>
  );
};

export default Skills;
