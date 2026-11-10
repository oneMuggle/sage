import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import type { OverviewFilters } from '../features/project-type/projectFilters';
import { projectApi, type ProjectType } from '../shared/api';
import type { ProjectStatus } from '../shared/api/projectApiTypes';
import { useStore } from '../shared/lib/store';
import { Button } from '../shared/ui/Button';
import { WorkbenchProjectList } from '../widgets/sidebar/sections/WorkbenchProjectList';

const TYPES: Array<{ value: ProjectType | 'all'; label: string }> = [
  { value: 'all', label: '全部类型' },
  { value: 'coding', label: '编码' },
  { value: 'research', label: '科研' },
  { value: 'business', label: '商务' },
  { value: 'personal', label: '个人' },
];

const DEFAULT_FILTERS: OverviewFilters = { q: '', type: 'all', status: 'active', sort: 'recent' };

const SELECT_CLASS =
  'rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground';

export function ProjectsOverview(): JSX.Element {
  const navigate = useNavigate();
  const setCurrentSessionId = useStore((s) => s.setCurrentSessionId);
  const [filters, setFilters] = useState<OverviewFilters>(DEFAULT_FILTERS);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [addSignal, setAddSignal] = useState(0);

  const toggleSelected = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelected([]);
  };

  const archiveSelected = async () => {
    for (const id of selected) await projectApi.setProjectStatus(id, 'archived');
    setSelected([]);
    setSelectMode(false);
    setRefreshKey((key) => key + 1);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="projects-overview">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[960px] px-6 py-6">
          <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-lg font-semibold text-foreground">项目</h1>
              <p className="mt-0.5 text-xs text-muted-foreground">
                管理项目规则、资料与会话；点击项目进入工作台。
              </p>
            </div>
            <Button
              size="sm"
              onClick={() => setAddSignal((n) => n + 1)}
              data-testid="projects-overview-new"
            >
              新建项目
            </Button>
          </header>

          <div className="mb-3 flex flex-wrap items-center gap-2" role="search">
            <input
              data-testid="projects-overview-search"
              className="input min-w-[220px] flex-1"
              placeholder="搜索项目名称、路径或描述"
              value={filters.q}
              onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            />
            <select
              data-testid="projects-overview-type"
              className={SELECT_CLASS}
              value={filters.type}
              onChange={(e) =>
                setFilters((f) => ({ ...f, type: e.target.value as ProjectType | 'all' }))
              }
            >
              {TYPES.map((type) => (
                <option key={type.value} value={type.value}>
                  {type.label}
                </option>
              ))}
            </select>
            <div className="flex overflow-hidden rounded-md border border-input">
              {(['active', 'archived'] as ProjectStatus[]).map((status) => (
                <button
                  key={status}
                  type="button"
                  data-testid={`projects-overview-status-${status}`}
                  aria-pressed={filters.status === status}
                  onClick={() => setFilters((f) => ({ ...f, status }))}
                  className={`px-2.5 py-1.5 text-xs transition-colors ${
                    filters.status === status
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {status === 'active' ? '活跃' : '归档'}
                </button>
              ))}
            </div>
            <select
              data-testid="projects-overview-sort"
              className={SELECT_CLASS}
              value={filters.sort}
              onChange={(e) =>
                setFilters((f) => ({ ...f, sort: e.target.value as OverviewFilters['sort'] }))
              }
            >
              <option value="recent">最近活动</option>
              <option value="name">名称</option>
              <option value="stage">阶段</option>
            </select>
            {selectMode ? (
              <>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={exitSelectMode}
                  data-testid="projects-overview-select-cancel"
                >
                  取消选择
                </Button>
                <Button
                  size="sm"
                  onClick={() => void archiveSelected()}
                  disabled={selected.length === 0}
                  data-testid="projects-overview-archive"
                >
                  归档所选（{selected.length}）
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSelectMode(true)}
                data-testid="projects-overview-select-mode"
              >
                批量管理
              </Button>
            )}
          </div>

          <div data-testid="projects-overview-rows">
            <WorkbenchProjectList
              showHeader={false}
              filters={filters}
              selectable={selectMode}
              selectedIds={selected}
              onToggleSelect={toggleSelected}
              refreshKey={refreshKey}
              addSignal={addSignal}
              onOpenSession={(sessionId) => {
                setCurrentSessionId(sessionId);
                navigate('/chat');
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
