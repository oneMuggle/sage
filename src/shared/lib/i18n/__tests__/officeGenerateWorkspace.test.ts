import { describe, expect, it } from 'vitest';

import { en } from '../en';
import { zh } from '../zh';

const WORKSPACE_KEYS = [
  'office.generate.workspace.title',
  'office.generate.workspace.mode.nl',
  'office.generate.workspace.mode.reference',
  'office.generate.workspace.mode.template',
  'office.generate.workspace.mode.iterate',
  'office.generate.workspace.instruction',
  'office.generate.workspace.instructionPlaceholder',
  'office.generate.workspace.docType',
  'office.generate.workspace.references',
  'office.generate.workspace.referencesEmpty',
  'office.generate.workspace.templatePick',
  'office.generate.workspace.chatPlaceholder',
  'office.generate.workspace.sourceDoc',
  'office.generate.workspace.sourceEmpty',
  'office.generate.workspace.submit',
  'office.generate.workspace.generating',
  'office.generate.workspace.resultTitle',
  'office.generate.workspace.resultEmpty',
  'office.generate.workspace.open',
  'office.generate.workspace.missingInstruction',
  'office.generate.workspace.missingTemplate',
  'office.generate.workspace.missingSource',
] as const;

describe('generate workspace i18n keys', () => {
  it.each(WORKSPACE_KEYS)('%s exists in zh and en', (key) => {
    expect(zh[key as keyof typeof zh]).toBeTruthy();
    expect(en[key as keyof typeof en]).toBeTruthy();
  });
});
