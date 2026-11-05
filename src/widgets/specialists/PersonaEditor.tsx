import { useState } from 'react';

import {
  PERSONA_SECTIONS,
  type PersonaSectionKey,
  type PersonaSections,
} from '../../entities/specialist/personaSections';

interface PersonaEditorProps {
  sections: PersonaSections;
  onChange: (next: PersonaSections) => void;
}

/**
 * M1-E 人设六段编辑器：左侧段导航 + 右侧文本域。
 *
 * 六段固定顺序（身份/职责/工作方式/风格/行为边界/输出模板），只有非空段
 * 会写入 system_prompt；解析/序列化由 `entities/specialist/personaSections`
 * 负责，本组件只维护当前激活段。
 */
export function PersonaEditor({ sections, onChange }: PersonaEditorProps) {
  const [active, setActive] = useState<PersonaSectionKey>('identity');
  const activeMeta = PERSONA_SECTIONS.find((meta) => meta.key === active) ?? PERSONA_SECTIONS[0];

  return (
    <div className="flex min-h-64 flex-col gap-3 sm:flex-row">
      <nav
        aria-label="人设段落"
        className="flex shrink-0 flex-row gap-1 overflow-x-auto sm:w-32 sm:flex-col sm:overflow-visible"
      >
        {PERSONA_SECTIONS.map((meta) => {
          const filled = (sections[meta.key] ?? '').trim().length > 0;
          return (
            <button
              key={meta.key}
              type="button"
              aria-current={active === meta.key ? 'true' : undefined}
              onClick={() => setActive(meta.key)}
              className={`flex items-center gap-1.5 rounded-radius-md px-2.5 py-1.5 text-left text-sm whitespace-nowrap ${
                active === meta.key
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-text-secondary hover:bg-bg-hover'
              }`}
            >
              <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  filled ? 'bg-primary' : 'bg-border'
                }`}
              />
              {meta.label}
            </button>
          );
        })}
      </nav>

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <label htmlFor={`persona-section-${activeMeta.key}`} className="text-sm font-medium">
          # {activeMeta.heading}
        </label>
        <textarea
          id={`persona-section-${activeMeta.key}`}
          data-testid={`persona-section-${activeMeta.key}`}
          value={sections[activeMeta.key] ?? ''}
          onChange={(event) => onChange({ ...sections, [activeMeta.key]: event.target.value })}
          placeholder={activeMeta.placeholder}
          rows={10}
          className="flex-1 resize-y rounded-radius-md border border-border bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-primary"
        />
        <p className="text-ui-xs text-faint">
          支持 Markdown。至少填写「身份」，其余段可留空；留空的段不会写入人设。
        </p>
      </div>
    </div>
  );
}
