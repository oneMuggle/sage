import { useState } from 'react';
import { useI18n } from '../../shared/lib/i18n';

interface FeedbackModalProps {
  isOpen: boolean;
  onClose: () => void;
  screenshot?: string | null;
}

export function FeedbackModal({ isOpen, onClose, screenshot }: FeedbackModalProps) {
  const { t } = useI18n();
  const [description, setDescription] = useState('');
  const [email, setEmail] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Placeholder: log to console (Task 11 will implement backend API)
    console.log('Feedback submitted:', {
      description,
      email,
      screenshotLength: screenshot?.length ?? 0,
    });

    setSubmitted(true);
    setTimeout(() => {
      setSubmitted(false);
      setDescription('');
      setEmail('');
      onClose();
    }, 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay">
      <div className="bg-bg-elevated rounded-lg shadow-lg p-6 w-[500px] max-w-[90vw] max-h-[90vh] overflow-auto">
        <h2 className="text-xl font-semibold mb-4">{t('feedback.title')}</h2>

        {submitted ? (
          <div className="text-center py-8">
            <div className="text-4xl mb-2">✓</div>
            <p className="text-lg">{t('feedback.success')}</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {screenshot && (
              <div>
                <label className="block text-sm font-medium mb-2">
                  {t('feedback.screenshot')}
                </label>
                <div className="border border-border rounded p-2 bg-bg-muted">
                  <img
                    src={`data:image/png;base64,${screenshot}`}
                    alt="Screenshot"
                    className="max-w-full h-auto max-h-[200px] object-contain"
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="description" className="block text-sm font-medium mb-2">
                {t('feedback.description')} *
              </label>
              <textarea
                id="description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                required
                rows={4}
                className="w-full px-3 py-2 bg-bg border border-border rounded focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder={t('feedback.description_placeholder')}
              />
            </div>

            <div>
              <label htmlFor="email" className="block text-sm font-medium mb-2">
                {t('feedback.email')}
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 bg-bg border border-border rounded focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder={t('feedback.email_placeholder')}
              />
            </div>

            <div className="flex gap-2 pt-2">
              <button
                type="submit"
                className="flex-1 px-4 py-2 bg-primary text-text-inverse rounded hover:bg-primary-hover transition-colors"
              >
                {t('feedback.submit')}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2 bg-bg-hover border border-border rounded hover:bg-bg-active transition-colors"
              >
                {t('common.cancel')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
