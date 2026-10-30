// Right Panel - 右侧面板（文件预览 + 研究面板）
import { X } from 'lucide-react';
import { useEffect, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { useResearchStore } from '../../entities/wiki/research-store';
import { useWikiStore } from '../../entities/wiki/store';
import { useSettings } from '../../features/manage-settings/useSettings';
import { settingsClient } from '../../shared/api/settingsClient';
import { parseTavilyKey } from '../../shared/lib/searchConfig';

import { MarkdownPreview } from './MarkdownPreview';
import { WikiResearchPanel } from './WikiResearchPanel';

export function RightPanel() {
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const fileContent = useWikiStore((s) => s.fileContent);
  const project = useWikiStore((s) => s.project);
  const researchPanelOpen = useResearchStore((s) => s.panelOpen);
  const settings = useSettings();
  const [tavilyKey, setTavilyKey] = useState('');

  useEffect(() => {
    let cancelled = false;
    void settingsClient
      .getPreference('search_config')
      .then((raw) => {
        if (!cancelled) setTavilyKey(parseTavilyKey(raw));
      })
      .catch(() => {
        // 读不到搜索配置时保持空值，面板会提示去设置。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const endpoint = settings
    ? resolveEndpoint(settings.settings.modelSelections.chatModel, settings.settings.endpoints)
    : undefined;
  const model = settings?.settings.modelSelections.chatModel.modelId ?? '';



  // 如果没有选中文件且研究面板未打开，不显示右侧面板
  if (!selectedFile && !researchPanelOpen) {
    return null;
  }

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-border bg-surface">
      {/* File preview section */}
      {selectedFile && (
        <div
          className={`flex-1 overflow-hidden ${researchPanelOpen ? 'border-b border-border' : ''}`}
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              预览: {selectedFile.split('/').pop()}
            </span>
            <div className="flex items-center gap-1">
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <MarkdownPreview content={fileContent} />
          </div>
        </div>
      )}

      {/* Research panel section */}
      {researchPanelOpen && (
        <div className={`${selectedFile ? 'h-1/2' : 'flex-1'} overflow-hidden`}>
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              深度研究
            </span>
            <button
              onClick={() => useResearchStore.getState().setPanelOpen(false)}
              className="text-muted hover:text-text transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {project && endpoint && model ? (
              <WikiResearchPanel
                projectPath={project.path}
                llmBaseUrl={endpoint.baseUrl}
                llmApiKey={endpoint.apiKey}
                llmModel={model}
                searchProvider="tavily"
                searchApiKey={tavilyKey}
                disabledReason={
                  tavilyKey ? null : '需要在「设置 → 网络」配置 Tavily API Key'
                }
              />
            ) : (
              <p className="text-sm text-muted p-4">请先选择项目并配置聊天模型</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
