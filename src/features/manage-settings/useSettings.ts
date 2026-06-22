import { useCallback, useEffect, useState } from 'react';

import {
  loadSettings,
  resetSettings as resetSettingsLib,
  saveSettings,
} from '../../entities/setting/storage';
import type { AppSettings } from '../../entities/setting/types';
import { DEFAULT_SETTINGS } from '../../entities/setting/types';

interface UseSettingsReturn {
  settings: AppSettings;
  isLoading: boolean;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
  resetSettings: () => Promise<void>;
}

/**
 * React hook for application settings.
 * 异步从后端加载，本地 cache 兜底；更新走双写。
 */
export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    loadSettings()
      .then((s) => {
        if (!cancelled) {
          setSettings(s);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const updateSettings = useCallback(async (partial: Partial<AppSettings>) => {
    setSettings((prev) => ({ ...prev, ...partial }));
    await saveSettings(partial);
  }, []);

  const resetSettings = useCallback(async () => {
    await resetSettingsLib();
    setSettings({ ...DEFAULT_SETTINGS });
  }, []);

  return { settings, isLoading, updateSettings, resetSettings };
}
