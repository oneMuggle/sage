/**
 * CodeMirror 6 主题编辑器
 *
 * 封装 @uiw/react-codemirror，提供 CSS 语言高亮 + 受控 value/onChange。
 * 暗色主题通过 Tailwind 类名适配。
 */

import { css } from '@codemirror/lang-css';
import CodeMirror from '@uiw/react-codemirror';
import type { Extension } from '@codemirror/state';
import { useMemo } from 'react';

interface CodeMirrorThemeEditorProps {
  value: string;
  onChange: (css: string) => void;
  /** 校验错误提示（来自 themeCssValidator.validate） */
  error?: string;
  readOnly?: boolean;
}

export function CodeMirrorThemeEditor({
  value,
  onChange,
  error,
  readOnly = false,
}: CodeMirrorThemeEditorProps) {
  const extensions: Extension[] = useMemo(() => [css()], []);

  return (
    <div
      className="border border-border rounded-radius-md overflow-hidden"
      data-testid="cm-editor"
      data-error={error || undefined}
    >
      <CodeMirror
        value={value}
        height="320px"
        extensions={extensions}
        onChange={onChange}
        readOnly={readOnly}
        placeholder=":root { --bg-base: #ffffff; }"
        basicSetup={{
          lineNumbers: true,
          highlightActiveLine: true,
          foldGutter: true,
        }}
      />
    </div>
  );
}
