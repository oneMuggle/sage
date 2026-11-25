import { useCallback, useEffect, useRef, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficeTemplateMeta } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

import { WordStyleTemplateLibrary } from './WordStyleTemplateLibrary';

export interface TemplateLibraryProps {
  workspacePath: string;
  selectedId: string | null;
  onSelect: (template: OfficeTemplateMeta) => void;
}

type LoadState = 'loading' | 'ready' | 'error';

const TEMPLATE_SOURCE_KEYS = {
  builtin: 'office.template.source.builtin',
  workspace: 'office.template.source.workspace',
} as const;

export function TemplateLibrary({ workspacePath, selectedId, onSelect }: TemplateLibraryProps) {
  const { t } = useI18n();
  const [templates, setTemplates] = useState<OfficeTemplateMeta[]>([]);
  const [state, setState] = useState<LoadState>('loading');
  const [thumbnails, setThumbnails] = useState<Record<string, string>>({});
  const requestIdRef = useRef(0);

  const load = useCallback(async () => {
    const requestId = (requestIdRef.current += 1);
    setState('loading');
    try {
      const res = await officeApi.listTemplates(workspacePath);
      if (requestId !== requestIdRef.current) return;
      setTemplates(res.templates);
      setState('ready');
    } catch {
      if (requestId !== requestIdRef.current) return;
      setTemplates([]);
      setState('error');
    }
  }, [workspacePath]);

  useEffect(() => {
    void load();
    // Invalidate any in-flight load when the path changes or the panel unmounts.
    return () => {
      requestIdRef.current += 1;
    };
  }, [load]);

  // M7: template first-page thumbnails. Decorative — failures just leave the
  // entry without an image, so each request is swallowed independently.
  useEffect(() => {
    if (state !== 'ready' || templates.length === 0) return;
    let cancelled = false;
    for (const template of templates) {
      void officeApi
        .templateThumbnail({
          workspace_path: workspacePath,
          ...(template.source === 'builtin'
            ? { template_id: template.id }
            : { workspace_template: template.filename }),
        })
        .then((res) => {
          if (cancelled || !res.ok || !res.data_url) return;
          setThumbnails((prev) => ({ ...prev, [template.id]: res.data_url as string }));
        })
        .catch(() => undefined);
    }
    return () => {
      cancelled = true;
    };
  }, [state, templates, workspacePath]);

  return (
    <div data-testid="office-template-library" className="space-y-2">
      <WordStyleTemplateLibrary workspacePath={workspacePath} />

      <h3 className="text-xs font-medium text-text-secondary">
        {t('office.generate.workspace.templatePick')}
      </h3>

      {state === 'loading' ? (
        <p className="text-xs text-muted" data-testid="office-template-library-loading">
          {t('office.template.loading')}
        </p>
      ) : null}

      {state === 'error' ? (
        <div className="flex items-center gap-2" data-testid="office-template-library-error">
          <span className="text-xs text-error">{t('office.template.loadFailed')}</span>
          <button
            type="button"
            data-testid="office-template-library-retry"
            className="text-xs text-primary hover:underline"
            onClick={() => void load()}
          >
            {t('office.template.retry')}
          </button>
        </div>
      ) : null}

      {state === 'ready' && templates.length === 0 ? (
        <p className="text-xs text-muted" data-testid="office-template-library-empty">
          {t('office.template.empty')}
        </p>
      ) : null}

      {state === 'ready' && templates.length > 0 ? (
        <ul className="space-y-1">
          {templates.map((template) => (
            <li key={`${template.source}-${template.id}`}>
              <button
                type="button"
                data-testid={`office-template-library-item-${template.id}`}
                aria-pressed={selectedId === template.id}
                className={`w-full rounded border px-3 py-2 text-left ${
                  selectedId === template.id
                    ? 'border-primary bg-primary/10'
                    : 'border-border bg-surface hover:bg-bg-hover'
                }`}
                onClick={() => onSelect(template)}
              >
                {thumbnails[template.id] ? (
                  <img
                    src={thumbnails[template.id]}
                    alt=""
                    data-testid={`office-template-library-thumb-${template.id}`}
                    className="mb-1.5 h-24 w-full rounded object-cover"
                  />
                ) : null}
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm text-text">{template.name}</span>
                  <span
                    className="text-xs text-muted"
                    data-testid={`office-template-library-source-${template.id}`}
                  >
                    {t(TEMPLATE_SOURCE_KEYS[template.source])}
                  </span>
                </span>
                {template.description ? (
                  <span className="mt-0.5 block text-xs text-muted">{template.description}</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
