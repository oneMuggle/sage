// Sources View - 源文件管理视图
import { FolderPlus, Upload } from 'lucide-react';
import { useState } from 'react';

import { mockSourcesTree } from '../../entities/wiki/mock-data';
import { SourcesTree } from './SourcesTree';

export function SourcesView() {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  // 模拟操作处理
  const handleIngest = (path: string) => {
    // 模拟导入操作
    alert(`模拟导入: ${path}`);
  };

  const handleDelete = (path: string) => {
    if (confirm(`确定删除 ${path}?`)) {
      // 模拟删除操作
      alert(`模拟删除: ${path}`);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-surface">
        <div>
          <h2 className="text-lg font-semibold text-text">来源文件</h2>
          <p className="text-xs text-muted mt-0.5">管理原始资料文档，支持导入到 Wiki</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors">
            <FolderPlus className="h-3 w-3" />
            新建文件夹
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors">
            <Upload className="h-4 w-4" />
            导入文件
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File tree */}
        <div className="w-72 border-r border-border overflow-y-auto bg-surface">
          <div className="px-3 py-2 border-b border-border">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              raw/sources
            </span>
          </div>
          <SourcesTree
            nodes={mockSourcesTree}
            onFileClick={setSelectedFile}
            onIngest={handleIngest}
            onDelete={handleDelete}
          />
        </div>

        {/* Preview/Info panel */}
        <div className="flex-1 overflow-y-auto">
          {selectedFile ? (
            <div className="p-6">
              <h3 className="text-base font-semibold text-text mb-2">
                {selectedFile.split('/').pop()}
              </h3>
              <p className="text-xs text-muted mb-4">{selectedFile}</p>

              <div className="rounded-lg border border-border bg-surface p-4 mb-4">
                <h4 className="text-sm font-medium text-text mb-2">文件信息</h4>
                <dl className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <dt className="text-muted">路径:</dt>
                    <dd className="text-text">{selectedFile}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">大小:</dt>
                    <dd className="text-text">2.3 MB</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">修改时间:</dt>
                    <dd className="text-text">2024-01-20 14:30</dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-lg border border-border bg-surface p-4">
                <h4 className="text-sm font-medium text-text mb-2">预览</h4>
                <p className="text-xs text-muted italic">（文件预览功能待实现）</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted">
              <FolderPlus className="h-12 w-12 mb-2 opacity-30" />
              <p className="text-sm">选择左侧文件查看详情</p>
              <p className="text-xs mt-1">或导入新文件到 Wiki</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
