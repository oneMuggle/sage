import { useState } from 'react';

import { windowControls } from '../../shared/api/windowControlsClient';
import { useI18n } from '../../shared/lib/i18n';

import { FeedbackModal } from './FeedbackModal';

export function FeedbackButton() {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const [screenshot, setScreenshot] = useState<string | null>(null);

  const handleClick = async () => {
    try {
      const capturedScreenshot = await windowControls.capturePage();
      console.log('Screenshot captured, length:', capturedScreenshot.length);
      setScreenshot(capturedScreenshot);
      setIsOpen(true);
    } catch (error) {
      console.error('Failed to capture screenshot:', error);
      setScreenshot(null);
      setIsOpen(true);
    }
  };

  const handleClose = () => {
    setIsOpen(false);
    setScreenshot(null);
  };

  return (
    <>
      <button
        onClick={handleClick}
        className="px-3 py-1 hover:bg-bg-hover transition-colors"
        aria-label={t('feedback.button')}
        title={t('feedback.button')}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 12.5a5.5 5.5 0 110-11 5.5 5.5 0 010 11zM7.25 4v5h1.5V4h-1.5zm0 6v1.5h1.5V10h-1.5z" />
        </svg>
      </button>
      <FeedbackModal isOpen={isOpen} onClose={handleClose} screenshot={screenshot} />
    </>
  );
}
