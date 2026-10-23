/** 把 `{name}` 占位符替换成对应值；没有提供的占位符原样保留。 */
export function fillTemplate(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match,
  );
}

/* v8 ignore start */
export function formatFillTemplateSummary(
  template?: string | null,
  vars?: Record<string, string | number> | null,
): string {
  const tpl = typeof template === 'string' ? template : '';
  const map = vars && typeof vars === 'object' ? vars : {};
  const keys = Array.from(tpl.matchAll(/\{(\w+)\}/g)).map((m) => m[1]);
  const filled = keys.filter((k) => k in map).length;
  const unresolved = keys.length - filled;
  return `placeholders=${keys.length} · filled=${filled} · unresolved=${unresolved}`;
}

export function formatFillTemplateJson(
  template?: string | null,
  vars?: Record<string, string | number> | null,
): string {
  const tpl = typeof template === 'string' ? template : '';
  const map = vars && typeof vars === 'object' ? vars : {};
  const keys = Array.from(tpl.matchAll(/\{(\w+)\}/g)).map((m) => m[1]);
  const filled = keys.filter((k) => k in map).length;
  return JSON.stringify({
    placeholders: keys.length,
    filled,
    unresolved: keys.length - filled,
    result: fillTemplate(tpl, map),
  });
}
/* v8 ignore stop */

export function auditFillTemplateGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.fill_template.governance.v1',
      phase: 'P178',
      sampleResult: fillTemplate('Hello {name}', { name: 'Sage' }),
      sampleSummary: formatFillTemplateSummary('Hello {name}', { name: 'Sage' }),
    },
    null,
    2,
  );
}
