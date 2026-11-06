import type { Skill } from '../../shared/api';
import { useI18n } from '../../shared/lib/i18n';

type Origin = NonNullable<Skill['origin']>;

const ORIGIN_STYLE: Record<Origin, string> = {
  builtin: 'bg-bg-subtle text-text-secondary',
  shipped: 'bg-accent/15 text-accent',
  generated: 'bg-primary/15 text-primary',
  imported: 'bg-success/15 text-success',
  user: 'bg-warning/15 text-warning',
};

const ORIGIN_KEY: Record<Origin, string> = {
  builtin: 'skills_page.origin_builtin',
  shipped: 'skills_page.origin_shipped',
  generated: 'skills_page.origin_generated',
  imported: 'skills_page.origin_imported',
  user: 'skills_page.origin_user',
};

interface SkillOriginBadgeProps {
  origin?: Skill['origin'];
  className?: string;
}

/**
 * M2: 技能来源徽章。后端 `list_skills_extended` 输出 origin；
 * 旧后端/旧数据缺省时按 user 回退（仍显示“本地”而非原始英文 source）。
 */
export default function SkillOriginBadge({ origin, className = '' }: SkillOriginBadgeProps) {
  const { t } = useI18n();
  const resolved: Origin = origin ?? 'user';
  const tKey = ORIGIN_KEY[resolved] as Parameters<typeof t>[0];
  return (
    <span
      className={`px-1.5 py-0.5 text-[11px] leading-none rounded-full whitespace-nowrap ${ORIGIN_STYLE[resolved]} ${className}`}
    >
      {t(tKey)}
    </span>
  );
}
