import { Search } from 'lucide-react';
import { useState, useMemo } from 'react';

import { Input } from '../../shared/ui/Input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../shared/ui/Select/Select';

export interface ProjectOption {
  id: string;
  name: string;
  path: string;
  sessionId: string | null;
}

export interface ProjectPickerProps {
  value: string | null;
  onChange: (projectId: string | null) => void;
  projects: ProjectOption[];
}

export function ProjectPicker({ value, onChange, projects }: ProjectPickerProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const filteredProjects = useMemo(() => {
    if (!searchQuery.trim()) return projects;
    const query = searchQuery.toLowerCase();
    return projects.filter(
      (p) => p.name.toLowerCase().includes(query) || p.path.toLowerCase().includes(query),
    );
  }, [projects, searchQuery]);

  const selectedProject = projects.find((p) => p.id === value);

  return (
    <Select value={value ?? 'none'} onValueChange={(val: string) => onChange(val === 'none' ? null : val)}>
      <SelectTrigger aria-label="选择项目" className="w-48">
        <SelectValue placeholder="选择项目">
          {selectedProject ? selectedProject.name : '选择项目'}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        <div className="p-2 border-b border-border">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
            <Input
              placeholder="搜索项目..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 h-8 text-sm"
            />
          </div>
        </div>
        <SelectItem value="none">不绑定项目</SelectItem>
        {filteredProjects.length > 0 ? (
          filteredProjects.map((project) => (
            <SelectItem key={project.id} value={project.id}>
              {project.name}
            </SelectItem>
          ))
        ) : (
          <div className="px-2 py-1.5 text-sm text-muted">
            {projects.length === 0 ? '暂无可用项目' : '未找到匹配的项目'}
          </div>
        )}
      </SelectContent>
    </Select>
  );
}
