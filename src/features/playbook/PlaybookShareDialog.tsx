/**
 * PlaybookShareDialog — 为规程库条目生成分享链接。
 *
 * 流程：点击分享 → 生成带 token 的 URL → 复制到剪贴板 → 展示有效期。
 */
import { Check, Copy, Link2, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { playbookApi } from '../../shared/api/playbookApi';
import type { PlaybookShareLink } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookShareDialogProps {
  open: boolean;
  libraryId: string | null;
  playbookName?: string;
  onClose: () => void;
}

/** 前端使用 HashRouter，分享链接需带 `#` 前缀才能直接打开落地页。 */
function absoluteUrl(sharePath: string): string {
  if (/^https?:\/\//i.test(sharePath)) return sharePath;
  return `${window.location.origin}/#${sharePath.startsWith('/') ? sharePath : `/${sharePath}`}`;
}

export function PlaybookShareDialog({
  open,
  libraryId,
  playbookName,
  onClose,
}: PlaybookShareDialogProps) {
  const { t, tf } = usePlaybookI18n();
  const [link, setLink] = useState<PlaybookShareLink | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !libraryId) {
      setLink(null);
      setCopied(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const result = await playbookApi.createShareLink(libraryId);
        if (!cancelled) setLink(result);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, libraryId]);

  const handleCopy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard?.writeText(absoluteUrl(link.share_url));
      setCopied(true);
    } catch {
      setError(t('playbook.share.copyFailed'));
    }
  };

  const expiresLabel = link ? new Date(link.expires_at).toLocaleDateString() : '';

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('playbook.share.title')}</DialogTitle>
          <DialogDescription>
            {playbookName ?? tf('playbook.share.description')}
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('playbook.share.generating')}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2">
              <Link2 className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span
                className="min-w-0 flex-1 break-all text-xs text-foreground"
                data-testid="playbook-share-url"
              >
                {link ? absoluteUrl(link.share_url) : ''}
              </span>
            </div>
            {link && (
              <div className="text-xs text-muted-foreground">
                {tf('playbook.share.expiresAt', { date: expiresLabel })}
              </div>
            )}
            {error && (
              <div role="status" className="text-xs text-destructive">
                {error}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            {t('playbook.share.close')}
          </Button>
          <Button
            variant="primary"
            onClick={handleCopy}
            disabled={!link || loading}
            data-testid="playbook-share-copy"
          >
            {copied ? (
              <Check className="mr-1 h-3.5 w-3.5" />
            ) : (
              <Copy className="mr-1 h-3.5 w-3.5" />
            )}
            {copied ? t('playbook.share.copied') : t('playbook.share.copy')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PlaybookShareDialog;
