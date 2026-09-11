import { useState } from 'react';

export interface ExportButtonProps {
  includePrompts: boolean;
  includeHostname: boolean;
}

const ERROR_MESSAGES: Record<string, string> = {
  dialog_cancelled: '已取消',
  backend_unreachable: '无法连接 Sage 后端,请确认应用已启动',
  zip_generation_failed: '诊断包生成失败,请查看后端日志',
  write_failed: '无法写入文件,请检查路径权限和磁盘空间',
};

export function ExportButton({ includePrompts, includeHostname }: ExportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleClick = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await window.electronAPI?.diagnostic?.exportBundle({
        includePrompts,
        includeHostname,
      });
      if (!result) {
        setMessage('诊断接口不可用,请确认应用版本');
        return;
      }
      if (result.ok) {
        setMessage(`已导出到 ${result.path}`);
      } else {
        const msg = ERROR_MESSAGES[result.code] ?? `导出失败: ${result.error}`;
        setMessage(msg);
      }
    } catch (e) {
      setMessage(`导出异常: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button
        onClick={handleClick}
        disabled={busy}
        className="px-3 py-1 rounded border"
        data-testid="diagnostic-export-btn"
      >
        {busy ? '导出中…' : '导出诊断包…'}
      </button>
      {message && (
        <p className="text-sm mt-1" data-testid="diagnostic-message">
          {message}
        </p>
      )}
    </div>
  );
}
