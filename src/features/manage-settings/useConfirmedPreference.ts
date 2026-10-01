import { useCallback, useEffect, useRef, useState } from 'react';

import { settingsClient, type PreferenceKey } from '../../shared/api/settingsClient';

type SaveStatus = 'loading' | 'idle' | 'saving' | 'saved' | 'error';
interface PreferenceOptions<T> {
  key: PreferenceKey;
  initial: T;
  parse: (value: string | null) => T;
  serialize: (value: T) => string;
  category?: string;
  optimistic?: boolean;
}

/** Serialize writes and keep confirmation/error separate from an input draft. */
export function useConfirmedPreference<T>(options: PreferenceOptions<T>) {
  const { key } = options;
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const [value, setValue] = useState(options.initial);
  const [loaded, setLoaded] = useState(false);
  const [status, setStatus] = useState<SaveStatus>('loading');
  const mounted = useRef(true);
  const revision = useRef(0);
  const confirmed = useRef(options.initial);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);

  const reload = useCallback(async () => {
    if (pending.current) return;
    const current = ++revision.current;
    setStatus('loading');
    try {
      const raw = await settingsClient.getPreferenceStrict(key);
      if (!mounted.current || current !== revision.current) return;
      const next = optionsRef.current.parse(raw);
      confirmed.current = next;
      setValue(next);
      setLoaded(true);
      setStatus('idle');
    } catch {
      if (mounted.current && current === revision.current) {
        setLoaded(false);
        setStatus('error');
      }
    }
  }, [key]);

  useEffect(() => {
    mounted.current = true;
    void reload();
    const changed = (event: Event) => {
      if ((event as CustomEvent<{ key: string }>).detail?.key === key) void reload();
    };
    window.addEventListener('sage:setting-changed', changed);
    return () => {
      mounted.current = false;
      revision.current += 1;
      window.removeEventListener('sage:setting-changed', changed);
    };
  }, [key, reload]);

  const update = useCallback(
    (next: T) => {
      const current = ++revision.current;
      const { serialize, category = 'ui', optimistic = false } = optionsRef.current;
      if (optimistic) setValue(next);
      setStatus('saving');
      pending.current += 1;
      const write = queue.current
        .catch(() => undefined)
        .then(() => settingsClient.setPreferenceStrict(key, serialize(next), category));
      queue.current = write;
      void write
        .then(() => {
          confirmed.current = next;
          if (mounted.current && current === revision.current) {
            setValue(next);
            setStatus('saved');
          }
        })
        .catch(() => {
          if (mounted.current && current === revision.current) {
            setValue(confirmed.current);
            setStatus('error');
          }
        })
        .finally(() => {
          pending.current -= 1;
        });
    },
    [key],
  );

  return { value, loaded, status, reload, update };
}
