import { useEffect, useState } from 'react';

import { getEndpointHealth, type EndpointHealthRow } from './api';

const HEALTH_POLL_INTERVAL_MS = 15_000;

/**
 * 2026-11-26: 端点健康轮询（设置页状态点）。
 *
 * ``enabled=false``（故障转移未开启）时不发请求；页签卸载即停止。
 * 任何请求失败静默（健康展示是辅助信息，不得打扰设置页）。
 */
export function useEndpointHealth(enabled: boolean): Record<string, EndpointHealthRow> {
  const [rows, setRows] = useState<Record<string, EndpointHealthRow>>({});

  useEffect(() => {
    if (!enabled) {
      setRows({});
      return;
    }
    let cancelled = false;
    const load = () => {
      void getEndpointHealth()
        .then((list) => {
          if (!cancelled) {
            setRows(Object.fromEntries(list.map((row) => [row.endpointId, row])));
          }
        })
        .catch(() => {});
    };
    load();
    const timer = window.setInterval(load, HEALTH_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  return rows;
}
