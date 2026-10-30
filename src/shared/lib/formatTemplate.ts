/**
 * 简单模板占位符替换：`{name}` → 值（全部出现位置都替换）。
 *
 * i18n 无内置插值，菜单/确认框的带参文案统一走这里。
 */
export function fillTemplate(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.split(`{${key}}`).join(String(value)),
    template,
  );
}
