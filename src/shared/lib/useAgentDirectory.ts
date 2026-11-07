/**
 * 专家目录轻量缓存（M1.2 会话列表 / M2 群聊成员展示共用）。
 *
 * `agentsApi.list()` 结果做模块级缓存（单次加载，失败不缓存），
 * 供侧边栏会话项、群聊成员气泡等按 agent_id 解析头像与名字。
 */
import { useEffect, useState } from 'react';

import { agentsApi, type AgentProfile } from '../api';

let cache: AgentProfile[] | null = null;
let inflight: Promise<AgentProfile[]> | null = null;

function loadDirectory(): Promise<AgentProfile[]> {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = agentsApi
      .list()
      .then((list) => {
        cache = list;
        return list;
      })
      .catch(() => {
        inflight = null;
        return [] as AgentProfile[];
      });
  }
  return inflight;
}

function toMap(list: AgentProfile[]): Map<string, AgentProfile> {
  return new Map(list.map((agent) => [agent.id, agent]));
}

/** 按 agent_id 查询专家；未加载完成时返回空 Map（调用方回退到 id）。 */
export function useAgentDirectory(): Map<string, AgentProfile> {
  const [directory, setDirectory] = useState<Map<string, AgentProfile>>(() =>
    toMap(cache ?? []),
  );

  useEffect(() => {
    let cancelled = false;
    void loadDirectory().then((list) => {
      if (!cancelled) setDirectory(toMap(list));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return directory;
}

/** 测试/群成员变更后失效缓存（下次挂载重新拉取）。 */
export function invalidateAgentDirectory(): void {
  cache = null;
  inflight = null;
}
