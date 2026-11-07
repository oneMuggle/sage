import type { SelectionState } from '../../../entities/office/officeWorkspaceStore';

export const PARAGRAPH_ATTRIBUTE = 'data-paragraph-index';
const MAX_RAW_CONTEXT = 80;

export function annotateParagraphIndexes(root: HTMLElement): void {
  let next = 0;
  root.querySelectorAll<HTMLElement>('p').forEach((el) => {
    el.removeAttribute(PARAGRAPH_ATTRIBUTE);
    // docx-preview 0.3.5 默认 renderHeaders/renderFooters=true，
    // 表格、页眉、页脚、脚注都会产出 <p>；后端 _extract_paragraphs 只数正文段落。
    if (el.closest('table, header, footer, li')) return;
    const text = el.textContent?.trim() ?? '';
    if (!text) return;
    el.setAttribute(PARAGRAPH_ATTRIBUTE, String(next));
    next += 1;
  });
}

export function findParagraphIndex(node: Node | null, root: HTMLElement): number | null {
  let current: Node | null = node;
  while (current && current !== root) {
    if (current instanceof HTMLElement) {
      const raw = current.getAttribute(PARAGRAPH_ATTRIBUTE);
      if (raw !== null) {
        const parsed = Number.parseInt(raw, 10);
        return Number.isNaN(parsed) ? null : parsed;
      }
    }
    current = current.parentNode;
  }
  return null;
}

export function collectDocumentParagraphs(root: HTMLElement): { index: number; text: string }[] {
  const out: { index: number; text: string }[] = [];
  root.querySelectorAll<HTMLElement>(`[${PARAGRAPH_ATTRIBUTE}]`).forEach((el) => {
    const index = Number.parseInt(el.getAttribute(PARAGRAPH_ATTRIBUTE) ?? '', 10);
    const text = el.textContent?.trim() ?? '';
    if (!Number.isNaN(index) && text) out.push({ index, text });
  });
  return out.sort((a, b) => a.index - b.index);
}

export function normalizeSelection(
  root: HTMLElement,
  selection: Selection | null,
): SelectionState | null {
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  const text = selection.toString();
  if (!text.trim()) return null;
  if (!root.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return null;
  return {
    text,
    anchorParaIndex: findParagraphIndex(selection.anchorNode, root),
    focusParaIndex: findParagraphIndex(selection.focusNode, root),
    rawContext: text.replace(/\s+/g, ' ').trim().slice(0, MAX_RAW_CONTEXT),
  };
}
