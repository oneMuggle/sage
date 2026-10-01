import { useI18n } from '../../shared/lib/i18n';
import { productMessages } from '../../shared/lib/productMessages';

interface Props {
  status: 'loading' | 'idle' | 'saving' | 'saved' | 'error';
  reload: () => Promise<void>;
}
export function PreferenceSaveStatus({ status, reload }: Props) {
  const { locale } = useI18n();
  const copy = productMessages(locale);
  if (status === 'idle' || status === 'loading') return null;
  return (
    <div
      role={status === 'error' ? 'alert' : 'status'}
      className={`text-ui-sm mt-1 ${status === 'error' ? 'text-error' : 'text-text-secondary'}`}
    >
      {status === 'saving' ? copy.saving : status === 'saved' ? copy.saved : copy.saveFailed}
      {status === 'error' && (
        <button type="button" onClick={() => void reload()} className="ml-2 underline">
          {copy.retry}
        </button>
      )}
    </div>
  );
}
