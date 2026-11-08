// src/features/office/rules/rulePackMarkdown.ts
import type { RulePack } from './ruleTypes';

/**
 * Render a RulePack as Markdown. Not localised — it mirrors the pack's own
 * text so the output is useful regardless of UI language.
 */
export function rulePackToMarkdown(pack: RulePack): string {
  const lines: string[] = [];
  lines.push(`# ${pack.name}`);
  lines.push('');
  lines.push(`> version ${pack.version} · exported ${pack.exportedAt} · by ${pack.exportedBy}`);
  for (const group of pack.groups) {
    lines.push('');
    lines.push(`## ${group.name} (priority ${group.priority})`);
    lines.push('');
    lines.push(group.description || '_ _');
    for (const rule of group.rules) {
      const checkbox = rule.enabled ? '- [x]' : '- [ ]';
      const headline = `**${rule.name}** — ${rule.type} / ${rule.severity} / ${rule.scope} / ${rule.checkMode}`;
      lines.push(`${checkbox} ${headline}`);
      if (rule.description) {
        lines.push(`  - ${rule.description}`);
      }
      if (rule.checkMode === 'regex' && rule.pattern) {
        lines.push(`  - pattern: \`${rule.pattern}\``);
      }
      if (rule.checkMode === 'ai' && rule.aiPrompt) {
        lines.push(`  - prompt: ${rule.aiPrompt}`);
      }
    }
  }
  return `${lines.join('\n')}\n`;
}
