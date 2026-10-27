// src/shared/lib/hooks/usePluginNames.ts
//
// R111: 生命周期插件名名单的共享缓存读取——给转录等「按条渲染」
// 的界面做插件归属标注供数。模块级缓存 + 在途合并：同一时刻多
// 个组件挂载只发一次 list()；TTL 后下一次挂载后台刷新，名单内
// 容未变时不换数组引用（避免全体订阅者无谓重渲染）。取数失败
// 不毒化缓存（返回 null，下次启用可重试）——读不到就整体不标
// 注，与 R107/R110 降级一致。
import { useEffect, useState } from 'react';

import { pluginClient } from '../../api/pluginClient';

const CACHE_TTL_MS = 60_000;

let cachedNames: string[] | null = null;
let cachedAt = 0;
let inFlight: Promise<string[] | null> | null = null;

function loadPluginNames(): Promise<string[] | null> {
  if (inFlight) return inFlight;
  inFlight = pluginClient
    .list()
    .then((records) => records.map((record) => record.name))
    .catch(() => null)
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/**
 * 返回生命周期插件名数组；不可用（未启用 / 未加载完 / 读取失
 * 败）时为 null，消费方据此整体降级不标注。
 */
export function usePluginNames(enabled: boolean): string[] | null {
  const [names, setNames] = useState<string[] | null>(cachedNames);

  useEffect(() => {
    if (!enabled) return;
    if (cachedNames !== null && Date.now() - cachedAt < CACHE_TTL_MS) {
      setNames(cachedNames);
      return;
    }
    let cancelled = false;
    void loadPluginNames().then((fresh) => {
      if (fresh !== null) {
        if (cachedNames === null || fresh.join('\n') !== cachedNames.join('\n')) {
          cachedNames = fresh;
        }
        cachedAt = Date.now();
      }
      if (!cancelled) setNames(cachedNames);
    });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return names;
}
