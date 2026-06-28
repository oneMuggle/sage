import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import { validateCss } from '../../shared/lib/theme/cssValidator';
import type { ThemeValidationResult } from '../../shared/types/theme';

import { CodeMirrorThemeEditor } from './CodeMirrorThemeEditor';
import { useTheme } from './ThemeProvider';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CssThemeModal({ open, onClose }: Props): JSX.Element | null {
  const { t } = useI18n();
  const { active, applyCustomCss } = useTheme();
  const [css, setCss] = useState<string>(active.customCss ?? '');
  const [validation, setValidation] = useState<ThemeValidationResult>({ valid: true });

  if (!open) return null;

  const handleChange = (next: string) => {
    setCss(next);
    setValidation(validateCss(next));
  };

  const handleSave = async () => {
    if (!validation.valid) return;
    await applyCustomCss(css);
    onClose();
  };

  return (
    <div role="dialog" aria-modal="true" data-testid="css-theme-modal">
      <h2>{t('theme.selector.custom')}</h2>
      <CodeMirrorThemeEditor value={css} onChange={handleChange} />
      {validation.valid === false && validation.errors && (
        <ul role="alert" data-testid="validation-errors">
          {validation.errors.map((e, i) => (
            <li key={i}>{e}</li>
          ))}
        </ul>
      )}
      <div>
        <button type="button" onClick={onClose}>
          {t('theme.editor.cancel')}
        </button>
        <button type="button" onClick={() => void handleSave()} disabled={!validation.valid}>
          {t('theme.editor.save')}
        </button>
      </div>
    </div>
  );
}
