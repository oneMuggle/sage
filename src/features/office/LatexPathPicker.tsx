import { useState } from 'react';

export interface LatexPathPickerProps {
  value: string;
  onChange: (value: string) => void;
  title: string;
  extensions: string[];
  placeholder?: string;
  testId: string;
  className?: string;
}

function hasExtension(name: string, extensions: string[]): boolean {
  const lower = name.toLowerCase();
  return extensions.some((extension) => lower.endsWith(`.${extension.toLowerCase()}`));
}

export function LatexPathPicker({
  value,
  onChange,
  title,
  extensions,
  placeholder,
  testId,
  className,
}: LatexPathPickerProps) {
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pickerAvailable =
    typeof window !== 'undefined' && Boolean(window.electronAPI?.selectFile);

  const handlePick = async () => {
    const picker = window.electronAPI?.selectFile;
    if (!picker) return;
    setError(null);
    try {
      const selected = await picker({
        title,
        filters: [{ name: title, extensions }],
      });
      if (selected) onChange(selected);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (!file) return;
    if (!hasExtension(file.name, extensions)) {
      setError(`不支持的文件类型：${file.name}`);
      return;
    }
    const filePath = (file as File & { path?: string }).path;
    if (!filePath) {
      setError('无法获取拖拽文件路径，请使用“选择”按钮');
      return;
    }
    setError(null);
    onChange(filePath);
  };

  return (
    <div className={`flex flex-col gap-1 ${className ?? ''}`}>
      <div
        className={`flex gap-2 rounded ${dragging ? 'ring-1 ring-accent' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(false);
        }}
        onDrop={handleDrop}
        data-testid={`${testId}-dropzone`}
      >
        <input
          className="min-w-0 flex-1 rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          data-testid={testId}
        />
        {pickerAvailable ? (
          <button
            type="button"
            className="rounded border border-border px-2 py-1 text-xs hover:bg-bg-hover"
            onClick={handlePick}
            data-testid={`${testId}-pick`}
          >
            选择
          </button>
        ) : null}
      </div>
      {error ? <span className="text-xs text-error">{error}</span> : null}
    </div>
  );
}
