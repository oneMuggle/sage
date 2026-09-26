/**
 * WorkspaceInfoSection — 侧边栏工作区信息展示组件
 *
 * 显示当前工作区的关键信息：
 * - 项目名称和路径
 * - Git 分支和状态
 * - 最近修改的文件
 * - 文件统计
 *
 * Author: Claude
 * Date: 2026-09-26
 */

import { FileText, Folder, GitBranch, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import {
  workspaceInfoApi,
  type WorkspaceInfo,
  type RecentFile,
} from '../../../shared/api/workspaceInfoApi';
import { useI18n } from '../../../shared/lib/i18n';
import { formatRelativeTime } from '../../../shared/lib/utils';
import { SiderSection } from '../SiderSection';

interface WorkspaceInfoSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  workspacePath?: string;
}

export function WorkspaceInfoSection({
  collapsed,
  onToggleCollapsed,
  workspacePath,
}: WorkspaceInfoSectionProps) {
  const { t } = useI18n();
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInfo = useCallback(async () => {
    if (!workspacePath) return;

    setLoading(true);
    setError(null);

    try {
      const data = await workspaceInfoApi.getInfo(workspacePath);
      setInfo(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workspace info');
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    void loadInfo();
  }, [loadInfo]);

  return (
    <SiderSection
      sectionKey="workspace-info"
      label={t('workspace.info.title')}
      icon={Folder}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      render={() => (
        <div className="flex flex-col gap-2 px-2 py-1" data-testid="workspace-info-section">
          {loading && (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="w-4 h-4 animate-spin text-muted" />
            </div>
          )}

          {error && <div className="text-[11px] text-error px-2 py-1 italic">{error}</div>}

          {!loading && !error && info && (
            <>
              {/* Project Info */}
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <Folder className="w-3.5 h-3.5 text-muted flex-shrink-0" />
                  <span className="text-xs font-medium text-text truncate">{info.projectName}</span>
                </div>
                <div className="text-[10px] text-muted truncate pl-5.5">{info.workspacePath}</div>
              </div>

              {/* Git Info */}
              {info.gitBranch && (
                <div className="flex items-center gap-2 pt-1">
                  <GitBranch className="w-3.5 h-3.5 text-muted flex-shrink-0" />
                  <span className="text-[11px] text-text">{info.gitBranch}</span>
                  {info.gitStatus && (
                    <span
                      className={[
                        'text-[10px] px-1.5 py-0.5 rounded-full',
                        info.gitStatus === 'clean'
                          ? 'bg-success/10 text-success'
                          : 'bg-warning/10 text-warning',
                      ].join(' ')}
                    >
                      {info.gitStatus}
                    </span>
                  )}
                  {(info.gitAhead > 0 || info.gitBehind > 0) && (
                    <span className="text-[10px] text-muted">
                      {info.gitAhead > 0 && `↑${info.gitAhead}`}
                      {info.gitBehind > 0 && ` ↓${info.gitBehind}`}
                    </span>
                  )}
                </div>
              )}

              {/* File Stats */}
              <div className="flex items-center gap-4 pt-1 text-[10px] text-muted">
                <span>{info.totalFiles} files</span>
                {info.lastActivity && (
                  <span>活跃于 {formatRelativeTime(new Date(info.lastActivity).getTime())}</span>
                )}
              </div>

              {/* Recent Files */}
              {info.recentFiles.length > 0 && (
                <div className="pt-2 border-t border-border/50">
                  <div className="text-[10px] text-muted font-medium mb-1">最近修改</div>
                  <ul className="flex flex-col gap-0.5">
                    {info.recentFiles.slice(0, 5).map((file) => (
                      <RecentFileItem key={file.path} file={file} />
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}

          {!workspacePath && (
            <div className="text-[11px] text-muted px-2 py-1 italic">未选择工作区</div>
          )}
        </div>
      )}
    />
  );
}

/** Recent file list item */
function RecentFileItem({ file }: { file: RecentFile }) {
  return (
    <li className="group flex items-center gap-2 px-1 py-0.5 rounded-radius-sm hover:bg-bg-hover">
      <FileText className="w-3 h-3 text-muted flex-shrink-0" />
      <span className="text-[11px] text-text truncate flex-1">{file.name}</span>
      <span className="text-[10px] text-muted flex-shrink-0">
        {formatRelativeTime(new Date(file.modified).getTime())}
      </span>
    </li>
  );
}
