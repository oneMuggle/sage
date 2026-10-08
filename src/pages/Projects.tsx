import { useNavigate } from 'react-router-dom';

import { useI18n } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { ProjectSection } from '../widgets/sidebar/sections/ProjectSection';

/** A spacious view of the same project APIs, not a second project registry. */
export function Projects() {
  const navigate = useNavigate();
  const { locale } = useI18n();
  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-4" data-testid="project-workbench">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-ui-xl font-semibold">
          {locale === 'en' ? 'Project workbench' : '项目工作台'}
        </h1>
        <p className="text-ui-sm text-text-secondary mt-1 mb-4">
          {locale === 'en'
            ? 'Expand a project to manage goals, instructions, sources and conversations. The folder binding still controls file access.'
            : '展开项目管理目标、指令、资料和会话。项目提供上下文，目录绑定与授权仍决定文件访问范围。'}
        </p>
        <ProjectSection
          collapsed={false}
          onToggleCollapsed={() => undefined}
          presentation="workbench"
          onOpenSession={(sessionId) => {
            useStore.getState().setCurrentSessionId(sessionId);
            navigate('/chat');
          }}
        />
        <div className="flex gap-2 mt-4">
          <button
            type="button"
            onClick={() => navigate('/welcome')}
            className="px-3 py-2 border border-ui-border rounded text-ui-base"
          >
            {locale === 'en' ? 'New deliverable' : '开始新的交付任务'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/office')}
            className="px-3 py-2 border border-ui-border rounded text-ui-base"
          >
            {locale === 'en' ? 'Open documents and reviews' : '查看文档与验收'}
          </button>
        </div>
      </div>
    </div>
  );
}
