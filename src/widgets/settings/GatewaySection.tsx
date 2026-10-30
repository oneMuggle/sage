// src/widgets/settings/GatewaySection.tsx
// 消息网关分组：默认折叠，展开后才挂载 GatewayCard。
// 折叠时不渲染卡片 → 设置页默认零网关请求（避免未配置时的 500 风暴）。

import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import { GATEWAY_PLATFORMS } from '../../shared/api/gatewayApi';

import { GatewayCard } from './GatewayCard';

export function GatewaySection({
  title = '消息网关（可选）',
}: {
  title?: string;
} = {}): JSX.Element {
  const [expanded, setExpanded] = useState(false);

  return (
    <section data-settings-anchor="gateway">
      <h3 className="text-ui-base font-semibold text-text mb-3">{title}</h3>
      <p className="text-xs text-muted mb-2">
        在 Telegram / Discord / Slack 上远程对话与审批。默认关闭；国内网络建议等待飞书 / 钉钉适配。
      </p>
      <button
        type="button"
        className="flex items-center gap-1 text-xs text-text-secondary hover:text-text"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5" aria-hidden="true" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" aria-hidden="true" />
        )}
        {expanded ? '收起网关配置' : '展开网关配置'}
      </button>
      {expanded && (
        <div className="mt-3 space-y-3">
          {GATEWAY_PLATFORMS.map((platform) => (
            <GatewayCard key={platform} platform={platform} />
          ))}
        </div>
      )}
    </section>
  );
}
