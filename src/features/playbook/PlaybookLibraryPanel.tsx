/**
 * PlaybookLibraryPanel — 全局规程库管理（列表 / 详情 / 导出 / 删除）。
 *
 * 库条目与项目解耦；删除条目不会影响已绑定项目的规程快照。
 */
import { Download, Library, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { playbookApi } from '../../shared/api/playbookApi';
import type { PlaybookLibraryDetail, PlaybookLibraryItem } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { downloadPlaybookText } from './playbookDownload';

export interface PlaybookLibraryPanelProps {
  onClose: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function PlaybookLibraryPanel({ onClose }: PlaybookLibraryPanelProps) {
  const [items, setItems] = useState<PlaybookLibraryItem[]>([]);
  const [detail, setDetail] = useState<PlaybookLibraryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await playbookApi.listLibrary();
      setItems(list);
      setDetail((prev) => (prev && list.some((item) => item.id === prev.item.id) ? prev : null));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleSelect = (item: PlaybookLibraryItem) => {
    if (detail?.item.id === item.id) {
      setDetail(null);
      return;
    }
    setBusy('detail');
    setError(null);
    void (async () => {
      try {
        setDetail(await playbookApi.getLibraryItem(item.id));
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(null);
      }
    })();
  };

  const handleExport = (item: PlaybookLibraryItem) => {
    setBusy('export');
    setError(null);
    setNotice(null);
    void (async () => {
      try {
        const result = await playbookApi.exportLibrary(item.id);
        const text =
          typeof result.content === 'string'
            ? result.content
            : JSON.stringify(result.content, null, 2);
        downloadPlaybookText(result.filename, text, 'application/json');
        setNotice('已导出：' + result.filename);
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(null);
      }
    })();
  };

  const handleDelete = (item: PlaybookLibraryItem) => {
    if (!window.confirm(`删除规程库条目「${item.name}」？已绑定项目不受影响。`)) {
      return;
    }
    setBusy('delete');
    setError(null);
    setNotice(null);
    void (async () => {
      try {
        await playbookApi.deleteLibrary(item.id);
        setNotice('已删除：' + item.name);
        if (detail?.item.id === item.id) setDetail(null);
        await refresh();
      } catch (err) {
        setError(errorMessage(err));
      } finally {
        setBusy(null);
      }
    })();
  };

  return (
    <div
      className="space-y-2 rounded-md border border-border p-3 text-xs"
      data-testid="playbook-library-panel"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 font-medium text-foreground">
          <Library className="h-3.5 w-3.5" />
          全局规程库
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={onClose}
          data-testid="playbook-library-close"
        >
          <X className="mr-1 h-3.5 w-3.5" />
          关闭
        </Button>
      </div>

      {loading ? (
        <div className="text-muted-foreground">加载中…</div>
      ) : items.length === 0 ? (
        <div className="text-muted-foreground" data-testid="playbook-library-empty">
          规程库为空。绑定规程后点击「保存到规程库」即可收藏，或导入时勾选「保存到规程库」。
        </div>
      ) : (
        <div className="space-y-1">
          {items.map((item) => (
            <div key={item.id} className="rounded-md border border-border">
              <div className="flex flex-wrap items-center justify-between gap-2 px-2 py-1.5">
                <button
                  type="button"
                  className="min-w-0 text-left text-muted-foreground hover:text-foreground"
                  onClick={() => handleSelect(item)}
                  data-testid={`playbook-library-item-${item.id}`}
                >
                  <span className="font-medium text-foreground">{item.name}</span>
                  <span className="ml-1.5 text-ui-2xs opacity-70">
                    {item.stage_count} 阶段 · {item.source} ·{' '}
                    {new Date(item.created_at).toLocaleDateString()}
                  </span>
                </button>
                <span className="flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleExport(item)}
                    disabled={busy === 'export'}
                    data-testid={`playbook-library-export-${item.id}`}
                  >
                    <Download className="mr-1 h-3.5 w-3.5" />
                    导出
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleDelete(item)}
                    disabled={busy === 'delete'}
                    data-testid={`playbook-library-delete-${item.id}`}
                  >
                    <Trash2 className="mr-1 h-3.5 w-3.5" />
                    删除
                  </Button>
                </span>
              </div>
              {detail?.item.id === item.id && (
                <div
                  className="space-y-1 border-t border-border px-2 py-1.5"
                  data-testid="playbook-library-detail"
                >
                  {detail.playbook.description && (
                    <div className="text-muted-foreground">{detail.playbook.description}</div>
                  )}
                  <div className="text-muted-foreground">
                    目录：
                    {detail.playbook.directory_layout.map((entry) => entry.path).join('、') || '无'}
                  </div>
                  <div className="text-muted-foreground">
                    阶段：
                    {detail.playbook.stages
                      .map((stage) => `${stage.label}（${stage.artifacts.length} 产物）`)
                      .join('、')}
                  </div>
                  <div className="text-ui-2xs opacity-70">
                    spec hash: {detail.item.spec_hash.slice(0, 12)}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {(error || notice) && (
        <div className={`text-xs ${error ? 'text-destructive' : 'text-primary'}`}>
          {error || notice}
        </div>
      )}
    </div>
  );
}

export default PlaybookLibraryPanel;
