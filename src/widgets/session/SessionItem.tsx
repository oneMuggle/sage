import { Download, GitBranch, Pin, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { downloadHtmlFile, sessionApi } from '../../shared/api/sessionApi';
import { useI18n } from '../../shared/lib/i18n';
import type { Session } from '../../shared/lib/store';
import { TwoStepDelete } from '../sidebar/TwoStepDelete';

interface SessionItemProps {
  session: Session;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

export function SessionItem({ session, isActive, onSelect, onDelete }: SessionItemProps) {
  const { t } = useI18n();
  const [exporting, setExporting] = useState(false);

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm('确定要删除这个会话吗？')) {
      onDelete();
    }
  };

  // U18: 导出完整会话为自包含 HTML(离线可开,含工具调用/diff/思考过程)
  const handleExport = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (exporting) {
      return;
    }
    setExporting(true);
    try {
      const result = await sessionApi.exportHtml(session.id);
      downloadHtmlFile(result.html, result.filename);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      alert(t('session.export_failed').replace('{message}', message));
    } finally {
      setExporting(false);
    }
  };
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      data-testid="session-item"
      data-session-id={session.id}
      aria-label={`选择会话 ${session.title}`}
      aria-pressed={isActive}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={`
        group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer
        transition-colors focus:outline-none focus:ring-2 focus:ring-primary
        ${isActive ? 'bg-primary/10 text-primary' : 'hover:bg-bg-hover'}
      `}
    >
      {/* 会话标题 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium flex items-center gap-1 min-w-0">
          {/* M4: fork 徽标 — session.fork_root 存在时显示，tooltip 带源会话 id */}
          {session.fork_root && (
            <span
              data-testid="fork-badge"
              aria-label={t('session.fork_badge')}
              title={`${t('session.fork_badge')} · fork_root: ${session.fork_root}`}
              className="inline-flex flex-shrink-0"
            >
              <GitBranch className="w-3 h-3 text-muted" />
            </span>
          )}
          <span className="truncate">{session.title}</span>
        </p>
        <p className="text-xs text-muted">{new Date(session.updated_at).toLocaleDateString()}</p>
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {session.is_pinned && <Pin className="w-4 h-4 text-primary" />}
        {/* U18: 导出完整会话为自包含 HTML */}
        <button
          data-testid="export-session"
          onClick={handleExport}
          disabled={exporting}
          className="p-1 rounded hover:bg-primary/10 text-muted hover:text-primary disabled:opacity-50"
          title={exporting ? t('session.export_html_exporting') : t('session.export_html')}
          aria-label={t('session.export_html')}
        >
          <Download className="w-4 h-4" />
        </button>
        {/* U12: 两步式确认删除 — 不弹 modal，armed 后二次点击生效 */}
        <TwoStepDelete
          data-testid="delete-session"
          onConfirm={onDelete}
          label={t('common.delete')}
          armedLabel={t('common.delete_confirm')}
          className="p-1"
        />
      </div>
    </div>
  );
}
