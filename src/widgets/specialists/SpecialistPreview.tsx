import {
  PERSONA_SECTIONS,
  serializePersonaSections,
  type PersonaSections,
} from '../../entities/specialist/personaSections';
import { describeToolSelection } from '../../entities/specialist/toolCapabilities';
import type { AgentProfile } from '../../shared/api';

import { PERMISSION_MODE_LABELS } from './SpecialistCard';

interface SpecialistPreviewProps {
  name: string;
  avatar: string;
  tagline: string;
  sections: PersonaSections;
  skills: string[];
  permissionMode: AgentProfile['permission_mode'];
  /** 保存后写入 `tools` 的值；空数组即纯对话专家。 */
  tools?: string[];
  /** 试聊/创建按钮（向导第 4 步注入）；编辑态可省略。 */
  footer?: React.ReactNode;
}

/**
 * M1-E 专家预览：画廊卡片样式的人设摘要 + 序列化后的 Markdown 原文。
 *
 * 与 SpecialistCard 的差异：预览面向「即将保存的草稿」，不含编辑/导出动作，
 * 且额外展示人设全文，便于用户在创建前确认实际写入 system_prompt 的内容。
 */
export function SpecialistPreview({
  name,
  avatar,
  tagline,
  sections,
  skills,
  permissionMode,
  tools,
  footer,
}: SpecialistPreviewProps) {
  const markdown = serializePersonaSections(sections);
  const filledSections = PERSONA_SECTIONS.filter(
    (meta) => (sections[meta.key] ?? '').trim().length > 0,
  );
  const toolSummary = tools ? describeToolSelection(tools) : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-3 rounded-xl border border-border bg-surface p-4">
        <span
          aria-hidden="true"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-bg-subtle text-2xl"
        >
          {avatar.trim() || '🤖'}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-medium">{name.trim() || '未命名专家'}</h3>
          <p className="mt-1 line-clamp-2 text-sm text-muted">{tagline.trim() || '尚未填写标语'}</p>
          <p className="mt-1 text-ui-xs text-faint">
            专家 · {PERMISSION_MODE_LABELS[permissionMode ?? 'read_only'] ?? permissionMode}
            {skills.length > 0 ? ` · ${skills.length} 项技能` : ''}
          </p>
        </div>
      </div>

      {toolSummary && (
        <div
          className="rounded-xl border border-border bg-surface p-4"
          data-testid="specialist-preview-tools"
        >
          <p className="text-sm font-medium">工具能力</p>
          {tools!.length === 0 ? (
            <p className="mt-1 text-ui-xs text-warning">
              纯对话专家：不授权任何工具，运行时所有工具调用都会被拒绝。
            </p>
          ) : (
            <>
              <p className="mt-1 text-ui-xs text-faint">共 {tools!.length} 项工具</p>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {toolSummary.covered.map((pack) => (
                  <span
                    key={pack.id}
                    className="rounded-full bg-primary/10 px-2 py-0.5 text-ui-xs text-primary"
                  >
                    {pack.label}
                  </span>
                ))}
                {toolSummary.partial.map((pack) => (
                  <span
                    key={pack.id}
                    className="rounded-full border border-border px-2 py-0.5 text-ui-xs text-text-secondary"
                  >
                    {pack.label}（部分）
                  </span>
                ))}
              </div>
              {toolSummary.uncategorized.length > 0 && (
                <p className="mt-1 break-all font-mono text-ui-xs text-faint">
                  未归类：{toolSummary.uncategorized.join('、')}
                </p>
              )}
            </>
          )}
        </div>
      )}

      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
        <p className="text-sm font-medium">人设摘要</p>
        {filledSections.length === 0 ? (
          <p className="text-sm text-faint">尚未填写任何段落。</p>
        ) : (
          filledSections.map((meta) => (
            <div key={meta.key}>
              <p className="text-ui-xs font-medium text-text-secondary">{meta.heading}</p>
              <p className="mt-0.5 line-clamp-3 text-sm text-muted whitespace-pre-wrap">
                {sections[meta.key]}
              </p>
            </div>
          ))
        )}
      </div>

      {skills.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full bg-bg-subtle px-2 py-0.5 text-ui-xs text-text-secondary"
            >
              {skill}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-1">
        <p className="text-ui-xs text-faint">写入 system_prompt 的原文：</p>
        <pre
          data-testid="specialist-preview-markdown"
          className="max-h-48 overflow-auto rounded-radius-md border border-border bg-bg-subtle p-3 font-mono text-ui-xs whitespace-pre-wrap"
        >
          {markdown || '（空）'}
        </pre>
      </div>

      {footer}
    </div>
  );
}
