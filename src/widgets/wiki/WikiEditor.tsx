// Wiki Editor - split-pane markdown editor/viewer
import { Eye, Pencil, Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useWikiStore } from '../../entities/wiki/store';

import { MarkdownPreview } from './MarkdownPreview';

export function WikiEditor() {
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const fileContent = useWikiStore((s) => s.fileContent);
  const saveFile = useWikiStore((s) => s.saveFile);
  const isLoading = useWikiStore((s) => s.isLoading);
  const [editContent, setEditContent] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  // Sync edit content when file changes
  useEffect(() => {
    setEditContent(fileContent);
    setIsEditing(false);
  }, [fileContent]);

  const handleSave = async () => {
    if (!selectedFile) return;
    await saveFile(selectedFile, editContent);
    setIsEditing(false);
  };

  if (!selectedFile) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">
        选择一个文件以查看或编辑
      </div>
    );
  }

  if (isLoading && !fileContent) {
    return (
      <div className="flex h-full items-center justify-center text-muted text-sm">加载中...</div>
    );
  }

  const fileName = selectedFile.split('/').pop() || selectedFile;

  return (
    <div className="flex h-full flex-col">
      {/* File header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2 bg-surface">
        <span className="text-sm font-medium text-text truncate">{fileName}</span>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => {
              if (!isEditing) {
                setEditContent(fileContent);
                setIsEditing(true);
              } else {
                handleSave();
              }
            }}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors"
          >
            {isEditing ? (
              <>
                <Save className="h-3 w-3" /> 保存
              </>
            ) : (
              <>
                <Pencil className="h-3 w-3" /> 编辑
              </>
            )}
          </button>
          {!isEditing && (
            <button
              onClick={() => setIsEditing(false)}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors"
            >
              <Eye className="h-3 w-3" /> 预览
            </button>
          )}
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 min-h-0 overflow-auto">
        {isEditing ? (
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="w-full h-full p-4 font-mono text-sm bg-surface text-text resize-none focus:outline-none"
            spellCheck={false}
          />
        ) : (
          <MarkdownPreview content={fileContent} />
        )}
      </div>
    </div>
  );
}
