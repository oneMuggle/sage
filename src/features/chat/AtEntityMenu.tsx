// src/features/chat/AtEntityMenu.tsx
//
// 对标 S3: @ 菜单顶部的实体类型行 —— @memory: / @wiki: / @skill: / @agent:。
// 选中后把 `@kind:` 写入输入框，用户接着输入查询词；发送时后端解析注入。
import { Bot, Brain, BookOpen, Sparkles } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';

import { getEntityKindSuggestions, type EntityKindSuggestion, type EntityRefKind } from './entityRefs';

const KIND_ICON = {
  memory: Brain,
  wiki: BookOpen,
  skill: Sparkles,
  agent: Bot,
} as const;

interface AtEntityMenuProps {
  query: string | null;
  onSelect: (suggestion: EntityKindSuggestion) => void;
}

export function AtEntityMenu({ query, onSelect }: AtEntityMenuProps) {
  const { t } = useI18n();
  const suggestions = getEntityKindSuggestions(query);
  if (suggestions.length === 0) return null;
  return (
    <div
      data-testid="at-entity-menu"
      className="flex flex-wrap items-center gap-1 px-2 py-1.5 border-b border-border text-xs"
    >
      <span className="text-text-tertiary mr-1">{t('chat.atEntity.label')}</span>
      {suggestions.map((s) => {
        const Icon = KIND_ICON[s.kind as EntityRefKind];
        return (
          <button
            key={s.kind}
            type="button"
            data-testid={`at-entity-${s.kind}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => onSelect(s)}
            title={t(`chat.atEntity.${s.kind}.desc`)}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-border text-text-secondary hover:bg-bg-hover hover:text-text"
          >
            <Icon className="w-3 h-3" aria-hidden />
            <span className="font-mono">{s.token}</span>
            <span>{t(`chat.atEntity.${s.kind}`)}</span>
          </button>
        );
      })}
    </div>
  );
}
