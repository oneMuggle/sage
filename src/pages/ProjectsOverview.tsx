import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { projectApi, type ProjectSummary, type ProjectType } from '../shared/api';
import type { ProjectStatus } from '../shared/api/projectApiTypes';
import { useStore } from '../shared/lib/store';
import { WorkbenchProjectList } from '../widgets/sidebar/sections/WorkbenchProjectList';

import { filterAndSortProjects, type OverviewFilters } from './projects/projectOverviewUtils';

const TYPES: Array<ProjectType | 'all'> = ['all', 'coding', 'research', 'business', 'personal'];
const DEFAULT_FILTERS: OverviewFilters = { q: '', type: 'all', status: 'active', sort: 'recent' };

interface OverviewHeaderProps {
  filters: OverviewFilters;
  onFiltersChange: (update: (prev: OverviewFilters) => OverviewFilters) => void;
  selectedCount: number;
  onArchive: () => void;
}

function OverviewHeader({
  filters,
  onFiltersChange,
  selectedCount,
  onArchive,
}: OverviewHeaderProps): JSX.Element {
  return (
    <header className="flex items-center gap-2 border-b px-4 py-3">
      <input
        data-testid="projects-overview-search"
        className="input flex-1"
        placeholder="搜索项目名称、路径或描述"
        value={filters.q}
        onChange={(e) => onFiltersChange((f) => ({ ...f, q: e.target.value }))}
      />
      <select
        data-testid="projects-overview-type"
        value={filters.type}
        onChange={(e) =>
          onFiltersChange((f) => ({ ...f, type: e.target.value as ProjectType | 'all' }))
        }
      >
        {TYPES.map((t) => (
          <option key={t} value={t}>
            {t === 'all' ? '全部类型' : t}
          </option>
        ))}
      </select>
      <div className="flex gap-1">
        {(['active', 'archived'] as ProjectStatus[]).map((s) => (
          <button
            key={s}
            data-testid={`projects-overview-status-${s}`}
            aria-pressed={filters.status === s}
            onClick={() => onFiltersChange((f) => ({ ...f, status: s }))}
          >
            {s === 'active' ? '活跃' : '归档'}
          </button>
        ))}
      </div>
      <select
        data-testid="projects-overview-sort"
        value={filters.sort}
        onChange={(e) =>
          onFiltersChange((f) => ({ ...f, sort: e.target.value as OverviewFilters['sort'] }))
        }
      >
        <option value="recent">最近活动</option>
        <option value="name">名称</option>
        <option value="stage">阶段</option>
      </select>
      <button
        data-testid="projects-overview-archive"
        disabled={selectedCount === 0}
        onClick={onArchive}
      >
        归档所选（{selectedCount}）
      </button>
    </header>
  );
}

interface OverviewRowsProps {
  projects: ProjectSummary[];
  selected: string[];
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
}

function OverviewRows({ projects, selected, onToggle, onOpen }: OverviewRowsProps): JSX.Element {
  if (projects.length === 0) {
    return (
      <p data-testid="projects-overview-empty" className="text-sm text-muted-foreground">
        没有匹配的项目。调整搜索或筛选条件试试。
      </p>
    );
  }
  return (
    <ul data-testid="projects-overview-rows" className="space-y-1">
      {projects.map((project) => (
        <li
          key={project.id}
          className="flex items-center gap-2"
          data-testid={`projects-overview-row-${project.id}`}
        >
          <input
            type="checkbox"
            data-testid={`projects-overview-select-${project.id}`}
            checked={selected.includes(project.id)}
            onChange={() => onToggle(project.id)}
          />
          <button className="flex-1 text-left" onClick={() => onOpen(project.id)}>
            {project.name}
          </button>
          <span className="text-xs text-muted-foreground">{project.projectStage ?? '—'}</span>
        </li>
      ))}
    </ul>
  );
}

export function ProjectsOverview(): JSX.Element {
  const navigate = useNavigate();
  const setCurrentSessionId = useStore((s) => s.setCurrentSessionId);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [filters, setFilters] = useState<OverviewFilters>(DEFAULT_FILTERS);
  const [selected, setSelected] = useState<string[]>([]);

  const load = useCallback(async () => {
    setProjects(await projectApi.list());
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const visible = useMemo(() => filterAndSortProjects(projects, filters), [projects, filters]);

  const toggleSelected = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const archiveSelected = async () => {
    for (const id of selected) await projectApi.setProjectStatus(id, 'archived');
    setSelected([]);
    await load();
  };

  return (
    <div className="flex h-full flex-col overflow-hidden" data-testid="projects-overview">
      <OverviewHeader
        filters={filters}
        onFiltersChange={setFilters}
        selectedCount={selected.length}
        onArchive={() => void archiveSelected()}
      />

      <div className="flex-1 overflow-auto px-4 py-3">
        <OverviewRows
          projects={visible}
          selected={selected}
          onToggle={toggleSelected}
          onOpen={(id) => navigate(`/projects/governance/${id}`)}
        />
      </div>

      <section className="border-t px-4 py-3">
        <WorkbenchProjectList
          onOpenSession={(sessionId) => {
            setCurrentSessionId(sessionId);
            navigate('/chat');
          }}
        />
      </section>
    </div>
  );
}
