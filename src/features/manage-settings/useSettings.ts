import { useState, useCallback } from 'react';

import { loadSettings, resetSettings as resetSettingsLib, saveSettings } from '../../entities/setting/storage';
import type { AppSettings } from '../../entities/setting/types';

interface UseSettingsReturn {
  settings: AppSettings;
  updateSettings: (partial: Partial<AppSettings>) => void;
  resetSettings: () => void;
}

/**
 * React hook for application settings.
 * Loads from localStorage on mount, persists changes on update.
 */
export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<AppSettings>(loadSettings);

  const updateSettings = useCallback((partial: Partial<AppSettings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...partial };
      saveSettings(partial);
      return next;
    });
  }, []);

  const resetSettings = useCallback(() => {
    resetSettingsLib();
    setSettings(loadSettings());
  }, []);

  return { settings, updateSettings, resetSettings };
}
