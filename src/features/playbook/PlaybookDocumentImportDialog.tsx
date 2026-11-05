/**
 * PlaybookDocumentImportDialog — 从 Word/PDF/Markdown 等文档导入 Playbook。
 *
 * 流程：选择文件 → base64 编码 → POST /playbooks/import/document → 预览 → 确认绑定。
 */
import { FileUp, Loader2 } from 'lucide-react';
import { useRef, useState } from 'react';

import { playbookApi } from '../../shared/api/playbookApi';
import type { PlaybookDocumentImportResult, PlaybookSpec } from '../../shared/api/playbookApi';
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

export interface PlaybookDocumentImportDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (spec: PlaybookSpec) => void;
}

const ACCEPTED_EXTENSIONS = '.docx,.pdf,.md,.pptx,.xlsx,.html,.txt';

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.split(',')[1] ?? '';
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function PlaybookDocumentImportDialog({
  open,
  onClose,
  onConfirm,
}: PlaybookDocumentImportDialogProps) {
  const { t, tf } = usePlaybookI18n();
  const [phase, setPhase] = useState<'select' | 'parsing' | 'preview'>('select');
  const [result, setResult] = useState<PlaybookDocumentImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = async (file: File) => {
    setError(null);
    setPhase('parsing');
    try {
      const contentBase64 = await fileToBase64(file);
      const importResult = await playbookApi.documentImport(file.name, contentBase64);
      setResult(importResult);
      setPhase('preview');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(tf('playbook.docImport.parseError', { message: msg }));
      setPhase('select');
    }
  };

  const handleConfirm = () => {
    if (result) {
      onConfirm(result.playbook);
      handleClose();
    }
  };

  const handleClose = () => {
    setPhase('select');
    setResult(null);
    setError(null);
    onClose();
  };

  const totalArtifacts =
    result?.playbook.stages.reduce((sum, stage) => sum + stage.artifacts.length, 0) ?? 0;
  const totalRules = result?.playbook.global_rules.length ?? 0;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('playbook.docImport.title')}</DialogTitle>
          <DialogDescription>{t('playbook.docImport.description')}</DialogDescription>
        </DialogHeader>

        {phase === 'select' && (
          <div className="flex flex-col items-center gap-3 py-6">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleFileSelect(file);
                event.target.value = '';
              }}
            />
            <Button
              variant="secondary"
              onClick={() => fileInputRef.current?.click()}
              data-testid="doc-import-file-picker"
            >
              <FileUp className="mr-2 h-4 w-4" />
              {t('playbook.docImport.selectFile')}
            </Button>
            {error && (
              <div role="status" className="text-xs text-destructive">
                {error}
              </div>
            )}
          </div>
        )}

        {phase === 'parsing' && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('playbook.docImport.parsing')}
          </div>
        )}

        {phase === 'preview' && result && (
          <div className="space-y-3">
            <div className="text-sm font-medium">
              {tf('playbook.docImport.previewTitle', { name: result.source_doc })}
            </div>
            {result.source === 'deterministic' && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-300">
                {t('playbook.docImport.llmFallback')}
              </div>
            )}
            <div className="max-h-64 space-y-2 overflow-y-auto rounded-md border border-border p-3 text-xs">
              <div>
                <div className="font-medium text-foreground">
                  {tf('playbook.docImport.stages', { count: result.playbook.stages.length })}
                </div>
                <ul className="mt-1 space-y-0.5 text-muted-foreground">
                  {result.playbook.stages.map((stage) => (
                    <li key={stage.id}>
                      {stage.order}. {stage.label}
                      {stage.objective ? ` — ${stage.objective}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
              {totalArtifacts > 0 && (
                <div>
                  <div className="font-medium text-foreground">
                    {tf('playbook.docImport.artifacts', { count: totalArtifacts })}
                  </div>
                  <ul className="mt-1 space-y-0.5 text-muted-foreground">
                    {result.playbook.stages.flatMap((stage) =>
                      stage.artifacts.map((artifact) => (
                        <li key={artifact.id}>
                          [{stage.label}] {artifact.label}
                        </li>
                      )),
                    )}
                  </ul>
                </div>
              )}
              {totalRules > 0 && (
                <div>
                  <div className="font-medium text-foreground">
                    {tf('playbook.docImport.rules', { count: totalRules })}
                  </div>
                  <ul className="mt-1 space-y-0.5 text-muted-foreground">
                    {result.playbook.global_rules.map((rule) => (
                      <li key={String(rule.id ?? '')}>{String(rule.content ?? '')}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          {phase === 'preview' ? (
            <>
              <Button variant="secondary" onClick={handleClose}>
                {t('playbook.docImport.cancel')}
              </Button>
              <Button variant="primary" onClick={handleConfirm} data-testid="doc-import-confirm">
                {t('playbook.docImport.confirm')}
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={handleClose}>
              {t('playbook.docImport.close')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PlaybookDocumentImportDialog;
