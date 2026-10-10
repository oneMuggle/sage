import type {
  OfficeDocType,
  OfficeTemplateMeta,
  OfficeTemplatePlaceholder,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export type TemplateModeType = Exclude<OfficeDocType, 'pdf'>;
export type TemplateLoadState = 'idle' | 'loading' | 'ready' | 'error';

interface OfficeTemplatePickerProps {
  type: TemplateModeType;
  templates: OfficeTemplateMeta[];
  templateLoad: TemplateLoadState;
  selectedTemplate: OfficeTemplateMeta | null;
  templateData: Record<string, string>;
  thumbnails: Record<string, string>;
  thumbnailLoading: boolean;
  inputClass: string;
  onRetryLoad: () => void;
  onPickTemplate: (tpl: OfficeTemplateMeta) => void;
  onChangePlaceholder: (name: string, value: string) => void;
}

export function OfficeTemplatePicker({
  type,
  templates,
  templateLoad,
  selectedTemplate,
  templateData,
  thumbnails,
  thumbnailLoading,
  inputClass,
  onRetryLoad,
  onPickTemplate,
  onChangePlaceholder,
}: OfficeTemplatePickerProps) {
  const { t } = useI18n();

  const renderPlaceholderField = (ph: OfficeTemplatePlaceholder) => {
    const value = templateData[ph.name] ?? '';
    if (ph.type === 'image') {
      return (
        <div key={ph.name} data-testid={`office-template-field-${ph.name}`}>
          <label className="block text-xs text-muted mb-1">{ph.name}</label>
          <p className="text-xs text-muted bg-bg-subtle border border-border rounded px-2 py-1.5">
            {t('office.template.hint.image')}
          </p>
        </div>
      );
    }
    const isLongForm = ph.type === 'table' || ph.type === 'rich_text';
    return (
      <div key={ph.name} data-testid={`office-template-field-${ph.name}`}>
        <label className="block text-xs text-muted mb-1">{ph.name}</label>
        {isLongForm ? (
          <textarea
            value={value}
            onChange={(e) => onChangePlaceholder(ph.name, e.target.value)}
            rows={3}
            className={inputClass}
            data-testid={`office-template-input-${ph.name}`}
          />
        ) : (
          <input
            type="text"
            value={value}
            onChange={(e) => onChangePlaceholder(ph.name, e.target.value)}
            placeholder={ph.type === 'date' ? t('office.template.hint.date') : undefined}
            className={inputClass}
            data-testid={`office-template-input-${ph.name}`}
          />
        )}
        {(ph.type === 'table' || ph.type === 'rich_text') && (
          <p className="text-xs text-muted mt-0.5">{t('office.template.hint.rich')}</p>
        )}
        {ph.type === 'date' && (
          <p className="text-xs text-muted mt-0.5">{t('office.template.hint.date')}</p>
        )}
        {ph.description && <p className="text-xs text-muted mt-0.5">{ph.description}</p>}
      </div>
    );
  };

  const visibleTemplates = templates.filter((tpl) => tpl.doc_type === type);
  return (
    <div className="space-y-2" data-testid="office-template-picker">
      <div className="text-xs text-muted">{t('office.template.pickTitle')}</div>

      {templateLoad === 'loading' && (
        <p className="text-xs text-muted" data-testid="office-template-loading">
          {t('office.template.loading')}
        </p>
      )}

      {templateLoad === 'error' && (
        <div className="space-y-1" data-testid="office-template-error">
          <p className="text-xs text-error">{t('office.template.loadFailed')}</p>
          <button
            type="button"
            onClick={onRetryLoad}
            className="px-2 py-1 text-xs border border-border rounded text-text-secondary hover:bg-bg-hover"
          >
            {t('office.template.retry')}
          </button>
        </div>
      )}

      {templateLoad === 'ready' && visibleTemplates.length === 0 && (
        <p className="text-xs text-muted" data-testid="office-template-empty">
          {t('office.template.empty')}
        </p>
      )}

      {templateLoad === 'ready' &&
        visibleTemplates.map((tpl) => (
          <button
            key={`${tpl.source}-${tpl.id}`}
            type="button"
            onClick={() => onPickTemplate(tpl)}
            data-testid={`office-template-option-${tpl.id}`}
            className={[
              'w-full text-left px-3 py-2 rounded border text-sm',
              selectedTemplate?.id === tpl.id && selectedTemplate.source === tpl.source
                ? 'border-primary bg-primary/10'
                : 'border-border hover:bg-bg-hover',
            ].join(' ')}
          >
            <span className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-text">{tpl.name}</span>
              <span
                data-testid="office-template-source"
                className={[
                  'px-1.5 py-0.5 rounded text-xs',
                  tpl.source === 'builtin'
                    ? 'bg-primary/10 text-primary'
                    : 'bg-bg-hover text-text-secondary border border-border',
                ].join(' ')}
              >
                {tpl.source === 'builtin'
                  ? t('office.template.source.builtin')
                  : t('office.template.source.workspace')}
              </span>
            </span>
            {tpl.description && (
              <span className="block text-xs text-muted mt-0.5">{tpl.description}</span>
            )}
          </button>
        ))}

      {selectedTemplate && selectedTemplate.doc_type === type && (
        <div className="space-y-2 pt-1" data-testid="office-template-fields">
          {(() => {
            const thumbKey = `${selectedTemplate.source}-${selectedTemplate.id}`;
            const thumb = thumbnails[thumbKey];
            if (thumb) {
              return (
                <img
                  src={thumb}
                  alt={selectedTemplate.name}
                  data-testid="office-template-thumbnail"
                  className="w-40 rounded border border-border shadow-sm bg-white"
                />
              );
            }
            if (thumbnailLoading) {
              return (
                <div
                  className="w-40 h-52 rounded border border-dashed border-border flex items-center justify-center text-xs text-muted"
                  data-testid="office-template-thumbnail-loading"
                >
                  {t('office.template.thumbnailLoading')}
                </div>
              );
            }
            return null;
          })()}
          {selectedTemplate.placeholders.map((ph) => renderPlaceholderField(ph))}
        </div>
      )}
    </div>
  );
}
