import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { rulesApi, type RulesExportOptions } from '../../shared/api/rulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Checkbox } from '../../shared/ui/Checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';
import { RadioGroup, RadioGroupItem } from '../../shared/ui/RadioGroup';

import { downloadRulesText } from './rulesDownload';

export interface RulesExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectName: string;
}

type Format = 'json' | 'md' | 'agents';

interface Scope {
  constraints: boolean;
  docs: boolean;
  global: boolean;
  playbook: boolean;
}

const FORMATS = ['json', 'md', 'agents'] as const;

const FORMAT_LABEL_KEY: Record<Format, TranslationKey> = {
  json: 'rules.export.format.json',
  md: 'rules.export.format.md',
  agents: 'rules.export.format.agents',
};

const FORMAT_MIME: Record<Format, string> = {
  json: 'application/json;charset=utf-8',
  md: 'text/markdown;charset=utf-8',
  agents: 'text/plain;charset=utf-8',
};

const SCOPE_KEYS = ['constraints', 'docs', 'playbook'] as const;

const SCOPE_LABEL_KEY: Record<(typeof SCOPE_KEYS)[number], TranslationKey> = {
  constraints: 'rules.export.scope.constraints',
  docs: 'rules.export.scope.docs',
  playbook: 'rules.export.scope.playbook',
};

const DEFAULT_SCOPE: Scope = {
  constraints: true,
  docs: true,
  global: false,
  playbook: true,
};

function isFormat(value: string): value is Format {
  return (FORMATS as readonly string[]).includes(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function FormatSection({
  format,
  setFormat,
}: {
  format: Format;
  setFormat: (v: Format) => void;
}) {
  const { t } = useI18n();
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-ink">{t('rules.export.format.label')}</p>
      <RadioGroup
        value={format}
        onValueChange={(next) => {
          if (isFormat(next)) setFormat(next);
        }}
        data-testid="rules-export-format"
      >
        {FORMATS.map((key) => (
          <label key={key} className="flex items-start gap-2 py-1 text-sm">
            <RadioGroupItem value={key} data-testid={`rules-export-format-${key}`} />
            <span>{t(FORMAT_LABEL_KEY[key])}</span>
          </label>
        ))}
      </RadioGroup>
    </div>
  );
}

function ScopeSection({
  scope,
  toggleScope,
  projectName,
}: {
  scope: Scope;
  toggleScope: (key: keyof Scope, next: boolean) => void;
  projectName: string;
}) {
  const { t } = useI18n();
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-ink">{projectName}</p>
      <div className="space-y-2">
        {SCOPE_KEYS.map((key) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={scope[key]}
              onCheckedChange={(next) => toggleScope(key, Boolean(next))}
              data-testid={`rules-export-scope-${key}`}
            />
            <span>{t(SCOPE_LABEL_KEY[key])}</span>
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={scope.global}
            onCheckedChange={(next) => toggleScope('global', Boolean(next))}
            data-testid="rules-export-scope-global"
          />
          <span>{t('rules.export.scope.global')}</span>
        </label>
      </div>
      {scope.global ? (
        <p
          role="alert"
          className="mt-2 rounded border border-warning/50 bg-warning/10 p-2 text-xs text-warning"
          data-testid="rules-export-global-warning"
        >
          {t('rules.export.global_warning')}
        </p>
      ) : null}
    </div>
  );
}

function useExportState(projectId: string, t: (key: TranslationKey) => string, onOpenChange: (open: boolean) => void) {
  const [format, setFormat] = useState<Format>('json');
  const [scope, setScope] = useState<Scope>(DEFAULT_SCOPE);
  const [busy, setBusy] = useState(false);
  const toggleScope = useCallback((key: keyof Scope, next: boolean) => {
    setScope((prev) => ({ ...prev, [key]: next }));
  }, []);
  const handleExport = useCallback(async () => {
    setBusy(true);
    try {
      const options: RulesExportOptions = {
        format, includeConstraints: scope.constraints, includeDocs: scope.docs,
        includeGlobal: scope.global, includePlaybook: scope.playbook,
      };
      const result = await rulesApi.exportRules(projectId, options);
      downloadRulesText(result.filename, result.content, FORMAT_MIME[format]);
      toast.success(t('rules.export.done').replace('{filename}', result.filename));
      onOpenChange(false);
    } catch (error) {
      toast.error(t('rules.export.failed').replace('{message}', errorMessage(error)));
    } finally {
      setBusy(false);
    }
  }, [format, scope, projectId, t, onOpenChange]);
  return { format, setFormat, scope, toggleScope, busy, handleExport };
}

export function RulesExportDialog({
  open,
  onOpenChange,
  projectId,
  projectName,
}: RulesExportDialogProps) {
  const { t } = useI18n();
  const { format, setFormat, scope, toggleScope, busy, handleExport } =
    useExportState(projectId, t, onOpenChange);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('rules.export.title')}</DialogTitle>
          <DialogDescription>{t('rules.export.description')}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <FormatSection format={format} setFormat={setFormat} />
          <ScopeSection scope={scope} toggleScope={toggleScope} projectName={projectName} />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            {t('rules.editor.cancel')}
          </Button>
          <Button onClick={handleExport} disabled={busy} data-testid="rules-export-confirm">
            {busy ? t('rules.export.exporting') : t('rules.export.action')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
