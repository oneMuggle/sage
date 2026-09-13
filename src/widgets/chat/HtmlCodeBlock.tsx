// src/widgets/chat/HtmlCodeBlock.tsx
//
// P1 (UI 优化方案 2026-09-13): ```html 代码块的「源码 / 预览」切换。
// 模型输出的单文件 HTML 页面此前只能看源码 —— 预览走与 ArtifactViewer
// 同款的 sandbox iframe（allow-scripts、无 allow-same-origin，阻止跨域/
// 顶层导航/表单提交），HTML 里可能含有的脚本被隔离在 opaque origin 里，
// 拿不到应用 cookie/storage，主页面不受影响。

import { Eye, FileCode2 } from 'lucide-react';
import { useState } from 'react';

import { ShikiCodeBlock } from './ShikiCodeBlock';

type View = 'code' | 'preview';

export function HtmlCodeBlock({ code }: { code: string }) {
  const [view, setView] = useState<View>('code');

  return (
    <div className="my-2 rounded-md overflow-hidden border border-border" data-testid="html-code-block">
      {/* tab 栏配色对齐 ShikiCodeBlock 头部 (#282c34) */}
      <div className="flex items-center gap-1 px-2 py-1 bg-[#282c34] text-xs">
        <button
          type="button"
          onClick={() => setView('code')}
          className={
            'flex items-center gap-1 px-2 py-0.5 rounded transition-colors ' +
            (view === 'code'
              ? 'bg-white/10 text-white'
              : 'text-gray-400 hover:text-white hover:bg-white/5')
          }
          aria-pressed={view === 'code'}
        >
          <FileCode2 className="w-3.5 h-3.5" />
          源码
        </button>
        <button
          type="button"
          onClick={() => setView('preview')}
          className={
            'flex items-center gap-1 px-2 py-0.5 rounded transition-colors ' +
            (view === 'preview'
              ? 'bg-white/10 text-white'
              : 'text-gray-400 hover:text-white hover:bg-white/5')
          }
          aria-pressed={view === 'preview'}
        >
          <Eye className="w-3.5 h-3.5" />
          预览
        </button>
        <span className="ml-auto font-mono text-gray-400">html</span>
      </div>

      {view === 'code' ? (
        // 隐藏 ShikiCodeBlock 自带头部（语言标签/复制），tab 栏已承担该职责。
        // 耦合点: ShikiCodeBlock 根节点第一个 div 是头部栏。
        <div className="[&>div:first-child]:hidden [&>div]:my-0">
          <ShikiCodeBlock language="html">{code}</ShikiCodeBlock>
        </div>
      ) : (
        // sandbox 不含 allow-same-origin: 内容运行在 opaque origin，
        // 与 ArtifactViewer 的 HTML 产物预览同一防线（无 DOMPurify 需求）。
        <iframe
          sandbox="allow-scripts"
          srcDoc={code}
          title="HTML 预览"
          className="w-full h-96 bg-white border-0"
          data-testid="html-preview-frame"
        />
      )}
    </div>
  );
}
